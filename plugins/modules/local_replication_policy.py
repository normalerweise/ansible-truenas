#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage local push-based replication policies for TrueNAS datasets

DOCUMENTATION = """
---
module: local_replication_policy
short_description: Manage local push-based replication policies for TrueNAS datasets
description:
  - Manages local replication policies for ZFS datasets on TrueNAS SCALE.
  - Creates push-based replication tasks that replicate snapshots to different pools on the same machine.
  - Automatically binds to snapshot tasks for specified tiers.
  - One replication task manages all specified tiers for a dataset.
options:
  name:
    description:
      - Name for the replication task.
      - If not specified, automatically generated as auto-repl-<source_dataset>.
    type: str
  source_dataset:
    description:
      - Source dataset to replicate from.
      - Must have snapshot tasks created for the specified tiers.
    type: str
    required: true
  target_dataset:
    description:
      - Target dataset to replicate to (on different pool).
    type: str
    required: true
  tiers:
    description:
      - List of snapshot tiers to replicate.
      - Valid tiers are frequent, hourly, daily, weekly, monthly, yearly.
      - Must have corresponding snapshot tasks created.
    type: list
    elements: str
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
  - Automatically finds and binds to snapshot tasks for specified tiers.
  - Uses LOCAL transport (no SSH required).
  - Retention policy inherits from source snapshot tasks.
author:
  - "Norman (@normalerweise)"
"""

EXAMPLES = """
- name: Create local replication for critical data
  local_replication_policy:
    source_dataset: "tank/data"
    target_dataset: "backup_pool/replicas/data"
    tiers: ["hourly", "daily", "weekly"]
    recursive: true
    state: present

- name: Replicate with custom encryption at target
  local_replication_policy:
    source_dataset: "tank/data"
    target_dataset: "backup_pool/replicas/data"
    tiers: ["daily", "weekly"]
    recursive: true
    preserve_source_encryption: false
    target_encryption: true
    target_encryption_key: "{{ vault_backup_pool_key }}"
    target_encryption_key_format: "HEX"
    state: present

- name: Replicate with encryption inherited from parent
  local_replication_policy:
    source_dataset: "tank/data"
    target_dataset: "backup_pool/encrypted/replicas/data"
    tiers: ["daily"]
    recursive: false
    preserve_source_encryption: false
    target_encryption: true
    target_encryption_inherit: true
    state: present

- name: Remove local replication policy
  local_replication_policy:
    source_dataset: "tank/data"
    target_dataset: "backup_pool/replicas/data"
    tiers: []
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
    direction: "PUSH"
    transport: "LOCAL"
    source_datasets: ["tank/data"]
    target_dataset: "backup_pool/replicas/data"
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
            tiers: List of tier names

        Returns:
            List of naming schemas like ["auto-hourly-%Y-%m-%d_%H:%M", ...]
        """
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
            tiers: List of tier names to validate

        Returns:
            True if all valid

        Raises:
            ValueError if any invalid tier names
        """
        valid_tiers = set(TIER_CONFIGS.keys())
        invalid_tiers = [t for t in tiers if t not in valid_tiers]
        if invalid_tiers:
            raise ValueError(
                f"Invalid tier names: {', '.join(invalid_tiers)}. "
                f"Valid tiers: {', '.join(sorted(valid_tiers))}"
            )
        return True


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


class SnapshotTaskFinder:
    """Finds snapshot tasks for binding in local replication."""

    def __init__(self, mw):
        """Initialize snapshot task finder.

        Args:
            mw: MiddleWare client instance
        """
        self.mw = mw

    def find_snapshot_tasks(self, source_dataset, tiers):
        """Find snapshot task IDs for specified tiers.

        Args:
            source_dataset: Source dataset name
            tiers: List of tier names

        Returns:
            List of snapshot task IDs

        Raises:
            Exception if required snapshot tasks not found
        """
        task_ids = []
        missing_tiers = []

        for tier in tiers:
            filters = [
                ["dataset", "=", source_dataset],
                ["naming_schema", "~", f"^auto-{tier}-"],
            ]
            try:
                tasks = self.mw.call("pool.snapshottask.query", filters)
                if not tasks:
                    missing_tiers.append(tier)
                else:
                    task_ids.append(tasks[0]["id"])
            except Exception as e:
                raise Exception(
                    f"Failed to query snapshot tasks for dataset '{source_dataset}': {e}"
                )

        if missing_tiers:
            raise Exception(
                f"No snapshot tasks found for tiers {missing_tiers} on dataset '{source_dataset}'. "
                f"Create snapshot policy first using pool_snapshot_policy module."
            )

        return task_ids


# ==============================================================================
# POLICY MANAGER
# ==============================================================================


class LocalReplicationPolicyManager:
    """Manages local push-based replication policy."""

    def __init__(self, api, snapshot_finder):
        """Initialize policy manager.

        Args:
            api: ReplicationTaskAPI instance
            snapshot_finder: SnapshotTaskFinder instance
        """
        self.api = api
        self.snapshot_finder = snapshot_finder

    def sync_policy(self, params, check_mode):
        """Synchronize local replication policy.

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
        tiers = params["tiers"]
        recursive = params["recursive"]

        # Find snapshot task IDs
        snapshot_task_ids = self.snapshot_finder.find_snapshot_tasks(
            source_dataset, tiers
        )

        # Build naming schemas
        naming_schemas = TierMatcher.build_naming_schemas(tiers)

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
            "direction": "PUSH",
            "transport": "LOCAL",
            "source_datasets": [source_dataset],
            "target_dataset": target_dataset,
            "recursive": recursive,
            "periodic_snapshot_tasks": snapshot_task_ids,
            "also_include_naming_schema": naming_schemas,
            "auto": True,
            "retention_policy": "SOURCE",
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
                "msg": f"Replication policy updated for '{source_dataset}'",
                "task": task,
            }
        else:
            task = self.api.create_task(repl_config)
            return {
                "changed": True,
                "msg": f"Replication policy created for '{source_dataset}'",
                "task": task,
            }

    def remove_policy(self, task_name, check_mode):
        """Remove local replication task.

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
            target_dataset=dict(type="str", required=True),
            tiers=dict(type="list", elements="str", required=True),
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
        snapshot_finder = SnapshotTaskFinder(mw)
        manager = LocalReplicationPolicyManager(api, snapshot_finder)
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
        module.fail_json(msg=f"Error managing local replication policy: {e}")


# Main
if __name__ == "__main__":
    main()
