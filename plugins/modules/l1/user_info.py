#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = """
---
module: user_info
short_description: Query TrueNAS user information
description:
  - Query information about a TrueNAS user account.
  - Returns user details including home directory, UID, shell, groups, etc.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  name:
    description:
      - Name of the user to query.
    type: str
    required: true
    aliases: [ user, username ]
notes:
  - Supports C(check_mode).
"""

EXAMPLES = """
- name: Query user information
  normalerweise.truenas.l1.user_info:
    name: myuser
  register: user_result

- name: Display user home directory
  debug:
    msg: "User home: {{ user_result.user_info.home }}"
"""

RETURN = """
user_info:
  description: User information from TrueNAS API
  returned: when user exists
  type: dict
  sample:
    id: 37
    uid: 1001
    username: myuser
    home: /mnt/tank/home/myuser
    shell: /usr/bin/zsh
    full_name: My User
    email: user@example.com
    groups: [1, 2, 3]
    password_disabled: true
exists:
  description: Whether the user exists
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True, aliases=["user", "username"]),
        ),
        supports_check_mode=True,
    )

    username = module.params["name"]
    result = dict(changed=False, exists=False)

    # Connect to TrueNAS middleware
    try:
        mw = MW()
    except Exception as e:
        module.fail_json(msg=f"Failed to connect to TrueNAS middleware: {e}")

    # Query user information
    try:
        user_info = mw.call("user.query", [["username", "=", username]])

        if len(user_info) == 0:
            # User doesn't exist
            result["exists"] = False
            result["msg"] = f"User {username} does not exist"
        else:
            # User exists
            result["exists"] = True
            result["user_info"] = user_info[0]

    except Exception as e:
        module.fail_json(msg=f"Error querying user {username}: {e}")

    module.exit_json(**result)


if __name__ == "__main__":
    main()
