#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage multi-tier snapshot policies for TrueNAS datasets

DOCUMENTATION = """
---
module: pool_snapshot_policy
short_description: Manage multi-tier snapshot policies for TrueNAS datasets
description:
  - Manages snapshot policies for ZFS datasets on TrueNAS SCALE.
  - Creates, updates, and deletes multiple snapshot tasks to implement
    multi-tier retention policies (hourly, daily, weekly, monthly, yearly).
  - Provides strict synchronization ensuring snapshot tasks exactly match the policy.
  - Policy-managed tasks are identified by the 'auto-' prefix in naming schema.
options:
  dataset:
    description:
      - The name of the dataset to manage snapshot policy for.
      - This can be a pool, ZFS dataset, or zvol.
    type: str
    required: true
  snapshot_policy:
    description:
      - Dictionary defining the snapshot policy with retention counts per tier.
      - Each tier is optional. Omit tiers you don't want.
      - The module determines optimal schedules for each tier automatically.
    type: dict
    suboptions:
      frequent:
        description:
          - Number of frequent (15-minute) snapshots to keep.
          - Schedule runs every 15 minutes.
        type: int
      hourly:
        description:
          - Number of hourly snapshots to keep.
          - Schedule runs at the top of every hour.
        type: int
      daily:
        description:
          - Number of daily snapshots to keep.
          - Schedule runs daily at midnight.
        type: int
      weekly:
        description:
          - Number of weekly snapshots to keep.
          - Schedule runs every Sunday at midnight.
        type: int
      monthly:
        description:
          - Number of monthly snapshots to keep.
          - Schedule runs on the 1st of each month at midnight.
        type: int
      yearly:
        description:
          - Number of yearly snapshots to keep.
          - Schedule runs on January 1st at midnight.
        type: int
  recursive:
    description:
      - Whether to take recursive snapshots (include child datasets).
    type: bool
    required: true
  state:
    description:
      - Whether the policy should be applied or removed.
      - C(present) ensures snapshot tasks match the policy (create, update, delete as needed).
      - C(absent) removes all policy-managed snapshot tasks for the dataset.
    type: str
    choices: [ absent, present ]
    default: present
version_added: 1.6.0
notes:
  - This module manages all snapshot tasks with 'auto-' prefix in their naming schema.
  - Tasks are identified by dataset and tier name prefix in naming schema.
  - Strict synchronization means tasks not in policy will be deleted.
  - Snapshots follow naming pattern auto-<tier>-%Y-%m-%d_%H:%M
author:
  - "Norman (@normalerweise)"
"""

EXAMPLES = """
- name: Create a complete snapshot policy
  pool_snapshot_policy:
    dataset: "tank/data"
    snapshot_policy:
      hourly: 24
      daily: 30
      weekly: 8
      monthly: 12
      yearly: 2
    recursive: true
    state: present

- name: Create a simple daily snapshot policy
  pool_snapshot_policy:
    dataset: "tank/backups"
    snapshot_policy:
      daily: 7
    recursive: false
    state: present

- name: Add frequent snapshots to existing policy
  pool_snapshot_policy:
    dataset: "tank/volatile"
    snapshot_policy:
      frequent: 4
      hourly: 12
    recursive: false
    state: present

- name: Remove all policy-managed snapshots
  pool_snapshot_policy:
    dataset: "tank/data"
    recursive: true
    state: absent

- name: Update policy (remove weekly, add yearly)
  pool_snapshot_policy:
    dataset: "tank/data"
    snapshot_policy:
      hourly: 24
      daily: 30
      monthly: 12
      yearly: 5
    recursive: true
    state: present
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
  sample: "Policy synchronized: 2 tasks created, 1 updated, 1 deleted"
created_tasks:
  description: List of snapshot tasks that were created
  type: list
  returned: when state=present and tasks were created
  sample:
    - id: 123
      dataset: "tank/data"
      naming_schema: "auto-hourly-%Y-%m-%d_%H:%M"
      lifetime_value: 24
      lifetime_unit: "HOUR"
updated_tasks:
  description: List of snapshot tasks that were updated
  type: list
  returned: when state=present and tasks were updated
  sample:
    - id: 124
      dataset: "tank/data"
      naming_schema: "auto-daily-%Y-%m-%d_%H:%M"
      lifetime_value: 30
      lifetime_unit: "DAY"
deleted_task_ids:
  description: List of task IDs that were deleted
  type: list
  returned: when tasks were deleted
  sample: [125, 126]
check_mode_changes:
  description: Summary of what would change (only in check mode)
  type: dict
  returned: when check mode is enabled
  sample:
    to_create: ["hourly", "daily"]
    to_update: ["weekly"]
    to_delete: [123]
"""

import re

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
# DATA CLASSES
# ==============================================================================


