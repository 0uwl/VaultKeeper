# VaultKeeper

VaultKeeper makes it easy to create and manage [Obsidian Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync)
vaults in CouchDB. It runs as a sidecar container alongside your existing CouchDB instance.

Instead of manually configuring databases, security documents, and setup URIs, VaultKeeper gives you a
browser UI and a CLI that handle everything - getting a new user from zero to a syncing Obsidian vault
in minutes, without touching config files or curl commands.

**Design principles:**

- **Vault-management-first.** The vault naming scheme, setup URI flow, and security model are all
  designed around LiveSync's expectations, not generic CouchDB usage.
- **Sidecar model.** VaultKeeper is its own container. Bring your own CouchDB instance; VaultKeeper
  connects to it over the network and manages it.
- **Operator-friendly.** Managed through a browser UI or a CLI. Fauxton (CouchDB's built-in UI) is
  intentionally not the primary management interface.
- **Additive, not destructive.** VaultKeeper creates and manages resources in CouchDB but does not
  modify CouchDB's core server configuration.

---

## Repository structure

```
.
├── vaultkeeper/                    # Python package
│   ├── __init__.py
│   ├── client.py                   # Core CouchDB module - shared by CLI and web app
│   ├── cli.py                      # Click-based CLI (entry point: couchdb-cli)
│   └── web/
│       ├── __init__.py
│       ├── app.py                  # Flask app factory (create_app) + main() entry point
│       ├── routes.py               # Blueprint "main" - all route handlers
│       ├── templates/              # Jinja2 HTML templates (Bootstrap 5)
│       └── static/                 # CSS overrides
├── tests/
│   ├── conftest.py
│   ├── test_server.py
│   ├── test_users.py
│   ├── test_vaults.py
│   └── test_setup_uri.py
├── Dockerfile
├── pyproject.toml                  # Package definition, dependencies, scripts
└── README.md                       # This file
```

---

## CLI (`cli`)

A Python CLI tool built with [Click](https://click.palletsprojects.com/).
Installed inside the container at `/usr/local/bin/cli` and invoked
via `docker exec`.

### Configuration

Connection settings are resolved in the following order for each command:

1. CLI flags (`--host`, `--admin`, `--password`)
2. Environment variables (`COUCHDB_HOST`, `COUCHDB_USER`, `COUCHDB_PASSWORD`)
3. Credentials file (`~/.vaultkeeper/credentials`)
4. Interactive prompt

| Variable                    | Description                               | Default                         |
|-----------------------------|-------------------------------------------|---------------------------------|
| `COUCHDB_HOST`              | CouchDB base URL                          | `http://localhost:5984`         |
| `COUCHDB_USER`              | Admin username                            | prompted                        |
| `COUCHDB_PASSWORD`          | Admin password                            | prompted                        |
| `COUCHDB_PUBLIC_URL`        | External URL embedded in setup URIs       | falls back to `COUCHDB_HOST`    |

### Commands

```
cli server init                               # Apply LiveSync CouchDB config (idempotent)
cli server login                              # Save login credentials to a file (in plain text)

cli user create <username>                    # Create a CouchDB user
cli user delete <username>                    # Delete a CouchDB user
cli user list                                 # List all users
cli user passwd <username>                    # Change a user's password

cli vault create <username> <vault_name>      # Create a vault database
cli vault delete <db_name>                    # Delete a vault database
cli vault list <username>                     # List vaults for a user
cli vault info <db_name>                      # Show size and doc stats
cli vault compact <db_name>                   # Compact a vault database
cli vault setup-uri <username> <vault_name>   # Generate a LiveSync setup URI

cli provision <username> <vault_name>         # Create user + vault + setup URI in one step
```

### `server login` - saving credentials

`cli server login` prompts for host, username, password, and optional
public URL, verifies the credentials against CouchDB, then writes a plain-text
credentials file:

```
COUCHDB_HOST=http://localhost:5984
COUCHDB_USER=admin
COUCHDB_PASSWORD=secret
COUCHDB_PUBLIC_URL=https://couchdb.example.com
```

Default location: `~/.vaultkeeper/credentials`. Override with
`$VAULTKEEPER_CREDENTIALS`. Credentials are stored in plain text - this is an
intentional operator convenience.

### Vault naming scheme

All vault databases follow a strict naming convention to conform to the requirements of CouchDB:

```
vault_<username>_<vault_name>
```

Examples: `vault_alice_notes`, `vault_alice_work`, `vault_bob_personal`

The `vault_name` argument in the CLI is the human-readable short name. The full CouchDB
database name is derived automatically. However, commands that operate on existing
databases (`vault delete`, `vault compact`, `vault info`) must be supplied with the full
database name.

To make it clear:

- "Vault name" → The vault name. Used when a username is also supplied in the command
- "Database name" → The full name used by CouchDB: `vault_<username>_<vault_name>`

### Setup URI generation

The `vault setup-uri` and `provision` commands invoke
`/scripts/generate_setupuri.ts` via Deno to produce an `obsidian://` deep
link that configures the LiveSync plugin in one tap.

Two passphrases are involved:

- **E2E passphrase** - encrypts vault data at rest in CouchDB; baked into the
  setup URI payload; needed if onboarding a device manually without a URI
- **URI passphrase** - encrypts the setup URI itself; Obsidian LiveSync prompts for
  this when the URI is pasted

Both are auto-generated (using `secrets.choice`, 32 characters) if not
supplied. The CLI prints them together with a clear warning to properly store them.

### Security model

Vault databases use CouchDB's `_security` document to restrict access:

```json
{
  "admins":  { "names": ["<username>"], "roles": [] },
  "members": { "names": ["<username>"], "roles": [] }
}
```

Only the vault owner and server admins can read or write the database.
The CLI always connects as the server admin.

---

## Web application (`vaultkeeper-web`)

A browser-based management UI that replaces the need for `docker exec` and CLI
usage for day-to-day operations. Runs on port **5985** alongside CouchDB on
port **5984**.

### Technology

- **Backend:** Python [Flask](https://flask.palletsprojects.com/) - shares core
  logic via imports from `vaultkeeper.client`
- **Frontend:** Server-rendered Jinja2 templates;
  [Bootstrap 5](https://getbootstrap.com/) via CDN, dark theme
- **Port:** Flask runs on port **5985** - CouchDB's port 5984 is untouched
- **Auth:** Session-based login using `COUCHDB_USER` / `COUCHDB_PASSWORD`;
  the web UI is protected behind a login page; the Flask app authenticates to
  CouchDB as the server admin

### Routes

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
```

### Reverse proxy

Flask serves port 5985 directly. VaultKeeper does not include a reverse proxy.
CouchDB runs on its own container (typically port 5984). Users who want both
behind a single HTTPS endpoint should place their own reverse proxy in front:

- `/_*` and `/` → CouchDB at port 5984
- `/manage` (or similar prefix) → VaultKeeper at port 5985

---

## Publishing

**GitHub Container Registry:** `ghcr.io/0uwl/vaultkeeper`

**Versioning:** Semantic versioning. Example: `1.0.0`.

---

## Quick start

A `compose.yml` is included that runs both services together using the official
`couchdb:3.3` image. VaultKeeper automatically applies the required LiveSync
CouchDB configuration on startup — no manual CouchDB setup is needed.

```bash
# Set your credentials - COUCHDB_PUBLIC_URL is the external URL LiveSync clients will use
export COUCHDB_PASSWORD=your-strong-password
export COUCHDB_PUBLIC_URL=https://couchdb.example.com

docker compose up -d
```

Then open `http://localhost:5985` to access the VaultKeeper web UI.

CouchDB is available on port **5984** and VaultKeeper on port **5985**. Both
should be placed behind a reverse proxy with TLS for production use.

### Using the CLI

```bash
docker exec -it vk-server cli --help
docker exec -it vk-server cli provision alice notes
```

---

## Development

### Building

```bash
docker build -t vaultkeeper .
```

### Python dependencies

Defined in `pyproject.toml`. To install for local development:

```bash
pip install -e .             # installs cli and vaultkeeper-web scripts
pip install -e ".[dev]"      # also installs pytest and testcontainers
pip install -e ".[serve]"    # also installs gunicorn
```

Core dependencies: `click`, `requests`, `flask`

### Running with Gunicorn

```bash
pip install -e ".[serve]"
cli server init   # run once to configure CouchDB
gunicorn "vaultkeeper.web.app:create_app()"
```

### Testing

Tests run against a real CouchDB instance - no mocking. A
[testcontainers](https://testcontainers.com/) fixture starts a
`couchdb:3.5.1` Docker container automatically.

```bash
pytest                                          # starts a test container
COUCHDB_TEST_URL=http://localhost:5984 pytest   # use an existing instance
```

Tests in `test_setup_uri.py` require Deno and `generate_setupuri.ts` and are
automatically skipped when Deno is not on PATH (i.e. outside the container).

---

## Planned / known issues

### Observability

- **Structured logging** — no logging is in place beyond Flask's default
  request log. Add a proper logging setup with configurable levels
  (`DEBUG` → `CRITICAL`) via a `LOG_LEVEL` environment variable.
