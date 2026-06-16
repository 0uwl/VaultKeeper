"""
vaultkeeper.client - CouchDB/LiveSync operations for VaultKeeper.

Reads connection settings from environment variables:
  COUCHDB_HOST               CouchDB base URL        (default: http://localhost:5984)
  COUCHDB_USER               Admin username
  COUCHDB_PASSWORD           Admin password
  COUCHDB_PUBLIC_URL         External URL embedded in setup URIs (falls back to COUCHDB_HOST)
  LIVESYNC_SETUP_URI_SCRIPT  Path to generate_setupuri.ts (default: /scripts/generate_setupuri.ts)
"""

from datetime import datetime, timezone, timedelta
import json
import os
import re
import secrets
import string
import subprocess

from uuid import uuid4

import requests
from requests.auth import HTTPBasicAuth

from vaultkeeper.logger import get_logger

_DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_$()+\-/]*$")
_SETUP_URI_SCRIPT_DEFAULT = "/scripts/generate_setupuri.ts"
CONFIG_DB = "vaultkeeper_data"

LOGGER = get_logger(__name__)

class CouchDBError(Exception):
    """A CouchDB operation failed."""


class ValidationError(CouchDBError):
    """Input failed validation before a CouchDB call was made."""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def validate_vault_name(vault_name: str) -> None:
    if not vault_name or not vault_name.strip():
        raise ValidationError("Vault name cannot be empty.")
    if len(vault_name) > 100:
        raise ValidationError("Vault name must be 100 characters or fewer.")


def validate_db_name(name: str) -> None:
    if not _DB_NAME_RE.match(name):
        raise ValidationError(
            f"'{name}' is not a valid CouchDB database name. "
            "Must start with a lowercase letter and contain only: a-z 0-9 _ $ ( ) + - /"
        )