class TierDefinition:
    """Encapsulates tier-specific configuration."""

    def __init__(self, name, count):
        """Initialize tier definition.

        Args:
            name: Tier name (must be key in TIER_CONFIGS)
            count: Number of snapshots to retain
        """
        if name not in TIER_CONFIGS:
            raise ValueError(
                f"Invalid tier name '{name}'. Valid tiers: {', '.join(TIER_CONFIGS.keys())}"
            )

        self.name = name
        self.count = count
        self._config = TIER_CONFIGS[name]

    def _get_schedule(self):
        """Return cron schedule for this tier."""
        return self._config["schedule"]

    def _get_lifetime_unit(self):
        """Return lifetime unit for this tier."""
        return self._config["lifetime_unit"]

    @property
    def naming_schema(self):
        """Return naming schema for this tier."""
        return f"auto-{self.name}-%Y-%m-%d_%H:%M"

    @property
    def schedule(self):
        """Return schedule dict."""
        return self._get_schedule()

    @property
    def lifetime_unit(self):
        """Return lifetime unit string."""
        return self._get_lifetime_unit()

    def to_api_config(self, dataset, recursive):
        """Convert to TrueNAS API payload.

        Args:
            dataset: Dataset name
            recursive: Whether to snapshot recursively

        Returns:
            Dict suitable for pool.snapshottask.create or .update
        """
        schedule = self.schedule
        return {
            "dataset": dataset,
            "recursive": recursive,
            "lifetime_value": self.count,
            "lifetime_unit": self.lifetime_unit,
            "naming_schema": self.naming_schema,
            "enabled": True,
            "allow_empty": True,
            "schedule": {
                "minute": schedule["minute"],
                "hour": schedule["hour"],
                "dom": schedule["dom"],
                "month": schedule["month"],
                "dow": schedule["dow"],
            },
        }


# ==============================================================================
# HELPER CLASSES
# ==============================================================================


class SnapshotTaskMatcher:
    """Identifies and queries policy-managed snapshot tasks."""

    @staticmethod
    def build_query_filters(dataset, tier_name=None):
        """Build API query filters.

        Args:
            dataset: Dataset name
            tier_name: Optional specific tier to filter by

        Returns:
            List of filter conditions for API query
        """
        filters = [["dataset", "=", dataset]]

        if tier_name:
            filters.append(["naming_schema", "~", f"^auto-{tier_name}-"])
        else:
            # Match all auto- prefixed tasks
            filters.append(["naming_schema", "~", "^auto-"])

        return filters

    @staticmethod
    def is_policy_managed(task):
        """Check if task is managed by this policy module.

        Args:
            task: Task dict from API

        Returns:
            True if task has auto- prefix
        """
        naming_schema = task.get("naming_schema", "")
        return naming_schema.startswith("auto-")

    @staticmethod
    def extract_tier_name(task):
        """Extract tier name from task naming schema.

        Args:
            task: Task dict from API

        Returns:
            Tier name (e.g., "hourly", "daily") or None if not parseable
        """
        naming_schema = task.get("naming_schema", "")
        # Pattern: auto-<tier>-%Y-%m-%d_%H:%M
        match = re.match(r"^auto-([a-z]+)-", naming_schema)
        if match:
            return match.group(1)
        return None


class StateDiff:
    """Represents the difference between current and desired state."""

    def __init__(self):
        """Initialize empty diff."""
        self.to_create = []  # List[TierDefinition]
        self.to_update = []  # List[(task_id, TierDefinition)]
        self.to_delete = []  # List[task_id]

    def has_changes(self):
        """Check if any changes are needed."""
        return bool(self.to_create or self.to_update or self.to_delete)

    def summary(self):
        """Return summary dict for reporting."""
        return {
            "to_create": [tier.name for tier in self.to_create],
            "to_update": [(task_id, tier.name) for task_id, tier in self.to_update],
            "to_delete": self.to_delete,
        }


