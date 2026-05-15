#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r"""
---
module: vm
short_description: Manage TrueNAS SCALE virtual machines (libvirt/KVM)
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Create, update, delete, and drive lifecycle for KVM VMs via the legacy C(vm.*) namespace.
  - Idempotent by C(name) — the module resolves C(name) to the int ID used by the middleware.
  - Devices are not managed here; use C(normalerweise.truenas.l1.vm_device) for that.
abstraction_level: L1
abstraction_type: direct_api
options:
  name:
    description:
      - VM name. Used as the idempotency key.
    type: str
    required: true
  state:
    description:
      - Desired state.
    type: str
    choices: [absent, present, started, stopped, restarted, poweroff]
    default: present
  description:
    description:
      - Free-form description for the VM.
    type: str
  vcpus:
    description:
      - Number of CPU sockets.
    type: int
  cores:
    description:
      - Cores per socket.
    type: int
  threads:
    description:
      - Threads per core.
    type: int
  memory:
    description:
      - RAM allocation in MiB. The middleware expects MB; we pass through verbatim.
    type: int
  min_memory:
    description:
      - Minimum RAM (MiB) for memory ballooning. C(null) disables ballooning.
    type: int
  bootloader:
    description:
      - Firmware type.
    type: str
    choices: [UEFI, UEFI_CSM]
  bootloader_ovmf:
    description:
      - OVMF firmware file name (e.g. C(OVMF_CODE_4M.fd) or C(OVMF_CODE_4M.secboot.fd)).
    type: str
  autostart:
    description:
      - Whether the VM auto-starts on host boot.
    type: bool
  time:
    description:
      - Guest time reference.
    type: str
    choices: [LOCAL, UTC]
  shutdown_timeout:
    description:
      - Seconds to wait for graceful shutdown before force-off (5–300).
    type: int
  enable_secure_boot:
    description:
      - Enable UEFI Secure Boot. Forces q35 machine type when set.
    type: bool
  command_line_args:
    description:
      - Extra QEMU command-line arguments.
    type: str
  arch_type:
    description:
      - Guest architecture (e.g. C(x86_64)). C(null) lets the host decide.
    type: str
  machine_type:
    description:
      - Guest machine type (e.g. C(pc-q35-6.2)). C(null) lets the host decide.
    type: str
  stop_force:
    description:
      - When C(state=stopped), bypass graceful shutdown.
    type: bool
    default: false
  stop_force_after_timeout:
    description:
      - When C(state=stopped), force shutdown if graceful exceeds C(shutdown_timeout).
    type: bool
    default: false
  delete_zvols:
    description:
      - When C(state=absent), also delete child ZFS volumes attached as disks.
    type: bool
    default: false
  delete_force:
    description:
      - When C(state=absent), force deletion even if running.
    type: bool
    default: false
notes:
  - C(vm.create), C(vm.update), C(vm.delete), C(vm.start), C(vm.poweroff) are plain calls.
  - C(vm.stop) and C(vm.restart) are job-type calls.
version_added: 1.6.0
"""

EXAMPLES = r"""
- name: Create the Forgejo runner VM
  normalerweise.truenas.l1.vm:
    name: forgejo-runner
    vcpus: 1
    cores: 2
    threads: 1
    memory: 4096
    bootloader: UEFI
    autostart: false
    time: UTC

- name: Ensure the runner VM is running
  normalerweise.truenas.l1.vm:
    name: forgejo-runner
    state: started

- name: Stop and remove the VM with its zvols
  normalerweise.truenas.l1.vm:
    name: forgejo-runner
    state: absent
    delete_zvols: true
    delete_force: true
"""

RETURN = r"""
vm:
  description: The VM record after the operation.
  returned: when state != absent
  type: dict
msg:
  description: Human-readable status.
  returned: always
  type: str
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


# Fields that are part of the VMCreate/VMUpdate schema and that this module exposes.
# Keys with None values are dropped before sending to the middleware so server defaults apply.
_MUTABLE_FIELDS = (
    "description",
    "vcpus",
    "cores",
    "threads",
    "memory",
    "min_memory",
    "bootloader",
    "bootloader_ovmf",
    "autostart",
    "time",
    "shutdown_timeout",
    "enable_secure_boot",
    "command_line_args",
    "arch_type",
    "machine_type",
)


def _query_vm(mw, name):
    found = mw.call("vm.query", [["name", "=", name]])
    return found[0] if found else None


def _build_payload(params, include_name=True):
    payload = {}
    if include_name:
        payload["name"] = params["name"]
    for key in _MUTABLE_FIELDS:
        value = params[key]
        if value is not None:
            payload[key] = value
    return payload


def _needs_update(existing, desired_payload):
    # enable_secure_boot is intentionally excluded from updates (the schema disallows it).
    for key, want in desired_payload.items():
        if key == "name":
            continue
        if key == "enable_secure_boot":
            continue
        if existing.get(key) != want:
            return True
    return False