def _random_passphrase(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class CouchDB:
    """
    Thin wrapper around the CouchDB HTTP API.

    All methods raise CouchDBError (or its subclass ValidationError) on failure.
    No output is written to stdout/stderr - callers handle presentation.
    """

    def __init__(
        self,
        host: str | None = None,
        username: str | None = None,
        password: str | None = None,
        public_url: str | None = None,
        setup_uri_script: str | None = None,
    ) -> None:
        self.host = (host or os.environ.get("COUCHDB_HOST", "http://localhost:5984")).rstrip("/")
        self.username = username or os.environ.get("COUCHDB_USER", "")
        self.password = password or os.environ.get("COUCHDB_PASSWORD", "")
        raw_public = public_url or os.environ.get("COUCHDB_PUBLIC_URL", "")
        self.public_url = raw_public.rstrip("/") if raw_public else self.host
        self.setup_uri_script = (
            setup_uri_script
            or os.environ.get("LIVESYNC_SETUP_URI_SCRIPT", _SETUP_URI_SCRIPT_DEFAULT)
        )
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(self.username, self.password)
        self._session.headers.update({"Content-Type": "application/json"})

    def _url(self, *parts: str) -> str:
        return "/".join([self.host] + [p.lstrip("/") for p in parts])

    # -----------------------------------------------------------------------
    # Server
    # -----------------------------------------------------------------------

    def ping(self) -> dict:
        """Return CouchDB server info dict. Raises CouchDBError if unreachable."""
        try:
            r = self._session.get(self._url("/"))
        except requests.exceptions.RequestException as e:
            raise CouchDBError(f"CouchDB unreachable: {e}") from e
        if r.status_code == 200:
            return r.json()
        raise CouchDBError(f"CouchDB unreachable: {r.status_code} {r.text}")

    def server_init(self) -> None:
        """Apply LiveSync-required CouchDB settings. Idempotent."""
        r = self._session.post(
            self._url("_cluster_setup"),
            data=json.dumps({
                "action": "enable_single_node",
                "username": self.username,
                "password": self.password,
                "bind_address": "0.0.0.0",
                "port": 5984,
                "singlenode": True,
            }),
        )
        if r.status_code not in (200, 201):
            raise CouchDBError(f"Cluster setup failed: {r.status_code} {r.text}")

        def _put(section: str, key: str, value: str) -> None:
            resp = self._session.put(
                self._url("_node/_local/_config", section, key),
                data=json.dumps(value),
            )
            if resp.status_code != 200:
                raise CouchDBError(f"Failed to set {section}/{key}: {resp.status_code} {resp.text}")

        _put("chttpd",      "require_valid_user",    "true")
        _put("chttpd_auth", "require_valid_user",    "true")
        _put("httpd",       "WWW-Authenticate",      'Basic realm="couchdb"')
        _put("httpd",       "enable_cors",           "true")
        _put("chttpd",      "enable_cors",           "true")
        _put("chttpd",      "max_http_request_size", "4294967296")
        _put("couchdb",     "max_document_size",     "50000000")
        _put("cors",        "credentials",           "true")
        _put("cors",        "origins",               "app://obsidian.md,capacitor://localhost,http://localhost")

        self.init_config_db()

    # -----------------------------------------------------------------------
    # Config DB
    # -----------------------------------------------------------------------

    def init_config_db(self) -> None:
        """Create the vaultkeeper_data database if it does not already exist."""
        r = self._session.put(self._url(CONFIG_DB))
        if r.status_code not in (201, 412):  # 412 = already exists
            raise CouchDBError(f"Failed to create config database: {r.status_code} {r.text}")

    def authenticate_user(self, username: str, password: str) -> bool:
        """Verify end-user credentials against CouchDB. Returns True if valid."""
        try:
            r = requests.post(
                self._url("_session"),
                data={"name": username, "password": password},
            )
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def create_invitation(self, expiry_hours: int = 72) -> str:
        """Create a one-time enrollment invitation. Returns the token string."""
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        doc = {
            "_id": f"invitation:{token}",
            "type": "invitation",
            "token": token,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=expiry_hours)).isoformat(),
            "used": False,
            "used_by": None,
            "used_at": None,
        }
        r = self._session.put(
            self._url(CONFIG_DB, f"invitation:{token}"),
            data=json.dumps(doc),
        )
        if r.status_code not in (201, 202):
            raise CouchDBError(f"Failed to create invitation: {r.status_code} {r.text}")
        return token

    def get_invitation(self, token: str) -> dict | None:
        """Return the invitation doc if valid (not used, not expired). Returns None otherwise."""
        r = self._session.get(self._url(CONFIG_DB, f"invitation:{token}"))
        if r.status_code != 200:
            return None
        doc = r.json()
        if doc.get("used"):
            return None
        if datetime.now(timezone.utc) > datetime.fromisoformat(doc["expires_at"]):
            return None
        return doc

    def consume_invitation(self, token: str, username: str) -> None:
        """Mark an invitation as used."""
        r = self._session.get(self._url(CONFIG_DB, f"invitation:{token}"))
        if r.status_code != 200:
            raise CouchDBError(f"Invitation not found.")
        doc = r.json()
        doc["used"] = True
        doc["used_by"] = username
        doc["used_at"] = datetime.now(timezone.utc).isoformat()
        r = self._session.put(
            self._url(CONFIG_DB, f"invitation:{token}"),
            data=json.dumps(doc),
        )
        if r.status_code not in (200, 201, 202):
            raise CouchDBError(f"Failed to consume invitation: {r.status_code} {r.text}")

    def list_invitations(self) -> list[dict]:
        """Return all invitation documents from the config database."""
        r = self._session.get(
            self._url(CONFIG_DB, "_all_docs"),
            params={
                "startkey": '"invitation:"',
                "endkey": '"invitation;"',
                "include_docs": "true",
            },
        )
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list invitations: {r.status_code} {r.text}")
        return [row["doc"] for row in r.json().get("rows", [])]

    def delete_invitation(self, token: str) -> None:
        """Delete an invitation document."""
        r = self._session.get(self._url(CONFIG_DB, f"invitation:{token}"))
        if r.status_code != 200:
            raise CouchDBError("Invitation not found.")
        rev = r.json()["_rev"]
        r = self._session.delete(
            self._url(CONFIG_DB, f"invitation:{token}"),
            params={"rev": rev},
        )
        if r.status_code != 200:
            raise CouchDBError(f"Failed to delete invitation: {r.status_code} {r.text}")

    def get_user_limits(self, username: str) -> dict:
        """Return per-user vault limits. Returns defaults if no limits doc exists."""
        r = self._session.get(self._url(CONFIG_DB, f"user_limits:{username}"))
        if r.status_code == 404:
            return {"max_vaults": None, "max_vault_size_bytes": None}
        if r.status_code != 200:
            raise CouchDBError(f"Failed to get limits for '{username}': {r.status_code} {r.text}")
        doc = r.json()
        return {
            "max_vaults": doc.get("max_vaults"),
            "max_vault_size_bytes": doc.get("max_vault_size_bytes"),
        }

    def set_user_limits(
        self,
        username: str,
        max_vaults: int | None,
        max_vault_size_bytes: int | None,
    ) -> None:
        """Upsert per-user vault limits in the data database."""
        doc_id = f"user_limits:{username}"
        r = self._session.get(self._url(CONFIG_DB, doc_id))
        if r.status_code == 200:
            doc = r.json()
        else:
            doc = {"_id": doc_id, "type": "user_limits", "username": username}
        doc["max_vaults"] = max_vaults
        doc["max_vault_size_bytes"] = max_vault_size_bytes
        r = self._session.put(self._url(CONFIG_DB, doc_id), data=json.dumps(doc))
        if r.status_code not in (200, 201, 202):
            raise CouchDBError(f"Failed to set limits for '{username}': {r.status_code} {r.text}")

    def get_server_settings(self) -> dict:
        """Return global default limits. Returns defaults if no settings doc exists."""
        r = self._session.get(self._url(CONFIG_DB, "server_settings"))
        if r.status_code == 404:
            return {"default_max_vaults": None, "default_max_vault_size_bytes": None}
        if r.status_code != 200:
            raise CouchDBError(f"Failed to get server settings: {r.status_code} {r.text}")
        doc = r.json()
        return {
            "default_max_vaults": doc.get("default_max_vaults"),
            "default_max_vault_size_bytes": doc.get("default_max_vault_size_bytes"),
        }

    def set_server_settings(
        self,
        default_max_vaults: int | None,
        default_max_vault_size_bytes: int | None,
    ) -> None:
        """Upsert the global default limits in the data database."""
        r = self._session.get(self._url(CONFIG_DB, "server_settings"))
        if r.status_code == 200:
            doc = r.json()
        else:
            doc = {"_id": "server_settings", "type": "server_settings"}
        doc["default_max_vaults"] = default_max_vaults
        doc["default_max_vault_size_bytes"] = default_max_vault_size_bytes
        r = self._session.put(self._url(CONFIG_DB, "server_settings"), data=json.dumps(doc))
        if r.status_code not in (200, 201, 202):
            raise CouchDBError(f"Failed to update server settings: {r.status_code} {r.text}")

    def log_audit_event(
        self,
        action: str,
        actor: str,
        target: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Write an audit event to vaultkeeper_data. Best-effort: never raises."""
        now_utc = datetime.now(timezone.utc)
        ts_id = now_utc.strftime("%Y%m%dT%H%M%S%f")  # UTC for consistent sort order
        doc_id = f"audit:{ts_id}:{secrets.token_hex(4)}"
        doc = {
            "_id": doc_id,
            "type": "audit",
            "timestamp": now_utc.astimezone().isoformat(),  # local tz via TZ env var
            "actor": actor,
            "action": action,
            "target": target,
            "details": details or {},
        }
        try:
            r = self._session.put(self._url(CONFIG_DB, doc_id), data=json.dumps(doc))
            if r.status_code not in (201, 202):
                LOGGER.warning(f"Failed to write audit event '{action}': {r.status_code} {r.text}")
        except Exception as e:
            LOGGER.warning(f"Failed to write audit event '{action}': {e}")

    def list_audit_log(self, limit: int = 200) -> list[dict]:
        """Return audit events newest-first from vaultkeeper_data."""
        r = self._session.get(
            self._url(CONFIG_DB, "_all_docs"),
            params={
                "startkey": '"audit;"',
                "endkey": '"audit:"',
                "descending": "true",
                "include_docs": "true",
                "limit": str(limit),
            },
        )
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list audit log: {r.status_code} {r.text}")
        return [row["doc"] for row in r.json().get("rows", [])]

    def purge_audit_events(self, id_rev_pairs: list[tuple[str, str]]) -> int:
        """Bulk-delete audit documents. Returns the count successfully deleted."""
        if not id_rev_pairs:
            return 0
        docs = [{"_id": doc_id, "_rev": rev, "_deleted": True} for doc_id, rev in id_rev_pairs]
        r = self._session.post(self._url(CONFIG_DB, "_bulk_docs"), data=json.dumps({"docs": docs}))
        if r.status_code not in (200, 201):
            raise CouchDBError(f"Failed to delete audit events: {r.status_code} {r.text}")
        return sum(1 for row in r.json() if not row.get("error"))

    def get_effective_limits(self, username: str) -> dict:
        """Return vault limits for a user, falling back to server defaults."""
        limits = self.get_user_limits(username)
        settings = self.get_server_settings()
        return {
            "max_vaults": limits["max_vaults"] if limits["max_vaults"] is not None
                          else settings["default_max_vaults"],
            "max_vault_size_bytes": limits["max_vault_size_bytes"] if limits["max_vault_size_bytes"] is not None
                                    else settings["default_max_vault_size_bytes"],
        }

    # -----------------------------------------------------------------------
    # Users
    # -----------------------------------------------------------------------

    def user_exists(self, username: str) -> bool:
        r = self._session.get(self._url(f"_users/org.couchdb.user:{username}"))
        return r.status_code == 200

    def list_users(self) -> list[str]:
        r = self._session.get(
            self._url("_users/_all_docs"),
            params={"startkey": '"org.couchdb.user:"', "endkey": '"org.couchdb.user;"'},
        )
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list users: {r.status_code} {r.text}")
        return [
            row["id"].replace("org.couchdb.user:", "")
            for row in r.json().get("rows", [])
        ]

    def create_user(self, username: str, password: str) -> None:
        if self.user_exists(username):
            raise CouchDBError(f"User '{username}' already exists.")
        payload = {"name": username, "password": password, "roles": [], "type": "user"}
        r = self._session.put(
            self._url(f"_users/org.couchdb.user:{username}"),
            data=json.dumps(payload),
        )
        if r.status_code not in (201, 202):
            raise CouchDBError(f"Failed to create user '{username}': {r.status_code} {r.text}")
        LOGGER.info(f"Created new user '{username}'")

    def delete_user(self, username: str) -> None:
        if not self.user_exists(username):
            raise CouchDBError(f"User '{username}' does not exist.")
        r = self._session.get(self._url(f"_users/org.couchdb.user:{username}"))
        rev = r.json().get("_rev")
        r = self._session.delete(
            self._url(f"_users/org.couchdb.user:{username}"),
            params={"rev": rev},
        )
        if r.status_code != 200:
            raise CouchDBError(f"Failed to delete user '{username}': {r.status_code} {r.text}")
        LOGGER.info(f"Deleted user '{username}'")

    def change_password(self, username: str, new_password: str) -> None:
        if not self.user_exists(username):
            raise CouchDBError(f"User '{username}' does not exist.")
        r = self._session.get(self._url(f"_users/org.couchdb.user:{username}"))
        doc = r.json()
        doc["password"] = new_password
        r = self._session.put(
            self._url(f"_users/org.couchdb.user:{username}"),
            data=json.dumps(doc),
        )
        if r.status_code not in (200, 201):
            raise CouchDBError(f"Failed to update password for '{username}': {r.status_code} {r.text}")
        LOGGER.info(f"Password for user '{username}' was changed")

    # -----------------------------------------------------------------------
    # Vaults
    # -----------------------------------------------------------------------

    def db_exists(self, db: str) -> bool:
        r = self._session.head(self._url(db))
        return r.status_code == 200

    def _write_vault_meta(self, db_name: str, username: str, vault_name: str) -> None:
        doc = {
            "_id": "_local/vaultkeeper",
            "vault_name": vault_name,
            "username": username,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        r = self._session.put(
            self._url(db_name, "_local", "vaultkeeper"),
            data=json.dumps(doc),
        )
        if r.status_code not in (200, 201):
            raise CouchDBError(f"Failed to write vault metadata: {r.status_code} {r.text}")

    def get_vault_meta(self, db_name: str) -> dict | None:
        r = self._session.get(self._url(db_name, "_local", "vaultkeeper"))
        if r.status_code != 200:
            return None
        return r.json()

    def find_vault_by_name(self, username: str, vault_name: str) -> str | None:
        """Return the db name for a vault owned by username with the given vault_name, or None."""
        prefix = f"vault_{username}_"
        r = self._session.get(self._url("_all_dbs"))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list databases: {r.status_code} {r.text}")
        for db in r.json():
            if not db.startswith(prefix):
                continue
            meta = self.get_vault_meta(db)
            if meta and meta.get("vault_name") == vault_name:
                return db
        return None

    def list_all_vaults(self) -> list[str]:
        r = self._session.get(self._url("_all_dbs"))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list databases: {r.status_code} {r.text}")
        return [db for db in r.json() if db.startswith("vault_")]

    def list_vaults_for_user(self, username: str) -> list[dict]:
        """Return vault metadata dicts for all vaults belonging to username."""
        prefix = f"vault_{username}_"
        r = self._session.get(self._url("_all_dbs"))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list databases: {r.status_code} {r.text}")
        result = []
        for db in r.json():
            if not db.startswith(prefix):
                continue
            meta = self.get_vault_meta(db)
            result.append({
                "db_name": db,
                "vault_name": meta.get("vault_name", db) if meta else db,
            })
        return result

    def create_vault(self, username: str, vault_name: str) -> str:
        """Create and secure a vault database. Returns the db name."""
        validate_vault_name(vault_name)
        if not self.user_exists(username):
            raise CouchDBError(f"User '{username}' does not exist. Create the user first.")
        if self.find_vault_by_name(username, vault_name):
            raise CouchDBError(f"Vault '{vault_name}' already exists for user '{username}'.")

        db = f"vault_{username}_{uuid4().hex}"
        r = self._session.put(self._url(db))
        if r.status_code != 201:
            raise CouchDBError(f"Failed to create database '{db}': {r.status_code} {r.text}")

        try:
            security = {
                "admins":  {"names": [username], "roles": []},
                "members": {"names": [username], "roles": []},
            }
            r = self._session.put(self._url(db, "_security"), data=json.dumps(security))
            if r.status_code != 200:
                raise CouchDBError(f"Failed to set security on '{db}': {r.status_code} {r.text}")
            self._write_vault_meta(db, username, vault_name)
        except CouchDBError:
            self._session.delete(self._url(db))
            raise

        LOGGER.info(f"Created vault '{vault_name}' for user '{username}'")
        return db

    def delete_vault(self, db_name: str) -> None:
        if not self.db_exists(db_name):
            raise CouchDBError(f"Database '{db_name}' does not exist.")
        meta = self.get_vault_meta(db_name)
        vault_name = meta.get("vault_name", db_name) if meta else db_name
        username = meta.get("username", "unknown") if meta else "unknown"
        r = self._session.delete(self._url(db_name))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to delete database '{db_name}': {r.status_code} {r.text}")
        LOGGER.info(f"Deleted vault '{vault_name}' ({db_name}) owned by '{username}'")


    def vault_info(self, db_name: str) -> dict:
        """Return a dict of size/doc stats for a vault database."""
        if not self.db_exists(db_name):
            raise CouchDBError(f"Database '{db_name}' does not exist.")
        r = self._session.get(self._url(db_name))
        d = r.json()
        sizes = d.get("sizes", {})
        data_size = sizes.get("active", 0)
        disk_size = sizes.get("file", 0)
        meta = self.get_vault_meta(db_name)
        return {
            "name":          db_name,
            "vault_name":    meta.get("vault_name", db_name) if meta else db_name,
            "doc_count":     d.get("doc_count", 0),
            "doc_del_count": d.get("doc_del_count", 0),
            "data_size":     data_size,
            "disk_size":     disk_size,
            "external_size": sizes.get("external", 0),
            "compact_needed": disk_size > data_size * 2 and disk_size > 0,
        }

    def compact_vault(self, db_name: str) -> None:
        if not self.db_exists(db_name):
            raise CouchDBError(f"Database '{db_name}' does not exist.")
        meta = self.get_vault_meta(db_name)
        vault_name = meta.get("vault_name", db_name) if meta else db_name
        r = self._session.post(self._url(db_name, "_compact"))
        if r.status_code != 202:
            raise CouchDBError(f"Failed to compact '{db_name}': {r.status_code} {r.text}")
        LOGGER.info(f"Vault '{vault_name}' ({db_name}) was compacted")

    # -----------------------------------------------------------------------
    # Setup URI
    # -----------------------------------------------------------------------

    def generate_setup_uri(
        self,
        username: str,
        user_password: str,
        db_name: str,
        passphrase: str | None = None,
        uri_passphrase: str | None = None,
    ) -> dict:
        """
        Generate a LiveSync setup URI via the upstream Deno script.

        Returns:
          uri                      obsidian:// deep link
          passphrase               E2E passphrase used (supplied or generated)
          uri_passphrase           URI passphrase (supplied, generated, or None)
          passphrase_generated     True if passphrase was auto-generated
          uri_passphrase_generated True if uri_passphrase was auto-generated
        """
        passphrase_generated = passphrase is None
        if passphrase_generated:
            passphrase = _random_passphrase()

        if not os.path.exists(self.setup_uri_script):
            raise CouchDBError(
                f"Setup URI script not found at {self.setup_uri_script}. "
                "Ensure you are running inside the VaultKeeper container."
            )

        env = {
            **os.environ,
            "hostname":   self.public_url,
            "database":   db_name,
            "username":   username,
            "password":   user_password,
            "passphrase": passphrase,
        }
        if uri_passphrase:
            env["uri_passphrase"] = uri_passphrase

        try:
            result = subprocess.run(
                ["deno", "run", "-A", self.setup_uri_script],
                env=env,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise CouchDBError("Deno is not installed or not on PATH.")

        if result.returncode != 0:
            raise CouchDBError(f"Setup URI generation failed:\n{result.stderr}")

        lines = result.stdout.splitlines()
        uri = next(
            (line.strip() for line in lines if line.strip().startswith("obsidian://")),
            None,
        )
        if not uri:
            raise CouchDBError(f"Could not find setup URI in script output:\n{result.stdout}")

        uri_passphrase_generated = uri_passphrase is None
        if uri_passphrase_generated:
            for line in lines:
                if "passphrase of Setup-URI is:" in line:
                    uri_passphrase = line.split(":", 1)[-1].strip()
                    break

        LOGGER.info(f"User '{username}' generated a Setup URI for '{db_name}'")

        return {
            "uri":                      uri,
            "passphrase":               passphrase,
            "uri_passphrase":           uri_passphrase,
            "passphrase_generated":     passphrase_generated,
            "uri_passphrase_generated": uri_passphrase_generated,
        }
