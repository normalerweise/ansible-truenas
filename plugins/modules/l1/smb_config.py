#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = """
---
module: smb_config
short_description: Configure SMB service
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Configure the SMB service global settings.
  - For individual SMB shares, see C(sharing_smb)
abstraction_level: L1
abstraction_type: direct_api
options:
  netbiosname:
    description:
      - The NetBIOS name of this server.
      - Defaults to the original hostname of the system.
    type: str
  netbiosalias:
    description:
      - List of NetBIOS aliases.
      - If Server is joined to an AD domain, additional Kerberos Service Principal Names will be generated for these aliases.
    type: list
    elements: str
  workgroup:
    description:
      - NetBIOS workgroup to which the TrueNAS server belongs.
      - This will be automatically set to the correct value during the process of joining an AD domain.
      - NOTE: workgroup and netbiosname should have different values.
    type: str
  description:
    description:
      - Description of the SMB server.
      - SMB clients may see this description during some operations.
    type: str
  enable_smb1:
    description:
      - Enable SMB1 support on the server.
      - WARNING: using the SMB1 protocol is not recommended.
    type: bool
  unixcharset:
    description:
      - Select character set for file names on local filesystem.
      - Use this option only if you know the names are not UTF-8.
    type: str
    choices:
      - UTF-8
      - GB2312
      - HZ-GB-2312
      - CP1361
      - BIG5
      - BIG5HKSCS
      - CP037
      - CP273
      - CP424
      - CP437
      - CP500
      - CP775
      - CP850
      - CP852
      - CP855
      - CP857
      - CP858
      - CP860
      - CP861
      - CP862
      - CP863
      - CP864
      - CP865
      - CP866
      - CP869
      - CP932
      - CP949
      - CP950
      - CP1026
      - CP1125
      - CP1140
      - CP1250
      - CP1251
      - CP1252
      - CP1253
      - CP1254
      - CP1255
      - CP1256
      - CP1257
      - CP1258
      - EUC_JIS_2004
      - EUC_JISX0213
      - EUC_JP
      - EUC_KR
      - GB18030
      - GBK
      - HZ
      - ISO2022_JP
      - ISO2022_JP_1
      - ISO2022_JP_2
      - ISO2022_JP_2004
      - ISO2022_JP_3
      - ISO2022_JP_EXT
      - ISO2022_KR
      - ISO8859_1
      - ISO8859_2
      - ISO8859_3
      - ISO8859_4
      - ISO8859_5
      - ISO8859_6
      - ISO8859_7
      - ISO8859_8
      - ISO8859_9
      - ISO8859_10
      - ISO8859_11
      - ISO8859_13
      - ISO8859_14
      - ISO8859_15
      - ISO8859_16
      - JOHAB
      - KOI8_R
      - KZ1048
      - LATIN_1
      - MAC_CYRILLIC
      - MAC_GREEK
      - MAC_ICELAND
      - MAC_LATIN2
      - MAC_ROMAN
      - MAC_TURKISH
      - PTCP154
      - SHIFT_JIS
      - SHIFT_JIS_2004
      - SHIFT_JISX0213
      - TIS_620
      - UTF_16
      - UTF_16_BE
      - UTF_16_LE
  localmaster:
    description:
      - When set to true the NetBIOS name server in TrueNAS participates in elections for the local master browser.
      - When set to false the NetBIOS name server does not attempt to become a local master browser on a subnet and loses all browsing elections.
      - NOTE: This parameter has no effect if the NetBIOS name server is disabled.
    type: bool
  syslog:
    description:
      - Send log messages to syslog.
      - Enable this option if you want SMB server error logs to be included in information sent to a remote syslog server.
      - NOTE: This requires that remote syslog is globally configured on TrueNAS.
    type: bool
  aapl_extensions:
    description:
      - Enable support for SMB2/3 AAPL protocol extensions.
      - This setting makes the TrueNAS server advertise support for Apple protocol extensions as a MacOS server.
      - Enabling this is required for Time Machine support.
    type: bool
  admin_group:
    description:
      - The selected group has full administrator privileges on TrueNAS via the SMB protocol.
    type: str
  guest:
    description:
      - SMB guest account username.
      - This username provides access to legacy SMB shares with guest access enabled.
      - It must be a valid, existing local user account.
    type: str
  filemask:
    description:
      - smb.conf create mask.
      - DEFAULT applies current server default which is 664.
    type: str
  dirmask:
    description:
      - smb.conf directory mask.
      - DEFAULT applies current server default which is 775.
    type: str
  ntlmv1_auth:
    description:
      - Enable legacy and very insecure NTLMv1 authentication.
      - This should never be done except in extreme edge cases and may be against regulations in non-home environments.
    type: bool
  multichannel:
    description:
      - Enable SMB3 multi-channel support.
    type: bool
  encryption:
    description:
      - SMB2/3 transport encryption setting for the TrueNAS SMB server.
      - NEGOTIATE - Enable negotiation of data encryption. Encrypt data only if the client explicitly requests it.
      - DESIRED - Enable negotiation of data encryption. Encrypt data on sessions and share connections for clients that support it.
      - REQUIRED - Require data encryption for sessions and share connections. NOTE: Clients that do not support encryption cannot access SMB shares.
      - DEFAULT - Use the TrueNAS SMB server default encryption settings. Currently, this is the same as NEGOTIATE.
    type: str
    choices:
      - DEFAULT
      - NEGOTIATE
      - DESIRED
      - REQUIRED
  bindip:
    description:
      - List of IP addresses used by the TrueNAS SMB server.
      - When empty, listen on all available addresses.
    type: list
    elements: str
  smb_options:
    description:
      - Additional unvalidated and unsupported configuration options for the SMB server.
      - WARNING: Using smb_options may produce unexpected server behavior.
    type: str
  debug:
    description:
      - Set SMB log levels to debug.
      - Use this setting only when troubleshooting a specific SMB issue.
      - Do not use it in production environments.
    type: bool
