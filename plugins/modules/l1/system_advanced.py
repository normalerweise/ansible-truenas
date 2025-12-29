#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = """
---
module: system_advanced
version_added: 1.3.0
short_description: Configure TrueNAS advanced system settings.
description:
  - Configure advanced system settings using the system.advanced.update API.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  login_banner:
    description:
      - Banner message displayed before login prompt.
      - Maximum 4096 characters.
    type: str
    required: false
  motd:
    description:
      - Message of the day displayed after login.
    type: str
    required: false
"""

EXAMPLES = """
- name: Set login banner
  normalerweise.truenas.l1.system_advanced:
    login_banner: |
      =================================================================
       This service is restricted to authorized users only.
       All activities on this system are logged and monitored.
       Unauthorized access will be fully investigated
       Disconnect IMMEDIATELY if you are not an authorized user!
      =================================================================

- name: Set message of the day
  normalerweise.truenas.l1.system_advanced:
    motd: "Welcome to TrueNAS!"
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

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            login_banner=dict(type="str", required=False),
            motd=dict(type="str", required=False),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Validate login_banner length
    if module.params["login_banner"] is not None:
        banner = module.params["login_banner"]
        if len(banner) > 4096:
            module.fail_json(
                msg=f"login_banner must be at most 4096 characters, got {len(banner)}"
            )

    # Build the update dict with only specified parameters
    update_params = {}
    if module.params["login_banner"] is not None:
        update_params["login_banner"] = module.params["login_banner"]
    if module.params["motd"] is not None:
        update_params["motd"] = module.params["motd"]

    # If no parameters specified, nothing to do
    if not update_params:
        module.exit_json(**result)

    # Look up the current system advanced config
    try:
        current_config = mw.call("system.advanced.config")
    except Exception as e:
        module.fail_json(msg=f"Error looking up system.advanced configuration: {e}")

    # Check if any changes are needed
    changes_needed = False
    for key, value in update_params.items():
        if current_config.get(key) != value:
            changes_needed = True
            break

    if changes_needed:
        if module.check_mode:
            result["msg"] = (
                f"Would have updated system.advanced settings: {update_params}"
            )
        else:
            try:
                mw.call("system.advanced.update", update_params)
                result["msg"] = f"Updated system.advanced settings"
            except Exception as e:
                module.fail_json(msg=f"Error updating system.advanced settings: {e}")
        result["changed"] = True
    else:
        result["msg"] = "No changes needed"

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
