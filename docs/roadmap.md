# Roadmap and known issues

## Web interface

- **OIDC authentication** - admins should be able to configure OIDC providers that they
  and end-users can use to login and enroll with.

## General

- **CLI audit logging** - the CLI is not audited yet. Since the CLI is only ever used by
  the server admin, this is low priority, but it would be consistent to record CLI-triggered
  events in the same audit log in `vaultkeeper_data`.
- **CouchDB backup tool** - there is currently no easy way to backup a CouchDB instance. VaultKeeper
  could act as a backup tool as well by utilising the existing API communication is already performs.
  The backups should be placed in the VaultKeeper container and the user can choose to bind mount
  that location when running their container, or download the backup archive from the web UI.