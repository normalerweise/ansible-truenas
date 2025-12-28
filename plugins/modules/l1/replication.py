#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Create and maintain ZFS replication tasks.

DOCUMENTATION = """
---
module: replication
short_description: Manage ZFS replication tasks
description:
  - Creates, updates, and deletes ZFS replication tasks in TrueNAS Scale.
  - Supports SSH and LOCAL transports (SSH+NETCAT is not implemented).
  - Push or pull replication with various retention policies.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  name:
    description:
      - Name for the replication task.
    type: str
    required: true
  direction:
    description:
      - Whether task will PUSH or PULL snapshots.
    type: str
    choices: ['PUSH', 'PULL']
    required: true
  transport:
    description:
      - Method of snapshot transfer.
      - SSH transfers via SSH connection.
      - LOCAL replicates to or from localhost.
      - SSH+NETCAT is not implemented.
    type: str
    choices: ['SSH', 'LOCAL']
    required: true
  ssh_credentials:
    description:
      - Keychain Credential ID of type SSH_CREDENTIALS.
      - Required for SSH transport.
    type: int
  sudo:
    description:
      - SSH transport should use sudo to run zfs command on remote machine.
      - Requires passwordless sudo.
    type: bool
    default: false
  source_datasets:
    description:
      - List of datasets to replicate snapshots from.
    type: list
    elements: str
    required: true
  target_dataset:
    description:
      - Dataset to put snapshots into.
    type: str
    required: true
  recursive:
    description:
      - Whether to recursively replicate child datasets.
    type: bool
    required: true
  exclude:
    description:
      - List of dataset patterns to exclude from replication.
    type: list
    elements: str
    default: []
  properties:
    description:
      - Send dataset properties along with snapshots.
    type: bool
    default: true
  properties_exclude:
    description:
      - List of dataset property names to exclude from replication.
    type: list
    elements: str
    default: []
  properties_override:
    description:
      - Dictionary mapping dataset property names to override values during replication.
    type: dict
    default: {}
  replicate:
    description:
      - Whether to use full ZFS replication.
    type: bool
    default: false
  encryption:
    description:
      - Whether to enable encryption for replicated datasets.
    type: bool
    default: false
  encryption_inherit:
    description:
      - Whether replicated datasets should inherit encryption from parent.
      - Only applicable when encryption is enabled.
    type: bool
  encryption_key:
    description:
      - Encryption key for replicated datasets.
      - Only applicable when encryption is enabled.
    type: str
  encryption_key_format:
    description:
      - Format of the encryption key.
      - Only applicable when encryption is enabled.
    type: str
    choices: ['HEX', 'PASSPHRASE']
  encryption_key_location:
    description:
      - Filesystem path where encryption key is stored.
      - Only applicable when encryption is enabled.
    type: str
  periodic_snapshot_tasks:
    description:
      - List of periodic snapshot task IDs for push replication.
      - Only push replication tasks can be bound to periodic snapshot tasks.
    type: list
    elements: int
    default: []
  naming_schema:
    description:
      - List of naming schemas for pull replication.
    type: list
    elements: str
    default: []
  also_include_naming_schema:
    description:
      - List of naming schemas for push replication.
    type: list
    elements: str
    default: []
  name_regex:
    description:
      - Replicate all snapshots matching this regular expression.
    type: str
  auto:
    description:
      - Allow replication to run automatically on schedule or after bound periodic snapshot task.
    type: bool
    required: true
  schedule:
    description:
      - Cron schedule for automatic replication.
      - Only for auto tasks without bound periodic snapshot tasks.
    type: dict
    suboptions:
      minute:
        description: Minute when task should run (cron format).
        type: str
        default: "00"
      hour:
        description: Hour when task should run (cron format).
        type: str
        default: "*"
      dom:
        description: Day of month when task should run (cron format).
        type: str
        default: "*"
      month:
        description: Month when task should run (cron format).
        type: str
        default: "*"
      dow:
        description: Day of week when task should run (cron format).
        type: str
        default: "*"
      begin:
        description: Start time for time window in HH:MM format.
        type: str
        default: "00:00"
      end:
        description: End time for time window in HH:MM format.
        type: str
        default: "23:59"
  restrict_schedule:
    description:
      - Restricts when replication with bound periodic snapshot tasks runs.
    type: dict
    suboptions:
      minute:
        description: Minute when task should run (cron format).
        type: str
        default: "00"
      hour:
        description: Hour when task should run (cron format).
        type: str
        default: "*"
      dom:
        description: Day of month when task should run (cron format).
        type: str
        default: "*"
      month:
        description: Month when task should run (cron format).
        type: str
        default: "*"
      dow:
        description: Day of week when task should run (cron format).
        type: str
        default: "*"
      begin:
        description: Start time for time window in HH:MM format.
        type: str
        default: "00:00"
      end:
        description: End time for time window in HH:MM format.
        type: str
        default: "23:59"
  only_matching_schedule:
    description:
      - Only replicate snapshots matching schedule or restrict_schedule.
    type: bool
    default: false
  allow_from_scratch:
    description:
      - Destroy all target snapshots and replicate from scratch if no matches.
    type: bool
    default: false
  readonly:
    description:
      - Controls destination datasets readonly property.
      - SET - Set all destination datasets to readonly=on after replication.
      - REQUIRE - Require all existing destination datasets to have readonly=on.
      - IGNORE - Do not enforce readonly behavior.
    type: str
    choices: ['SET', 'REQUIRE', 'IGNORE']
    default: 'SET'
  hold_pending_snapshots:
    description:
      - Prevent source snapshots from being deleted if replication fails.
    type: bool
    default: false
  retention_policy:
    description:
      - How to delete old snapshots on target side.
      - SOURCE - Delete snapshots absent on source.
      - CUSTOM - Delete snapshots older than lifetime_value/lifetime_unit.
      - NONE - Do not delete any snapshots.
    type: str
    choices: ['SOURCE', 'CUSTOM', 'NONE']
    required: true
  lifetime_value:
    description:
      - Number of time units to retain snapshots.
      - Required when retention_policy is CUSTOM.
    type: int
  lifetime_unit:
    description:
      - Time unit for snapshot retention.
      - Required when retention_policy is CUSTOM.
    type: str
    choices: ['HOUR', 'DAY', 'WEEK', 'MONTH', 'YEAR']
  large_block:
    description:
      - Enable large block support for ZFS send streams.
    type: bool
    default: true
  embed:
    description:
      - Enable embedded block support for ZFS send streams.
    type: bool
    default: false
  compressed:
    description:
      - Enable compressed ZFS send streams.
    type: bool
    default: true
  retries:
    description:
      - Number of retries before considering replication failed.
    type: int
    default: 5
  logging_level:
    description:
      - Log level for replication task execution.
    type: str
    choices: ['DEBUG', 'INFO', 'WARNING', 'ERROR']
  enabled:
    description:
      - Whether this replication task is enabled.
    type: bool
    default: true
  state:
    description:
      - Whether the task should exist or not.
    type: str
    choices: ['absent', 'present']
    default: present
notes:
  - SSH+NETCAT transport is not implemented (netcat_* parameters are ignored).
  - SSH compression and speed_limit options are not implemented.
  - Advanced lifetimes array is not implemented (use lifetime_value/lifetime_unit).
version_added: 1.6.0
"""

