#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage alert services

DOCUMENTATION = """
---
module: alertservice
short_description: Manage TrueNAS alert services
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
  - Configure alert services for TrueNAS notifications.
  - Supports Email (Mail) alert service type.
options:
  name:
    description:
      - Human-readable name for the alert service.
    type: str
    required: true
  type:
    description:
      - Alert service type.
    type: str
    choices: [ Mail ]
    default: Mail
  email:
    description:
      - Email address to send alerts to.
      - Empty string uses system default.
      - Only applicable when type is Mail.
    type: str
  level:
    description:
      - Minimum alert severity level that triggers notifications.
    type: str
    choices: [ INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY ]
    default: WARNING
  enabled:
    description:
      - Whether the alert service is active and will send notifications.
    type: bool
    default: true
  state:
    description:
      - Whether the alert service should exist or not.
    type: str
    choices: [ present, absent ]
    default: present
version_added: 1.3.0
"""

EXAMPLES = """
- name: Configure email alerts
  hosts: my-truenas-host
  tasks:
    - name: Create email alert service
      normalerweise.truenas.l1.alertservice:
        name: "Email Alerts"
        type: Mail
        email: admin@example.com
        level: WARNING
        enabled: true
        state: present
"""

RETURN = """#"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            type=dict(type="str", default="Mail", choices=["Mail"]),
            email=dict(type="str"),
            level=dict(
                type="str",
                default="WARNING",
                choices=[
                    "INFO",
                    "NOTICE",
                    "WARNING",
                    "ERROR",
                    "CRITICAL",
                    "ALERT",
                    "EMERGENCY",
                ],
            ),
            enabled=dict(type="bool", default=True),
            state=dict(type="str", default="present", choices=["present", "absent"]),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Assign variables from properties, for convenience
    name = module.params["name"]
    service_type = module.params["type"]
    email = module.params["email"]
    level = module.params["level"]
    enabled = module.params["enabled"]
    state = module.params["state"]

    # Query existing alert services
    try:
        alert_services = mw.call("alertservice.query", [["name", "=", name]])
    except Exception as e:
        module.fail_json(msg=f"Error querying alert services: {e}")

    existing_service = alert_services[0] if alert_services else None

    if state == "absent":
        if existing_service:
            # Delete the service
            if module.check_mode:
                result["msg"] = f"Would have deleted alert service: {name}"
            else:
                try:
                    mw.call("alertservice.delete", existing_service["id"])
                    result["msg"] = f"Deleted alert service: {name}"
                except Exception as e:
                    module.fail_json(msg=f"Error deleting alert service {name}: {e}")
            result["changed"] = True
        else:
            result["msg"] = f"Alert service {name} does not exist"
    else:  # state == 'present'
        # Build attributes based on service type
        attributes = {"type": service_type}

        if service_type == "Mail":
            if email is not None:
                attributes["email"] = email
            else:
                attributes["email"] = ""  # Use system default

        if existing_service:
            # Update existing service - check what needs to change
            needs_update = False

            # Check if attributes differ
            if existing_service["attributes"] != attributes:
                needs_update = True

            if existing_service["level"] != level:
                needs_update = True

            if existing_service["enabled"] != enabled:
                needs_update = True

            if not needs_update:
                # No changes needed
                result["msg"] = f"Alert service {name} already configured correctly"
            else:
                # Build update args - name and level are always required by the API
                arg = {
                    "name": name,
                    "level": level,
                    "attributes": attributes,
                    "enabled": enabled,
                }

                # Update the service
                if module.check_mode:
                    result["msg"] = f"Would have updated alert service {name}: {arg}"
                else:
                    try:
                        mw.call("alertservice.update", existing_service["id"], arg)
                        result["msg"] = f"Updated alert service: {name}"
                    except Exception as e:
                        module.fail_json(
                            msg=f"Error updating alert service {name} with {arg}: {e}"
                        )
                result["changed"] = True
        else:
            # Create new service
            arg = {
                "name": name,
                "attributes": attributes,
                "level": level,
                "enabled": enabled,
            }

            if module.check_mode:
                result["msg"] = f"Would have created alert service: {arg}"
            else:
                try:
                    mw.call("alertservice.create", arg)
                    result["msg"] = f"Created alert service: {name}"
                except Exception as e:
                    module.fail_json(
                        msg=f"Error creating alert service with {arg}: {e}"
                    )
            result["changed"] = True

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
