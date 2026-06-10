#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage TrueNAS cron jobs.

DOCUMENTATION = """
---
module: cronjob
short_description: Manage TrueNAS cron jobs.
description:
  - Create, update and delete cron jobs managed by the TrueNAS middleware.
  - Cron jobs are stored in the middleware configuration database, so they
    survive reboots and system upgrades (unlike hand-edited crontab files).
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  description:
    description:
      - Human-readable description of the cron job.
      - Acts as the unique identifier used to look the job up, so it must be
        stable across runs.
    type: str
    required: true
  command:
    description:
      - The command line to execute.
      - Required when C(state=present).
    type: str
  user:
    description:
      - The user account the command runs as.
    type: str
    default: root
  schedule:
    description:
      - The cron schedule. Any omitted key defaults to C(*) (every).
    type: dict
    suboptions:
      minute:
        description: Minute field (0-59).
        type: str
        default: "0"
      hour:
        description: Hour field (0-23).
        type: str
        default: "0"
      dom:
        description: Day of month field (1-31).
        type: str
        default: "*"
      month:
        description: Month field (1-12).
        type: str
        default: "*"
      dow:
        description: Day of week field (0-7, where 0 and 7 are Sunday).
        type: str
        default: "*"
  enabled:
    description:
      - Whether the cron job is enabled.
    type: bool
    default: true
  hide_stdout:
    description:
      - When true, standard output is discarded.
      - When false, standard output is mailed to the C(user) (the TrueNAS default
        behaviour for cron jobs).
    type: bool
    default: true
  hide_stderr:
    description:
      - When true, standard error is discarded.
      - When false, standard error is mailed to the C(user).
    type: bool
    default: false
  state:
    description:
      - Whether the cron job should exist or not.
    type: str
    choices: [ absent, present ]
    default: present
version_added: 1.15.0
"""

EXAMPLES = """
- name: Daily app auto-update at 04:00
  normalerweise.truenas.l1.cronjob:
    description: Auto-update catalog apps
    command: /mnt/dozer/apps/_ops/app_auto_update/run.py
    user: root
    schedule:
      minute: "0"
      hour: "4"
    hide_stdout: true
    hide_stderr: false

- name: Remove a cron job
  normalerweise.truenas.l1.cronjob:
    description: Auto-update catalog apps
    state: absent
"""

RETURN = """
cronjob:
  description:
    - A data structure describing the created or updated cron job.
  type: dict
  returned: on create or update
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW

# Schedule keys and their defaults, matching the TrueNAS cronjob API.
SCHEDULE_DEFAULTS = {
    "minute": "0",
    "hour": "0",
    "dom": "*",
    "month": "*",
    "dow": "*",
}


def normalized_schedule(schedule):
    """Return a full schedule dict, filling omitted keys with defaults."""
    result = dict(SCHEDULE_DEFAULTS)
    if schedule:
        for key in SCHEDULE_DEFAULTS:
            if schedule.get(key) is not None:
                result[key] = str(schedule[key])
    return result


def main():
    module = AnsibleModule(
        argument_spec=dict(
            description=dict(type="str", required=True),
            command=dict(type="str"),
            user=dict(type="str", default="root"),
            schedule=dict(
                type="dict",
                options=dict(
                    minute=dict(type="str", default="0"),
                    hour=dict(type="str", default="0"),
                    dom=dict(type="str", default="*"),
                    month=dict(type="str", default="*"),
                    dow=dict(type="str", default="*"),
                ),
            ),
            enabled=dict(type="bool", default=True),
            hide_stdout=dict(type="bool", default=True),
            hide_stderr=dict(type="bool", default=False),
            state=dict(type="str", default="present", choices=["absent", "present"]),
        ),
        supports_check_mode=True,
        required_if=[("state", "present", ("command",))],
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    description = module.params["description"]
    command = module.params["command"]
    user = module.params["user"]
    schedule = normalized_schedule(module.params["schedule"])
    enabled = module.params["enabled"]
    hide_stdout = module.params["hide_stdout"]
    hide_stderr = module.params["hide_stderr"]
    state = module.params["state"]

    # Look up the cron job by its description, which we treat as the identifier.
    try:
        existing = mw.call("cronjob.query", [["description", "=", description]])
        existing = existing[0] if existing else None
    except Exception as e:
        module.fail_json(msg=f"Error looking up cron job {description!r}: {e}")

    if existing is None:
        if state == "absent":
            # Nothing to do.
            module.exit_json(**result)

        # Create the cron job.
        arg = {
            "description": description,
            "command": command,
            "user": user,
            "schedule": schedule,
            "enabled": enabled,
            "stdout": hide_stdout,
            "stderr": hide_stderr,
        }

        if module.check_mode:
            result["msg"] = f"Would have created cron job {description!r}"
            result["changed"] = True
            module.exit_json(**result)

        try:
            result["cronjob"] = mw.call("cronjob.create", arg)
        except Exception as e:
            result["failed_invocation"] = arg
            module.fail_json(msg=f"Error creating cron job {description!r}: {e}")

        result["changed"] = True
        result["msg"] = f"Created cron job {description!r}"
        module.exit_json(**result)

    # The cron job exists.
    if state == "absent":
        if module.check_mode:
            result["msg"] = f"Would have deleted cron job {description!r}"
            result["changed"] = True
            module.exit_json(**result)

        try:
            mw.call("cronjob.delete", existing["id"])
        except Exception as e:
            module.fail_json(msg=f"Error deleting cron job {description!r}: {e}")

        result["changed"] = True
        result["msg"] = f"Deleted cron job {description!r}"
        module.exit_json(**result)

    # state == present: build the set of fields that differ.
    desired = {
        "command": command,
        "user": user,
        "schedule": schedule,
        "enabled": enabled,
        "stdout": hide_stdout,
        "stderr": hide_stderr,
    }
    arg = {key: value for key, value in desired.items() if existing.get(key) != value}

    if not arg:
        result["changed"] = False
        result["cronjob"] = existing
        result["msg"] = f"Cron job {description!r} is up to date"
        module.exit_json(**result)

    if module.check_mode:
        result["msg"] = f"Would have updated cron job {description!r}: {arg}"
        result["changed"] = True
        module.exit_json(**result)

    try:
        result["cronjob"] = mw.call("cronjob.update", existing["id"], arg)
    except Exception as e:
        result["failed_invocation"] = arg
        module.fail_json(msg=f"Error updating cron job {description!r}: {e}")

    result["changed"] = True
    result["msg"] = f"Updated cron job {description!r}"
    module.exit_json(**result)


if __name__ == "__main__":
    main()
