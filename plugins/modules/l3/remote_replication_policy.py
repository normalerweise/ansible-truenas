#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage remote pull-based replication policies for TrueNAS datasets

DOCUMENTATION = """
---
module: remote_replication_policy
short_description: Manage remote pull-based replication policies for TrueNAS datasets
description:
  - Manages remote replication policies for ZFS datasets on TrueNAS SCALE.
  - Creates pull-based replication tasks that pull snapshots from remote TrueNAS machines.
  - Runs on destination machine, pulls from remote source.
  - One replication task manages all specified tiers for a dataset.
  - Requires SSH credentials configured in keychain.
  - This is a Level 3 (L3) module that orchestrates multiple resources as a cohesive policy.
abstraction_level: L3
abstraction_type: pattern_orchestration
related_modules:
  - normalerweise.truenas.l1.replication for managing individual replication tasks
  - normalerweise.truenas.l2.keychaincredential for managing SSH credentials
  - normalerweise.truenas.l3.pool_snapshot_policy for managing snapshot policies
options:
  name:
    description:
      - Name for the replication task.
      - If not specified, automatically generated as auto-repl-<source_dataset>.
    type: str
  source_dataset:
    description:
      - Source dataset to replicate from (on remote machine).
      - Must have snapshots with auto-<tier>- naming convention.
    type: str
    required: true
  source_host:
    description:
      - Remote hostname or IP address (for documentation/clarity).
      - Not used directly by module but helpful for understanding the task.
    type: str
  target_dataset:
    description:
      - Target dataset to replicate to (on this machine).
    type: str
    required: true
  ssh_credentials_id:
    description:
      - Keychain credential ID for SSH connection to remote machine.
      - Must be created in TrueNAS keychain before running this module.
    type: int
    required: true
  tiers:
    description:
      - Dictionary mapping tier names to retention counts.
      - Valid tier names are frequent, hourly, daily, weekly, monthly, yearly.
      - Retention count specifies how many snapshots to keep for each tier.
    type: dict
    required: true
  recursive:
    description:
      - Whether to recursively replicate child datasets.
    type: bool
    required: true
  preserve_source_encryption:
    description:
      - Keep source dataset encryption keys at target.
      - Mutually exclusive with target_encryption options.
    type: bool
    default: true
  target_encryption:
    description:
      - Enable encryption at target (when not preserving source).
      - Requires either target_encryption_key or target_encryption_inherit.
    type: bool
  target_encryption_key:
    description:
      - Encryption key for target dataset.
      - Mutually exclusive with target_encryption_inherit.
    type: str
    no_log: true
  target_encryption_key_format:
    description:
      - Format of target encryption key.
    type: str
    choices: ['HEX', 'PASSPHRASE']
  target_encryption_inherit:
    description:
      - Inherit encryption from parent at target.
      - Mutually exclusive with target_encryption_key.
    type: bool
  state:
    description:
      - Whether the replication policy should exist or not.
      - C(present) creates or updates the replication task.
      - C(absent) removes the replication task.
    type: str
    choices: [ absent, present ]
    default: present
version_added: 1.6.0
notes:
  - This module manages replication tasks with 'auto-repl-' prefix in their names.
  - Uses SSH transport to connect to remote TrueNAS machine.
  - Custom retention policy with explicit counts per tier.
  - Remote source must have snapshots created with pool_snapshot_policy module.
author:
  - "Norman (@normalerweise)"
"""

EXAMPLES = """
- name: Pull replication from remote NAS
  remote_replication_policy:
    source_dataset: "tank/data"
    source_host: "nas01.local"
    target_dataset: "local_pool/replicas/data"
    ssh_credentials_id: 1
    tiers:
      hourly: 24
      daily: 30
      weekly: 8
    recursive: true
    state: present

- name: Pull with custom encryption at target
  remote_replication_policy:
    source_dataset: "tank/data"
    source_host: "remote-nas.local"
    target_dataset: "local_pool/replicas/data"
    ssh_credentials_id: 2
    tiers:
      daily: 14
      weekly: 4
    recursive: true
    preserve_source_encryption: false
    target_encryption: true
    target_encryption_key: "{{ vault_local_pool_key }}"
    target_encryption_key_format: "HEX"
    state: present

- name: Pull with encryption inherited from parent
  remote_replication_policy:
    source_dataset: "tank/critical"
    source_host: "remote-nas.local"
    target_dataset: "encrypted_pool/replicas/critical"
    ssh_credentials_id: 2
    tiers:
      daily: 7
      monthly: 12
    recursive: false
    preserve_source_encryption: false
    target_encryption: true
    target_encryption_inherit: true
    state: present

- name: Remove remote replication policy
  remote_replication_policy:
    source_dataset: "tank/data"
    target_dataset: "local_pool/replicas/data"
    ssh_credentials_id: 1
    tiers: {}
    recursive: true
    state: absent
"""