class StateComparator:
    """Compares current vs desired state and calculates diff."""

    @staticmethod
    def calculate_diff(current_tasks, desired_tiers, dataset):
        """Calculate what needs to change.

        Args:
            current_tasks: List of current task dicts from API
            desired_tiers: List of TierDefinition objects
            dataset: Dataset name

        Returns:
            StateDiff object
        """
        diff = StateDiff()

        # Build index of current tasks by tier name
        current_by_tier = {}
        for task in current_tasks:
            tier_name = SnapshotTaskMatcher.extract_tier_name(task)
            if tier_name:
                current_by_tier[tier_name] = task

        # Build index of desired tiers by name
        desired_by_tier = {tier.name: tier for tier in desired_tiers}

        # Find tiers to create or update
        for tier_name, tier_def in desired_by_tier.items():
            if tier_name not in current_by_tier:
                # Tier doesn't exist, need to create
                diff.to_create.append(tier_def)
            else:
                # Tier exists, check if it needs update
                current_task = current_by_tier[tier_name]
                if StateComparator._needs_update(current_task, tier_def):
                    diff.to_update.append((current_task["id"], tier_def))

        # Find tasks to delete (in current but not in desired)
        for tier_name, task in current_by_tier.items():
            if tier_name not in desired_by_tier:
                diff.to_delete.append(task["id"])

        return diff

    @staticmethod
    def _needs_update(task, tier_def):
        """Check if existing task needs update.

        Args:
            task: Current task dict from API
            tier_def: Desired TierDefinition

        Returns:
            True if task needs to be updated
        """
        # Check lifetime
        if task.get("lifetime_value") != tier_def.count:
            return True
        if task.get("lifetime_unit") != tier_def.lifetime_unit:
            return True

        # Check naming schema
        if task.get("naming_schema") != tier_def.naming_schema:
            return True

        # Check schedule (each field)
        schedule = tier_def.schedule
        task_schedule = task.get("schedule", {})

        schedule_fields = ["minute", "hour", "dom", "month", "dow"]
        for field in schedule_fields:
            if task_schedule.get(field) != schedule.get(field):
                return True

        return False


class SnapshotTaskAPI:
    """Wrapper for TrueNAS snapshot task API operations."""

    def __init__(self, mw):
        """Initialize API wrapper.

        Args:
            mw: MiddleWare client instance
        """
        self.mw = mw

    def query_tasks(self, dataset):
        """Query all policy-managed tasks for a dataset.

        Args:
            dataset: Dataset name

        Returns:
            List of task dicts

        Raises:
            Exception on API error
        """
        try:
            filters = SnapshotTaskMatcher.build_query_filters(dataset)
            return self.mw.call("pool.snapshottask.query", filters)
        except Exception as e:
            raise Exception(
                f"Failed to query snapshot tasks for dataset '{dataset}': {e}"
            )

    def create_task(self, config):
        """Create a new snapshot task.

        Args:
            config: Task configuration dict

        Returns:
            Created task dict

        Raises:
            Exception on API error
        """
        try:
            return self.mw.call("pool.snapshottask.create", config)
        except Exception as e:
            dataset = config.get("dataset", "unknown")
            tier = config.get("naming_schema", "unknown")
            raise Exception(
                f"Failed to create snapshot task for '{dataset}' ({tier}): {e}"
            )

    def update_task(self, task_id, config):
        """Update an existing snapshot task.

        Args:
            task_id: Task ID to update
            config: New task configuration dict

        Returns:
            Updated task dict

        Raises:
            Exception on API error
        """
        try:
            return self.mw.call("pool.snapshottask.update", task_id, config)
        except Exception as e:
            raise Exception(f"Failed to update snapshot task {task_id}: {e}")

    def delete_task(self, task_id):
        """Delete a snapshot task.

        Args:
            task_id: Task ID to delete

        Returns:
            True on success

        Raises:
            Exception on API error
        """
        try:
            return self.mw.call("pool.snapshottask.delete", task_id)
        except Exception as e:
            raise Exception(f"Failed to delete snapshot task {task_id}: {e}")


