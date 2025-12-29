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
      ae_who_str:
        description:
          - Username or group name for this ACL entry.
          - TrueNAS will resolve the name to the appropriate SID.
          - Cannot be used together with ae_who_sid or ae_who_id.
        type: str
      ae_who_sid:
        description:
          - Windows Security Identifier (SID) for this ACL entry.
          - Use this for explicit SID references (e.g., 'S-1-1-0' for Everyone).
          - Cannot be used together with ae_who_str or ae_who_id.
        type: str
      ae_who_id:
        description:
          - Unix ID information for user or group to which the ACL entry applies.
          - Cannot be used together with ae_who_str or ae_who_sid.
        type: dict
        suboptions:
          id_type:
            description:
              - The type of Unix ID (USER or GROUP).
            type: str
            choices: ['USER', 'GROUP']
            required: true
          id:
            description:
              - Unix user ID (UID) or group ID (GID) depending on the id_type field.
            type: int
            required: true
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
      - ae_who_str: norman
        ae_perm: FULL
        ae_type: ALLOWED

- name: Set share ACL for multiple users with different permissions
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: shared_docs
    share_acl:
      - ae_who_str: norman
        ae_perm: FULL
        ae_type: ALLOWED
      - ae_who_str: editors
        ae_perm: CHANGE
        ae_type: ALLOWED
      - ae_who_str: readers
        ae_perm: READ
        ae_type: ALLOWED

- name: Set share ACL using explicit SID
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: restricted
    share_acl:
      - ae_who_sid: S-1-5-32-544
        ae_perm: FULL
        ae_type: ALLOWED

- name: Set share ACL using Unix ID
  normalerweise.truenas.l1.sharing_smb_acl:
    share_name: restricted
    share_acl:
      - ae_who_id:
          id_type: USER
          id: 1000
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
      ae_who_str: norman
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


def resolve_name_to_sid(mw, name):
    """
    Resolve a username or group name to a Windows SID.

    Args:
        mw: MiddleWare client instance
        name: Username or group name to resolve

    Returns:
        dict with 'sid' and 'id_type' (USER or GROUP), or None if not found
    """
    # Try to find as user first
    try:
        users = mw.call("user.query", [["username", "=", name]])
        if users and len(users) > 0:
            user = users[0]
            if "sid" in user and user["sid"]:
                return {"sid": user["sid"], "id_type": "USER"}
    except Exception:
        pass

    # Try to find as group
    try:
        groups = mw.call("group.query", [["name", "=", name]])
        if groups and len(groups) > 0:
            group = groups[0]
            if "sid" in group and group["sid"]:
                return {"sid": group["sid"], "id_type": "GROUP"}
    except Exception:
        pass

    return None


def normalize_ace(ace):
    """
    Normalize an ACE for comparison purposes.

    Args:
        ace: ACL entry dict

    Returns:
        Normalized tuple (who_identifier, perm, type) for comparison
    """
    # Use SID if available, otherwise use str, otherwise use id as tuple
    who = ace.get("ae_who_sid")
    if not who:
        who = ace.get("ae_who_str")
    if not who:
        who_id = ace.get("ae_who_id")
        if who_id:
            # Convert dict to tuple for hashability
            who = (who_id.get("id_type"), who_id.get("id"))
        else:
            who = ""

    perm = ace.get("ae_perm", "READ")
    atype = ace.get("ae_type", "ALLOWED")

    return (who, perm, atype)


