# Ansible Collection - normalerweise.truenas

Manage a [TrueNAS](https://www.truenas.com/) machine.

## Included content

This collection consists primarily of a set of Ansible modules to
configure a TrueNAS machine, using the
[TrueNAS API](https://www.truenas.com/docs/api/websocket.html)
to control the Middleware Daemon.

It aims to be intuitive to use, and to avoid unpleasant surprises.

## Module Organization

This collection uses abstraction levels similar to AWS CDK to help you choose the right module for your needs:

### L1 - Direct API (Low-Level Control)
Located in `plugins/modules/l1/`

Direct wrappers around TrueNAS middleware API. Use when you need fine-grained control over individual resources.

**Usage:** `normalerweise.truenas.l1.<module>`

**Examples:**
- `normalerweise.truenas.l1.user` - Manage individual user accounts
- `normalerweise.truenas.l1.filesystem` - Manage ZFS datasets
- `normalerweise.truenas.l1.service` - Control TrueNAS services
- `normalerweise.truenas.l1.sharing_smb` - Configure SMB shares

### L2 - Intent-Based (Mid-Level)
Located in `plugins/modules/l2/`

Type-aware modules with intelligent defaults and normalization. Provides a balance between control and convenience.

**Usage:** `normalerweise.truenas.l2.<module>`

**Examples:**
- `normalerweise.truenas.l2.keychaincredential` - Manage SSH credentials with type-aware validation

### L3 - Pattern Orchestration (Recommended for Most Users)
Located in `plugins/modules/l3/`

High-level policy-driven modules that manage multiple resources as cohesive units. These modules automate complex workflows and follow best practices.

**Usage:** `normalerweise.truenas.l3.<module>`

**Examples:**
- `normalerweise.truenas.l3.pool_snapshot_policy` - Tier-based snapshot retention (hourly: 24, daily: 30, etc.)
- `normalerweise.truenas.l3.local_replication_policy` - Push replication with auto-discovery
- `normalerweise.truenas.l3.remote_replication_policy` - Pull replication with tier-based retention

**When to use each level:**
- **L1**: When you need complete control over individual resources or when L3 modules don't cover your use case
- **L2**: When you need type-specific features with some abstraction
- **L3**: For most common use cases - these modules handle the complexity for you

## Installing this collection

The easiest way to install this collection is
[through Ansible Galaxy](https://galaxy.ansible.com/arensb/truenas):

    ansible-galaxy collection install arensb.truenas

## Examples

### L1 - Direct API Examples

    - name: Example L1 tasks
      hosts: truenas-box
      become: yes
      tasks:
        - name: Set the hostname
          normalerweise.truenas.l1.hostname:
            name: new-hostname
        
        - name: Turn on sshd
          normalerweise.truenas.l1.service:
            name: ssh
            enabled: true
            state: started
        
        - name: Create a user
          normalerweise.truenas.l1.user:
            name: johndoe
            comment: "John Doe"
            group: users

### L3 - Policy Examples (Recommended)

    - name: Example L3 policy tasks
      hosts: truenas-box
      become: yes
      tasks:
        - name: Configure snapshot retention policy
          normalerweise.truenas.l3.pool_snapshot_policy:
            dataset: tank/data
            snapshot_policy:
              hourly: 24
              daily: 7
              weekly: 4
              monthly: 12
            state: present
        
        - name: Configure local replication
          normalerweise.truenas.l3.local_replication_policy:
            source_dataset: tank/data
            target_dataset: backup/data
            tiers:
              - hourly
              - daily
            state: present

## Environment Variables

### `middleware_method`

There are two ways of communicating with the middleware daemon on
TrueNAS, referred to here as `midclt` and `client`. `midclt` is older
and better-tested, while `client` is faster but less-well-tested. The
default is `client`.

Set the `middleware_method` environment variable to either `client` or
`midclt` at either the play or task level in your playbook to manually
select how this module communicates with the middleware daemon.

Example:

    - collections: arensb.truenas
      hosts: my-nas
      become: yes
      environment:
        middleware_method: client
      tasks:
        - name: Create a jail
          jail:
            name: my-jail
            release: 13.1-RELEASE
            state: running

## Contributing to this collection
The best way to contribute a patch or feature is to create a pull request.

If you'd like to write your own module, the `extras/template` file
provides a good starting point.

The [HACKING](HACKING.md) file has some tips on how to get around.

## Documentation

See [the online documentation](https://arensb.github.io/truenas/index.html).

## Supported versions of Ansible
- Tested with 2.10.8

## Changelog

See [the user-friendly docs](https://arensb.github.io/truenas/CHANGELOG.html),
or the latest [changelog.yaml](changelogs/changelog.yaml).

## Authors and Contributors

- Andrew Arensburger ([@arensb](https://mastodon.social/@arensb))
- Ed Hull (https://github.com/edhull)
- Mozzie (https://github.com/MozzieBytes)
- bmarinov (https://github.com/bmarinov)
- Paul Heidenreich (https://github.com/Paulomart)
- Gustavo Campos (https://github.com/guhcampos)
- kamransaeed (https://github.com/kamransaeed)