version_added: 0.4.0
"""

EXAMPLES = """
- name: Set NetBIOS name to hostname
  normalerweise.truenas.l1.smb_config:
    netbiosname: "{{ ansible_facts['hostname'] }}"

- name: Configure SMB service with description
  normalerweise.truenas.l1.smb_config:
    description: "F3 NAS"
    enable_smb1: false
    unixcharset: "UTF-8"
    syslog: true
    aapl_extensions: true
    multichannel: true

- name: Set guest account
  normalerweise.truenas.l1.smb_config:
    guest: "guest"

- name: Enable encryption (required)
  normalerweise.truenas.l1.smb_config:
    encryption: "REQUIRED"

- name: Bind to specific IPs
  normalerweise.truenas.l1.smb_config:
    bindip:
      - "192.168.1.10"
      - "10.0.0.5"
"""

RETURN = """
status:
  description:
    - A data structure describing the state of the SMB service.
    - In check_mode and when no changes are needed, this is the current state of the SMB service.
    - When changes have successfully been made, this is the new state of the SMB service.
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def main():
    module = AnsibleModule(
        argument_spec=dict(
            netbiosname=dict(type="str"),
            netbiosalias=dict(type="list", elements="str"),
            workgroup=dict(type="str"),
            description=dict(type="str"),
            enable_smb1=dict(type="bool"),
            unixcharset=dict(
                type="str",
                choices=[
                    "UTF-8",
                    "GB2312",
                    "HZ-GB-2312",
                    "CP1361",
                    "BIG5",
                    "BIG5HKSCS",
                    "CP037",
                    "CP273",
                    "CP424",
                    "CP437",
                    "CP500",
                    "CP775",
                    "CP850",
                    "CP852",
                    "CP855",
                    "CP857",
                    "CP858",
                    "CP860",
                    "CP861",
                    "CP862",
                    "CP863",
                    "CP864",
                    "CP865",
                    "CP866",
                    "CP869",
                    "CP932",
                    "CP949",
                    "CP950",
                    "CP1026",
                    "CP1125",
                    "CP1140",
                    "CP1250",
                    "CP1251",
                    "CP1252",
                    "CP1253",
                    "CP1254",
                    "CP1255",
                    "CP1256",
                    "CP1257",
                    "CP1258",
                    "EUC_JIS_2004",
                    "EUC_JISX0213",
                    "EUC_JP",
                    "EUC_KR",
                    "GB18030",
                    "GBK",
                    "HZ",
                    "ISO2022_JP",
                    "ISO2022_JP_1",
                    "ISO2022_JP_2",
                    "ISO2022_JP_2004",
                    "ISO2022_JP_3",
                    "ISO2022_JP_EXT",
                    "ISO2022_KR",
                    "ISO8859_1",
                    "ISO8859_2",
                    "ISO8859_3",
                    "ISO8859_4",
                    "ISO8859_5",
                    "ISO8859_6",
                    "ISO8859_7",
                    "ISO8859_8",
                    "ISO8859_9",
                    "ISO8859_10",
                    "ISO8859_11",
                    "ISO8859_13",
                    "ISO8859_14",
                    "ISO8859_15",
                    "ISO8859_16",
                    "JOHAB",
                    "KOI8_R",
                    "KZ1048",
                    "LATIN_1",
                    "MAC_CYRILLIC",
                    "MAC_GREEK",
                    "MAC_ICELAND",
                    "MAC_LATIN2",
                    "MAC_ROMAN",
                    "MAC_TURKISH",
                    "PTCP154",
                    "SHIFT_JIS",
                    "SHIFT_JIS_2004",
                    "SHIFT_JISX0213",
                    "TIS_620",
                    "UTF_16",
                    "UTF_16_BE",
                    "UTF_16_LE",
                ],
            ),
            localmaster=dict(type="bool"),
            syslog=dict(type="bool"),
            aapl_extensions=dict(type="bool"),
            admin_group=dict(type="str"),
            guest=dict(type="str"),
            filemask=dict(type="str"),
            dirmask=dict(type="str"),
            ntlmv1_auth=dict(type="bool"),
            multichannel=dict(type="bool"),
            encryption=dict(
                type="str", choices=["DEFAULT", "NEGOTIATE", "DESIRED", "REQUIRED"]
            ),
            bindip=dict(type="list", elements="str"),
            smb_options=dict(type="str"),
            debug=dict(type="bool"),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Assign variables from properties, for convenience
    netbiosname = module.params["netbiosname"]
    netbiosalias = module.params["netbiosalias"]
    workgroup = module.params["workgroup"]
    description = module.params["description"]
    enable_smb1 = module.params["enable_smb1"]
    unixcharset = module.params["unixcharset"]
    localmaster = module.params["localmaster"]
    syslog = module.params["syslog"]
    aapl_extensions = module.params["aapl_extensions"]
    admin_group = module.params["admin_group"]
    guest = module.params["guest"]
    filemask = module.params["filemask"]
    dirmask = module.params["dirmask"]
    ntlmv1_auth = module.params["ntlmv1_auth"]
    multichannel = module.params["multichannel"]
    encryption = module.params["encryption"]
    bindip = module.params["bindip"]
    smb_options = module.params["smb_options"]
    debug = module.params["debug"]

    try:
        smb_info = mw.call("smb.config")
    except Exception as e:
        module.fail_json(msg=f"Error looking up smb configuration: {e}")

    result["status"] = smb_info

    # Make list of differences between what is and what should be
    arg = {}

    if netbiosname is not None and smb_info["netbiosname"] != netbiosname:
        arg["netbiosname"] = netbiosname

    if netbiosalias is not None and set(smb_info["netbiosalias"]) != set(netbiosalias):
        arg["netbiosalias"] = netbiosalias

    if workgroup is not None and smb_info["workgroup"] != workgroup:
        arg["workgroup"] = workgroup

    if description is not None and smb_info["description"] != description:
        arg["description"] = description

    if enable_smb1 is not None and smb_info["enable_smb1"] is not enable_smb1:
        arg["enable_smb1"] = enable_smb1

    if unixcharset is not None and smb_info["unixcharset"] != unixcharset:
        arg["unixcharset"] = unixcharset

    if localmaster is not None and smb_info["localmaster"] is not localmaster:
        arg["localmaster"] = localmaster

    if syslog is not None and smb_info["syslog"] is not syslog:
        arg["syslog"] = syslog

    if (
        aapl_extensions is not None
        and smb_info["aapl_extensions"] is not aapl_extensions
    ):
        arg["aapl_extensions"] = aapl_extensions

    if admin_group is not None and smb_info["admin_group"] != admin_group:
        arg["admin_group"] = admin_group

    if guest is not None and smb_info["guest"] != guest:
        arg["guest"] = guest

    if filemask is not None and smb_info["filemask"] != filemask:
        arg["filemask"] = filemask

    if dirmask is not None and smb_info["dirmask"] != dirmask:
        arg["dirmask"] = dirmask

    if ntlmv1_auth is not None and smb_info["ntlmv1_auth"] is not ntlmv1_auth:
        arg["ntlmv1_auth"] = ntlmv1_auth

    if multichannel is not None and smb_info["multichannel"] is not multichannel:
        arg["multichannel"] = multichannel

    if encryption is not None and smb_info["encryption"] != encryption:
        arg["encryption"] = encryption

    if bindip is not None and set(smb_info["bindip"]) != set(bindip):
        arg["bindip"] = bindip

    if smb_options is not None and smb_info["smb_options"] != smb_options:
        arg["smb_options"] = smb_options

    if debug is not None and smb_info["debug"] is not debug:
        arg["debug"] = debug

    # If there are any changes, smb.update()
    if len(arg) == 0:
        # No changes
        result["changed"] = False
    else:
        # Update smb
        if module.check_mode:
            result["msg"] = f"Would have updated smb: {arg}"
        else:
            try:
                err = mw.call("smb.update", arg)
                result["status"] = err
            except Exception as e:
                module.fail_json(msg=f"Error updating smb with {arg}: {e}")

        result["changed"] = True

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
