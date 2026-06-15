# Roadmap and known issues

## Web interface

- **Separate admin and end-user dashboard** - currently, only the admin can log into
  VaultKeeper to manage vaults. In the future, end-users should have their own dashboards
  for the vaults they own.
- **OIDC authentication** - admins should be able to configure OIDC providers that they
  and end-users can use to login.
- **Build a proper frontend** - all static files are currently served directly by Flask.
  It works fine and is made pretty using Bootstrap but using an established frontend
  framework would make future frontend development easier.
