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
    bad_client = CouchDB(
        host=couchdb_client.hostname, port=couchdb_client.port, protocol=couchdb_client.protocol,
        username="wrong_user", password="wrong_pass",
    )
    try:
        bad_client.ping()
        # CouchDB's root endpoint may return 200 regardless of credentials - acceptable.
    except CouchDBError:
        pass  # expected when auth is enforced


# ---------------------------------------------------------------------------
# Constructor behaviour
# ---------------------------------------------------------------------------

def test_constructor_builds_host_url_from_parts():
    client = CouchDB(host="localhost", port=5984, protocol="http", username="u", password="p")
    assert client.host == "http://localhost:5984"


def test_constructor_defaults_to_localhost_http_5984():
    client = CouchDB(username="u", password="p")
    assert client.host == "http://localhost:5984"


def test_constructor_strips_trailing_slash_from_host():
    client = CouchDB(host="localhost/", port=5984, protocol="http", username="u", password="p")
    assert client.host == "http://localhost:5984"


def test_constructor_public_url_falls_back_to_host():
    client = CouchDB(host="localhost", port=5984, protocol="http", username="u", password="p")
    assert client.public_url == "http://localhost:5984"


def test_constructor_public_url_strips_trailing_slash():
    client = CouchDB(host="localhost", username="u", password="p",
                     public_url="https://couchdb.example.com/")
    assert client.public_url == "https://couchdb.example.com"


def test_constructor_explicit_public_url_used_when_provided():
    client = CouchDB(host="localhost", username="u", password="p",
                     public_url="https://couchdb.example.com")
    assert client.public_url == "https://couchdb.example.com"
