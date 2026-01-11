#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r"""
---
module: app
short_description: Manage TrueNAS SCALE applications
description:
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
  - Create, manage, and delete applications on TrueNAS SCALE.
  - Supports both catalog apps and custom Docker Compose applications.
  - Uses the modern app.create/update/delete API methods.
options:
  app_name:
    description:
      - Name of the application instance.
      - Must be alphanumeric with hyphens, 1-40 characters.
      - Must start and end with a letter or number.
    type: str
    required: true
    aliases: ['name']
  state:
    description:
      - Desired state of the application.
      - C(present) ensures the app exists and is configured as specified.
      - C(absent) ensures the app is removed.
      - C(started) ensures the app is running (idempotent).
      - C(stopped) ensures the app is stopped (idempotent).
      - C(restarted) always restarts the app.
      - C(reloaded) reloads the app if running, starts if stopped.
    type: str
    choices: [ absent, present, started, stopped, restarted, reloaded ]
    default: present
  custom_app:
    description:
      - If true, creates a custom Docker Compose application.
      - If false, installs from the TrueNAS catalog.
    type: bool
    default: false
  catalog_app:
    description:
      - Name of the catalog application to install.
      - Required when custom_app is false.
      - Should be null or omitted for custom apps.
    type: str
  train:
    description:
      - Catalog train to use (e.g., "stable", "enterprise").
      - Only applicable for catalog apps.
    type: str
    default: stable
  version:
    description:
      - Version of the catalog app to install.
      - Use "latest" for the most recent version.
      - Only applicable for catalog apps.
    type: str
    default: latest
  values:
    description:
      - Configuration values for the application.
      - Structure depends on the specific app being installed.
      - For catalog apps, these are the chart values.
    type: dict
  custom_compose_config:
    description:
      - Docker Compose configuration as a structured dictionary.
      - Use this for custom apps with programmatic configuration.
      - Mutually exclusive with custom_compose_config_string.
    type: dict
  custom_compose_config_string:
    description:
      - Docker Compose configuration as a YAML string.
      - Use this for custom apps with YAML-based configuration.
      - Mutually exclusive with custom_compose_config.
    type: str
notes:
  - This module uses the TrueNAS middleware API via websocket/JSON-RPC.
  - The app.create method is a job-type operation that may take time to complete.
  - Catalog apps require the catalog to be synchronized before installation.
  - For custom apps, provide either custom_compose_config or custom_compose_config_string.
version_added: 1.5.0
"""

EXAMPLES = r"""
- name: Install Plex from catalog
  normalerweise.truenas.app:
    app_name: plex
    catalog_app: plex
    train: stable
    version: latest
    values:
      plex_claim_token: "claim-xxxxxxxxxxxx"
      network_mode: host

- name: Create custom Docker Compose app
  normalerweise.truenas.app:
    app_name: my-custom-app
    custom_app: true
    custom_compose_config_string: |
      version: '3.8'
      services:
        web:
          image: nginx:latest
          ports:
            - "8080:80"

- name: Create custom app with structured config
  normalerweise.truenas.app:
    app_name: redis-cache
    custom_app: true
    custom_compose_config:
      version: '3.8'
      services:
        redis:
          image: redis:7-alpine
          ports:
            - "6379:6379"
          volumes:
            - redis_data:/data
      volumes:
        redis_data:

- name: Remove an application
  normalerweise.truenas.app:
    app_name: old-app
    state: absent

- name: Ensure app is running
  normalerweise.truenas.app:
    app_name: caddy-reverse-proxy
    state: started

- name: Stop an app
  normalerweise.truenas.app:
    app_name: caddy-reverse-proxy
    state: stopped

- name: Restart app (always bounces)
  normalerweise.truenas.app:
    app_name: caddy-reverse-proxy
    state: restarted

- name: Reload app (start if stopped)
  normalerweise.truenas.app:
    app_name: caddy-reverse-proxy
    state: reloaded
"""

RETURN = r"""
app:
  description:
    - Information about the application after creation or update.
  type: dict
  returned: when state is present
  contains:
    id:
      description: Unique identifier for the app.
      type: str
    name:
      description: Name of the application.
      type: str
    state:
      description: Current state (RUNNING, STOPPED, DEPLOYING, etc.).
      type: str
    version:
      description: Version identifier.
      type: str
    custom_app:
      description: Whether this is a custom app.
      type: bool
    metadata:
      description: App metadata including description and category.
      type: dict
msg:
  description: Human-readable message about the operation.
  type: str
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def validate_app_name(name):
    """
    Validate app name meets TrueNAS requirements.

    Args:
        name: App name to validate

    Returns:
        tuple: (valid, error_message)
    """
    import re

    if not name:
        return False, "App name cannot be empty"

    if len(name) < 1 or len(name) > 40:
        return False, "App name must be 1-40 characters"

    # Must be alphanumeric with hyphens, start/end with letter or number
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$", name):
        return (
            False,
            "App name must be alphanumeric with hyphens, starting and ending with letter or number",
        )

    return True, None


