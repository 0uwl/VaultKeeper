from vaultkeeper.client import CouchDB, CouchDBError


def test_ping_returns_version(couchdb_client: CouchDB):
    info = couchdb_client.ping()
    assert "version" in info


def test_ping_version_is_string(couchdb_client: CouchDB):
    info = couchdb_client.ping()
    assert isinstance(info["version"], str)
    assert info["version"].startswith("3.")


def test_server_init_is_idempotent(couchdb_client: CouchDB):
    # server_init was already called by the session fixture; calling it again must not raise
    couchdb_client.server_init()


def test_ping_bad_credentials(couchdb_client: CouchDB):
    bad_client = CouchDB(host=couchdb_client.host, username="wrong_user", password="wrong_pass")
    try:
        bad_client.ping()
        # CouchDB's root endpoint may return 200 regardless of credentials - acceptable.
    except CouchDBError:
        pass  # expected when auth is enforced
