import pytest

from vaultkeeper.client import CouchDB, CouchDBError


def test_create_user_exists(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    assert couchdb_client.user_exists(username)


def test_created_user_appears_in_list(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    assert username in couchdb_client.list_users()


def test_unknown_user_does_not_exist(couchdb_client: CouchDB):
    assert not couchdb_client.user_exists("no_such_user_xyzzy")


def test_create_duplicate_user_raises(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    with pytest.raises(CouchDBError, match="already exists"):
        couchdb_client.create_user(username, "any_password")


def test_delete_user(couchdb_client: CouchDB, unique_username: str):
    couchdb_client.create_user(unique_username, "password123")
    couchdb_client.delete_user(unique_username)
    assert not couchdb_client.user_exists(unique_username)


def test_deleted_user_absent_from_list(couchdb_client: CouchDB, unique_username: str):
    couchdb_client.create_user(unique_username, "password123")
    couchdb_client.delete_user(unique_username)
    assert unique_username not in couchdb_client.list_users()


def test_delete_nonexistent_user_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.delete_user("no_such_user_xyzzy")


def test_change_password(couchdb_client: CouchDB, managed_user):
    username, _ = managed_user
    couchdb_client.change_password(username, "brand_new_password_456")
    assert couchdb_client.user_exists(username)


def test_change_password_nonexistent_user_raises(couchdb_client: CouchDB):
    with pytest.raises(CouchDBError, match="does not exist"):
        couchdb_client.change_password("no_such_user_xyzzy", "pass")