def _values_differ(existing, new):
    """
    Deep comparison of configuration values to detect changes.

    Args:
        existing: Existing configuration from TrueNAS (dict)
        new: New configuration values (dict)

    Returns:
        bool: True if values differ and update is needed
    """
    # Handle None cases
    if new is None:
        return False
    if existing is None:
        return True

    # Recursively compare dictionaries
    if isinstance(new, dict):
        for key, new_value in new.items():
            existing_value = existing.get(key)

            # Recursively check nested structures
            if isinstance(new_value, (dict, list)):
                if _values_differ(existing_value, new_value):
                    return True
            else:
                # Direct comparison for primitive types
                # Handle type coercion (e.g., "true" vs True, "1" vs 1)
                if _normalize_value(existing_value) != _normalize_value(new_value):
                    return True
        return False

    # Compare lists
    elif isinstance(new, list):
        if not isinstance(existing, list):
            return True
        if len(new) != len(existing):
            return True

        # Compare list elements
        for i, new_item in enumerate(new):
            if i >= len(existing):
                return True
            if _values_differ(existing[i], new_item):
                return True
        return False

    # Primitive comparison
    else:
        return _normalize_value(existing) != _normalize_value(new)


def _normalize_value(value):
    """
    Normalize values for comparison to handle type differences.

    TrueNAS may return values in different types than what we send
    (e.g., boolean as string, numbers as strings, etc.)
    """
    if value is None:
        return None

    # Convert booleans represented as strings
    if isinstance(value, str):
        if value.lower() in ("true", "yes", "1"):
            return True
        elif value.lower() in ("false", "no", "0"):
            return False

    # Convert boolean to consistent representation
    if isinstance(value, bool):
        return value

    # Try to convert numeric strings to numbers for comparison
    if isinstance(value, str):
        try:
            # Try integer first
            return int(value)
        except ValueError:
            try:
                # Try float
                return float(value)
            except ValueError:
                # Return as-is if not numeric
                return value

    return value


