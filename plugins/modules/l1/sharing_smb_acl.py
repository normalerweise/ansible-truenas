#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage SMB share ACLs using TrueNAS SCALE API.

DOCUMENTATION = """
---
module: sharing_smb_acl
short_description: Manage SMB share ACLs
description:
  - Set and manage Access Control Lists (ACLs) for SMB shares on TrueNAS SCALE.
  - Uses the sharing.smb.getacl and sharing.smb.setacl middleware APIs.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Share ACLs control SMB protocol-level access (who can see and access the share).
  - Combine with access_based_share_enumeration to hide shares from unauthorized users.
abstraction_level: L1
abstraction_type: direct_api
options:
  share_name:
    description:
      - Name of the SMB share to manage ACLs for.
      - Must be an existing SMB share name (case-sensitive).
    type: str
    required: true
  share_acl:
    description:
      - List of ACL entries (ACEs) to apply to the share.
      - When state is 'present', this replaces the entire share ACL.
      - When omitted with state 'present', keeps current ACLs unchanged.
    type: list
    elements: dict
    suboptions:
      ae_who_name:
        description:
          - Username or group name for this ACL entry.
          - TrueNAS will resolve the name to the appropriate SID.
          - Cannot be used together with ae_who_sid.
        type: str
      ae_who_sid:
        description:
          - Windows Security Identifier (SID) for this ACL entry.
          - Use this for explicit SID references (e.g., 'S-1-1-0' for Everyone).
          - Cannot be used together with ae_who_name.
        type: str
      ae_perm:
        description:
          - Permission level for this ACL entry.
          - FULL = read, write, execute, delete, write ACL, change owner
          - CHANGE = read, write, execute, delete
          - READ = read and execute only
        type: str
        choices: ['FULL', 'CHANGE', 'READ']
        default: 'READ'
      ae_type:
        description:
          - Whether this entry grants (ALLOWED) or denies (DENIED) access.
        type: str
        choices: ['ALLOWED', 'DENIED']
        default: 'ALLOWED'
  state:
    description:
      - Whether custom ACLs should be configured or reset to default.
      - present = Apply the specified share_acl
      - absent = Reset share ACL to TrueNAS default (Everyone with FULL access)
    type: str
    choices: ['present', 'absent']
    default: 'present'
version_added: 1.4.4
author:
  - "Norman Ziegner"
"""

EXAMPLES = """
- name: Set share ACL for single user
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: home_norman
    share_acl:
      - ae_who_name: norman
        ae_perm: FULL
        ae_type: ALLOWED

- name: Set share ACL for multiple users with different permissions
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: shared_docs
    share_acl:
      - ae_who_name: norman
        ae_perm: FULL
        ae_type: ALLOWED
      - ae_who_name: editors
        ae_perm: CHANGE
        ae_type: ALLOWED
      - ae_who_name: readers
        ae_perm: READ
        ae_type: ALLOWED

- name: Set share ACL using explicit SID
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: restricted
    share_acl:
      - ae_who_sid: S-1-5-32-544
        ae_perm: FULL
        ae_type: ALLOWED

- name: Reset share ACL to default (Everyone)
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: public_share
    state: absent
"""

