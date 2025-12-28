#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Manage TrueNAS keychain credentials (SSH keys and connection credentials)

DOCUMENTATION = """
---
module: keychaincredential
short_description: Manage TrueNAS keychain credentials
description:
  - Manages keychain credentials for TrueNAS SCALE.
  - Supports SSH key pairs and SSH connection credentials.
  - SSH key pairs store public/private keys for authentication.
  - SSH connection credentials store complete SSH connection configuration including host, port, and authentication details.
  - This is a Level 2 (L2) module that provides intent-based API access with type-aware normalization.
abstraction_level: L2
abstraction_type: intent_based
options:
  name:
    description:
      - Name for the keychain credential.
      - Must be unique across all keychain credentials.
    type: str
    required: true
  type:
    description:
      - Type of keychain credential.
      - C(SSH_KEY_PAIR) for SSH public/private key pairs.
      - C(SSH_CREDENTIALS) for complete SSH connection configuration.
    type: str
    required: true
    choices: ['SSH_KEY_PAIR', 'SSH_CREDENTIALS']
  attributes:
    description:
      - Type-specific attributes for the credential.
      - For C(SSH_KEY_PAIR), requires private_key and optionally public_key.
      - For C(SSH_CREDENTIALS), requires host, private_key (credential ID), and remote_host_key.
    type: dict
    required: true
    suboptions:
      private_key:
        description:
          - For SSH_KEY_PAIR - SSH private key in OpenSSH format.
          - For SSH_CREDENTIALS - Keychain credential ID of the SSH key pair to use.
        type: raw
        required: true
      public_key:
        description:
          - SSH public key in OpenSSH format.
          - Can be omitted and will be automatically derived from private key.
          - Only used for SSH_KEY_PAIR type.
        type: str
        required: false
      host:
        description:
          - SSH server hostname or IP address.
          - Only used for SSH_CREDENTIALS type.
        type: str
        required: false
      port:
        description:
          - SSH server port number.
          - Only used for SSH_CREDENTIALS type.
        type: int
        default: 22
      username:
        description:
          - SSH username for authentication.
          - Only used for SSH_CREDENTIALS type.
        type: str
        default: 'root'
      remote_host_key:
        description:
          - SSH host key of the remote server.
          - Can be discovered using keychaincredential.remote_ssh_host_key_scan API.
          - Only used for SSH_CREDENTIALS type.
        type: str
        required: false
      connect_timeout:
        description:
          - Connection timeout in seconds for SSH connections.
          - Only used for SSH_CREDENTIALS type.
        type: int
        default: 10
  state:
    description:
      - Whether the credential should exist or not.
      - C(present) creates or updates the credential.
      - C(absent) removes the credential.
    type: str
    choices: [ absent, present ]
    default: present
version_added: 1.15.0
notes:
  - This module manages keychain credentials stored in the TrueNAS keychain.
  - SSH key pairs are used by SSH connection credentials.
  - Changes to credentials may affect services using them.
author:
  - "Norman (@normalerweise)"
"""

EXAMPLES = """
- name: Create SSH key pair credential
  normalerweise.truenas.keychaincredential:
    name: "repl-keypair"
    type: "SSH_KEY_PAIR"
    attributes:
      private_key: "{{ lookup('community.general.onepassword', 'ssh-key', field='private_key') }}"
      public_key: "{{ lookup('community.general.onepassword', 'ssh-key', field='public_key') }}"
    state: present

- name: Create SSH connection credential
  normalerweise.truenas.keychaincredential:
    name: "repl-ssh-connection"
    type: "SSH_CREDENTIALS"
    attributes:
      host: "192.168.1.10"
      port: 22
      username: "svc-repl-sender"
      private_key: 1  # ID of SSH_KEY_PAIR credential
      remote_host_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5..."
      connect_timeout: 10
    state: present

- name: Remove keychain credential
  normalerweise.truenas.keychaincredential:
    name: "old-keypair"
    type: "SSH_KEY_PAIR"
    attributes: {}
    state: absent
"""