EXAMPLES = """
- name: Create local replication task
  normalerweise.truenas.replication:
    name: "Local backup replication"
    direction: PUSH
    transport: LOCAL
    source_datasets:
      - tank/data
    target_dataset: backup/data
    recursive: true
    auto: false
    retention_policy: SOURCE

- name: Create SSH push replication with periodic snapshots
  normalerweise.truenas.replication:
    name: "Offsite backup"
    direction: PUSH
    transport: SSH
    ssh_credentials: 1
    sudo: true
    source_datasets:
      - tank/important
    target_dataset: remote/important
    recursive: true
    exclude:
      - tank/important/temp
    periodic_snapshot_tasks:
      - 5
    auto: true
    retention_policy: CUSTOM
    lifetime_value: 30
    lifetime_unit: DAY
    readonly: SET
    enabled: true

- name: Create pull replication with schedule
  normalerweise.truenas.replication:
    name: "Pull from remote"
    direction: PULL
    transport: SSH
    ssh_credentials: 2
    source_datasets:
      - remote/dataset
    target_dataset: local/dataset
    recursive: false
    naming_schema:
      - "auto-%Y-%m-%d_%H-%M"
    auto: true
    schedule:
      minute: "0"
      hour: "2"
      dom: "*"
      month: "*"
      dow: "*"
    retention_policy: NONE
    enabled: true

- name: Delete replication task
  normalerweise.truenas.replication:
    name: "Old replication"
    state: absent
"""

RETURN = """
task:
  description: The replication task configuration.
  type: dict
  returned: success when state is present
  sample:
    id: 1
    name: "Local backup replication"
    direction: "PUSH"
    transport: "LOCAL"
    source_datasets:
      - "tank/data"
    target_dataset: "backup/data"
    recursive: true
    auto: false
    retention_policy: "SOURCE"
    enabled: true
deleted_task:
  description: The deleted task information.
  type: dict
  returned: success when state is absent and task existed
"""

