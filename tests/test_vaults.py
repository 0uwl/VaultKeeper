import pytest

from vaultkeeper.client import CouchDB, CouchDBError, ValidationError, vault_name_to_db_name


# ---------------------------------------------------------------------------
# Pure-function tests (no fixtures needed)
# ---------------------------------------------------------------------------

def test_vault_name_to_db_name():
    assert vault_name_to_db_name("alice", "notes") == "vault_alice_notes"


def test_vault_name_to_db_name_with_numbers():
    assert vault_name_to_db_name("user1", "vault2") == "vault_user1_vault2"


# ---------------------------------------------------------------------------
# Vault creation
# ---------------------------------------------------------------------------

def test_create_vault_db_exists(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    assert couchdb_client.db_exists(db_name)


def test_create_vault_follows_naming_convention(couchdb_client: CouchDB, managed_vault):
    username, _, db_name = managed_vault
    assert db_name == f"vault_{username}_testvault"


def test_create_vault_without_user_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.create_vault("no_such_user_xyzzy", "notes")


def test_create_duplicate_vault_raises(couchdb_client: CouchDB, managed_vault):
    username, _, _ = managed_vault
    with pytest.raises(CouchDBError, match="already exists"):
        couchdb_client.create_vault(username, "testvault")


@pytest.mark.parametrize("bad_name", [
    "Has Spaces",
    "UPPERCASE",
    "has-hyphens",
    "has.dots",
    "1startswithnumber",
    "",
])
def test_invalid_vault_name_raises(couchdb_client: CouchDB, managed_user, bad_name: str):
    username, _ = managed_user
    with pytest.raises(ValidationError):
        couchdb_client.create_vault(username, bad_name)


# ---------------------------------------------------------------------------
# Vault listing
# ---------------------------------------------------------------------------

def test_vault_appears_in_user_list(couchdb_client: CouchDB, managed_vault):
    username, _, db_name = managed_vault
    assert db_name in couchdb_client.list_vaults_for_user(username)


def test_vault_appears_in_all_vaults(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    assert db_name in couchdb_client.list_all_vaults()


def test_all_vaults_are_prefixed(couchdb_client: CouchDB, managed_vault):
    for db in couchdb_client.list_all_vaults():
        assert db.startswith("vault_")


def test_vault_not_in_other_users_list(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    assert db_name not in couchdb_client.list_vaults_for_user("no_such_user_xyzzy")


# ---------------------------------------------------------------------------
# Vault info
# ---------------------------------------------------------------------------

def test_vault_info_structure(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    info = couchdb_client.vault_info(db_name)
    assert info["name"] == db_name
    assert isinstance(info["doc_count"], int)
    assert isinstance(info["doc_del_count"], int)
    assert isinstance(info["data_size"], int)
    assert isinstance(info["disk_size"], int)
    assert isinstance(info["compact_needed"], bool)


def test_vault_info_fresh_vault_zero_docs(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    info = couchdb_client.vault_info(db_name)
    assert info["doc_count"] == 0


def test_vault_info_nonexistent_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.vault_info("vault_nobody_nowhere")


# ---------------------------------------------------------------------------
# Compact
# ---------------------------------------------------------------------------

def test_compact_vault(couchdb_client: CouchDB, managed_vault):
    _, _, db_name = managed_vault
    couchdb_client.compact_vault(db_name)  # should not raise; CouchDB returns 202


def test_compact_nonexistent_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.compact_vault("vault_nobody_nowhere")


# ---------------------------------------------------------------------------
# Vault deletion
# ---------------------------------------------------------------------------

def test_delete_vault(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    db_name = couchdb_client.create_vault(username, "todelete")
    couchdb_client.delete_vault(db_name)
    assert not couchdb_client.db_exists(db_name)


def test_deleted_vault_absent_from_all_vaults(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    db_name = couchdb_client.create_vault(username, "todelete2")
    couchdb_client.delete_vault(db_name)
    assert db_name not in couchdb_client.list_all_vaults()


def test_delete_nonexistent_vault_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.delete_vault("vault_nobody_nowhere")
