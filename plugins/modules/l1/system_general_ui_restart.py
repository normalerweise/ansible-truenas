#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = """
---
module: system_general_ui_restart
version_added: 0.1.0
short_description: Restart TrueNAS web UI.
description:
  - Restart the TrueNAS HTTP/HTTPS server to apply UI configuration changes.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Uses the system.general.ui_restart API method.
abstraction_level: L1
abstraction_type: direct_api
options:
  delay:
    description:
      - How long to wait (in seconds) before the UI is restarted.
      - Must be greater than or equal to 0.
    type: int
    required: false
    default: 3
"""

EXAMPLES = """
- name: Restart UI immediately
  normalerweise.truenas.l1.system_general_ui_restart:
    delay: 0

- name: Restart UI with 3 second delay
  normalerweise.truenas.l1.system_general_ui_restart:
    delay: 3

- name: Restart UI only when ports changed
  normalerweise.truenas.l1.system_general_ui_restart:
  when: ui_config_changed
"""

RETURN = """
msg:
  description: Status message.
  returned: always
  type: str
changed:
  description: Always true when UI restart is initiated.
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            delay=dict(type="int", required=False, default=3),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    delay = module.params["delay"]

    # Validate delay parameter
    if delay < 0:
        module.fail_json(msg=f"delay must be greater than or equal to 0, got {delay}")

    if module.check_mode:
        result["msg"] = f"Would have restarted UI with {delay} second delay"
        result["changed"] = True
        module.exit_json(**result)

    mw = MW.client()

    try:
        mw.call("system.general.ui_restart", delay)
        result["msg"] = f"UI restart initiated with {delay} second delay"
        result["changed"] = True
    except Exception as e:
        module.fail_json(msg=f"Error restarting UI: {e}")

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