class PolicyManager:
    """Orchestrates policy synchronization."""

    def __init__(self, api):
        """Initialize policy manager.

        Args:
            api: SnapshotTaskAPI instance
        """
        self.api = api

    def sync_policy(self, dataset, policy, recursive, check_mode):
        """Synchronize policy to desired state.

        Args:
            dataset: Dataset name
            policy: Policy dict (tier: count)
            recursive: Whether to snapshot recursively
            check_mode: Whether to run in check mode

        Returns:
            Result dict with changed flag and details
        """
        # Parse policy into tier definitions
        tier_defs = self._parse_policy(policy)

        # Query current state
        current_tasks = self.api.query_tasks(dataset)

        # Calculate diff
        diff = StateComparator.calculate_diff(current_tasks, tier_defs, dataset)

        # Apply changes or return what would change
        if check_mode:
            return self._format_check_mode_result(diff)
        else:
            return self._apply_changes(diff, dataset, recursive)

    def remove_policy(self, dataset, check_mode):
        """Remove all policy-managed tasks for dataset.

        Args:
            dataset: Dataset name
            check_mode: Whether to run in check mode

        Returns:
            Result dict with changed flag and details
        """
        current_tasks = self.api.query_tasks(dataset)

        if check_mode:
            return {
                "changed": len(current_tasks) > 0,
                "msg": f"Would delete {len(current_tasks)} snapshot tasks",
                "check_mode_changes": {
                    "to_delete": [task["id"] for task in current_tasks]
                },
            }
        else:
            deleted_ids = []
            for task in current_tasks:
                self.api.delete_task(task["id"])
                deleted_ids.append(task["id"])

            return {
                "changed": len(deleted_ids) > 0,
                "msg": f"Deleted {len(deleted_ids)} snapshot tasks",
                "deleted_task_ids": deleted_ids,
            }

    def _parse_policy(self, policy):
        """Convert user policy dict to tier definitions.

        Args:
            policy: Dict mapping tier names to counts

        Returns:
            List of TierDefinition objects
        """
        tiers = []
        for tier_name, count in policy.items():
            if count is not None and count > 0:
                tiers.append(TierDefinition(tier_name, count))
        return tiers

    def _apply_changes(self, diff, dataset, recursive):
        """Apply the calculated changes.

        Args:
            diff: StateDiff object
            dataset: Dataset name
            recursive: Whether to snapshot recursively

        Returns:
            Result dict with details of changes made
        """
        created = []
        updated = []
        deleted = []

        # Create new tasks
        for tier_def in diff.to_create:
            config = tier_def.to_api_config(dataset, recursive)
            task = self.api.create_task(config)
            created.append(task)

        # Update existing tasks
        for task_id, tier_def in diff.to_update:
            config = tier_def.to_api_config(dataset, recursive)
            task = self.api.update_task(task_id, config)
            updated.append(task)

        # Delete obsolete tasks
        for task_id in diff.to_delete:
            self.api.delete_task(task_id)
            deleted.append(task_id)

        # Build result message
        parts = []
        if created:
            parts.append(f"{len(created)} created")
        if updated:
            parts.append(f"{len(updated)} updated")
        if deleted:
            parts.append(f"{len(deleted)} deleted")

        msg = (
            "Policy synchronized: " + ", ".join(parts) if parts else "No changes needed"
        )

        result = {
            "changed": diff.has_changes(),
            "msg": msg,
        }

        if created:
            result["created_tasks"] = created
        if updated:
            result["updated_tasks"] = updated
        if deleted:
            result["deleted_task_ids"] = deleted

        return result

    def _format_check_mode_result(self, diff):
        """Format result for check mode.

        Args:
            diff: StateDiff object

        Returns:
            Result dict describing what would change
        """
        summary = diff.summary()

        parts = []
        if summary["to_create"]:
            parts.append(f"{len(summary['to_create'])} would be created")
        if summary["to_update"]:
            parts.append(f"{len(summary['to_update'])} would be updated")
        if summary["to_delete"]:
            parts.append(f"{len(summary['to_delete'])} would be deleted")

        msg = (
            "Would synchronize policy: " + ", ".join(parts)
            if parts
            else "No changes needed"
        )

        return {
            "changed": diff.has_changes(),
            "msg": msg,
            "check_mode_changes": summary,
        }


# ==============================================================================
# MAIN FUNCTION
# ==============================================================================


def main():
    """Ansible module entry point."""

    # Define module
    module = AnsibleModule(
        argument_spec=dict(
            dataset=dict(type="str", required=True),
            snapshot_policy=dict(
                type="dict",
                options=dict(
                    frequent=dict(type="int"),
                    hourly=dict(type="int"),
                    daily=dict(type="int"),
                    weekly=dict(type="int"),
                    monthly=dict(type="int"),
                    yearly=dict(type="int"),
                ),
            ),
            recursive=dict(type="bool", required=True),
            state=dict(type="str", default="present", choices=["absent", "present"]),
        ),
        required_if=[
            ["state", "present", ["snapshot_policy"], True],
        ],
        supports_check_mode=True,
    )

    # Extract parameters
    dataset = module.params["dataset"]
    policy = module.params["snapshot_policy"]
    recursive = module.params["recursive"]
    state = module.params["state"]
    check_mode = module.check_mode

    # Validate when state=present
    if state == "present":
        if not policy or not any(v for v in policy.values() if v is not None and v > 0):
            module.fail_json(
                msg="At least one tier with a positive count must be specified in snapshot_policy when state=present"
            )

        # Validate tier names
        valid_tiers = set(TIER_CONFIGS.keys())
        for tier_name in policy.keys():
            if tier_name not in valid_tiers:
                module.fail_json(
                    msg=f"Invalid tier name '{tier_name}'. Valid tiers: {', '.join(sorted(valid_tiers))}"
                )

    # Initialize
    try:
        mw = MW.client()
        api = SnapshotTaskAPI(mw)
        manager = PolicyManager(api)
    except Exception as e:
        module.fail_json(msg=f"Failed to initialize: {e}")

    # Execute
    try:
        if state == "present":
            result = manager.sync_policy(dataset, policy, recursive, check_mode)
        else:
            result = manager.remove_policy(dataset, check_mode)

        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Error managing snapshot policy for '{dataset}': {e}")


# Main
if __name__ == "__main__":
    main()
