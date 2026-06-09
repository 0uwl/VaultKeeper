"""
Tests for generate_setup_uri.

Tests marked requires_deno are automatically skipped when deno is not on PATH
(i.e. outside the VaultKeeper container).  test_missing_script_raises is not
marked and runs everywhere because it exercises the pre-Deno guard.
"""

import pytest

from vaultkeeper.client import CouchDB, CouchDBError


@pytest.mark.requires_deno
def test_generate_setup_uri_returns_obsidian_uri(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    result = couchdb_client.generate_setup_uri(username, password, db_name)
    assert result["uri"].startswith("obsidian://")


@pytest.mark.requires_deno
def test_generate_setup_uri_auto_generates_passphrase(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    result = couchdb_client.generate_setup_uri(username, password, db_name)
    assert result["passphrase_generated"] is True
    assert isinstance(result["passphrase"], str)
    assert len(result["passphrase"]) == 32


@pytest.mark.requires_deno
def test_generate_setup_uri_auto_generates_uri_passphrase(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    result = couchdb_client.generate_setup_uri(username, password, db_name)
    assert result["uri_passphrase_generated"] is True
    assert result["uri_passphrase"] is not None


@pytest.mark.requires_deno
def test_generate_setup_uri_custom_passphrase_preserved(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    result = couchdb_client.generate_setup_uri(
        username, password, db_name, passphrase="my_custom_passphrase"
    )
    assert result["passphrase"] == "my_custom_passphrase"
    assert result["passphrase_generated"] is False


@pytest.mark.requires_deno
def test_generate_setup_uri_custom_uri_passphrase_preserved(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    result = couchdb_client.generate_setup_uri(
        username, password, db_name, uri_passphrase="my_uri_pass"
    )
    assert result["uri_passphrase"] == "my_uri_pass"
    assert result["uri_passphrase_generated"] is False


@pytest.mark.requires_deno
def test_generate_setup_uri_different_each_call(couchdb_client: CouchDB, managed_vault):
    username, password, db_name = managed_vault
    r1 = couchdb_client.generate_setup_uri(username, password, db_name)
    r2 = couchdb_client.generate_setup_uri(username, password, db_name)
    assert r1["passphrase"] != r2["passphrase"]


def test_generate_setup_uri_missing_script_raises(couchdb_client: CouchDB, managed_vault, tmp_path):
    """Missing script is caught before Deno is invoked — runs everywhere."""
    username, password, db_name = managed_vault
    client = CouchDB(
        host=couchdb_client.host,
        username=couchdb_client.username,
        password=couchdb_client.password,
        setup_uri_script=str(tmp_path / "nonexistent.ts"),
    )
    with pytest.raises(CouchDBError, match="not found"):
        client.generate_setup_uri(username, password, db_name)
