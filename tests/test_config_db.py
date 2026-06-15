"""
Tests for vaultkeeper_config database operations:
invitation CRUD, user limits, and user authentication.
"""

import time

import pytest

from vaultkeeper.client import CouchDB, CouchDBError


# ---------------------------------------------------------------------------
# Invitation tests
# ---------------------------------------------------------------------------

class TestInvitations:
    def test_create_invitation_returns_token(self, couchdb_client: CouchDB):
        token = couchdb_client.create_invitation()
        assert isinstance(token, str)
        assert len(token) > 16
        # cleanup
        couchdb_client.delete_invitation(token)

    def test_get_valid_invitation(self, couchdb_client: CouchDB):
        token = couchdb_client.create_invitation(expiry_hours=24)
        doc = couchdb_client.get_invitation(token)
        assert doc is not None
        assert doc["token"] == token
        assert doc["used"] is False
        couchdb_client.delete_invitation(token)

    def test_get_missing_invitation_returns_none(self, couchdb_client: CouchDB):
        result = couchdb_client.get_invitation("this-token-does-not-exist")
        assert result is None

    def test_get_expired_invitation_returns_none(self, couchdb_client: CouchDB):
        # Create with a very short expiry by manipulating the doc directly
        token = couchdb_client.create_invitation(expiry_hours=24)
        # Fetch and back-date expires_at
        from datetime import datetime, timezone, timedelta
        r = couchdb_client._session.get(couchdb_client._url("vaultkeeper_config", f"invitation:{token}"))
        doc = r.json()
        doc["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        couchdb_client._session.put(
            couchdb_client._url("vaultkeeper_config", f"invitation:{token}"),
            data=__import__("json").dumps(doc),
        )
        result = couchdb_client.get_invitation(token)
        assert result is None
        couchdb_client.delete_invitation(token)

    def test_consume_invitation(self, couchdb_client: CouchDB):
        token = couchdb_client.create_invitation()
        couchdb_client.consume_invitation(token, "alice")
        # get_invitation should now return None (used)
        result = couchdb_client.get_invitation(token)
        assert result is None
        # Verify the doc itself has the used fields
        r = couchdb_client._session.get(
            couchdb_client._url("vaultkeeper_config", f"invitation:{token}")
        )
        doc = r.json()
        assert doc["used"] is True
        assert doc["used_by"] == "alice"
        assert doc["used_at"] is not None
        couchdb_client.delete_invitation(token)

    def test_list_invitations(self, couchdb_client: CouchDB):
        token1 = couchdb_client.create_invitation()
        token2 = couchdb_client.create_invitation()
        try:
            listing = couchdb_client.list_invitations()
            tokens = [inv["token"] for inv in listing]
            assert token1 in tokens
            assert token2 in tokens
        finally:
            couchdb_client.delete_invitation(token1)
            couchdb_client.delete_invitation(token2)

    def test_delete_invitation(self, couchdb_client: CouchDB):
        token = couchdb_client.create_invitation()
        couchdb_client.delete_invitation(token)
        assert couchdb_client.get_invitation(token) is None

    def test_delete_nonexistent_invitation_raises(self, couchdb_client: CouchDB):
        with pytest.raises(CouchDBError):
            couchdb_client.delete_invitation("nonexistent-token")


# ---------------------------------------------------------------------------
# User limits tests
# ---------------------------------------------------------------------------

class TestUserLimits:
    def test_get_limits_defaults_when_none_set(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        limits = couchdb_client.get_user_limits(username)
        assert limits == {"max_vaults": None, "max_vault_size_bytes": None}

    def test_set_and_get_limits(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_user_limits(username, max_vaults=5, max_vault_size_bytes=1_000_000)
        limits = couchdb_client.get_user_limits(username)
        assert limits["max_vaults"] == 5
        assert limits["max_vault_size_bytes"] == 1_000_000

    def test_update_existing_limits(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_user_limits(username, max_vaults=3, max_vault_size_bytes=None)
        couchdb_client.set_user_limits(username, max_vaults=10, max_vault_size_bytes=None)
        limits = couchdb_client.get_user_limits(username)
        assert limits["max_vaults"] == 10

    def test_clear_limits_with_none(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_user_limits(username, max_vaults=5, max_vault_size_bytes=500_000)
        couchdb_client.set_user_limits(username, max_vaults=None, max_vault_size_bytes=None)
        limits = couchdb_client.get_user_limits(username)
        assert limits["max_vaults"] is None
        assert limits["max_vault_size_bytes"] is None


# ---------------------------------------------------------------------------
# User authentication tests
# ---------------------------------------------------------------------------

class TestAuthentication:
    def test_valid_user_credentials(self, couchdb_client: CouchDB, managed_user):
        username, password = managed_user
        assert couchdb_client.authenticate_user(username, password) is True

    def test_invalid_password(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        assert couchdb_client.authenticate_user(username, "wrongpassword") is False

    def test_nonexistent_user(self, couchdb_client: CouchDB):
        assert couchdb_client.authenticate_user("no_such_user_xyz", "anypassword") is False
