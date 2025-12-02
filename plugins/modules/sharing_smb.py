#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Create and manage SMB shares using modern TrueNAS SCALE API.

DOCUMENTATION = """
---
module: sharing_smb
short_description: Manage SMB sharing
description:
  - Create, manage, and delete SMB shares on TrueNAS SCALE.
  - Uses the modern sharing.smb API with purpose-based configuration.
options:
  name:
    description:
      - Name of the share, as seen by the SMB client.
      - Must be unique, case-insensitive, max 80 characters.
    type: str
    required: true
  path:
    description:
      - Directory to share, on the server.
      - Must start with /mnt/ and be in a ZFS pool.
      - Use "EXTERNAL" for DFS proxy shares.
    type: str
    required: true
  state:
    description:
      - Whether the share should exist or not.
    type: str
    choices: [ absent, present ]
    default: present
  purpose:
    description:
      - |
        Share purpose controlling behavior and available features.
        - DEFAULT_SHARE: Best for most applications
        - LEGACY_SHARE: Compatibility with older TrueNAS versions
        - TIMEMACHINE_SHARE: Apple Time Machine target (requires aapl_extensions in smb.config)
        - MULTIPROTOCOL_SHARE: Multi-protocol access (NFS/FTP/containers)
        - TIME_LOCKED_SHARE: Files become read-only after grace_period
        - PRIVATE_DATASETS_SHARE: Per-user datasets created on connection
        - EXTERNAL_SHARE: DFS proxy to external SMB server
        - VEEAM_REPOSITORY_SHARE: Veeam Backup & Replication with Fast Clone (Enterprise only)
        - FCP_SHARE: Final Cut Pro storage
    type: str
    choices:
      - DEFAULT_SHARE
      - LEGACY_SHARE
      - TIMEMACHINE_SHARE
      - MULTIPROTOCOL_SHARE
      - TIME_LOCKED_SHARE
      - PRIVATE_DATASETS_SHARE
      - EXTERNAL_SHARE
      - VEEAM_REPOSITORY_SHARE
      - FCP_SHARE
    default: DEFAULT_SHARE
  enabled:
    description:
      - If true, the share is enabled. Otherwise, it is present but disabled.
    type: bool
    default: true
  comment:
    description:
      - Description of the share, for the system maintainer.
    type: str
    default: ''
  readonly:
    description:
      - If true, share is read-only for SMB clients.
      - Local processes and other protocols can still write.
    type: bool
    default: false
  browsable:
    description:
      - If true, share is visible when browsing shares.
    type: bool
    default: true
  access_based_share_enumeration:
    description:
      - If true, only show share to users with access.
    type: bool
    default: false
  audit:
    description:
      - Audit configuration for monitoring share access.
    type: dict
    suboptions:
      enable:
        description: Enable auditing for the share.
        type: bool
        default: false
      watch_list:
        description: Only audit these groups (empty means all).
        type: list
        elements: str
        default: []
      ignore_list:
        description: Groups to exclude from auditing.
        type: list
        elements: str
        default: []
  options:
    description:
      - Purpose-specific configuration options.
      - Content depends on the purpose parameter.
    type: dict
version_added: 1.4.3
"""

EXAMPLES = """
- name: Simple default share
  sharing_smb:
    name: documents
    path: /mnt/tank/documents

- name: Time Machine share with quota
  sharing_smb:
    name: timemachine
    path: /mnt/tank/backups/timemachine
    purpose: TIMEMACHINE_SHARE
    browsable: false
    options:
      timemachine_quota: "3TB"
      auto_snapshot: false

- name: Multiprotocol share
  sharing_smb:
    name: shared_data
    path: /mnt/tank/shared
    purpose: MULTIPROTOCOL_SHARE
    comment: "Accessed via SMB and NFS"
"""

RETURN = """
share:
  description:
    - A data structure describing the share.
  type: dict
  returned: always
status:
  description:
    - Status message when operations fail.
  type: str
  returned: on failure
"""

from ansible.module_utils.basic import AnsibleModule

from ..module_utils.middleware import MiddleWare as MW


def to_bytes(size_str):
    """
    Convert human-readable size to bytes.

    Args:
        size_str: Size string (e.g., "3TB", "2.5GiB") or integer

    Returns:
        Integer number of bytes
    """
    import re

    if isinstance(size_str, int):
        return size_str
    if isinstance(size_str, float):
        return int(size_str)

    size_str = str(size_str).strip().upper()
    match = re.match(r"^([0-9.]+)\s*([KMGTP]I?B?)?$", size_str)
    if not match:
        raise ValueError(f"Invalid size format: {size_str}")

    number = float(match.group(1))
    unit = match.group(2) or ""

    binary_units = {
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
        "PIB": 1024**5,
    }
    decimal_units = {
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "PB": 1000**5,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "P": 1000**5,
    }

    if unit in binary_units:
        multiplier = binary_units[unit]
    elif unit in decimal_units:
        multiplier = decimal_units[unit]
    elif unit == "" or unit == "B":
        multiplier = 1
    else:
        raise ValueError(f"Unknown unit: {unit}")

    return int(number * multiplier)


