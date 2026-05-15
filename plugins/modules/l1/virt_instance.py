#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r"""
---
module: virt_instance
short_description: Manage TrueNAS SCALE Instances (Incus VMs/containers)
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Create, update, start, stop, and delete Incus-backed instances on TrueNAS SCALE.
  - Idempotent by C(name).
abstraction_level: L1
abstraction_type: direct_api
options:
  name:
    description:
      - Instance name. Must be unique on the host.
    type: str
    required: true
  state:
    description:
      - Desired state.
      - C(present) ensures the instance exists and matches configuration.
      - C(absent) removes the instance.
      - C(started) / C(stopped) / C(restarted) drive lifecycle.
    type: str
    choices: [absent, present, started, stopped, restarted]
    default: present
  instance_type:
    description:
      - VM or system container.
    type: str
    choices: [VM, CONTAINER]
    default: VM
  source_type:
    description:
      - Where the instance's root disk comes from.
      - C(IMAGE) pulls from a remote image server (e.g. linuxcontainers).
    type: str
    choices: [IMAGE]
    default: IMAGE
  image:
    description:
      - Image identifier on the remote (e.g. C(ubuntu/24.04/cloud)).
      - Required when C(source_type=IMAGE) and the instance does not yet exist.
    type: str
  remote:
    description:
      - Image remote name. SCALE bundles the C(linuxcontainers) remote by default.
    type: str
    default: linuxcontainers
  cpu:
    description:
      - CPU allocation passed through verbatim (e.g. C("2") for two vCPUs, or a cpuset).
    type: str
  memory:
    description:
      - Memory in MiB. Converted to bytes for the middleware call.
    type: int
  autostart:
    description:
      - Whether the instance starts on host boot.
    type: bool
    default: true
  cloud_init_user_data:
    description:
      - Raw cloud-init user-data injected into the instance. VM only.
    type: str
  environment:
    description:
      - Extra environment variables / Incus config keys passed through verbatim.
    type: dict
  devices:
    description:
      - List of device specifications passed through verbatim to the middleware.
      - Each device is a dict with at minimum C(name) and C(dev_type) (e.g. DISK, NIC, PROXY).
    type: list
    elements: dict
notes:
  - C(virt.instance.create), C(update), C(delete), C(start), C(stop), C(restart) are job-type calls.
  - Memory is accepted in MiB for ergonomics; the middleware is called with bytes.
version_added: 1.6.0
"""

EXAMPLES = r"""
- name: Create an Ubuntu VM for the Forgejo runner
  normalerweise.truenas.l1.virt_instance:
    name: forgejo-runner
    instance_type: VM
    source_type: IMAGE
    image: ubuntu/24.04/cloud
    cpu: "2"
    memory: 4096
    autostart: true
    cloud_init_user_data: "{{ lookup('template', 'cloud-init.yaml.j2') }}"

- name: Stop the runner VM
  normalerweise.truenas.l1.virt_instance:
    name: forgejo-runner
    state: stopped

- name: Remove the runner VM
  normalerweise.truenas.l1.virt_instance:
    name: forgejo-runner
    state: absent
"""

RETURN = r"""
instance:
  description: The instance record after the operation (or null on absent).
  returned: when state != absent
  type: dict
msg:
  description: Human-readable status.
  returned: always
  type: str
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


MIB = 1024 * 1024


def _mib_to_bytes(mib):
    if mib is None:
        return None
    return int(mib) * MIB


def _query_instance(mw, name):
    found = mw.call("virt.instance.query", [["name", "=", name]])
    return found[0] if found else None


def _build_create_payload(params):
    """Compose the virt.instance.create payload from module params.

    Only includes keys with non-None values, so the middleware applies its own defaults
    for anything the caller didn't specify.
    """
    payload = {
        "name": params["name"],
        "instance_type": params["instance_type"],
        "source_type": params["source_type"],
        "autostart": params["autostart"],
        "remote": params["remote"],
    }
    if params["image"] is not None:
        payload["image"] = params["image"]
    if params["cpu"] is not None:
        payload["cpu"] = params["cpu"]
    if params["memory"] is not None:
        payload["memory"] = _mib_to_bytes(params["memory"])
    if params["cloud_init_user_data"] is not None:
        payload["cloud_init_user_data"] = params["cloud_init_user_data"]
    if params["environment"]:
        payload["environment"] = params["environment"]
    if params["devices"]:
        payload["devices"] = params["devices"]
    return payload


def _build_update_payload(params):
    """virt.instance.update only accepts mutable fields — exclude immutable ones like image/source."""
    payload = {}
    if params["cpu"] is not None:
        payload["cpu"] = params["cpu"]
    if params["memory"] is not None:
        payload["memory"] = _mib_to_bytes(params["memory"])
    if params["autostart"] is not None:
        payload["autostart"] = params["autostart"]
    if params["cloud_init_user_data"] is not None:
        payload["cloud_init_user_data"] = params["cloud_init_user_data"]
    if params["environment"]:
        payload["environment"] = params["environment"]
    return payload


