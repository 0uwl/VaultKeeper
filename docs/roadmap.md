# Roadmap and known issues

## Web interface

- **OIDC authentication** - admins should be able to configure OIDC providers that they
  and end-users can use to login and enroll with.
- **Build a proper frontend** - all static files are currently served directly by Flask.
  It works fine and is made pretty using Bootstrap but using an established frontend
  framework would make future frontend development easier and would make the app feel
  snappier and less janky.

## General

- **CLI audit logging** - the CLI is not audited yet. Since the CLI is only ever used by
  the server admin, this is low priority, but it would be consistent to record CLI-triggered
  events in the same audit log in `vaultkeeper_data`.