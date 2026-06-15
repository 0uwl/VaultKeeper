"""
couchdb-cli - VaultKeeper CLI.

Credential resolution order (highest to lowest priority):
  1. CLI flags (--host, --admin, --password)
  2. Environment variables (COUCHDB_HOST, COUCHDB_USER, COUCHDB_PASSWORD)
  3. Credentials file (~/.vaultkeeper/credentials, or $VAULTKEEPER_CREDENTIALS)
  4. Interactive prompt
"""

import functools
import os
import sys

import click

from vaultkeeper.client import CouchDB, CouchDBError, ValidationError

_CREDS_FILE = os.path.expanduser("~/.vaultkeeper/credentials")


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _load_credentials() -> dict:
    path = os.environ.get("VAULTKEEPER_CREDENTIALS", _CREDS_FILE)
    if not os.path.isfile(path):
        return {}
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def _get_client(host: str | None, admin: str | None, password: str | None) -> CouchDB:
    """
    Build a CouchDB client. Falls back to the credentials file, then prompts,
    if CLI flags and env vars don't supply a value.
    """
    creds = _load_credentials()
    host = host or creds.get("COUCHDB_HOST")
    admin = admin or creds.get("COUCHDB_USER")
    password = password or creds.get("COUCHDB_PASSWORD")
    public_url = os.environ.get("COUCHDB_PUBLIC_URL") or creds.get("COUCHDB_PUBLIC_URL")

    if not admin:
        admin = click.prompt("Admin username")
    if not password:
        password = click.prompt("Admin password", hide_input=True)

    return CouchDB(host=host, username=admin, password=password, public_url=public_url or None)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    click.echo(click.style(f"  ✓ {msg}", fg="green"))

def _info(msg: str) -> None:
    click.echo(click.style(f"  → {msg}", fg="cyan"))

def _warn(msg: str) -> None:
    click.echo(click.style(f"  ⚠ {msg}", fg="yellow"))

def _abort(msg: str) -> None:
    click.echo(click.style(f"  ✗ {msg}", fg="red"), err=True)
    sys.exit(1)


def _print_uri_result(result: dict) -> None:
    click.echo("")
    click.echo(click.style("  ⚠  Store these in your password manager:", bold=True, fg="yellow"))
    if result["passphrase_generated"]:
        click.echo(f"  E2E passphrase (auto-generated): {result['passphrase']}")
    if result["uri_passphrase"] and result["uri_passphrase_generated"]:
        click.echo(f"  URI passphrase (auto-generated): {result['uri_passphrase']}")
    click.echo("")
    click.echo(click.style("  Setup URI:", bold=True))
    click.echo(f"  {result['uri']}")
    click.echo("")
    click.echo("  In Obsidian: command palette → 'Self-hosted LiveSync: Use the copied setup URI'")
    if result["uri_passphrase"]:
        click.echo("  When prompted, enter the URI passphrase above.")


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


# ---------------------------------------------------------------------------
# Common options decorator
# ---------------------------------------------------------------------------

def common_options(f):
    @click.option("--host", envvar="COUCHDB_HOST", default=None, help="CouchDB base URL.")
    @click.option("--admin", envvar="COUCHDB_USER", default=None, help="Admin username.")
    @click.option("--password", envvar="COUCHDB_PASSWORD", default=None, help="Admin password.")
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("0.1.0", prog_name="couchdb-cli")
def cli():
    """VaultKeeper - CouchDB management for Obsidian LiveSync."""


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------

@cli.group()
def server():
    """Manage CouchDB server configuration."""


@server.command("init")
@common_options
def server_init(host, admin, password):
    """Apply LiveSync CouchDB configuration (idempotent)."""
    client = _get_client(host, admin, password)
    try:
        _info("Configuring CouchDB for LiveSync...")
        client.server_init()
        _ok("CouchDB is ready for LiveSync.")
    except CouchDBError as e:
        _abort(str(e))


@server.command("login")
@click.option("--host", default=None, help="CouchDB base URL.")
@click.option("--public-url", "public_url", envvar="COUCHDB_PUBLIC_URL",
              default=None, help="External URL for LiveSync clients.")
