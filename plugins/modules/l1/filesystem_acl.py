#!/usr/bin/python
# -*- coding: utf-8 -*-

__metaclass__ = type

DOCUMENTATION = """
---
module: filesystem_acl
short_description: Manage filesystem ACLs via TrueNAS middleware
description:
  - Set and manage NFSv4 or POSIX ACLs on TrueNAS SCALE filesystems.
  - Uses the filesystem.setacl middleware API.
  - Supports both NFSv4 and POSIX1E ACL types.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  path:
    description:
      - Absolute filesystem path to set ACL on.
    required: true
    type: str
  dacl:
    description:
      - Array of Access Control Entries to apply to the filesystem object.
      - Format depends on the ACL type (NFSv4 or POSIX1E).
    required: true
    type: list
    elements: dict
  uid:
    description:
      - Numeric user ID to set as owner.
      - Use -1 to preserve existing owner.
    type: int
    default: -1
  user:
    description:
      - Username to set as owner.
      - Cannot be used together with uid.
    type: str
  gid:
    description:
      - Numeric group ID to set as group.
      - Use -1 to preserve existing group.
    type: int
    default: -1
  group:
    description:
      - Group name to set as group.
      - Cannot be used together with gid.
    type: str
  stripacl:
    description:
      - Whether to remove the ACL entirely and revert to basic POSIX permissions.
    type: bool
    default: false
  recursive:
    description:
      - Whether to apply ACL changes recursively to all child files and directories.
    type: bool
    default: false
  traverse:
    description:
      - Whether to traverse filesystem boundaries during recursive operations.
    type: bool
    default: false
  canonicalize:
    description:
      - Whether to reorder ACL entries in Windows canonical order.
    type: bool
    default: true
  validate_effective_acl:
    description:
      - Whether to validate that users/groups granted access can actually access the path.
    type: bool
    default: true
  acltype:
    description:
      - ACL type to use. If not specified, auto-detected from filesystem.
    type: str
    choices: ['NFS4', 'POSIX1E']
  nfs41_flags:
    description:
      - NFS4 ACL flags for inheritance and protection behavior.
    type: dict
    suboptions:
      autoinherit:
        description: Whether inheritance is automatically applied from parent directories.
        type: bool
        default: false
      protected:
        description: Whether the ACL is protected from inheritance modifications.
        type: bool
        default: false
      defaulted:
        description: Whether this ACL was created by default rules.
        type: bool
        default: false
author:
  - "Norman Ziegner"
version_added: "1.0.0"
"""

EXAMPLES = r"""
- name: Set NFSv4 ACL on a directory
  normalerweise.truenas.filesystem_acl:
    path: /mnt/tank/shared
    dacl:
      - tag: "owner@"
        type: "ALLOW"
        perms:
          BASIC: "FULL_CONTROL"
        flags:
          BASIC: "INHERIT"
      - tag: "USER"
        id: 2001
        who: "norman"
        type: "ALLOW"
        perms:
          BASIC: "FULL_CONTROL"
        flags:
          BASIC: "INHERIT"
    uid: 3000
    gid: 3000

- name: Set POSIX ACL on a directory
  normalerweise.truenas.filesystem_acl:
    path: /mnt/tank/posix_dir
    dacl:
      - tag: "USER_OBJ"
        perms:
          READ: true
          WRITE: true
          EXECUTE: true
        default: false
      - tag: "USER"
        id: 2001
        who: "norman"
        perms:
          READ: true
          WRITE: true
          EXECUTE: true
        default: false
    acltype: "POSIX1E"

- name: Strip ACL and revert to basic permissions
  normalerweise.truenas.filesystem_acl:
    path: /mnt/tank/simple
    dacl: []
    stripacl: true
"""

RETURN = r"""
acl_info:
  description: ACL information for the filesystem path after setting.
  type: dict
  returned: always
  sample:
    path: "/mnt/tank/shared"
    user: "norman"
    group: "users"
    uid: 2001
    gid: 4000
    acltype: "NFS4"
    trivial: false
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type="str", required=True),
            dacl=dict(type="list", elements="dict", required=True),
            uid=dict(type="int"),
            user=dict(type="str"),
            gid=dict(type="int"),
            group=dict(type="str"),
            stripacl=dict(type="bool", default=False),
            recursive=dict(type="bool", default=False),
            traverse=dict(type="bool", default=False),
            canonicalize=dict(type="bool", default=True),
            validate_effective_acl=dict(type="bool", default=True),
            acltype=dict(type="str", choices=["NFS4", "POSIX1E"]),
            nfs41_flags=dict(
                type="dict",
                options=dict(
                    autoinherit=dict(type="bool", default=False),
                    protected=dict(type="bool", default=False),
                    defaulted=dict(type="bool", default=False),
                ),
            ),
        ),
        mutually_exclusive=[
            ("uid", "user"),
            ("gid", "group"),
        ],
        supports_check_mode=True,
    )

    result = dict(changed=False, acl_info={})

    mw = MW.client()

    p = module.params
    path = p["path"]
    dacl = p["dacl"]

    # Build the setacl API call parameters
    acl_params = {
        "path": path,
        "dacl": dacl,
        "options": {
            "stripacl": p["stripacl"],
            "recursive": p["recursive"],
            "traverse": p["traverse"],
            "canonicalize": p["canonicalize"],
            "validate_effective_acl": p["validate_effective_acl"],
        },
    }

    # Add ownership parameters
    # Only include if explicitly provided (not None)
    if p["uid"] is not None:
        acl_params["uid"] = p["uid"]
    if p["user"] is not None:
        acl_params["user"] = p["user"]
    if p["gid"] is not None:
        acl_params["gid"] = p["gid"]
    if p["group"] is not None:
        acl_params["group"] = p["group"]

    # Add optional parameters
    if p["acltype"] is not None:
        acl_params["acltype"] = p["acltype"]

    if p["nfs41_flags"] is not None:
        acl_params["options"]["nfs41_flags"] = p["nfs41_flags"]

    # Get current ACL state for comparison
    try:
        # filesystem.getacl is a synchronous call, not a job
        current_acl = mw.call("filesystem.getacl", path)
    except Exception as e:
        module.fail_json(msg=f"Failed to get current ACL for '{path}': {e}")

    # Check if changes are needed
    # This is a simplified check - in production you'd want more sophisticated comparison
    needs_change = True
    if not p["stripacl"]:
        # Compare ACLs (simplified - you might want deeper comparison)
        if current_acl.get("acl") == dacl:
            needs_change = False

    if not needs_change:
        result["acl_info"] = current_acl
        module.exit_json(**result)

    if module.check_mode:
        result["changed"] = True
        result["msg"] = f"Would set ACL on '{path}'"
        module.exit_json(**result)

    # Apply the ACL
    try:
        # filesystem.setacl is an async job
        updated_acl = mw.call("filesystem.setacl", acl_params)
        result["acl_info"] = updated_acl
        result["changed"] = True

    except Exception as e:
        import traceback

        module.fail_json(
            msg=f"Failed to set ACL on '{path}': {e}", traceback=traceback.format_exc()
        )

    module.exit_json(**result)


if __name__ == "__main__":
    main()