RETURN = """
share_acl:
  description:
    - The current share ACL after the operation.
  type: list
  returned: always
  sample:
    - ae_who_sid: S-1-5-21-...
      ae_who_name: norman
      ae_perm: FULL
      ae_type: ALLOWED
changed:
  description:
    - Whether the share ACL was modified.
  type: bool
  returned: always
msg:
  description:
    - Human-readable message about the operation.
  type: str
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def normalize_ace(ace):
    """
    Normalize an ACE for comparison purposes.

    Args:
        ace: ACL entry dict

    Returns:
        Normalized tuple (who_identifier, perm, type) for comparison
    """
    # Use SID if available, otherwise use name
    who = ace.get("ae_who_sid") or ace.get("ae_who_name", "")
    perm = ace.get("ae_perm", "READ")
    atype = ace.get("ae_type", "ALLOWED")

    return (who, perm, atype)


def compare_acls(current_acl, desired_acl):
    """
    Compare two ACL lists to determine if they are equivalent.

    Args:
        current_acl: Current ACL from TrueNAS
        desired_acl: Desired ACL from module parameters

    Returns:
        True if ACLs are equivalent, False otherwise
    """
    if current_acl is None or desired_acl is None:
        return current_acl == desired_acl

    if len(current_acl) != len(desired_acl):
        return False

    # Normalize and compare as sets (order-independent)
    current_normalized = set(normalize_ace(ace) for ace in current_acl)
    desired_normalized = set(normalize_ace(ace) for ace in desired_acl)

    return current_normalized == desired_normalized


def validate_ace_list(ace_list, module):
    """
    Validate that ACE list has required fields.

    Args:
        ace_list: List of ACE dicts
        module: AnsibleModule instance for error reporting
    """
    if not ace_list:
        return

    for i, ace in enumerate(ace_list):
        # Must have either ae_who_name or ae_who_sid
        if not ace.get("ae_who_name") and not ace.get("ae_who_sid"):
            module.fail_json(
                msg=f"ACE #{i}: must specify either ae_who_name or ae_who_sid"
            )

        # Cannot have both
        if ace.get("ae_who_name") and ace.get("ae_who_sid"):
            module.fail_json(
                msg=f"ACE #{i}: cannot specify both ae_who_name and ae_who_sid"
            )


def build_ace_for_api(ace_param):
    """
    Build an ACE dict suitable for the TrueNAS API.

    Args:
        ace_param: ACE dict from module parameters

    Returns:
        ACE dict formatted for TrueNAS API
    """
    ace_api = {
        "ae_perm": ace_param.get("ae_perm", "READ"),
        "ae_type": ace_param.get("ae_type", "ALLOWED"),
    }

    if "ae_who_name" in ace_param:
        ace_api["ae_who_name"] = ace_param["ae_who_name"]
    elif "ae_who_sid" in ace_param:
        ace_api["ae_who_sid"] = ace_param["ae_who_sid"]

    return ace_api


def main():
    module = AnsibleModule(
        argument_spec=dict(
            share_name=dict(type="str", required=True),
            share_acl=dict(
                type="list",
                elements="dict",
                options=dict(
                    ae_who_name=dict(type="str"),
                    ae_who_sid=dict(type="str"),
                    ae_perm=dict(
                        type="str", default="READ", choices=["FULL", "CHANGE", "READ"]
                    ),
                    ae_type=dict(
                        type="str", default="ALLOWED", choices=["ALLOWED", "DENIED"]
                    ),
                ),
            ),
            state=dict(type="str", default="present", choices=["present", "absent"]),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Assign variables from parameters
    share_name = module.params["share_name"]
    share_acl_param = module.params["share_acl"]
    state = module.params["state"]

    # Validate ACE list if provided
    if share_acl_param is not None:
        validate_ace_list(share_acl_param, module)

    # Verify that the share exists
    try:
        share_query = mw.call("sharing.smb.query", [["name", "=", share_name]])
        if len(share_query) == 0:
            # In check mode, the share might not exist yet if it would be created
            if module.check_mode and share_acl_param is not None:
                result["changed"] = True
                result["msg"] = (
                    f"Would configure ACL for share '{share_name}' (share will be created)"
                )
                result["share_acl"] = [
                    build_ace_for_api(ace) for ace in share_acl_param
                ]
                module.exit_json(**result)
            else:
                module.fail_json(msg=f"SMB share '{share_name}' not found")
        share_info = share_query[0]
    except Exception as e:
        module.fail_json(msg=f"Error querying share '{share_name}': {e}")

    # Get current share ACL
    try:
        current_acl_result = mw.call("sharing.smb.getacl", {"share_name": share_name})
        current_acl = current_acl_result.get("share_acl", [])
    except Exception as e:
        module.fail_json(msg=f"Error getting ACL for share '{share_name}': {e}")

    if state == "absent":
        # Reset to default (typically Everyone with FULL)
        # Check if already at default by looking for Everyone SID
        is_default = False
        if len(current_acl) == 1:
            ace = current_acl[0]
            if (
                ace.get("ae_who_sid") == "S-1-1-0"
                and ace.get("ae_perm") == "FULL"
                and ace.get("ae_type") == "ALLOWED"
            ):
                is_default = True

        if is_default:
            result["changed"] = False
            result["msg"] = f"Share '{share_name}' ACL is already at default"
            result["share_acl"] = current_acl
        else:
            # Reset to default
            default_acl = [
                {
                    "ae_who_sid": "S-1-1-0",  # Everyone
                    "ae_perm": "FULL",
                    "ae_type": "ALLOWED",
                }
            ]

            if module.check_mode:
                result["changed"] = True
                result["msg"] = f"Would reset share '{share_name}' ACL to default"
                result["share_acl"] = default_acl
            else:
                try:
                    acl_result = mw.call(
                        "sharing.smb.setacl",
                        {"share_name": share_name, "share_acl": default_acl},
                    )
                    result["changed"] = True
                    result["msg"] = f"Reset share '{share_name}' ACL to default"
                    result["share_acl"] = acl_result.get("share_acl", default_acl)
                except Exception as e:
                    module.fail_json(
                        msg=f"Error resetting ACL for share '{share_name}': {e}"
                    )

    else:  # state == 'present'
        if share_acl_param is None:
            # No ACL specified, just return current state
            result["changed"] = False
            result["msg"] = f"Share '{share_name}' ACL unchanged (no ACL specified)"
            result["share_acl"] = current_acl
        else:
            # Build desired ACL for API
            desired_acl = [build_ace_for_api(ace) for ace in share_acl_param]

            # Compare current vs desired
            if compare_acls(current_acl, desired_acl):
                # ACLs are equivalent, no change needed
                result["changed"] = False
                result["msg"] = (
                    f"Share '{share_name}' ACL is already correctly configured"
                )
                result["share_acl"] = current_acl
            else:
                # ACLs differ, need to update
                if module.check_mode:
                    result["changed"] = True
                    result["msg"] = f"Would update share '{share_name}' ACL"
                    result["share_acl"] = desired_acl
                else:
                    try:
                        acl_result = mw.call(
                            "sharing.smb.setacl",
                            {"share_name": share_name, "share_acl": desired_acl},
                        )
                        result["changed"] = True
                        result["msg"] = f"Updated share '{share_name}' ACL"
                        result["share_acl"] = acl_result.get("share_acl", desired_acl)
                    except Exception as e:
                        module.fail_json(
                            msg=f"Error setting ACL for share '{share_name}': {e}",
                            desired_acl=desired_acl,
                        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
