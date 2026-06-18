# CLI reference

A Python CLI tool built with [Click](https://click.palletsprojects.com/).
Installed inside the container at `/usr/local/bin/cli` and invoked via `docker exec`.

## Configuration

Connection settings are resolved in the following order for each command:

1. CLI flags (`--host`, `--port`, `--protocol`, `--admin`, `--password`)
2. Environment variables (`COUCHDB_HOST`, `COUCHDB_PORT`, `COUCHDB_PROTOCOL`, `COUCHDB_USER`, `COUCHDB_PASSWORD`)
3. Credentials file (`~/.vaultkeeper/credentials`)
4. Interactive prompt

See the [environment variables](../README.md#environment-variables) section in the README for the full variable reference.

## Commands

```
cli server init                               # Apply LiveSync CouchDB config (idempotent)
cli server login                              # Save login credentials to a file (in plain text)

cli user create <username>                    # Create a CouchDB user
cli user delete <username> [--delete-vaults]  # Delete a CouchDB user (optionally with all their vaults)
cli user list                                 # List all users
cli user passwd <username>                    # Change a user's password

cli vault create <username> <vault_name>      # Create a vault database
cli vault delete <db_name>                    # Delete a vault database
cli vault list <username>                     # List vaults for a user
cli vault info <db_name>                      # Show size and doc stats
cli vault compact <db_name>                   # Compact a vault database
cli vault setup-uri <username> <vault_name>   # Generate a LiveSync setup URI

cli provision <username> <vault_name>         # Create user + vault + setup URI in one step

cli backup create [--vault DB_NAME ...]       # Create a backup archive (.tar.gz) of selected databases
cli backup list                               # List backup archives
cli backup restore <filename>                 # Restore databases from a backup archive
cli backup delete <filename>                  # Delete a backup archive
```

## `server login` - saving credentials

`cli server login` prompts for host, port, protocol, username, password, and optional
public URL, verifies the credentials against CouchDB, then writes a plain-text
credentials file:

```
COUCHDB_HOST=localhost
COUCHDB_PORT=5984
COUCHDB_PROTOCOL=http
COUCHDB_USER=admin
COUCHDB_PASSWORD=secret
COUCHDB_PUBLIC_URL=https://couchdb.example.com
```

Default location: `~/.vaultkeeper/credentials`. Override with `$VAULTKEEPER_CREDENTIALS`.
Credentials are stored in plain text - this is an intentional operator convenience.

## Vault naming scheme

All vault databases follow a strict naming convention to conform to CouchDB's requirements:

```
vault_<username>_<vault_name>
```

Examples: `vault_alice_notes`, `vault_alice_work`, `vault_bob_personal`

The `vault_name` argument in the CLI is the human-readable short name. The full CouchDB
database name is derived automatically. Commands that operate on existing databases
(`vault delete`, `vault compact`, `vault info`) must be supplied with the full database name.

To make it clear:

- "Vault name" - the human-readable name; used when a username is also supplied in the command
- "Database name" - the full name used by CouchDB: `vault_<username>_<vault_name>`

## Setup URI generation

The `vault setup-uri` and `provision` commands invoke `/scripts/generate_setupuri.ts` via
Deno to produce an `obsidian://` deep link that configures the LiveSync plugin in one tap.

Two passphrases are involved:

- **E2E passphrase** - encrypts vault data at rest in CouchDB; baked into the setup URI
  payload; needed if onboarding a device manually without a URI
- **URI passphrase** - encrypts the setup URI itself; Obsidian LiveSync prompts for this
  when the URI is pasted

Both are auto-generated (using `secrets.choice`, 32 characters) if not supplied. The CLI
prints them together with a clear warning to store them in a password manager.

## Security model

Vault databases use CouchDB's `_security` document to restrict access:

```json
{
  "admins":  { "names": ["<username>"], "roles": [] },
  "members": { "names": ["<username>"], "roles": [] }
}
```

Only the vault owner and server admins can read or write the database. The CLI always
connects as the server admin.

## Backup and restore

`cli backup create` writes a `.tar.gz` archive: one NDJSON file per database (first
line is a header with the database's `_security` document, remaining lines are its
documents), plus a `manifest.json` describing the archive. By default the archive is
saved to `$VAULTKEEPER_BACKUP_DIR` (default `/backups`), overridable with `--output-dir`.

Choose what to back up with `--vault <db_name>` (repeatable), `--all-vaults`, `--users`
(the `_users` database), and/or `--config` (the `vaultkeeper_data` database). At least
one of these is required.

```bash
docker exec vk-server cli backup create --all-vaults --users
```

### Streaming a backup to stdout

`docker exec` doesn't give direct filesystem access to the host, so to get a backup
archive out of the container without a bind mount, pass `--stdout` to write the archive
to stdout instead of a file and pipe it to a local file:

```bash
docker exec vk-server cli backup create --stdout --all-vaults > ./backup.tar.gz
```

`--stdout` is mutually exclusive with `--output-dir` - the archive is streamed and never
written to disk inside the container. All status/progress messages are written to stderr
in this mode so they don't end up mixed into the binary archive on stdout.

### Listing, restoring, and deleting archives

```
cli backup list                              # List archives in --output-dir
cli backup restore <filename> [--databases]  # Restore all or selected databases from an archive
cli backup delete <filename>                 # Delete an archive
```

Restoring drops and recreates vault databases for a clean restore. The `_users` and
`vaultkeeper_data` databases are merged instead: documents present in the backup
overwrite existing documents with the same ID, but documents created after the backup
was taken are left in place.
