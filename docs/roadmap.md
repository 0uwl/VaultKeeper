# Roadmap and known issues

## Web interface

- **OIDC authentication** - admins should be able to configure OIDC providers that they
  and end-users can use to login and enroll with.
- **Build a proper frontend** - all static files are currently served directly by Flask.
  It works fine and is made pretty using Bootstrap but using an established frontend
  framework would make future frontend development easier.

## General

- **Audit log** - an event log should be available to the admin to see detailed events triggered by
  users. This log can be stored in the new `vaultkeeper_data` database and be viewable on the admin dashboard.