#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = """
---
module: system_general
version_added: 0.1.0
short_description: Configure TrueNAS general system settings.
description:
  - Configure general system settings using the system.general.update API.
options:
  ui_port:
    description:
      - HTTP port for the web UI.
    type: int
    required: false
  ui_httpsport:
    description:
      - HTTPS port for the web UI.
    type: int
    required: false
  timezone:
    description:
      - System timezone (e.g., "Europe/Berlin", "America/New_York").
      - Must be a valid timezone from the tz database.
    type: str
    required: false
"""

EXAMPLES = """
- name: Configure web UI ports
  normalerweise.truenas.system_general:
    ui_port: 81
    ui_httpsport: 4443

- name: Set system timezone
  normalerweise.truenas.system_general:
    timezone: "Europe/Berlin"

- name: Configure web UI ports and timezone
  normalerweise.truenas.system_general:
    ui_port: 8080
    ui_httpsport: 4443
    timezone: "Europe/Berlin"
"""

RETURN = """
msg:
  description: Status message, if warranted.
  returned: In some cases
  type: str
changed:
  description: Whether the configuration was changed.
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule

from ..module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            ui_port=dict(type="int", required=False),
            ui_httpsport=dict(type="int", required=False),
            timezone=dict(type="str", required=False),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Validate port ranges (API requirement: 1-65535)
    for port_param in ["ui_port", "ui_httpsport"]:
        if module.params[port_param] is not None:
            port = module.params[port_param]
            if port < 1 or port > 65535:
                module.fail_json(
                    msg=f"{port_param} must be between 1 and 65535, got {port}"
                )

    # Build the update dict with only specified parameters
    update_params = {}
    if module.params["ui_port"] is not None:
        update_params["ui_port"] = module.params["ui_port"]
    if module.params["ui_httpsport"] is not None:
        update_params["ui_httpsport"] = module.params["ui_httpsport"]
    if module.params["timezone"] is not None:
        update_params["timezone"] = module.params["timezone"]

    # If no parameters specified, nothing to do
    if not update_params:
        module.exit_json(**result)

    # Look up the current system general config
    try:
        current_config = mw.call("system.general.config")
    except Exception as e:
        module.fail_json(msg=f"Error looking up system.general configuration: {e}")

    # Check if any changes are needed
    changes_needed = False
    for key, value in update_params.items():
        if current_config.get(key) != value:
            changes_needed = True
            break

    if changes_needed:
        if module.check_mode:
            result["msg"] = (
                f"Would have updated system.general settings: {update_params}"
            )
        else:
            try:
                mw.call("system.general.update", update_params)
                result["msg"] = f"Updated system.general settings: {update_params}"
            except Exception as e:
                module.fail_json(msg=f"Error updating system.general settings: {e}")
        result["changed"] = True
    else:
        result["msg"] = "No changes needed"

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