RETURN = """
---
changed:
  description: Whether any changes were made
  type: bool
  returned: always
  sample: true
msg:
  description: Human-readable message describing what happened
  type: str
  returned: always
  sample: "Replication policy created successfully"
task:
  description: The replication task that was created or updated
  type: dict
  returned: when state=present and task was created/updated
  sample:
    id: 1
    name: "auto-repl-tank_data"
    direction: "PULL"
    transport: "SSH"
    ssh_credentials: 1
    source_datasets: ["tank/data"]
    target_dataset: "local_pool/replicas/data"
deleted_task_id:
  description: ID of task that was deleted
  type: int
  returned: when state=absent and task was deleted
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule

from ..module_utils.middleware import MiddleWare as MW

# ==============================================================================
# CONSTANTS
# ==============================================================================

TIER_CONFIGS = {
    "frequent": {
        "schedule": {
            "minute": "*/15",
            "hour": "*",
            "dom": "*",
            "month": "*",
            "dow": "*",
        },
        "lifetime_unit": "HOUR",
    },
    "hourly": {
        "schedule": {"minute": "0", "hour": "*", "dom": "*", "month": "*", "dow": "*"},
        "lifetime_unit": "HOUR",
    },
    "daily": {
        "schedule": {"minute": "0", "hour": "0", "dom": "*", "month": "*", "dow": "*"},
        "lifetime_unit": "DAY",
    },
    "weekly": {
        "schedule": {"minute": "0", "hour": "0", "dom": "*", "month": "*", "dow": "0"},
        "lifetime_unit": "WEEK",
    },
    "monthly": {
        "schedule": {"minute": "0", "hour": "0", "dom": "1", "month": "*", "dow": "*"},
        "lifetime_unit": "MONTH",
    },
    "yearly": {
        "schedule": {"minute": "0", "hour": "0", "dom": "1", "month": "1", "dow": "*"},
        "lifetime_unit": "YEAR",
    },
}


# ==============================================================================
# HELPER CLASSES
# ==============================================================================


class TierMatcher:
    """Handles tier-based naming schema generation."""

    @staticmethod
    def build_naming_schemas(tiers):
        """Build list of naming schemas for tiers.

        Args:
            tiers: List of tier names or dict keys

        Returns:
            List of naming schemas like ["auto-hourly-%Y-%m-%d_%H:%M", ...]
        """
        if isinstance(tiers, dict):
            tiers = list(tiers.keys())
        return [f"auto-{tier}-%Y-%m-%d_%H:%M" for tier in tiers]

    @staticmethod
    def get_tier_schedule(tier_name):
        """Get retention schedule for a tier.

        Args:
            tier_name: Name of the tier

        Returns:
            Schedule dict with minute, hour, dom, month, dow
        """
        if tier_name not in TIER_CONFIGS:
            raise ValueError(f"Invalid tier name: {tier_name}")
        return TIER_CONFIGS[tier_name]["schedule"]

    @staticmethod
    def get_tier_lifetime_unit(tier_name):
        """Get lifetime unit for a tier.

        Args:
            tier_name: Name of the tier

        Returns:
            Lifetime unit string (HOUR, DAY, WEEK, MONTH, YEAR)
        """
        if tier_name not in TIER_CONFIGS:
            raise ValueError(f"Invalid tier name: {tier_name}")
        return TIER_CONFIGS[tier_name]["lifetime_unit"]

    @staticmethod
    def validate_tiers(tiers):
        """Validate tier names.

        Args:
            tiers: Dict of tier names to validate

        Returns:
            True if all valid

        Raises:
            ValueError if any invalid tier names
        """
        valid_tiers = set(TIER_CONFIGS.keys())
        invalid_tiers = [t for t in tiers.keys() if t not in valid_tiers]
        if invalid_tiers:
            raise ValueError(
                f"Invalid tier names: {', '.join(invalid_tiers)}. "
                f"Valid tiers: {', '.join(sorted(valid_tiers))}"
            )
        return True

    @staticmethod
    def get_most_frequent_tier(tiers_dict):
        """Get the most frequent tier from the tiers dict.

        Args:
            tiers_dict: Dict mapping tier names to retention counts

        Returns:
            Name of the most frequent tier

        Raises:
            ValueError if tiers_dict is empty
        """
        if not tiers_dict:
            raise ValueError("tiers_dict cannot be empty")

        # Define tier order by frequency (most frequent first)
        tier_order = ["frequent", "hourly", "daily", "weekly", "monthly", "yearly"]

        # Find the most frequent tier present in tiers_dict
        for tier in tier_order:
            if tier in tiers_dict:
                return tier

        # If none of the standard tiers found, return first key
        return list(tiers_dict.keys())[0]

    @staticmethod
    def get_longest_retention_tier(tiers_dict):
        """Get the tier with the longest retention period.

        Args:
            tiers_dict: Dict mapping tier names to retention counts

        Returns:
            Tuple of (tier_name, retention_count)

        Raises:
            ValueError if tiers_dict is empty
        """
        if not tiers_dict:
            raise ValueError("tiers_dict cannot be empty")

        # Conversion factors to hours for comparison
        unit_to_hours = {
            "HOUR": 1,
            "DAY": 24,
            "WEEK": 24 * 7,
            "MONTH": 24 * 30,  # Approximation
            "YEAR": 24 * 365,  # Approximation
        }

        longest_tier = None
        longest_hours = 0

        for tier_name, count in tiers_dict.items():
            unit = TierMatcher.get_tier_lifetime_unit(tier_name)
            total_hours = count * unit_to_hours.get(unit, 0)

            if total_hours > longest_hours:
                longest_hours = total_hours
                longest_tier = tier_name

        return longest_tier, tiers_dict[longest_tier]


class TaskNameGenerator:
    """Generates and validates replication task names."""

    @staticmethod
    def generate_name(source_dataset, prefix="auto-repl"):
        """Generate task name from dataset.

        Args:
            source_dataset: Source dataset path (e.g., "tank/data/home")
            prefix: Name prefix

        Returns:
            Sanitized name like "auto-repl-tank_data_home"
        """
        sanitized = source_dataset.replace("/", "_")
        return f"{prefix}-{sanitized}"

    @staticmethod
    def is_policy_managed(task_name):
        """Check if task is managed by our modules.

        Args:
            task_name: Task name to check

        Returns:
            True if task has auto-repl- prefix
        """
        return task_name.startswith("auto-repl-")


class EncryptionConfigBuilder:
    """Builds encryption configuration for replication tasks."""

    @staticmethod
    def build_config(
        preserve_source,
        target_encryption,
        target_key,
        target_key_format,
        target_inherit,
    ):
        """Build encryption config dict.

        Args:
            preserve_source: Keep source encryption
            target_encryption: Enable target encryption
            target_key: Target encryption key
            target_key_format: Target key format (HEX/PASSPHRASE)
            target_inherit: Inherit from parent

        Returns:
            Dict with encryption configuration
        """
        if preserve_source:
            return {"encryption": False}

        if target_encryption:
            config = {"encryption": True}
            if target_inherit:
                config["encryption_inherit"] = True
            elif target_key:
                config["encryption_key"] = target_key
                config["encryption_key_format"] = target_key_format
            return config

        return {"encryption": False}


# ==============================================================================
# API WRAPPER
# ==============================================================================


class ReplicationTaskAPI:
    """Wrapper for TrueNAS replication API operations."""

    def __init__(self, mw):
        """Initialize API wrapper.

        Args:
            mw: MiddleWare client instance
        """
        self.mw = mw

    def query_task_by_name(self, name):
        """Query replication task by name.

        Args:
            name: Task name to query

        Returns:
            Task dict or None if not found
        """
        try:
            filters = [["name", "=", name]]
            tasks = self.mw.call("replication.query", filters)
            return tasks[0] if tasks else None
        except Exception as e:
            raise Exception(f"Failed to query replication task '{name}': {e}")

    def create_task(self, config):
        """Create replication task.

        Args:
            config: Task configuration dict

        Returns:
            Created task dict
        """
        try:
            return self.mw.call("replication.create", config)
        except Exception as e:
            name = config.get("name", "unknown")
            raise Exception(f"Failed to create replication task '{name}': {e}")

    def update_task(self, task_id, config):
        """Update replication task.

        Args:
            task_id: Task ID to update
            config: New configuration dict

        Returns:
            Updated task dict
        """
        try:
            return self.mw.call("replication.update", task_id, config)
        except Exception as e:
            raise Exception(f"Failed to update replication task {task_id}: {e}")

    def delete_task(self, task_id):
        """Delete replication task.

        Args:
            task_id: Task ID to delete

        Returns:
            True on success
        """
        try:
            return self.mw.call("replication.delete", task_id)
        except Exception as e:
            raise Exception(f"Failed to delete replication task {task_id}: {e}")


# ==============================================================================
# POLICY MANAGER
# ==============================================================================


class RemoteReplicationPolicyManager:
    """Manages remote pull-based replication policy."""

    def __init__(self, api):
        """Initialize policy manager.

        Args:
            api: ReplicationTaskAPI instance
        """
        self.api = api

    def sync_policy(self, params, check_mode):
        """Synchronize remote replication policy.

        Args:
            params: Module parameters dict
            check_mode: Whether running in check mode

        Returns:
            Result dict with changed flag and details
        """
        # Extract parameters
        task_name = params["name"]
        source_dataset = params["source_dataset"]
        target_dataset = params["target_dataset"]
        ssh_credentials_id = params["ssh_credentials_id"]
        tiers = params["tiers"]
        recursive = params["recursive"]

        # Build naming schemas
        naming_schemas = TierMatcher.build_naming_schemas(tiers)

        # Build lifetimes array
        lifetimes = self._build_lifetimes(tiers)

        # Determine replication schedule from most frequent tier
        most_frequent_tier = TierMatcher.get_most_frequent_tier(tiers)
        replication_schedule = TierMatcher.get_tier_schedule(most_frequent_tier)

        # Determine simple retention fields from longest retention tier
        # API requires these even when using lifetimes array
        longest_tier, longest_count = TierMatcher.get_longest_retention_tier(tiers)
        simple_lifetime_value = longest_count
        simple_lifetime_unit = TierMatcher.get_tier_lifetime_unit(longest_tier)

        # Build encryption config
        encryption_config = EncryptionConfigBuilder.build_config(
            params["preserve_source_encryption"],
            params.get("target_encryption"),
            params.get("target_encryption_key"),
            params.get("target_encryption_key_format"),
            params.get("target_encryption_inherit"),
        )

        # Build replication config
        repl_config = {
            "name": task_name,
            "direction": "PULL",
            "transport": "SSH",
            "ssh_credentials": ssh_credentials_id,
            "source_datasets": [source_dataset],
            "target_dataset": target_dataset,
            "recursive": recursive,
            "naming_schema": naming_schemas,
            "auto": True,
            "schedule": replication_schedule,
            "retention_policy": "CUSTOM",
            "lifetime_value": simple_lifetime_value,  # Set to longest tier
            "lifetime_unit": simple_lifetime_unit,
            "lifetimes": lifetimes,
            "readonly": "SET",
            "enabled": True,
        }
        repl_config.update(encryption_config)

        # Query existing task
        existing_task = self.api.query_task_by_name(task_name)

        if check_mode:
            if existing_task:
                return {
                    "changed": True,
                    "msg": f"Would update replication task '{task_name}'",
                    "config": repl_config,
                }
            else:
                return {
                    "changed": True,
                    "msg": f"Would create replication task '{task_name}'",
                    "config": repl_config,
                }

        # Create or update task
        if existing_task:
            task = self.api.update_task(existing_task["id"], repl_config)
            return {
                "changed": True,
                "msg": f"Remote replication policy updated for '{source_dataset}'",
                "task": task,
            }
        else:
            task = self.api.create_task(repl_config)
            return {
                "changed": True,
                "msg": f"Remote replication policy created for '{source_dataset}'",
                "task": task,
            }

    def remove_policy(self, task_name, check_mode):
        """Remove remote replication task.

        Args:
            task_name: Task name to remove
            check_mode: Whether running in check mode

        Returns:
            Result dict with changed flag and details
        """
        existing_task = self.api.query_task_by_name(task_name)

        if not existing_task:
            return {
                "changed": False,
                "msg": f"Replication task '{task_name}' does not exist",
            }

        if check_mode:
            return {
                "changed": True,
                "msg": f"Would delete replication task '{task_name}'",
                "task_id": existing_task["id"],
            }

        self.api.delete_task(existing_task["id"])
        return {
            "changed": True,
            "msg": f"Replication task '{task_name}' deleted",
            "deleted_task_id": existing_task["id"],
        }

    def _build_lifetimes(self, tiers_dict):
        """Build lifetimes array from tiers dict.

        Args:
            tiers_dict: Dict mapping tier names to retention counts

        Returns:
            List of lifetime dicts for API
        """
        lifetimes = []
        for tier_name, count in tiers_dict.items():
            lifetime_entry = {
                "schedule": TierMatcher.get_tier_schedule(tier_name),
                "lifetime_value": count,
                "lifetime_unit": TierMatcher.get_tier_lifetime_unit(tier_name),
            }
            lifetimes.append(lifetime_entry)
        return lifetimes


# ==============================================================================
# MAIN FUNCTION
# ==============================================================================


def main():
    """Ansible module entry point."""

    # Define module
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str"),
            source_dataset=dict(type="str", required=True),
            source_host=dict(type="str"),  # For documentation only
            target_dataset=dict(type="str", required=True),
            ssh_credentials_id=dict(type="int", required=True),
            tiers=dict(type="dict", required=True),
            recursive=dict(type="bool", required=True),
            preserve_source_encryption=dict(type="bool", default=True),
            target_encryption=dict(type="bool"),
            target_encryption_key=dict(type="str", no_log=True),
            target_encryption_key_format=dict(
                type="str", choices=["HEX", "PASSPHRASE"]
            ),
            target_encryption_inherit=dict(type="bool"),
            state=dict(type="str", default="present", choices=["absent", "present"]),
        ),
        supports_check_mode=True,
        mutually_exclusive=[
            ("target_encryption_key", "target_encryption_inherit"),
        ],
    )

    # Extract parameters
    name = module.params["name"]
    source_dataset = module.params["source_dataset"]
    target_dataset = module.params["target_dataset"]
    ssh_credentials_id = module.params["ssh_credentials_id"]
    tiers = module.params["tiers"]
    state = module.params["state"]
    preserve_source = module.params["preserve_source_encryption"]
    target_encryption = module.params.get("target_encryption")
    target_key = module.params.get("target_encryption_key")
    target_key_format = module.params.get("target_encryption_key_format")
    target_inherit = module.params.get("target_encryption_inherit")
    check_mode = module.check_mode

    # Generate name if not provided
    if not name:
        name = TaskNameGenerator.generate_name(source_dataset)
        module.params["name"] = name

    # Validate parameters
    if state == "present":
        if not tiers:
            module.fail_json(
                msg="At least one tier must be specified when state=present"
            )

        # Validate tier names
        try:
            TierMatcher.validate_tiers(tiers)
        except ValueError as e:
            module.fail_json(msg=str(e))

        # Validate retention counts
        for tier_name, count in tiers.items():
            if not isinstance(count, int) or count < 1:
                module.fail_json(
                    msg=f"Invalid retention count for tier '{tier_name}': {count}. Must be positive integer."
                )

        # Validate encryption config
        if preserve_source and (target_encryption or target_key):
            module.fail_json(
                msg="Cannot specify target_encryption options when preserve_source_encryption=True"
            )

        if target_encryption and not (target_key or target_inherit):
            module.fail_json(
                msg="target_encryption=True requires either target_encryption_key or target_encryption_inherit"
            )

    # Initialize
    try:
        mw = MW.client()
        api = ReplicationTaskAPI(mw)
        manager = RemoteReplicationPolicyManager(api)
    except Exception as e:
        module.fail_json(msg=f"Failed to initialize: {e}")

    # Execute
    try:
        if state == "present":
            result = manager.sync_policy(module.params, check_mode)
        else:
            result = manager.remove_policy(name, check_mode)

        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Error managing remote replication policy: {e}")


# Main
if __name__ == "__main__":
    main()