from ansible.module_utils.basic import AnsibleModule
from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            direction=dict(type="str", choices=["PUSH", "PULL"], required=True),
            transport=dict(type="str", choices=["SSH", "LOCAL"], required=True),
            ssh_credentials=dict(type="int"),
            sudo=dict(type="bool", default=False),
            source_datasets=dict(type="list", elements="str", required=True),
            target_dataset=dict(type="str", required=True),
            recursive=dict(type="bool", required=True),
            exclude=dict(type="list", elements="str", default=[]),
            properties=dict(type="bool", default=True),
            properties_exclude=dict(type="list", elements="str", default=[]),
            properties_override=dict(type="dict", default={}),
            replicate=dict(type="bool", default=False),
            encryption=dict(type="bool", default=False),
            encryption_inherit=dict(type="bool"),
            encryption_key=dict(type="str", no_log=True),
            encryption_key_format=dict(type="str", choices=["HEX", "PASSPHRASE"]),
            encryption_key_location=dict(type="str"),
            periodic_snapshot_tasks=dict(type="list", elements="int", default=[]),
            naming_schema=dict(type="list", elements="str", default=[]),
            also_include_naming_schema=dict(type="list", elements="str", default=[]),
            name_regex=dict(type="str"),
            auto=dict(type="bool", required=True),
            schedule=dict(
                type="dict",
                options=dict(
                    minute=dict(type="str", default="00"),
                    hour=dict(type="str", default="*"),
                    dom=dict(type="str", default="*"),
                    month=dict(type="str", default="*"),
                    dow=dict(type="str", default="*"),
                    begin=dict(type="str", default="00:00"),
                    end=dict(type="str", default="23:59"),
                ),
            ),
            restrict_schedule=dict(
                type="dict",
                options=dict(
                    minute=dict(type="str", default="00"),
                    hour=dict(type="str", default="*"),
                    dom=dict(type="str", default="*"),
                    month=dict(type="str", default="*"),
                    dow=dict(type="str", default="*"),
                    begin=dict(type="str", default="00:00"),
                    end=dict(type="str", default="23:59"),
                ),
            ),
            only_matching_schedule=dict(type="bool", default=False),
            allow_from_scratch=dict(type="bool", default=False),
            readonly=dict(
                type="str", choices=["SET", "REQUIRE", "IGNORE"], default="SET"
            ),
            hold_pending_snapshots=dict(type="bool", default=False),
            retention_policy=dict(
                type="str", choices=["SOURCE", "CUSTOM", "NONE"], required=True
            ),
            lifetime_value=dict(type="int"),
            lifetime_unit=dict(
                type="str", choices=["HOUR", "DAY", "WEEK", "MONTH", "YEAR"]
            ),
            large_block=dict(type="bool", default=True),
            embed=dict(type="bool", default=False),
            compressed=dict(type="bool", default=True),
            retries=dict(type="int", default=5),
            logging_level=dict(
                type="str", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            enabled=dict(type="bool", default=True),
            state=dict(type="str", default="present", choices=["absent", "present"]),
        ),
        supports_check_mode=True,
        required_if=[
            ("transport", "SSH", ["ssh_credentials"]),
            ("retention_policy", "CUSTOM", ["lifetime_value", "lifetime_unit"]),
        ],
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Extract parameters
    name = module.params["name"]
    state = module.params["state"]

    # Look up existing task by name
    try:
        existing_tasks = mw.call("replication.query", [["name", "=", name]])
        task_info = existing_tasks[0] if existing_tasks else None
    except Exception as e:
        module.fail_json(msg=f"Error looking up replication task: {e}")

    if state == "absent":
        if task_info is None:
            # Task doesn't exist, nothing to do
            result["changed"] = False
        else:
            # Delete the task
            if module.check_mode:
                result["msg"] = "Would have deleted replication task."
                result["deleted_task"] = task_info
            else:
                try:
                    mw.call("replication.delete", task_info["id"])
                    result["deleted_task"] = task_info
                except Exception as e:
                    module.fail_json(msg=f"Error deleting replication task: {e}")
            result["changed"] = True

    else:  # state == 'present'
        # Build the configuration
        config = {
            "name": name,
            "direction": module.params["direction"],
            "transport": module.params["transport"],
            "source_datasets": module.params["source_datasets"],
            "target_dataset": module.params["target_dataset"],
            "recursive": module.params["recursive"],
            "auto": module.params["auto"],
            "retention_policy": module.params["retention_policy"],
        }

        # Add optional parameters
        if module.params["ssh_credentials"] is not None:
            config["ssh_credentials"] = module.params["ssh_credentials"]

        if module.params["sudo"] is not None:
            config["sudo"] = module.params["sudo"]

        if module.params["exclude"]:
            config["exclude"] = module.params["exclude"]

        if module.params["properties"] is not None:
            config["properties"] = module.params["properties"]

        if module.params["properties_exclude"]:
            config["properties_exclude"] = module.params["properties_exclude"]

        if module.params["properties_override"]:
            config["properties_override"] = module.params["properties_override"]

        if module.params["replicate"] is not None:
            config["replicate"] = module.params["replicate"]

        if module.params["encryption"] is not None:
            config["encryption"] = module.params["encryption"]

        if module.params["encryption_inherit"] is not None:
            config["encryption_inherit"] = module.params["encryption_inherit"]

        if module.params["encryption_key"] is not None:
            config["encryption_key"] = module.params["encryption_key"]

        if module.params["encryption_key_format"] is not None:
            config["encryption_key_format"] = module.params["encryption_key_format"]

        if module.params["encryption_key_location"] is not None:
            config["encryption_key_location"] = module.params["encryption_key_location"]

        if module.params["periodic_snapshot_tasks"]:
            config["periodic_snapshot_tasks"] = module.params["periodic_snapshot_tasks"]

        if module.params["naming_schema"]:
            config["naming_schema"] = module.params["naming_schema"]

        if module.params["also_include_naming_schema"]:
            config["also_include_naming_schema"] = module.params[
                "also_include_naming_schema"
            ]

        if module.params["name_regex"] is not None:
            config["name_regex"] = module.params["name_regex"]

        if module.params["schedule"] is not None:
            config["schedule"] = module.params["schedule"]

        if module.params["restrict_schedule"] is not None:
            config["restrict_schedule"] = module.params["restrict_schedule"]

        if module.params["only_matching_schedule"] is not None:
            config["only_matching_schedule"] = module.params["only_matching_schedule"]

        if module.params["allow_from_scratch"] is not None:
            config["allow_from_scratch"] = module.params["allow_from_scratch"]

        if module.params["readonly"] is not None:
            config["readonly"] = module.params["readonly"]

        if module.params["hold_pending_snapshots"] is not None:
            config["hold_pending_snapshots"] = module.params["hold_pending_snapshots"]

        if module.params["lifetime_value"] is not None:
            config["lifetime_value"] = module.params["lifetime_value"]

        if module.params["lifetime_unit"] is not None:
            config["lifetime_unit"] = module.params["lifetime_unit"]

        if module.params["large_block"] is not None:
            config["large_block"] = module.params["large_block"]

        if module.params["embed"] is not None:
            config["embed"] = module.params["embed"]

        if module.params["compressed"] is not None:
            config["compressed"] = module.params["compressed"]

        if module.params["retries"] is not None:
            config["retries"] = module.params["retries"]

        if module.params["logging_level"] is not None:
            config["logging_level"] = module.params["logging_level"]

        if module.params["enabled"] is not None:
            config["enabled"] = module.params["enabled"]

        if task_info is None:
            # Create new task
            if module.check_mode:
                result["changes"] = config
                result["msg"] = "Would have created replication task. See 'changes'."
            else:
                try:
                    new_task = mw.call("replication.create", config)
                    result["task"] = new_task
                except Exception as e:
                    module.fail_json(msg=f"Error creating replication task: {e}")
            result["changed"] = True

        else:
            # Update existing task - compare and build diff
            updates = {}

            for key, value in config.items():
                if key in task_info:
                    # Handle schedule comparison specially (it's a dict)
                    if key in ["schedule", "restrict_schedule"]:
                        if value is not None and task_info.get(key) != value:
                            updates[key] = value
                    # Handle list comparison
                    elif isinstance(value, list):
                        if set(task_info.get(key, [])) != set(value):
                            updates[key] = value
                    # Handle dict comparison
                    elif isinstance(value, dict):
                        if task_info.get(key) != value:
                            updates[key] = value
                    # Simple comparison
                    elif task_info.get(key) != value:
                        updates[key] = value

            if not updates:
                # No changes needed
                result["changed"] = False
                result["task"] = task_info
            else:
                # Update the task
                if module.check_mode:
                    result["changes"] = updates
                    result["msg"] = (
                        "Would have updated replication task. See 'changes'."
                    )
                else:
                    try:
                        updated_task = mw.call(
                            "replication.update", task_info["id"], updates
                        )
                        result["task"] = updated_task
                    except Exception as e:
                        module.fail_json(
                            msg=f"Error updating replication task with {updates}: {e}"
                        )
                result["changed"] = True
                result['changed'] = True

    module.exit_json(**result)


if __name__ == "__main__":
    main()