RETURN = """
---
changed:
  description: Whether any changes were made
  type: bool
  returned: always
  sample: true
msg:
  description: Human-readable message describing what happened
  type: str
  returned: always
  sample: "Keychain credential created successfully"
credential:
  description: The keychain credential that was created or updated
  type: dict
  returned: when state=present
  sample:
    id: 1
    name: "repl-keypair"
    type: "SSH_KEY_PAIR"
    attributes:
      private_key: "-----BEGIN OPENSSH PRIVATE KEY-----\\n..."
      public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5..."
credential_id:
  description: ID of the created or updated credential
  type: int
  returned: when state=present
  sample: 1
deleted_id:
  description: ID of credential that was deleted
  type: int
  returned: when state=absent and credential was deleted
  sample: 1
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def normalize_attributes(credential_type, attributes):
    """Normalize and validate attributes based on credential type.

    Args:
        credential_type: Type of credential (SSH_KEY_PAIR or SSH_CREDENTIALS)
        attributes: Dictionary of attributes

    Returns:
        Normalized attributes dictionary

    Raises:
        ValueError: If required attributes are missing
    """
    if credential_type == "SSH_KEY_PAIR":
        if "private_key" not in attributes:
            raise ValueError("private_key is required for SSH_KEY_PAIR")

        normalized = {
            "private_key": attributes["private_key"],
        }

        if "public_key" in attributes and attributes["public_key"]:
            normalized["public_key"] = attributes["public_key"]

        return normalized

    elif credential_type == "SSH_CREDENTIALS":
        required = ["host", "private_key", "remote_host_key"]
        missing = [f for f in required if f not in attributes]
        if missing:
            raise ValueError(
                f"Missing required attributes for SSH_CREDENTIALS: {', '.join(missing)}"
            )

        normalized = {
            "host": attributes["host"],
            "private_key": int(attributes["private_key"]),
            "remote_host_key": attributes["remote_host_key"],
            "port": attributes.get("port", 22),
            "username": attributes.get("username", "root"),
            "connect_timeout": attributes.get("connect_timeout", 10),
        }

        return normalized

    else:
        raise ValueError(f"Unknown credential type: {credential_type}")


def credentials_match(existing, desired, credential_type):
    """Compare existing and desired credentials to determine if update is needed.

    Args:
        existing: Existing credential dict from API
        desired: Desired credential dict
        credential_type: Type of credential

    Returns:
        True if credentials match, False if update needed
    """
    # Name must match
    if existing.get("name") != desired.get("name"):
        return False

    # Type must match
    if existing.get("type") != desired.get("type"):
        return False

    # Check attributes based on type
    existing_attrs = existing.get("attributes", {})
    desired_attrs = desired.get("attributes", {})

    if credential_type == "SSH_KEY_PAIR":
        # Compare private and public keys
        if existing_attrs.get("private_key") != desired_attrs.get("private_key"):
            return False

        # Public key is optional - only compare if provided
        if "public_key" in desired_attrs:
            if existing_attrs.get("public_key") != desired_attrs.get("public_key"):
                return False

        return True

    elif credential_type == "SSH_CREDENTIALS":
        # Compare all SSH connection attributes
        keys_to_compare = [
            "host",
            "port",
            "username",
            "private_key",
            "remote_host_key",
            "connect_timeout",
        ]

        for key in keys_to_compare:
            if existing_attrs.get(key) != desired_attrs.get(key):
                return False

        return True

    return False


# ==============================================================================
# MAIN LOGIC
# ==============================================================================


def query_credential(mw, name):
    """Query keychain credential by name.

    Args:
        mw: MiddleWare client
        name: Credential name

    Returns:
        Credential dict or None if not found
    """
    try:
        filters = [["name", "=", name]]
        credentials = mw.call("keychaincredential.query", filters)
        return credentials[0] if credentials else None
    except Exception as e:
        raise Exception(f"Failed to query keychain credential '{name}': {e}")


def create_credential(mw, config):
    """Create keychain credential.

    Args:
        mw: MiddleWare client
        config: Credential configuration dict

    Returns:
        Created credential dict
    """
    try:
        return mw.call("keychaincredential.create", config)
    except Exception as e:
        name = config.get("name", "unknown")
        raise Exception(f"Failed to create keychain credential '{name}': {e}")


def update_credential(mw, credential_id, config):
    """Update keychain credential.

    Args:
        mw: MiddleWare client
        credential_id: Credential ID to update
        config: New configuration dict

    Returns:
        Updated credential dict
    """
    try:
        return mw.call("keychaincredential.update", credential_id, config)
    except Exception as e:
        raise Exception(f"Failed to update keychain credential {credential_id}: {e}")


def delete_credential(mw, credential_id):
    """Delete keychain credential.

    Args:
        mw: MiddleWare client
        credential_id: Credential ID to delete

    Returns:
        True on success
    """
    try:
        return mw.call("keychaincredential.delete", credential_id)
    except Exception as e:
        raise Exception(f"Failed to delete keychain credential {credential_id}: {e}")


def ensure_present(module, mw, params):
    """Ensure keychain credential exists with desired configuration.

    Args:
        module: AnsibleModule instance
        mw: MiddleWare client
        params: Module parameters

    Returns:
        Result dict with changed flag and credential info
    """
    name = params["name"]
    credential_type = params["type"]
    attributes = params["attributes"]
    check_mode = module.check_mode

    # Normalize attributes
    try:
        normalized_attrs = normalize_attributes(credential_type, attributes)
    except ValueError as e:
        module.fail_json(msg=str(e))

    # Build desired configuration
    desired_config = {
        "name": name,
        "type": credential_type,
        "attributes": normalized_attrs,
    }

    # Query existing credential
    existing = query_credential(mw, name)

    if existing:
        # Check if update needed
        if credentials_match(existing, desired_config, credential_type):
            return {
                "changed": False,
                "msg": f"Keychain credential '{name}' already exists with desired configuration",
                "credential": existing,
                "credential_id": existing["id"],
            }

        # Update needed
        if check_mode:
            return {
                "changed": True,
                "msg": f"Would update keychain credential '{name}'",
                "credential_id": existing["id"],
            }

        updated = update_credential(mw, existing["id"], desired_config)
        return {
            "changed": True,
            "msg": f"Keychain credential '{name}' updated",
            "credential": updated,
            "credential_id": updated["id"],
        }

    else:
        # Create new credential
        if check_mode:
            return {
                "changed": True,
                "msg": f"Would create keychain credential '{name}'",
            }

        created = create_credential(mw, desired_config)
        return {
            "changed": True,
            "msg": f"Keychain credential '{name}' created",
            "credential": created,
            "credential_id": created["id"],
        }


def ensure_absent(module, mw, params):
    """Ensure keychain credential does not exist.

    Args:
        module: AnsibleModule instance
        mw: MiddleWare client
        params: Module parameters

    Returns:
        Result dict with changed flag and deleted ID
    """
    name = params["name"]
    check_mode = module.check_mode

    # Query existing credential
    existing = query_credential(mw, name)

    if not existing:
        return {
            "changed": False,
            "msg": f"Keychain credential '{name}' does not exist",
        }

    # Delete credential
    if check_mode:
        return {
            "changed": True,
            "msg": f"Would delete keychain credential '{name}'",
            "deleted_id": existing["id"],
        }

    delete_credential(mw, existing["id"])
    return {
        "changed": True,
        "msg": f"Keychain credential '{name}' deleted",
        "deleted_id": existing["id"],
    }


# ==============================================================================
# ANSIBLE MODULE
# ==============================================================================


def main():
    """Ansible module entry point."""

    # Define module
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            type=dict(
                type="str",
                required=True,
                choices=["SSH_KEY_PAIR", "SSH_CREDENTIALS"],
            ),
            attributes=dict(type="dict", required=True),
            state=dict(type="str", default="present", choices=["absent", "present"]),
        ),
        supports_check_mode=True,
    )

    # Extract parameters
    params = {
        "name": module.params["name"],
        "type": module.params["type"],
        "attributes": module.params["attributes"],
        "state": module.params["state"],
    }

    # Initialize middleware
    try:
        mw = MW.client()
    except Exception as e:
        module.fail_json(msg=f"Failed to initialize middleware client: {e}")

    # Execute based on state
    try:
        if params["state"] == "present":
            result = ensure_present(module, mw, params)
        else:
            result = ensure_absent(module, mw, params)

        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=f"Error managing keychain credential: {e}")


# Main
if __name__ == "__main__":
    main()
