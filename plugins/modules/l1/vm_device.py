#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r"""
---
module: vm_device
short_description: Manage devices on TrueNAS SCALE virtual machines
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Manage VM devices (DISK, CDROM, NIC, DISPLAY, RAW, PCI, USB) via the C(vm.device.*) API.
  - Idempotent within a VM by a caller-supplied C(identity) subset of attributes.
  - When C(identity) is omitted the module falls back to common per-dtype defaults
    (e.g. C(serial) for DISK, C(mac) for NIC, C(path) for CDROM/RAW).
abstraction_level: L1
abstraction_type: direct_api
options:
  vm:
    description:
      - Integer ID of the parent VM. Mutually exclusive with C(vm_name).
    type: int
  vm_name:
    description:
      - Name of the parent VM. Resolved to ID via C(vm.query). Mutually exclusive with C(vm).
    type: str
  state:
    description:
      - Desired state.
    type: str
    choices: [present, absent]
    default: present
  dtype:
    description:
      - Device type. Injected into C(attributes.dtype) before the API call.
    type: str
    choices: [DISK, CDROM, NIC, DISPLAY, RAW, PCI, USB]
    required: true
  attributes:
    description:
      - Per-dtype device attributes (see the middleware schema for the discriminated union).
      - C(dtype) is set automatically from the top-level option and must not be set here.
    type: dict
    default: {}
  identity:
    description:
      - Subset of C(attributes) keys that uniquely identify this device within the VM.
      - Defaults per dtype - DISK=[path], CDROM=[path], NIC=[mac], RAW=[path], DISPLAY=[type], PCI=[pptdev], USB=[device].
      - For DISK with C(create_zvol=true), pass C(path) explicitly as C(/dev/zvol/<zvol_name>)
        in C(attributes) — the middleware only persists C(zvol_name)/C(zvol_volsize) at create
        time and resets them to null/false afterwards, so they cannot be used to re-identify an
        already-created device on a later run.
    type: list
    elements: str
  create_only:
    description:
      - Subset of C(attributes) keys that only apply at creation and are excluded from drift
        detection and update payloads. Needed for fields the middleware doesn't persist back
        (e.g. DISK's C(create_zvol)/C(zvol_name)/C(zvol_volsize), reset to null/false once the
        zvol exists) — without this they would appear to "differ" forever and trigger a
        C(vm.device.update) on every run.
      - Defaults per dtype - DISK=[create_zvol, zvol_name, zvol_volsize].
    type: list
    elements: str
  order:
    description:
      - Boot order priority (lower boots first). C(null) for automatic assignment.
    type: int
  delete_zvol:
    description:
      - When C(state=absent) and the device is a DISK with C(create_zvol), also destroy the zvol.
    type: bool
    default: false
  delete_raw_file:
    description:
      - When C(state=absent) and the device is RAW, also delete the backing file.
    type: bool
    default: false
  delete_force:
    description:
      - When C(state=absent), force deletion even if the device is in use.
    type: bool
    default: false
notes:
  - C(vm.device.create/update/delete) are plain calls (not jobs).
version_added: 1.6.0
"""

EXAMPLES = r"""
- name: Attach a 30G zvol root disk to the runner VM
  normalerweise.truenas.l1.vm_device:
    vm_name: forgejo-runner
    dtype: DISK
    attributes:
      create_zvol: true
      zvol_name: dozer/vms/forgejo-runner
      zvol_volsize: 32212254720  # 30 GiB in bytes
      path: /dev/zvol/dozer/vms/forgejo-runner
      type: VIRTIO

- name: Attach the cloud-init seed CDROM
  normalerweise.truenas.l1.vm_device:
    vm_name: forgejo-runner
    dtype: CDROM
    attributes:
      path: /mnt/dozer/apps/forgejo_runner_vm/seed.iso

- name: Attach a NIC on br0
  normalerweise.truenas.l1.vm_device:
    vm_name: forgejo-runner
    dtype: NIC
    attributes:
      nic_attach: br0
      type: VIRTIO
      mac: "52:54:00:12:34:56"
"""

RETURN = r"""
device:
  description: The device record after the operation.
  returned: when state == present
  type: dict
msg:
  description: Human-readable status.
  returned: always
  type: str
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


_DEFAULT_IDENTITY = {
    # zvol_name/serial are both unusable as default identities: zvol_name is
    # reset to null by the middleware once the zvol exists, and serial is a
    # middleware-generated value the caller can't know in advance. path is
    # the only field that's both deterministic up front and persisted back.
    "DISK": ("path",),
    "CDROM": ("path",),
    "NIC": ("mac",),
    "RAW": ("path",),
    "DISPLAY": ("type",),
    "PCI": ("pptdev",),
    "USB": ("device",),
}

# Attributes that only take effect at vm.device.create and are never
# persisted back by the middleware (it resets them to null/false once
# applied) — comparing them on later runs would look like permanent drift.
_DEFAULT_CREATE_ONLY = {
    "DISK": ("create_zvol", "zvol_name", "zvol_volsize"),
}


def _resolve_vm_id(mw, module):
    vm_id = module.params["vm"]
    vm_name = module.params["vm_name"]
    if vm_id is not None:
        return vm_id
    found = mw.call("vm.query", [["name", "=", vm_name]])
    if not found:
        module.fail_json(msg=f"VM {vm_name!r} not found")
    return found[0]["id"]


def _resolve_identity_keys(module):
    keys = module.params["identity"]
    if keys:
        return tuple(keys)
    return _DEFAULT_IDENTITY[module.params["dtype"]]