def server_login(host, public_url):
    """Save CouchDB credentials to a file for use by future CLI invocations.

    Credentials are stored in plain text at ~/.vaultkeeper/credentials
    (override path with $VAULTKEEPER_CREDENTIALS).
    """
    host = host or click.prompt("CouchDB host", default="http://localhost:5984")
    admin = click.prompt("Admin username")
    password = click.prompt("Admin password", hide_input=True)
    if not public_url:
        public_url = click.prompt(
            "Public URL for LiveSync clients",
            default=host,
        )

    _info("Verifying credentials...")
    try:
        CouchDB(host=host, username=admin, password=password).ping()
    except CouchDBError as e:
        _abort(f"Could not connect to CouchDB: {e}")

    creds_path = os.environ.get("VAULTKEEPER_CREDENTIALS", _CREDS_FILE)
    creds_dir = os.path.dirname(os.path.abspath(creds_path))
    os.makedirs(creds_dir, exist_ok=True)

    with open(creds_path, "w") as f:
        f.write(f"COUCHDB_HOST={host}\n")
        f.write(f"COUCHDB_USER={admin}\n")
        f.write(f"COUCHDB_PASSWORD={password}\n")
        if public_url and public_url != host:
            f.write(f"COUCHDB_PUBLIC_URL={public_url}\n")

    _ok(f"Credentials saved to {creds_path}")
    _warn("Credentials are stored in plain text. Protect the file accordingly.")


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------

@cli.group()
def user():
    """Manage CouchDB users."""


@user.command("create")
@common_options
@click.argument("username")
@click.option(
    "--user-password", "user_password",
    prompt=True, hide_input=True, confirmation_prompt=True,
    help="Password for the new user.",
)
def user_create(host, admin, password, username, user_password):
    """Create a CouchDB user."""
    client = _get_client(host, admin, password)
    try:
        _info(f"Creating user '{username}'...")
        client.create_user(username, user_password)
        _ok(f"User '{username}' created.")
    except CouchDBError as e:
        _abort(str(e))


@user.command("delete")
@common_options
@click.argument("username")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def user_delete(host, admin, password, username, yes):
    """Delete a CouchDB user."""
    if not yes:
        click.confirm(f"Delete user '{username}'? This cannot be undone.", abort=True)
    client = _get_client(host, admin, password)
    try:
        client.delete_user(username)
        _ok(f"User '{username}' deleted.")
    except CouchDBError as e:
        _abort(str(e))


@user.command("list")
@common_options
def user_list(host, admin, password):
    """List all CouchDB users."""
    client = _get_client(host, admin, password)
    try:
        users = client.list_users()
    except CouchDBError as e:
        _abort(str(e))
    if not users:
        click.echo("  No users found.")
        return
    for u in users:
        click.echo(f"  • {u}")


@user.command("passwd")
@common_options
@click.argument("username")
@click.option(
    "--new-password", "new_password",
    prompt=True, hide_input=True, confirmation_prompt=True,
    help="New password.",
)
def user_passwd(host, admin, password, username, new_password):
    """Change a user's password."""
    client = _get_client(host, admin, password)
    try:
        client.change_password(username, new_password)
        _ok(f"Password updated for '{username}'.")
    except CouchDBError as e:
        _abort(str(e))


# ---------------------------------------------------------------------------
# vault
# ---------------------------------------------------------------------------

@cli.group()
def vault():
    """Manage LiveSync vault databases."""


@vault.command("create")
@common_options
@click.argument("username")
@click.argument("vault_name")
def vault_create(host, admin, password, username, vault_name):
    """Create and secure a vault database for a user."""
    client = _get_client(host, admin, password)
    try:
        _info(f"Creating vault '{vault_name}' for '{username}'...")
        db_name = client.create_vault(username, vault_name)
        _ok(f"Vault '{db_name}' created.")
    except (CouchDBError, ValidationError) as e:
        _abort(str(e))


