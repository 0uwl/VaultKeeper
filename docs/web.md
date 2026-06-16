# Web application

A browser-based management UI that replaces the need for `docker exec` and CLI usage
for day-to-day operations. Runs on port **5985** alongside CouchDB on port **5984**.

## Technology

- **Backend:** Python [Flask](https://flask.palletsprojects.com/) - shares core logic via
  imports from `vaultkeeper.client`
- **Frontend:** Server-rendered Jinja2 templates; [Bootstrap 5](https://getbootstrap.com/)
  via CDN, dark theme
- **Port:** Flask runs on port **5985**
- **Auth:** Session-based login using `COUCHDB_USER` / `COUCHDB_PASSWORD`; the web UI is
  protected behind a login page; the Flask app authenticates to CouchDB as the server admin

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **Yes** | Signs session cookies. Must be stable and shared across all workers. Generate with `openssl rand -hex 32`. |
| `COUCHDB_HOST` | No | CouchDB base URL (default: `http://localhost:5984`) |
| `COUCHDB_USER` | No | CouchDB admin username |
| `COUCHDB_PASSWORD` | No | CouchDB admin password |
| `COUCHDB_PUBLIC_URL` | No | External CouchDB URL for setup URIs (falls back to `COUCHDB_HOST`) |
| `VAULTKEEPER_WEB_PORT` | No | Web server port (default: `5985`) |
| `TZ` | No | IANA timezone name for audit log timestamps (default: `UTC`). Example: `Europe/Amsterdam`. |

`SECRET_KEY` is required - the app exits with a clear message at startup if it is not set.
Using a random fallback would silently break sessions across Gunicorn workers (each worker
would sign cookies with a different key, so requests routed to a different worker than the
one that created the session would reject it and redirect to the login page).

## Routes

```
GET  /                            Dashboard - server status, user count, vault count
GET  /login                       Login page
POST /login                       Authenticate
POST /logout

GET  /users                       List all users
POST /users                       Create a user
GET  /users/<username>            User detail - vaults, change password, delete
POST /users/<username>/delete     Delete a user
POST /users/<username>/passwd     Change password

GET  /vaults                      List all vaults
POST /vaults                      Create a vault (username + vault_name)
GET  /vaults/<db_name>            Vault detail - stats, actions
POST /vaults/<db_name>/compact    Trigger compaction
POST /vaults/<db_name>/delete     Delete a vault
GET  /vaults/<db_name>/setup-uri  Show setup URI form
POST /vaults/<db_name>/setup-uri  Generate and display a LiveSync setup URI

GET  /provision                   Provision form
POST /provision                   Create user + vault + setup URI in one step

GET  /audit                       Audit log - chronological event history (admin only)
```

## Audit log

Every significant action taken through the web UI is recorded as an audit event in the
`vaultkeeper_data` CouchDB database. Events are stored as documents with the `audit:` prefix
and are queryable in time order. The `/audit` page (admin only) shows the 200 most recent
events; the 10 most recent also appear on the admin dashboard.

### Event reference

| Action | Actor | Target | Details |
|---|---|---|---|
| `login.success` | username | - | - |
| `login.failure` | `anonymous` | attempted username | - |
| `logout` | username | - | - |
| `user.create` | admin | new username | - |
| `user.delete` | admin | username | - |
| `user.passwd` | actor | username | - |
| `user.limits` | admin | username | `max_vaults`, `max_vault_size_bytes` |
| `user.enroll` | new username | - | `token` (first 8 chars) |
| `vault.create` | actor | db_name | `vault_name`, `owner` |
| `vault.delete` | actor | db_name | `vault_name` |
| `vault.compact` | actor | db_name | `vault_name` |
| `vault.setup_uri` | actor | db_name | `vault_name` |
| `invitation.create` | admin | token (first 8 chars) | `expiry_hours` |
| `invitation.delete` | admin | token (first 8 chars) | - |
| `settings.update` | admin | - | `default_max_vaults`, `default_max_vault_size_bytes` |
| `provision` | admin | username | `vault_name`, `db_name` |

### Document schema

```json
{
  "_id": "audit:20260615T103000123456:a1b2c3d4",
  "type": "audit",
  "timestamp": "2026-06-15T10:30:00.123456+00:00",
  "actor": "admin",
  "action": "vault.create",
  "target": "vault_alice_abc123",
  "details": { "vault_name": "notes", "owner": "alice" }
}
```

The document ID encodes a compact UTC timestamp followed by a random 4-byte hex suffix,
which makes events sortable by `_all_docs` without a view.

## Reverse proxy

Flask serves port 5985 directly. VaultKeeper does not include a reverse proxy.
CouchDB runs on its own container (typically port 5984). Users who want both behind
a single HTTPS endpoint should place their own reverse proxy in front:

- `/_*` and `/` - CouchDB at port 5984
- `/vaultkeeper` (or similar prefix) - VaultKeeper at port 5985