def _lifecycle(mw, module, vm_record, desired):
    vm_id = vm_record["id"]
    status_obj = vm_record.get("status") or {}
    current = status_obj.get("state") or "UNKNOWN"
    is_running = current == "RUNNING"

    if desired == "started":
        if is_running:
            return False, f"VM {vm_record['name']} already running"
        if module.check_mode:
            return True, f"Would start VM {vm_record['name']}"
        mw.call("vm.start", vm_id)
        return True, f"Started VM {vm_record['name']}"

    if desired == "stopped":
        if not is_running:
            return False, f"VM {vm_record['name']} already stopped"
        if module.check_mode:
            return True, f"Would stop VM {vm_record['name']}"
        mw.job("vm.stop", vm_id, {
            "force": module.params["stop_force"],
            "force_after_timeout": module.params["stop_force_after_timeout"],
        })
        return True, f"Stopped VM {vm_record['name']}"

    if desired == "restarted":
        if module.check_mode:
            return True, f"Would restart VM {vm_record['name']}"
        mw.job("vm.restart", vm_id)
        return True, f"Restarted VM {vm_record['name']}"

    if desired == "poweroff":
        if not is_running:
            return False, f"VM {vm_record['name']} already off"
        if module.check_mode:
            return True, f"Would power off VM {vm_record['name']}"
        mw.call("vm.poweroff", vm_id)
        return True, f"Powered off VM {vm_record['name']}"

    raise AssertionError(f"Unhandled lifecycle state {desired}")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            state=dict(
                type="str",
                default="present",
                choices=["absent", "present", "started", "stopped", "restarted", "poweroff"],
            ),
            description=dict(type="str"),
            vcpus=dict(type="int"),
            cores=dict(type="int"),
            threads=dict(type="int"),
            memory=dict(type="int"),
            min_memory=dict(type="int"),
            bootloader=dict(type="str", choices=["UEFI", "UEFI_CSM"]),
            bootloader_ovmf=dict(type="str"),
            autostart=dict(type="bool"),
            time=dict(type="str", choices=["LOCAL", "UTC"]),
            shutdown_timeout=dict(type="int"),
            enable_secure_boot=dict(type="bool"),
            command_line_args=dict(type="str"),
            arch_type=dict(type="str"),
            machine_type=dict(type="str"),
            stop_force=dict(type="bool", default=False),
            stop_force_after_timeout=dict(type="bool", default=False),
            delete_zvols=dict(type="bool", default=False),
            delete_force=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()
    name = module.params["name"]
    state = module.params["state"]

    try:
        existing = _query_vm(mw, name)
    except Exception as e:
        module.fail_json(msg=f"Error querying VM {name}: {e}")

    if state == "absent":
        if existing is None:
            result["msg"] = f"VM {name} does not exist"
            module.exit_json(**result)
        if module.check_mode:
            result["changed"] = True
            result["msg"] = f"Would delete VM {name}"
            module.exit_json(**result)
        try:
            mw.call("vm.delete", existing["id"], {
                "zvols": module.params["delete_zvols"],
                "force": module.params["delete_force"],
            })
        except Exception as e:
            module.fail_json(msg=f"Error deleting VM {name}: {e}")
        result["changed"] = True
        result["msg"] = f"Deleted VM {name}"
        module.exit_json(**result)

    if state == "present":
        payload = _build_payload(module.params, include_name=True)

        if existing is None:
            # enable_secure_boot only meaningful on create — schema excludes it from update
            if module.params["enable_secure_boot"] is not None:
                payload["enable_secure_boot"] = module.params["enable_secure_boot"]
            if module.check_mode:
                result["changed"] = True
                result["msg"] = f"Would create VM {name}"
                module.exit_json(**result)
            try:
                created = mw.call("vm.create", payload)
            except Exception as e:
                module.fail_json(
                    msg=f"Error creating VM {name}: {e}",
                    failed_invocation=payload,
                )
            result["changed"] = True
            result["msg"] = f"Created VM {name}"
            result["vm"] = created
            module.exit_json(**result)

        # Exists → check drift on mutable fields
        if _needs_update(existing, payload):
            update_payload = _build_payload(module.params, include_name=False)
            if module.check_mode:
                result["changed"] = True
                result["msg"] = f"Would update VM {name}"
                result["vm"] = existing
                module.exit_json(**result)
            try:
                updated = mw.call("vm.update", existing["id"], update_payload)
            except Exception as e:
                module.fail_json(
                    msg=f"Error updating VM {name}: {e}",
                    failed_invocation=update_payload,
                )
            result["changed"] = True
            result["msg"] = f"Updated VM {name}"
            result["vm"] = updated
            module.exit_json(**result)

        result["msg"] = f"VM {name} is up to date"
        result["vm"] = existing
        module.exit_json(**result)

    # Lifecycle states require the VM to exist.
    if existing is None:
        module.fail_json(msg=f"VM {name} does not exist; cannot manage lifecycle")
    try:
        changed, msg = _lifecycle(mw, module, existing, state)
    except Exception as e:
        module.fail_json(msg=f"Error during '{state}' on VM {name}: {e}")
    result["changed"] = changed
    result["msg"] = msg
    result["vm"] = _query_vm(mw, name)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
