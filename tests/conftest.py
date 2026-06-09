"""
Shared pytest fixtures for VaultKeeper tests.

A real CouchDB instance is used for every test — no mocking.

By default a CouchDB container is started automatically via testcontainers.
Set COUCHDB_TEST_URL to point at an already-running instance instead:

  export COUCHDB_TEST_URL=http://localhost:5984
  export COUCHDB_TEST_USER=admin        # defaults to "admin"
  export COUCHDB_TEST_PASSWORD=password  # defaults to "password"
"""

import os
import shutil
import time
import uuid

import pytest
import requests

from vaultkeeper.client import CouchDB

_COUCHDB_IMAGE = "couchdb:3.5.1"
_DEFAULT_USER = "admin"
_DEFAULT_PASSWORD = "password"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wait_for_couchdb(url: str, username: str, password: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{url}/", auth=(username, password), timeout=2)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"CouchDB at {url} did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# Session-scoped CouchDB client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def couchdb_client() -> CouchDB:
    """
    Yields a configured CouchDB client for the test session.

    Starts a testcontainer unless COUCHDB_TEST_URL is set.
    server_init() is called once so every test runs against a LiveSync-ready instance.
    """
    test_url = os.environ.get("COUCHDB_TEST_URL")

    if test_url:
        username = os.environ.get("COUCHDB_TEST_USER", _DEFAULT_USER)
        password = os.environ.get("COUCHDB_TEST_PASSWORD", _DEFAULT_PASSWORD)
        client = CouchDB(host=test_url, username=username, password=password)
        client.server_init()
        yield client
        return

    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(_COUCHDB_IMAGE)
        .with_env("COUCHDB_USER", _DEFAULT_USER)
        .with_env("COUCHDB_PASSWORD", _DEFAULT_PASSWORD)
        .with_exposed_ports(5984)
    )
    with container as c:
        host = c.get_container_host_ip()
        port = c.get_exposed_port(5984)
        url = f"http://{host}:{port}"
        _wait_for_couchdb(url, _DEFAULT_USER, _DEFAULT_PASSWORD)

        client = CouchDB(host=url, username=_DEFAULT_USER, password=_DEFAULT_PASSWORD)
        client.server_init()
        yield client


# ---------------------------------------------------------------------------
# Per-test resource fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def unique_username() -> str:
    """A username that is unique to this test invocation."""
    return f"testuser_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def managed_user(couchdb_client: CouchDB, unique_username: str):
    """
    Creates a CouchDB user before the test and deletes it afterwards.
    Yields (username, password).
    """
    password = "testpassword"
    couchdb_client.create_user(unique_username, password)
    yield unique_username, password
    try:
        couchdb_client.delete_user(unique_username)
    except Exception:
        pass


@pytest.fixture
def managed_vault(couchdb_client: CouchDB, managed_user):
    """
    Creates a vault database before the test and deletes it afterwards.
    Yields (username, password, db_name).
    """
    username, password = managed_user
    db_name = couchdb_client.create_vault(username, "testvault")
    yield username, password, db_name
    try:
        couchdb_client.delete_vault(db_name)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auto-skip requires_deno tests when Deno is not on PATH
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    if shutil.which("deno") is not None:
        return
    skip = pytest.mark.skip(reason="deno not on PATH — only runs inside the VaultKeeper container")
    for item in items:
        if item.get_closest_marker("requires_deno"):
            item.add_marker(skip)