@vault.command("delete")
@common_options
@click.argument("db_name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def vault_delete(host, admin, password, db_name, yes):
    """Delete a vault database."""
    if not yes:
        click.confirm(f"Delete '{db_name}'? ALL DATA WILL BE LOST.", abort=True)
    client = _get_client(host, admin, password)
    try:
        client.delete_vault(db_name)
        _ok(f"Vault '{db_name}' deleted.")
    except CouchDBError as e:
        _abort(str(e))


@vault.command("list")
@common_options
@click.argument("username")
def vault_list(host, admin, password, username):
    """List all vault databases belonging to a user."""
    client = _get_client(host, admin, password)
    try:
        vaults = client.list_vaults_for_user(username)
    except CouchDBError as e:
        _abort(str(e))
    if not vaults:
        click.echo(f"  No vaults found for '{username}'.")
        return
    for v in vaults:
        click.echo(f"  • {v['vault_name']}  ({v['db_name']})")


@vault.command("info")
@common_options
@click.argument("db_name")
def vault_info(host, admin, password, db_name):
    """Show size and document statistics for a vault."""
    client = _get_client(host, admin, password)
    try:
        d = client.vault_info(db_name)
    except CouchDBError as e:
        _abort(str(e))

    click.echo(click.style(f"  {db_name}", bold=True))
    click.echo(f"    Documents:  {d['doc_count']:,}")
    click.echo(f"    Deleted:    {d['doc_del_count']:,}")
    click.echo(f"    Data size:  {_fmt_bytes(d['data_size'])}")
    click.echo(f"    Disk size:  {_fmt_bytes(d['disk_size'])}")
    if d["compact_needed"]:
        _warn("Compaction recommended.")


@vault.command("compact")
@common_options
@click.argument("db_name")
def vault_compact(host, admin, password, db_name):
    """Compact a vault database to reclaim disk space."""
    client = _get_client(host, admin, password)
    try:
        client.compact_vault(db_name)
        _ok(f"Compaction started for '{db_name}'. Runs in the background.")
    except CouchDBError as e:
        _abort(str(e))


@vault.command("setup-uri")
@common_options
@click.argument("username")
@click.argument("vault_name")
@click.option(
    "--user-password", "user_password",
    prompt=True, hide_input=True,
    help="Password for the vault user (not the admin password).",
)
@click.option("--passphrase", default=None,
              help="E2E encryption passphrase (auto-generated if omitted).")
@click.option("--uri-passphrase", "uri_passphrase", default=None,
              help="Passphrase to encrypt the setup URI (auto-generated if omitted).")
def vault_setup_uri(host, admin, password, username, vault_name,
                    user_password, passphrase, uri_passphrase):
    """Generate a LiveSync setup URI for easy plugin configuration."""
    client = _get_client(host, admin, password)
    try:
        db_name = client.find_vault_by_name(username, vault_name)
        if db_name is None:
            _abort(f"Vault '{vault_name}' not found for user '{username}'.")
            return
        result = client.generate_setup_uri(
            username, user_password, db_name, passphrase, uri_passphrase
        )
        _print_uri_result(result)
    except CouchDBError as e:
        _abort(str(e))


# ---------------------------------------------------------------------------
# provision
# ---------------------------------------------------------------------------

@cli.command()
@common_options
@click.argument("username")
@click.argument("vault_name")
@click.option(
    "--user-password", "user_password",
    prompt=True, hide_input=True, confirmation_prompt=True,
    help="Password for the new user.",
)
@click.option("--passphrase", default=None,
              help="E2E encryption passphrase (auto-generated if omitted).")
@click.option("--uri-passphrase", "uri_passphrase", default=None,
              help="Passphrase to encrypt the setup URI (auto-generated if omitted).")
def provision(host, admin, password, username, vault_name,
              user_password, passphrase, uri_passphrase):
    """Create a user, their first vault, and a setup URI in one step."""
    client = _get_client(host, admin, password)
    try:
        _info(f"Creating user '{username}'...")
        client.create_user(username, user_password)
        _ok(f"User '{username}' created.")

        _info(f"Creating vault '{vault_name}'...")
        db_name = client.create_vault(username, vault_name)
        _ok(f"Vault '{db_name}' created.")

        result = client.generate_setup_uri(
            username, user_password, db_name, passphrase, uri_passphrase
        )
        _print_uri_result(result)
    except (CouchDBError, ValidationError) as e:
        _abort(str(e))
