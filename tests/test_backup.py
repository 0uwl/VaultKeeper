import json
import os
import tarfile

import pytest

from vaultkeeper.client import CONFIG_DB, CouchDB, CouchDBError


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def backup_dir(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return str(d)


def _put_doc(client: CouchDB, db_name: str, doc: dict) -> None:
    r = client._session.put(
        client._url(db_name, doc["_id"]),
        data=json.dumps(doc),
    )
    assert r.status_code in (201, 202)


def _doc_exists(client: CouchDB, db_name: str, doc_id: str) -> bool:
    return client._session.head(client._url(db_name, doc_id)).status_code == 200


def _archive_names(path: str) -> list:
    with tarfile.open(path, "r:gz") as tar:
        return tar.getnames()


def _read_ndjson_lines(path: str, member: str) -> list:
    with tarfile.open(path, "r:gz") as tar:
        content = tar.extractfile(member).read().decode()
    return [line for line in content.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# backup() — archive creation
# ---------------------------------------------------------------------------

def test_backup_creates_file(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert os.path.isfile(dest)


def test_backup_creates_output_dir_if_missing(couchdb_client: CouchDB, managed_vault, tmp_path):
    _, _, db_name = managed_vault
    dest = str(tmp_path / "new_dir" / "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert os.path.isfile(dest)


def test_backup_archive_contains_manifest(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert "manifest.json" in _archive_names(dest)


def test_backup_archive_contains_ndjson_for_each_db(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert f"{db_name}.ndjson" in _archive_names(dest)


def test_backup_returns_manifest_dict(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name])
    assert manifest["version"] == 1
    assert "created_at" in manifest
    assert db_name in manifest["databases"]


def test_backup_manifest_doc_count_empty_vault(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name])
    assert manifest["databases"][db_name]["doc_count"] == 0


def test_backup_manifest_doc_count_with_docs(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    _put_doc(couchdb_client, db_name, {"_id": "doc1", "value": "a"})
    _put_doc(couchdb_client, db_name, {"_id": "doc2", "value": "b"})
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name])
    assert manifest["databases"][db_name]["doc_count"] == 2


def test_backup_manifest_records_vault_name_and_username(couchdb_client: CouchDB, managed_vault, backup_dir):
    username, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name])
    db_meta = manifest["databases"][db_name]
    assert db_meta["vault_name"] == "testvault"
    assert db_meta["username"] == username


def test_backup_ndjson_first_line_is_header_with_security(couchdb_client: CouchDB, managed_vault, backup_dir):
    username, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    header = json.loads(_read_ndjson_lines(dest, f"{db_name}.ndjson")[0])
    assert header["type"] == "header"
    assert header["db"] == db_name
    assert username in header["security"]["admins"]["names"]
    assert username in header["security"]["members"]["names"]


def test_backup_ndjson_contains_vault_documents(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    _put_doc(couchdb_client, db_name, {"_id": "my_doc", "content": "hello"})
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    lines = _read_ndjson_lines(dest, f"{db_name}.ndjson")
    doc_ids = [json.loads(line)["_id"] for line in lines[1:]]
    assert "my_doc" in doc_ids


def test_backup_multiple_databases(couchdb_client: CouchDB, managed_user, backup_dir):
    username, _ = managed_user
    db1 = couchdb_client.create_vault(username, "multi_a")
    db2 = couchdb_client.create_vault(username, "multi_b")
    try:
        dest = os.path.join(backup_dir, "multi.tar.gz")
        manifest = couchdb_client.backup(dest, [db1, db2])
        assert db1 in manifest["databases"]
        assert db2 in manifest["databases"]
        names = _archive_names(dest)
        assert f"{db1}.ndjson" in names
        assert f"{db2}.ndjson" in names
    finally:
        couchdb_client.delete_vault(db1)
        couchdb_client.delete_vault(db2)


def test_backup_nonexistent_db_raises(couchdb_client: CouchDB, backup_dir):
    dest = os.path.join(backup_dir, "fail.tar.gz")
    with pytest.raises(CouchDBError):
        couchdb_client.backup(dest, ["vault_nobody_nowhere_xyzzy"])


# ---------------------------------------------------------------------------
# include_users / include_config flags
# ---------------------------------------------------------------------------

def test_backup_users_not_included_by_default(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert "_users.ndjson" not in _archive_names(dest)


def test_backup_includes_users_when_flag_set(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name], include_users=True)
    assert "_users" in manifest["databases"]
    assert "_users.ndjson" in _archive_names(dest)


def test_backup_config_not_included_by_default(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    couchdb_client.backup(dest, [db_name])
    assert f"{CONFIG_DB}.ndjson" not in _archive_names(dest)


def test_backup_includes_config_when_flag_set(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [db_name], include_config=True)
    assert CONFIG_DB in manifest["databases"]
    assert f"{CONFIG_DB}.ndjson" in _archive_names(dest)


def test_backup_deduplicates_db_when_also_passed_as_explicit_database(couchdb_client: CouchDB, backup_dir):
    dest = os.path.join(backup_dir, "test.tar.gz")
    manifest = couchdb_client.backup(dest, [CONFIG_DB], include_config=True)
    assert list(manifest["databases"].keys()).count(CONFIG_DB) == 1


# ---------------------------------------------------------------------------
# read_backup_manifest()
# ---------------------------------------------------------------------------

def test_read_backup_manifest_matches_returned_manifest(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "test.tar.gz")
    original = couchdb_client.backup(dest, [db_name])
    read_back = couchdb_client.read_backup_manifest(dest)
    assert read_back["version"] == original["version"]
    assert read_back["created_at"] == original["created_at"]
    assert list(read_back["databases"].keys()) == list(original["databases"].keys())


def test_read_backup_manifest_corrupt_file_raises(couchdb_client: CouchDB, tmp_path):
    bad = str(tmp_path / "garbage.tar.gz")
    with open(bad, "wb") as f:
        f.write(b"this is not a valid tar.gz")
    with pytest.raises(CouchDBError):
        couchdb_client.read_backup_manifest(bad)


def test_read_backup_manifest_missing_file_raises(couchdb_client: CouchDB, tmp_path):
    with pytest.raises(CouchDBError):
        couchdb_client.read_backup_manifest(str(tmp_path / "nonexistent.tar.gz"))


# ---------------------------------------------------------------------------
# list_backups()
# ---------------------------------------------------------------------------

def test_list_backups_empty_dir_returns_empty_list(couchdb_client: CouchDB, backup_dir):
    assert couchdb_client.list_backups(backup_dir) == []


def test_list_backups_nonexistent_dir_returns_empty_list(couchdb_client: CouchDB, tmp_path):
    assert couchdb_client.list_backups(str(tmp_path / "does_not_exist")) == []


def test_list_backups_returns_one_entry_per_archive(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    couchdb_client.backup(os.path.join(backup_dir, "b1.tar.gz"), [db_name])
    couchdb_client.backup(os.path.join(backup_dir, "b2.tar.gz"), [db_name])
    assert len(couchdb_client.list_backups(backup_dir)) == 2


def test_list_backups_entry_has_expected_keys(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    couchdb_client.backup(os.path.join(backup_dir, "b.tar.gz"), [db_name])
    entry = couchdb_client.list_backups(backup_dir)[0]
    for key in ("filename", "path", "size", "created_at", "databases"):
        assert key in entry


def test_list_backups_size_is_positive(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    couchdb_client.backup(os.path.join(backup_dir, "b.tar.gz"), [db_name])
    assert couchdb_client.list_backups(backup_dir)[0]["size"] > 0


def test_list_backups_databases_metadata_matches_manifest(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    couchdb_client.backup(os.path.join(backup_dir, "b.tar.gz"), [db_name])
    entry = couchdb_client.list_backups(backup_dir)[0]
    assert db_name in entry["databases"]


def test_list_backups_ignores_non_tar_gz_files(couchdb_client: CouchDB, backup_dir):
    with open(os.path.join(backup_dir, "readme.txt"), "w") as f:
        f.write("not a backup")
    assert couchdb_client.list_backups(backup_dir) == []


def test_list_backups_sorted_newest_first(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    # Create two backups; the second has a later created_at timestamp
    couchdb_client.backup(os.path.join(backup_dir, "a_first.tar.gz"), [db_name])
    couchdb_client.backup(os.path.join(backup_dir, "z_second.tar.gz"), [db_name])
    result = couchdb_client.list_backups(backup_dir)
    timestamps = [b["created_at"] for b in result if b["created_at"]]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# delete_backup()
# ---------------------------------------------------------------------------

def test_delete_backup_removes_file(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    path = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(path, [db_name])
    couchdb_client.delete_backup(path)
    assert not os.path.isfile(path)


def test_delete_backup_no_longer_listed(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    path = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(path, [db_name])
    couchdb_client.delete_backup(path)
    assert couchdb_client.list_backups(backup_dir) == []


def test_delete_nonexistent_backup_raises(couchdb_client: CouchDB, backup_dir):
    with pytest.raises(CouchDBError):
        couchdb_client.delete_backup(os.path.join(backup_dir, "ghost.tar.gz"))


# ---------------------------------------------------------------------------
# restore()
# ---------------------------------------------------------------------------

def test_restore_vault_db_exists_after_restore(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    couchdb_client.delete_vault(db_name)
    couchdb_client.restore(dest, [db_name])
    assert couchdb_client.db_exists(db_name)


def test_restore_returns_doc_count_per_db(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    _put_doc(couchdb_client, db_name, {"_id": "doc1", "v": 1})
    _put_doc(couchdb_client, db_name, {"_id": "doc2", "v": 2})
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    couchdb_client.delete_vault(db_name)
    results = couchdb_client.restore(dest, [db_name])
    assert results[db_name] == 2


def test_restore_vault_documents_are_present(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    _put_doc(couchdb_client, db_name, {"_id": "important_doc", "data": "hello"})
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    couchdb_client.delete_vault(db_name)
    couchdb_client.restore(dest, [db_name])
    assert _doc_exists(couchdb_client, db_name, "important_doc")


def test_restore_vault_drops_existing_data(couchdb_client: CouchDB, managed_vault, backup_dir):
    """Documents added after the backup point must be absent after restore."""
    _, _, db_name = managed_vault
    _put_doc(couchdb_client, db_name, {"_id": "pre_backup_doc", "v": 1})
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    _put_doc(couchdb_client, db_name, {"_id": "post_backup_doc", "v": 2})
    couchdb_client.restore(dest, [db_name])
    assert _doc_exists(couchdb_client, db_name, "pre_backup_doc")
    assert not _doc_exists(couchdb_client, db_name, "post_backup_doc")


def test_restore_vault_security_doc_is_restored(couchdb_client: CouchDB, managed_vault, backup_dir):
    username, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    couchdb_client.delete_vault(db_name)
    couchdb_client.restore(dest, [db_name])
    r = couchdb_client._session.get(couchdb_client._url(db_name, "_security"))
    sec = r.json()
    assert username in sec["admins"]["names"]
    assert username in sec["members"]["names"]


def test_restore_selective_databases_only_restores_chosen(couchdb_client: CouchDB, managed_user, backup_dir):
    username, _ = managed_user
    db1 = couchdb_client.create_vault(username, "sel_a")
    db2 = couchdb_client.create_vault(username, "sel_b")
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db1, db2])
    couchdb_client.delete_vault(db1)
    couchdb_client.delete_vault(db2)
    try:
        results = couchdb_client.restore(dest, [db1])
        assert db1 in results
        assert db2 not in results
        assert couchdb_client.db_exists(db1)
        assert not couchdb_client.db_exists(db2)
    finally:
        try:
            couchdb_client.delete_vault(db1)
        except Exception:
            pass


def test_restore_all_databases_when_none_specified(couchdb_client: CouchDB, managed_user, backup_dir):
    username, _ = managed_user
    db1 = couchdb_client.create_vault(username, "all_a")
    db2 = couchdb_client.create_vault(username, "all_b")
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db1, db2])
    couchdb_client.delete_vault(db1)
    couchdb_client.delete_vault(db2)
    try:
        results = couchdb_client.restore(dest)  # databases=None → restore all
        assert db1 in results
        assert db2 in results
        assert couchdb_client.db_exists(db1)
        assert couchdb_client.db_exists(db2)
    finally:
        for db in [db1, db2]:
            try:
                couchdb_client.delete_vault(db)
            except Exception:
                pass


def test_restore_db_not_in_archive_raises(couchdb_client: CouchDB, managed_vault, backup_dir):
    _, _, db_name = managed_vault
    dest = os.path.join(backup_dir, "b.tar.gz")
    couchdb_client.backup(dest, [db_name])
    with pytest.raises(CouchDBError, match="not in this backup"):
        couchdb_client.restore(dest, ["vault_nobody_xyzzy_99"])
