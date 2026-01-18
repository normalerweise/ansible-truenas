#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = '''
---
module: network_config
version_added: 0.1.0
short_description: Configure TrueNAS network settings including DNS nameservers.
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Manages network configuration settings via the network.configuration.update API.
  - Supports configuring DNS nameservers (primary, secondary, tertiary).
abstraction_level: L1
abstraction_type: direct_api
options:
  nameserver1:
    description:
      - Primary DNS nameserver IP address.
      - Set to empty string to clear.
    type: str
    required: false
  nameserver2:
    description:
      - Secondary DNS nameserver IP address.
      - Set to empty string to clear.
    type: str
    required: false
  nameserver3:
    description:
      - Tertiary DNS nameserver IP address.
      - Set to empty string to clear.
    type: str
    required: false
'''

EXAMPLES = '''
- name: Set primary and secondary DNS nameservers
  normalerweise.truenas.l1.network_config:
    nameserver1: "8.8.8.8"
    nameserver2: "8.8.4.4"

- name: Set all three DNS nameservers
  normalerweise.truenas.l1.network_config:
    nameserver1: "100.100.100.100"
    nameserver2: "192.168.178.2"
    nameserver3: "1.1.1.1"

- name: Clear secondary nameserver
  normalerweise.truenas.l1.network_config:
    nameserver2: ""
'''

RETURN = '''
msg:
  description: Status message describing actions taken.
  returned: always
  type: str
changed_fields:
  description: List of fields that were changed.
  returned: when changed
  type: list
'''

from ansible.module_utils.basic import AnsibleModule
from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            nameserver1=dict(type='str', required=False, default=None),
            nameserver2=dict(type='str', required=False, default=None),
            nameserver3=dict(type='str', required=False, default=None),
        ),
        supports_check_mode=True,
    )

    result = dict(
        changed=False,
        msg='',
        changed_fields=[]
    )

    mw = MW.client()

    # Look up the current network config
    try:
        network_config = mw.call("network.configuration.config")
    except Exception as e:
        module.fail_json(msg=f"Error looking up network configuration: {e}")

    # Build update payload with only changed fields
    update_payload = {}
    nameserver_fields = ['nameserver1', 'nameserver2', 'nameserver3']

    for field in nameserver_fields:
        new_value = module.params[field]
        if new_value is not None:
            current_value = network_config.get(field, '')
            if current_value != new_value:
                update_payload[field] = new_value
                result['changed_fields'].append(field)

    # Apply changes if needed
    if update_payload:
        result['changed'] = True
        if module.check_mode:
            result['msg'] = f"Would have updated: {', '.join(result['changed_fields'])}"
        else:
            try:
                mw.call("network.configuration.update", update_payload)
                result['msg'] = f"Updated: {', '.join(result['changed_fields'])}"
            except Exception as e:
                module.fail_json(msg=f"Error updating network configuration: {e}")
    else:
        result['msg'] = "Network configuration already up to date"

    module.exit_json(**result)


if __name__ == "__main__":
    main()
