# CLI reference

A Python CLI tool built with [Click](https://click.palletsprojects.com/).
Installed inside the container at `/usr/local/bin/cli` and invoked via `docker exec`.

## Configuration

Connection settings are resolved in the following order for each command:

1. CLI flags (`--host`, `--admin`, `--password`)
2. Environment variables (`COUCHDB_HOST`, `COUCHDB_USER`, `COUCHDB_PASSWORD`)
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
```

## `server login` - saving credentials

`cli server login` prompts for host, username, password, and optional public URL,
verifies the credentials against CouchDB, then writes a plain-text credentials file:

```
COUCHDB_HOST=http://localhost:5984
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