def _needs_update(existing, params):
    """Compare existing instance fields against desired mutable params."""
    if params["cpu"] is not None and str(existing.get("cpu")) != str(params["cpu"]):
        return True
    if params["memory"] is not None:
        want_bytes = _mib_to_bytes(params["memory"])
        have = existing.get("memory")
        if have != want_bytes:
            return True
    if params["autostart"] is not None and existing.get("autostart") != params["autostart"]:
        return True
    # cloud_init_user_data: middleware may not echo it back; only update on explicit changes via re-run is unsafe.
    # Treat user-data as immutable post-create; users rebuild the VM to rotate it (matches the ephemeral model).
    return False


def _handle_lifecycle(mw, module, name, current_state, desired):
    is_running = current_state == "RUNNING"

    if desired == "started":
        if is_running:
            return False, f"Instance {name} is already running"
        if module.check_mode:
            return True, f"Would start instance {name}"
        mw.job("virt.instance.start", name)
        return True, f"Started instance {name}"

    if desired == "stopped":
        if not is_running:
            return False, f"Instance {name} is already stopped"
        if module.check_mode:
            return True, f"Would stop instance {name}"
        mw.job("virt.instance.stop", name)
        return True, f"Stopped instance {name}"

    if desired == "restarted":
        if module.check_mode:
            return True, f"Would restart instance {name}"
        mw.job("virt.instance.restart", name)
        return True, f"Restarted instance {name}"

    raise AssertionError(f"Unhandled lifecycle state {desired}")


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            state=dict(
                type="str",
                default="present",
                choices=["absent", "present", "started", "stopped", "restarted"],
            ),
            instance_type=dict(type="str", default="VM", choices=["VM", "CONTAINER"]),
            source_type=dict(type="str", default="IMAGE", choices=["IMAGE"]),
            image=dict(type="str"),
            remote=dict(type="str", default="linuxcontainers"),
            cpu=dict(type="str"),
            memory=dict(type="int"),
            autostart=dict(type="bool", default=True),
            cloud_init_user_data=dict(type="str", no_log=False),
            environment=dict(type="dict"),
            devices=dict(type="list", elements="dict"),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()
    name = module.params["name"]
    state = module.params["state"]

    try:
        existing = _query_instance(mw, name)
    except Exception as e:
        module.fail_json(msg=f"Error querying virt.instance {name}: {e}")

    if state == "absent":
        if existing is None:
            result["msg"] = f"Instance {name} does not exist"
            module.exit_json(**result)
        if module.check_mode:
            result["changed"] = True
            result["msg"] = f"Would delete instance {name}"
            module.exit_json(**result)
        try:
            # Stop first if running — virt.instance.delete won't proceed against a running instance.
            if existing.get("status") == "RUNNING" or existing.get("state") == "RUNNING":
                mw.job("virt.instance.stop", name)
            mw.job("virt.instance.delete", name)
        except Exception as e:
            module.fail_json(msg=f"Error deleting instance {name}: {e}")
        result["changed"] = True
        result["msg"] = f"Deleted instance {name}"
        module.exit_json(**result)

    if state == "present":
        if existing is None:
            if module.params["image"] is None:
                module.fail_json(msg="image is required to create a new instance")
            payload = _build_create_payload(module.params)
            if module.check_mode:
                result["changed"] = True
                result["msg"] = f"Would create instance {name}"
                module.exit_json(**result)
            try:
                created = mw.job("virt.instance.create", payload)
            except Exception as e:
                module.fail_json(
                    msg=f"Error creating instance {name}: {e}",
                    failed_invocation=payload,
                )
            result["changed"] = True
            result["msg"] = f"Created instance {name}"
            result["instance"] = created if isinstance(created, dict) else _query_instance(mw, name)
            module.exit_json(**result)

        # Exists — check for mutable drift
        if _needs_update(existing, module.params):
            update_payload = _build_update_payload(module.params)
            if module.check_mode:
                result["changed"] = True
                result["msg"] = f"Would update instance {name}"
                result["instance"] = existing
                module.exit_json(**result)
            try:
                mw.job("virt.instance.update", name, update_payload)
            except Exception as e:
                module.fail_json(
                    msg=f"Error updating instance {name}: {e}",
                    failed_invocation=update_payload,
                )
            result["changed"] = True
            result["msg"] = f"Updated instance {name}"
            result["instance"] = _query_instance(mw, name)
            module.exit_json(**result)

        result["msg"] = f"Instance {name} is up to date"
        result["instance"] = existing
        module.exit_json(**result)

    # Lifecycle states
    if existing is None:
        module.fail_json(msg=f"Instance {name} does not exist; cannot manage lifecycle")
    current = existing.get("status") or existing.get("state") or "UNKNOWN"
    try:
        changed, msg = _handle_lifecycle(mw, module, name, current, state)
    except Exception as e:
        module.fail_json(msg=f"Error during lifecycle op '{state}' on {name}: {e}")
    result["changed"] = changed
    result["msg"] = msg
    result["instance"] = _query_instance(mw, name)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