def process_options(purpose, options):
    """
    Process and validate purpose-specific options.

    Args:
        purpose: Share purpose
        options: Options dict from module params

    Returns:
        Processed options dict ready for API
    """
    if not options:
        return None

    # Make a copy to avoid modifying original
    processed = dict(options)

    # Handle size conversions for quota fields
    if "timemachine_quota" in processed:
        processed["timemachine_quota"] = to_bytes(processed["timemachine_quota"])

    if "auto_quota" in processed and isinstance(processed["auto_quota"], str):
        # auto_quota is in GiB
        processed["auto_quota"] = to_bytes(processed["auto_quota"]) // (1024**3)

    return processed


def main():
    module = AnsibleModule(
        argument_spec=dict(
            path=dict(type="str", required=True),
            name=dict(type="str", required=True),
            state=dict(type="str", default="present", choices=["absent", "present"]),
            purpose=dict(
                type="str",
                default="DEFAULT_SHARE",
                choices=[
                    "DEFAULT_SHARE",
                    "LEGACY_SHARE",
                    "TIMEMACHINE_SHARE",
                    "MULTIPROTOCOL_SHARE",
                    "TIME_LOCKED_SHARE",
                    "PRIVATE_DATASETS_SHARE",
                    "EXTERNAL_SHARE",
                    "VEEAM_REPOSITORY_SHARE",
                    "FCP_SHARE",
                ],
            ),
            enabled=dict(type="bool", default=True),
            comment=dict(type="str", default=""),
            readonly=dict(type="bool", default=False),
            browsable=dict(type="bool", default=True),
            access_based_share_enumeration=dict(type="bool", default=False),
            audit=dict(type="dict", default=None),
            options=dict(type="dict", default=None),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Assign variables from properties
    name = module.params["name"]
    path = module.params["path"]
    state = module.params["state"]
    purpose = module.params["purpose"]
    enabled = module.params["enabled"]
    comment = module.params["comment"]
    readonly = module.params["readonly"]
    browsable = module.params["browsable"]
    abe = module.params["access_based_share_enumeration"]
    audit = module.params["audit"]
    options = module.params["options"]

    # Look up the share
    try:
        share_info = mw.call("sharing.smb.query", [["path", "=", path]])
        if len(share_info) == 0:
            share_info = None
        else:
            share_info = share_info[0]
    except Exception as e:
        module.fail_json(msg=f"Error looking up share {name}: {e}")

    if share_info is None:
        # Share doesn't exist
        if state == "present":
            # Create share
            arg = {
                "path": path,
                "name": name,
                "purpose": purpose,
                "enabled": enabled,
                "comment": comment,
                "readonly": readonly,
                "browsable": browsable,
                "access_based_share_enumeration": abe,
            }

            if audit is not None:
                arg["audit"] = audit

            if options is not None:
                try:
                    arg["options"] = process_options(purpose, options)
                except Exception as e:
                    module.fail_json(msg=f"Error processing options: {e}")

            if module.check_mode:
                result["msg"] = f"Would have created share {name}"
                result["changed"] = True
            else:
                try:
                    share_result = mw.call("sharing.smb.create", arg)
                    result["share"] = share_result
                    result["changed"] = True
                    result["msg"] = f"Created share {name}"
                except Exception as e:
                    result["failed_invocation"] = arg
                    module.fail_json(msg=f"Error creating share {name}: {e}")
        else:
            # Share not supposed to exist, all is well
            result["changed"] = False

    else:
        # Share exists
        if state == "present":
            # Update share if needed
            arg = {}

            if share_info["name"] != name:
                arg["name"] = name

            if share_info["purpose"] != purpose:
                arg["purpose"] = purpose

            if share_info["enabled"] != enabled:
                arg["enabled"] = enabled

            if share_info["comment"] != comment:
                arg["comment"] = comment

            if share_info["readonly"] != readonly:
                arg["readonly"] = readonly

            if share_info["browsable"] != browsable:
                arg["browsable"] = browsable

            if share_info["access_based_share_enumeration"] != abe:
                arg["access_based_share_enumeration"] = abe

            # Check audit changes
            if audit is not None:
                if share_info.get("audit") != audit:
                    arg["audit"] = audit

            # Check options changes
            if options is not None:
                try:
                    processed_options = process_options(purpose, options)
                    if share_info.get("options") != processed_options:
                        arg["options"] = processed_options
                except Exception as e:
                    module.fail_json(msg=f"Error processing options: {e}")

            if len(arg) == 0:
                # No changes
                result["changed"] = False
                result["share"] = share_info
            else:
                # Update share
                if module.check_mode:
                    result["msg"] = f"Would have updated share {name}: {arg}"
                    result["changed"] = True
                else:
                    try:
                        share_result = mw.call(
                            "sharing.smb.update", share_info["id"], arg
                        )
                        result["share"] = share_result
                        result["changed"] = True
                        result["msg"] = f"Updated share {name}"
                    except Exception as e:
                        module.fail_json(
                            msg=f"Error updating share {name} with {arg}: {e}"
                        )
        else:
            # Delete share
            if module.check_mode:
                result["msg"] = f"Would have deleted share {name}"
                result["changed"] = True
            else:
                try:
                    mw.call("sharing.smb.delete", share_info["id"])
                    result["changed"] = True
                    result["msg"] = f"Deleted share {name}"
                except Exception as e:
                    module.fail_json(msg=f"Error deleting share {name}: {e}")

    module.exit_json(**result)


if __name__ == "__main__":
    main()
