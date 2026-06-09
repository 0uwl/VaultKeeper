"""
vaultkeeper.client — CouchDB/LiveSync operations for VaultKeeper.

Reads connection settings from environment variables:
  COUCHDB_HOST               CouchDB base URL        (default: http://localhost:5984)
  COUCHDB_USER               Admin username
  COUCHDB_PASSWORD           Admin password
  COUCHDB_PUBLIC_URL         External URL embedded in setup URIs (falls back to COUCHDB_HOST)
  LIVESYNC_SETUP_URI_SCRIPT  Path to generate_setupuri.ts (default: /scripts/generate_setupuri.ts)
"""

import json
import os
import re
import secrets
import string
import subprocess

import requests
from requests.auth import HTTPBasicAuth

_DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_$()+\-/]*$")
_VAULT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SETUP_URI_SCRIPT_DEFAULT = "/scripts/generate_setupuri.ts"


class CouchDBError(Exception):
    """A CouchDB operation failed."""


class ValidationError(CouchDBError):
    """Input failed validation before a CouchDB call was made."""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def vault_name_to_db_name(username: str, vault_name: str) -> str:
    return f"vault_{username}_{vault_name}"


def validate_vault_name(vault_name: str) -> None:
    if not _VAULT_NAME_RE.match(vault_name):
        raise ValidationError(
            f"'{vault_name}' is not a valid vault name. "
            "Use only lowercase letters, digits, and underscores, "
            "starting with a letter."
        )


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
    No output is written to stdout/stderr — callers handle presentation.
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

    # -----------------------------------------------------------------------
    # Vaults
    # -----------------------------------------------------------------------

    def db_exists(self, db: str) -> bool:
        r = self._session.head(self._url(db))
        return r.status_code == 200

    def list_all_vaults(self) -> list[str]:
        r = self._session.get(self._url("_all_dbs"))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to list databases: {r.status_code} {r.text}")
        return [db for db in r.json() if db.startswith("vault_")]

    def list_vaults_for_user(self, username: str) -> list[str]:
        """Return vault db names that list username in their _security document."""
        vaults = []
        for db in self.list_all_vaults():
            r = self._session.get(self._url(db, "_security"))
            if r.status_code != 200:
                continue
            sec = r.json()
            names = (
                sec.get("admins", {}).get("names", [])
                + sec.get("members", {}).get("names", [])
            )
            if username in names:
                vaults.append(db)
        return vaults

    def create_vault(self, username: str, vault_name: str) -> str:
        """Create and secure a vault database. Returns the db name."""
        validate_vault_name(vault_name)
        db = vault_name_to_db_name(username, vault_name)

        if not self.user_exists(username):
            raise CouchDBError(f"User '{username}' does not exist. Create the user first.")
        if self.db_exists(db):
            raise CouchDBError(f"Vault '{db}' already exists.")

        r = self._session.put(self._url(db))
        if r.status_code != 201:
            raise CouchDBError(f"Failed to create database '{db}': {r.status_code} {r.text}")

        security = {
            "admins":  {"names": [username], "roles": []},
            "members": {"names": [username], "roles": []},
        }
        r = self._session.put(self._url(db, "_security"), data=json.dumps(security))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to set security on '{db}': {r.status_code} {r.text}")

        return db

    def delete_vault(self, db_name: str) -> None:
        if not self.db_exists(db_name):
            raise CouchDBError(f"Database '{db_name}' does not exist.")
        r = self._session.delete(self._url(db_name))
        if r.status_code != 200:
            raise CouchDBError(f"Failed to delete database '{db_name}': {r.status_code} {r.text}")

    def vault_info(self, db_name: str) -> dict:
        """Return a dict of size/doc stats for a vault database."""
        if not self.db_exists(db_name):
            raise CouchDBError(f"Database '{db_name}' does not exist.")
        r = self._session.get(self._url(db_name))
        d = r.json()
        sizes = d.get("sizes", {})
        data_size = sizes.get("active", 0)
        disk_size = sizes.get("file", 0)
        return {
            "name":          db_name,
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
        r = self._session.post(self._url(db_name, "_compact"))
        if r.status_code != 202:
            raise CouchDBError(f"Failed to compact '{db_name}': {r.status_code} {r.text}")

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

        return {
            "uri":                      uri,
            "passphrase":               passphrase,
            "uri_passphrase":           uri_passphrase,
            "passphrase_generated":     passphrase_generated,
            "uri_passphrase_generated": uri_passphrase_generated,
        }
