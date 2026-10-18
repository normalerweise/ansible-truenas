#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

# Bring a TrueNAS app's images up to date, without risking the running app.

DOCUMENTATION = """
---
module: app_images
version_added: 1.16.0
short_description: Pull a TrueNAS app's images and redeploy only when they changed.
description:
  - Pulls the current images for every tag an app uses, then redeploys the app
    only if at least one tag now resolves to a different image.
  - Pairs with C(pull_policy: missing) in a custom app's compose file. That
    policy keeps an app start or restart from depending on the registry, so a
    registry outage cannot take the app down; this module is then the explicit
    step that moves the app onto a newly published tag.
  - The pull happens before anything is stopped. If the registry is
    unreachable the module fails and the running containers are untouched.
  - Uses the app.pull_images, app.image.query and app.redeploy API methods.
  - This is a Level 1 (L1) module that provides direct API access to TrueNAS middleware.
abstraction_level: L1
abstraction_type: direct_api
options:
  app_name:
    description:
      - Name of the application instance.
    type: str
    required: true
    aliases: ['name']
  redeploy:
    description:
      - Redeploy the app when a pull changed any of its images.
      - With C(false) the new images are only pulled; they take effect on the
        app's next start or redeploy.
    type: bool
    default: true
notes:
  - Change detection compares local image IDs before and after the pull. If a
    pull succeeded but the redeploy that followed it failed, the next run sees
    no change and will not redeploy; recover with C(midclt call --job
    app.redeploy <app_name>).
  - In check mode nothing is pulled. The result is predicted from the
    middleware's image update cache (app.outdated_docker_images), which is
    refreshed periodically and may lag a just-published tag.
"""

EXAMPLES = """
- name: Move the app onto newly published images
  normalerweise.truenas.l1.app_images:
    app_name: smarthome-data-platform

- name: Pre-pull only; apply on the next restart
  normalerweise.truenas.l1.app_images:
    app_name: smarthome-data-platform
    redeploy: false
"""

RETURN = """
msg:
  description: Status message.
  returned: always
  type: str
changed:
  description: Whether any image changed (and, with C(redeploy), the app was redeployed).
  returned: always
  type: bool
updated_images:
  description: Image tags that now resolve to a different image.
  returned: always
  type: list
  elements: str
redeployed:
  description: Whether the app was redeployed.
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule

from ...module_utils.middleware import MiddleWare as MW


def app_image_tags(mw, app_name):
    """Return the image tags the app's compose file uses."""
    app = mw.call("app.get_instance", app_name)
    return app["active_workloads"]["images"]


def local_image_ids(mw, tags):
    """Map each tag to the ID of the local image it currently resolves to."""
    ids = {}
    for image in mw.call("app.image.query"):
        for tag in image["repo_tags"]:
            if tag in tags:
                ids[tag] = image["id"]
    return ids


def changed_tags(before, after):
    """Return the tags whose image ID differs between two snapshots, sorted."""
    return sorted(tag for tag in after if before.get(tag) != after[tag])


def predict(mw, app_name):
    """Check-mode result: what the image update cache says is outdated."""
    outdated = sorted(mw.call("app.outdated_docker_images", app_name))
    return dict(
        changed=bool(outdated),
        updated_images=outdated,
        redeployed=False,
        msg=(f"Would pull and redeploy for {', '.join(outdated)}" if outdated
             else "Image update cache reports no outdated images"),
    )


def pull_and_redeploy(mw, app_name, redeploy):
    """Pull the app's images; redeploy if any tag moved."""
    tags = app_image_tags(mw, app_name)
    before = local_image_ids(mw, tags)
    mw.job("app.pull_images", app_name, {"redeploy": False})
    updated = changed_tags(before, local_image_ids(mw, tags))

    redeployed = bool(updated) and redeploy
    if redeployed:
        mw.job("app.redeploy", app_name)

    if not updated:
        msg = "All images already up to date"
    elif redeployed:
        msg = f"Redeployed with new images: {', '.join(updated)}"
    else:
        msg = f"Pulled new images, not redeployed: {', '.join(updated)}"
    return dict(changed=bool(updated), updated_images=updated, redeployed=redeployed, msg=msg)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            app_name=dict(type="str", required=True, aliases=["name"]),
            redeploy=dict(type="bool", default=True),
        ),
        supports_check_mode=True,
    )

    app_name = module.params["app_name"]
    mw = MW.client()

    try:
        if module.check_mode:
            result = predict(mw, app_name)
        else:
            result = pull_and_redeploy(mw, app_name, module.params["redeploy"])
    except Exception as e:
        module.fail_json(msg=f"Error updating images for app {app_name}: {e}")

    module.exit_json(**result)


# Main
if __name__ == "__main__":
    main()