def main():
    module = AnsibleModule(
        argument_spec=dict(
            app_name=dict(type="str", required=True, aliases=["name"]),
            state=dict(
                type="str",
                default="present",
                choices=[
                    "absent",
                    "present",
                    "started",
                    "stopped",
                    "restarted",
                    "reloaded",
                ],
            ),
            custom_app=dict(type="bool", default=False),
            catalog_app=dict(type="str"),
            train=dict(type="str", default="stable"),
            version=dict(type="str", default="latest"),
            values=dict(type="dict"),
            custom_compose_config=dict(type="dict"),
            custom_compose_config_string=dict(type="str"),
        ),
        supports_check_mode=True,
        mutually_exclusive=[["custom_compose_config", "custom_compose_config_string"]],
    )

    result = dict(changed=False, msg="")

    mw = MW.client()

    # Get parameters
    app_name = module.params["app_name"]
    state = module.params["state"]
    custom_app = module.params["custom_app"]
    catalog_app = module.params["catalog_app"]
    train = module.params["train"]
    version = module.params["version"]
    values = module.params["values"]
    custom_compose_config = module.params["custom_compose_config"]
    custom_compose_config_string = module.params["custom_compose_config_string"]

    # Validate app name
    valid, error = validate_app_name(app_name)
    if not valid:
        module.fail_json(msg=f"Invalid app name: {error}")

    # Check if app exists
    try:
        app_list = mw.call("app.query", [["name", "=", app_name]])
        app_exists = len(app_list) > 0
        existing_app = app_list[0] if app_exists else None
    except Exception as e:
        module.fail_json(msg=f"Error querying app {app_name}: {e}")

    # Validate parameters for state=present
    if state == "present":
        if not custom_app and not catalog_app:
            module.fail_json(msg="catalog_app is required when custom_app is False")

    if state == "present":
        if not app_exists:
            # Create new app
            create_args = {
                "app_name": app_name,
                "custom_app": custom_app,
            }

            # Add catalog-specific parameters
            if not custom_app:
                create_args["catalog_app"] = catalog_app
                create_args["train"] = train
                create_args["version"] = version
            else:
                # Set catalog_app to null for custom apps
                create_args["catalog_app"] = None

            # Add optional parameters
            if values is not None:
                create_args["values"] = values

            if custom_compose_config is not None:
                create_args["custom_compose_config"] = custom_compose_config

            if custom_compose_config_string is not None:
                create_args["custom_compose_config_string"] = (
                    custom_compose_config_string
                )

            if module.check_mode:
                result["msg"] = f"Would have created app {app_name}"
                result["changed"] = True
            else:
                try:
                    # app.create is a job-type method
                    app_result = mw.job("app.create", create_args)
                    result["app"] = app_result
                    result["changed"] = True
                    result["msg"] = f"Created app {app_name}"
                except Exception as e:
                    result["failed_invocation"] = create_args
                    module.fail_json(msg=f"Error creating app {app_name}: {e}")
        else:
            # App exists - check if update is needed
            update_args = {}

            # Add optional parameters (only those accepted by app.update)
            if values is not None:
                update_args["values"] = values

            if custom_compose_config is not None:
                update_args["custom_compose_config"] = custom_compose_config

            if custom_compose_config_string is not None:
                update_args["custom_compose_config_string"] = (
                    custom_compose_config_string
                )

            # Check if update is needed by comparing configuration
            needs_update = False
            if custom_app:
                # For custom apps, check if compose config changed
                existing_compose = existing_app.get("custom_compose_config_string", "")
                new_compose = custom_compose_config_string or ""
                if existing_compose != new_compose:
                    needs_update = True
            else:
                # For catalog apps, compare values to detect changes
                if values is not None:
                    # Get existing app configuration
                    existing_config = existing_app.get("config", {})

                    # Deep comparison of configuration values
                    # We need to check if the new values differ from existing config
                    if _values_differ(existing_config, values):
                        needs_update = True

            if needs_update:
                if module.check_mode:
                    result["msg"] = f"Would have updated app {app_name}"
                    result["changed"] = True
                else:
                    try:
                        # app.update is a job-type method
                        app_result = mw.job("app.update", app_name, update_args)
                        result["app"] = app_result
                        result["changed"] = True
                        result["msg"] = f"Updated app {app_name}"
                    except Exception as e:
                        result["failed_invocation"] = update_args
                        module.fail_json(msg=f"Error updating app {app_name}: {e}")
            else:
                result["changed"] = False
                result["app"] = existing_app
                result["msg"] = f"App {app_name} is up to date"

    elif state == "absent":
        if app_exists:
            # Delete the app
            if module.check_mode:
                result["msg"] = f"Would have deleted app {app_name}"
                result["changed"] = True
            else:
                try:
                    # app.delete takes the app name and optional parameters
                    mw.job("app.delete", app_name)
                    result["changed"] = True
                    result["msg"] = f"Deleted app {app_name}"
                except Exception as e:
                    module.fail_json(msg=f"Error deleting app {app_name}: {e}")
        else:
            # App doesn't exist, nothing to do
            result["changed"] = False
            result["msg"] = f"App {app_name} does not exist"

    elif state in ["started", "stopped", "restarted", "reloaded"]:
        # Lifecycle management - app must exist
        if not app_exists:
            module.fail_json(
                msg=f"App {app_name} does not exist. Cannot manage lifecycle."
            )

        current_state = existing_app.get("state", "UNKNOWN")
        is_running = current_state == "RUNNING"

        if state == "started":
            if is_running:
                result["msg"] = f"App {app_name} is already running"
                result["changed"] = False
            else:
                if module.check_mode:
                    result["msg"] = f"Would have started app {app_name}"
                    result["changed"] = True
                else:
                    try:
                        mw.job("app.start", app_name)
                        result["changed"] = True
                        result["msg"] = f"Started app {app_name}"
                    except Exception as e:
                        module.fail_json(msg=f"Error starting app {app_name}: {e}")

        elif state == "stopped":
            if not is_running:
                result["msg"] = f"App {app_name} is already stopped"
                result["changed"] = False
            else:
                if module.check_mode:
                    result["msg"] = f"Would have stopped app {app_name}"
                    result["changed"] = True
                else:
                    try:
                        mw.job("app.stop", app_name)
                        result["changed"] = True
                        result["msg"] = f"Stopped app {app_name}"
                    except Exception as e:
                        module.fail_json(msg=f"Error stopping app {app_name}: {e}")

        elif state == "restarted":
            # Always restart regardless of current state
            if module.check_mode:
                result["msg"] = f"Would have restarted app {app_name}"
                result["changed"] = True
            else:
                try:
                    # Stop if running
                    if is_running:
                        mw.job("app.stop", app_name)
                    # Always start (even if was already stopped)
                    mw.job("app.start", app_name)
                    result["changed"] = True
                    result["msg"] = f"Restarted app {app_name}"
                except Exception as e:
                    module.fail_json(msg=f"Error restarting app {app_name}: {e}")

        elif state == "reloaded":
            # Reload if running, start if stopped
            if module.check_mode:
                result["msg"] = f"Would have reloaded/started app {app_name}"
                result["changed"] = True
            else:
                try:
                    if is_running:
                        # For containers, restart is equivalent to reload
                        mw.job("app.stop", app_name)
                        mw.job("app.start", app_name)
                        result["changed"] = True
                        result["msg"] = f"Reloaded app {app_name}"
                    else:
                        mw.job("app.start", app_name)
                        result["changed"] = True
                        result["msg"] = f"Started app {app_name} (was stopped)"
                except Exception as e:
                    module.fail_json(msg=f"Error reloading app {app_name}: {e}")

    module.exit_json(**result)


if __name__ == "__main__":
    main()