def normalize_ace_from_api(ace):
    """
    Normalize an ACE received from TrueNAS API.

    TrueNAS returns ACEs with all three "who" fields present,
    with unused fields set to null. We need to strip out the null
    fields for proper comparison with our desired state.

    Args:
        ace: ACL entry dict from TrueNAS API

    Returns:
        Normalized ACE dict with only non-null fields
    """
    normalized = {
        "ae_perm": ace.get("ae_perm", "READ"),
        "ae_type": ace.get("ae_type", "ALLOWED"),
    }

    # Only include non-null "who" fields
    if ace.get("ae_who_str") is not None:
        normalized["ae_who_str"] = ace["ae_who_str"]
    if ace.get("ae_who_sid") is not None:
        normalized["ae_who_sid"] = ace["ae_who_sid"]
    if ace.get("ae_who_id") is not None:
        normalized["ae_who_id"] = ace["ae_who_id"]

    return normalized


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
        # Must have exactly one of ae_who_str, ae_who_sid, or ae_who_id
        who_fields = [
            ace.get("ae_who_str"),
            ace.get("ae_who_sid"),
            ace.get("ae_who_id"),
        ]
        who_count = sum(1 for field in who_fields if field is not None)

        if who_count == 0:
            module.fail_json(
                msg=f"ACE #{i}: must specify one of ae_who_str, ae_who_sid, or ae_who_id"
            )

        if who_count > 1:
            module.fail_json(
                msg=f"ACE #{i}: cannot specify more than one of ae_who_str, ae_who_sid, or ae_who_id"
            )


def build_ace_for_api(ace_param, mw=None):
    """
    Build an ACE dict suitable for the TrueNAS API.

    WORKAROUND for TrueNAS SCALE v25.10 bug:
    TrueNAS has a bug where it tries to access entry['ae_who_id']['id_type']
    without checking if ae_who_id is None first. To work around this, we
    convert ae_who_str to ae_who_sid by resolving usernames to SIDs.

    Args:
        ace_param: ACE dict from module parameters
        mw: MiddleWare client instance (required for ae_who_str resolution)

    Returns:
        ACE dict formatted for TrueNAS API
    """
    # Build base ACE with required fields
    ace_api = {
        "ae_perm": ace_param.get("ae_perm", "READ"),
        "ae_type": ace_param.get("ae_type", "ALLOWED"),
    }

    # WORKAROUND: Convert ae_who_str to ae_who_sid to avoid TrueNAS bug
    if "ae_who_str" in ace_param and ace_param["ae_who_str"] is not None:
        if mw is not None:
            # Try to resolve the name to a SID
            resolved = resolve_name_to_sid(mw, ace_param["ae_who_str"])
            if resolved and resolved.get("sid"):
                # Use SID instead of string to avoid TrueNAS bug
                ace_api["ae_who_sid"] = resolved["sid"]
            else:
                # Fallback to string if we can't resolve
                # This may still fail due to TrueNAS bug
                ace_api["ae_who_str"] = ace_param["ae_who_str"]
        else:
            ace_api["ae_who_str"] = ace_param["ae_who_str"]
    elif "ae_who_sid" in ace_param and ace_param["ae_who_sid"] is not None:
        ace_api["ae_who_sid"] = ace_param["ae_who_sid"]
    elif "ae_who_id" in ace_param and ace_param["ae_who_id"] is not None:
        ace_api["ae_who_id"] = ace_param["ae_who_id"]

    return ace_api


def main():
    module = AnsibleModule(
        argument_spec=dict(
            share_name=dict(type="str", required=True),
            share_acl=dict(
                type="list",
                elements="dict",
                options=dict(
                    ae_who_str=dict(type="str"),
                    ae_who_sid=dict(type="str"),
                    ae_who_id=dict(
                        type="dict",
                        options=dict(
                            id_type=dict(
                                type="str", required=True, choices=["USER", "GROUP"]
                            ),
                            id=dict(type="int", required=True),
                        ),
                    ),
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
                    build_ace_for_api(ace, mw) for ace in share_acl_param
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
        current_acl_raw = current_acl_result.get("share_acl", [])
        # Normalize ACEs from API (strip null fields)
        current_acl = [normalize_ace_from_api(ace) for ace in current_acl_raw]
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
            desired_acl = [build_ace_for_api(ace, mw) for ace in share_acl_param]

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
                        # Ensure we don't send any None/null values that could trigger TrueNAS bugs
                        cleaned_acl = []
                        for ace in desired_acl:
                            cleaned_ace = {
                                k: v for k, v in ace.items() if v is not None
                            }
                            cleaned_acl.append(cleaned_ace)

                        acl_result = mw.call(
                            "sharing.smb.setacl",
                            {"share_name": share_name, "share_acl": cleaned_acl},
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
