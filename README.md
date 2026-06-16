# VaultKeeper

VaultKeeper makes it easy to create and manage [Obsidian Self-hosted LiveSync](https://github.com/vrtmrz/obsidian-livesync)
vaults in CouchDB. It runs as a sidecar container alongside your existing CouchDB instance.

Instead of manually configuring databases, security documents, and Setup URIs, VaultKeeper
gives you a browser UI and a CLI that handle everything - getting a new user from zero to a
syncing Obsidian vault in minutes, without touching config files or curl commands.

## Design principles

- **Vault-management-first.** The vault naming scheme, Setup URI flow, and security model are
  all designed around LiveSync's expectations, not generic CouchDB usage.
- **Sidecar model.** VaultKeeper is its own container. Bring your own CouchDB instance;
  VaultKeeper connects to it over the network and manages it.
- **Operator-friendly.** Managed through a browser UI or a CLI. Fauxton (CouchDB's built-in
  UI) is intentionally not the primary management interface.
- **Additive, not destructive.** VaultKeeper creates and manages resources in CouchDB but
  does not modify CouchDB's core server configuration.

---

## Quick start

A `compose.yml` is included that runs both services together using the official
`couchdb:3.3` image. VaultKeeper automatically applies the required LiveSync CouchDB
configuration on startup - no manual CouchDB setup is needed.

An `.env.example` is also available to quickly setup the required environment variables. 
Copy it, place it next to your `compose.yml` and rename it to `.env` then edit the 
`COUCHDB_PASSWORD` and `SECRET_KEY` variable.

> NOTE: `.env.example` contains an insecure admin password. You _must_ set your own strong password
before exposing the application to the public internet

After this you can run the stack using Docker Compose:
```bash
docker compose up -d
```

Then open `http://localhost:5985` to access the VaultKeeper web UI.

CouchDB is available on port **5984** and VaultKeeper on port **5985**. Both should be
placed behind a reverse proxy with TLS for production use, see [Web application](docs/web.md)

---

### Using the CLI

```bash
docker exec -it vk-server cli --help
docker exec -it vk-server cli provision alice notes
```

---

## Environment variables

| Variable             | Description                                          | Default                      |
|----------------------|------------------------------------------------------|------------------------------|
| `COUCHDB_HOST`       | CouchDB base URL                                     | `http://localhost:5984`      |
| `COUCHDB_USER`       | Admin username                                       | prompted                     |
| `COUCHDB_PASSWORD`   | Admin password                                       | prompted                     |
| `COUCHDB_PUBLIC_URL` | External URL embedded in setup URIs                  | falls back to `COUCHDB_HOST` |
| `LOG_DIR`            | Directory inside the container where logs are stored | `/var/log/`                  |

---

## Features

- **Vault management** - create, delete, and inspect CouchDB vault databases from a browser UI
- **User management** - create users, change passwords, set per-user vault limits
- **Enrollment invitations** - generate time-limited invite links for self-service account creation
- **Setup URI generation** - produce Obsidian LiveSync setup URIs with one click
- **Audit log** - every significant action (logins, vault creation, user changes) is recorded
  and viewable by the admin at `/audit` and on the dashboard

---

## Documentation

- [CLI reference](docs/cli.md) - commands, configuration, vault naming, Setup URIs
- [Web application](docs/web.md) - routes, technology stack, audit log, reverse proxy setup
- [Development](docs/development.md) - building, dependencies, testing
- [Roadmap](docs/roadmap.md) - planned features and known issues