def _resolve_create_only_keys(module):
    keys = module.params["create_only"]
    if keys:
        return tuple(keys)
    return _DEFAULT_CREATE_ONLY.get(module.params["dtype"], ())


def _matches(existing_attrs, desired_attrs, identity_keys):
    """A device matches when its dtype is equal AND every identity key has the same value."""
    if existing_attrs.get("dtype") != desired_attrs.get("dtype"):
        return False
    for key in identity_keys:
        if existing_attrs.get(key) != desired_attrs.get(key):
            return False
    return True


def _attrs_differ(existing_attrs, desired_attrs, create_only_keys=()):
    """Drift detection — every non-create-only key the caller provided must equal the
    existing record. create_only_keys are excluded since the middleware doesn't persist
    them back (see _DEFAULT_CREATE_ONLY)."""
    for key, want in desired_attrs.items():
        if key in create_only_keys:
            continue
        if existing_attrs.get(key) != want:
            return True
    return False


def _find_matching_device(mw, vm_id, desired_attrs, identity_keys):
    devices = mw.call("vm.device.query", [["vm", "=", vm_id]])
    for dev in devices:
        if _matches(dev.get("attributes") or {}, desired_attrs, identity_keys):
            return dev
    return None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            vm=dict(type="int"),
            vm_name=dict(type="str"),
            state=dict(type="str", default="present", choices=["present", "absent"]),
            dtype=dict(
                type="str",
                required=True,
                choices=["DISK", "CDROM", "NIC", "DISPLAY", "RAW", "PCI", "USB"],
            ),
            attributes=dict(type="dict", default={}),
            identity=dict(type="list", elements="str"),
            create_only=dict(type="list", elements="str"),
            order=dict(type="int"),
            delete_zvol=dict(type="bool", default=False),
            delete_raw_file=dict(type="bool", default=False),
            delete_force=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
        mutually_exclusive=[["vm", "vm_name"]],
        required_one_of=[["vm", "vm_name"]],
    )

    result = dict(changed=False, msg="")
    mw = MW.client()

    # Inject dtype into attributes for the wire schema (discriminator).
    desired_attrs = dict(module.params["attributes"] or {})
    if "dtype" in desired_attrs and desired_attrs["dtype"] != module.params["dtype"]:
        module.fail_json(msg="attributes.dtype must not contradict top-level dtype")
    desired_attrs["dtype"] = module.params["dtype"]

    try:
        vm_id = _resolve_vm_id(mw, module)
    except Exception as e:
        module.fail_json(msg=f"Error resolving VM id: {e}")

    identity_keys = _resolve_identity_keys(module)
    create_only_keys = _resolve_create_only_keys(module)

    try:
        existing = _find_matching_device(mw, vm_id, desired_attrs, identity_keys)
    except Exception as e:
        module.fail_json(msg=f"Error querying devices on VM {vm_id}: {e}")

    state = module.params["state"]

    if state == "absent":
        if existing is None:
            result["msg"] = "Device does not exist"
            module.exit_json(**result)
        if module.check_mode:
            result["changed"] = True
            result["msg"] = f"Would delete device {existing['id']}"
            module.exit_json(**result)
        try:
            mw.call(
                "vm.device.delete",
                existing["id"],
                {
                    "zvol": module.params["delete_zvol"],
                    "raw_file": module.params["delete_raw_file"],
                    "force": module.params["delete_force"],
                },
            )
        except Exception as e:
            module.fail_json(msg=f"Error deleting device {existing['id']}: {e}")
        result["changed"] = True
        result["msg"] = f"Deleted device {existing['id']}"
        module.exit_json(**result)

    # state == "present"
    payload = {
        "vm": vm_id,
        "attributes": desired_attrs,
    }
    if module.params["order"] is not None:
        payload["order"] = module.params["order"]

    if existing is None:
        if module.check_mode:
            result["changed"] = True
            result["msg"] = "Would create device"
            module.exit_json(**result)
        try:
            created = mw.call("vm.device.create", payload)
        except Exception as e:
            module.fail_json(
                msg=f"Error creating device on VM {vm_id}: {e}",
                failed_invocation=payload,
            )
        result["changed"] = True
        result["msg"] = f"Created device {created.get('id')}"
        result["device"] = created
        module.exit_json(**result)

    # Exists — drift check
    existing_attrs = existing.get("attributes") or {}
    order_changed = (
        module.params["order"] is not None
        and existing.get("order") != module.params["order"]
    )
    if not _attrs_differ(existing_attrs, desired_attrs, create_only_keys) and not order_changed:
        result["msg"] = f"Device {existing['id']} is up to date"
        result["device"] = existing
        module.exit_json(**result)

    if module.check_mode:
        result["changed"] = True
        result["msg"] = f"Would update device {existing['id']}"
        result["device"] = existing
        module.exit_json(**result)

    # create-only keys are never valid on vm.device.update — the middleware already
    # reset them to null/false, and resending them (e.g. create_zvol=true) risks the
    # update path re-triggering zvol creation logic that only makes sense at create time.
    update_attrs = {k: v for k, v in desired_attrs.items() if k not in create_only_keys}
    update_payload = {"attributes": update_attrs}
    if module.params["order"] is not None:
        update_payload["order"] = module.params["order"]
    try:
        updated = mw.call("vm.device.update", existing["id"], update_payload)
    except Exception as e:
        module.fail_json(
            msg=f"Error updating device {existing['id']}: {e}",
            failed_invocation=update_payload,
        )
    result["changed"] = True
    result["msg"] = f"Updated device {existing['id']}"
    result["device"] = updated
    module.exit_json(**result)


if __name__ == "__main__":
    main()
