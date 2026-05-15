#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r"""
---
module: virt_global
short_description: Manage TrueNAS SCALE Instances (Incus) global configuration
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
  - Initializes the SCALE virt (Incus) subsystem by binding a ZFS pool.
  - Idempotent — no-op when the requested pool is already bound and state is INITIALIZED.
abstraction_level: L1
abstraction_type: direct_api
options:
  pool:
    description:
      - ZFS pool to host Incus instances and images.
      - When set, SCALE creates the C(.ix-virt) dataset and an C(incusbr0) bridge.
    type: str
    required: true
  storage_pools:
    description:
      - Optional list of additional pools made available to instances.
      - When omitted, defaults to a single-element list containing C(pool).
    type: list
    elements: str
  bridge:
    description:
      - Name of an existing host bridge to attach instances to.
      - When omitted, SCALE auto-creates and manages C(incusbr0) with NAT.
    type: str
  v4_network:
    description:
      - IPv4 CIDR for the managed bridge. Ignored when C(bridge) is set to a pre-existing bridge.
    type: str
  v6_network:
    description:
      - IPv6 CIDR for the managed bridge. Ignored when C(bridge) is set to a pre-existing bridge.
    type: str
notes:
  - C(virt.global.update) is a job-type middleware call; provisioning the pool can take a few minutes.
  - To tear down virt entirely (unbind the pool), use the TrueNAS UI — destructive ops are not exposed here.
version_added: 1.6.0
"""

EXAMPLES = r"""
- name: Bind virt to the SSD pool
  normalerweise.truenas.l1.virt_global:
    pool: dozer

- name: Bind virt with explicit storage pools and a custom bridge
  normalerweise.truenas.l1.virt_global:
    pool: dozer
    storage_pools: [dozer]
    bridge: incusbr0
"""

RETURN = r"""
config:
  description: The resulting virt.global.config payload.
  returned: always
  type: dict
msg:
  description: Human-readable status.
  returned: always
  type: str
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def _normalize_storage_pools(pool, storage_pools):
    """Default storage_pools to [pool] when not explicitly provided."""
    if storage_pools is None:
        return [pool]
    return storage_pools


def _diff_config(existing, desired):
    """Return the subset of desired keys whose values differ from existing.

    Only keys with a non-None desired value participate in the comparison.
    """
    delta = {}
    for key, want in desired.items():
        if want is None:
            continue
        have = existing.get(key)
        if isinstance(want, list) and isinstance(have, list):
            if sorted(want) != sorted(have):
                delta[key] = want
        elif have != want:
            delta[key] = want
    return delta


def main():
    module = AnsibleModule(
        argument_spec=dict(
            pool=dict(type="str", required=True),
            storage_pools=dict(type="list", elements="str"),
            bridge=dict(type="str"),
            v4_network=dict(type="str"),
            v6_network=dict(type="str"),
        ),
        supports_check_mode=True,
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    pool = module.params["pool"]
    storage_pools = _normalize_storage_pools(pool, module.params["storage_pools"])

    desired = {
        "pool": pool,
        "storage_pools": storage_pools,
        "bridge": module.params["bridge"],
        "v4_network": module.params["v4_network"],
        "v6_network": module.params["v6_network"],
    }

    try:
        existing = mw.call("virt.global.config")
    except Exception as e:
        module.fail_json(msg=f"Error reading virt.global.config: {e}")

    delta = _diff_config(existing, desired)
    already_initialized = existing.get("state") == "INITIALIZED"

    if not delta and already_initialized:
        result["config"] = existing
        result["msg"] = f"virt already initialized with pool '{existing.get('pool')}'"
        module.exit_json(**result)

    if module.check_mode:
        result["changed"] = True
        result["msg"] = f"Would update virt.global with {delta}"
        result["config"] = existing
        module.exit_json(**result)

    try:
        # virt.global.update is a job — initializing the pool runs storage-pool setup,
        # creates the .ix-virt dataset, and provisions the managed bridge.
        updated = mw.job("virt.global.update", delta or desired)
    except Exception as e:
        module.fail_json(
            msg=f"Error updating virt.global with {delta or desired}: {e}",
            failed_invocation=delta or desired,
        )

    # The job return shape isn't documented as the full config object; re-read to be safe.
    try:
        result["config"] = mw.call("virt.global.config")
    except Exception:
        result["config"] = updated

    result["changed"] = True
    result["msg"] = f"virt.global updated: {sorted(delta.keys()) if delta else 'initialized'}"
    module.exit_json(**result)


if __name__ == "__main__":
    main()
