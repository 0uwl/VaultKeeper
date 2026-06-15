"""
Tests for vaultkeeper_data database operations:
invitation CRUD, user limits, server settings, and user authentication.
"""

import json

import pytest

from vaultkeeper.client import CouchDB, CouchDBError, CONFIG_DB


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
        from datetime import datetime, timezone, timedelta
        token = couchdb_client.create_invitation(expiry_hours=24)
        r = couchdb_client._session.get(couchdb_client._url(CONFIG_DB, f"invitation:{token}"))
        doc = r.json()
        doc["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        couchdb_client._session.put(
            couchdb_client._url(CONFIG_DB, f"invitation:{token}"),
            data=json.dumps(doc),
        )
        result = couchdb_client.get_invitation(token)
        assert result is None
        couchdb_client.delete_invitation(token)

    def test_consume_invitation(self, couchdb_client: CouchDB):
        token = couchdb_client.create_invitation()
        couchdb_client.consume_invitation(token, "alice")
        assert couchdb_client.get_invitation(token) is None
        r = couchdb_client._session.get(
            couchdb_client._url(CONFIG_DB, f"invitation:{token}")
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
# Server settings tests
# ---------------------------------------------------------------------------

class TestServerSettings:
    def test_get_settings_returns_defaults_when_unset(self, couchdb_client: CouchDB):
        # Reset to no settings first
        couchdb_client.set_server_settings(None, None)
        settings = couchdb_client.get_server_settings()
        assert settings["default_max_vaults"] is None
        assert settings["default_max_vault_size_bytes"] is None

    def test_set_and_get_settings(self, couchdb_client: CouchDB):
        couchdb_client.set_server_settings(
            default_max_vaults=10,
            default_max_vault_size_bytes=5_000_000,
        )
        settings = couchdb_client.get_server_settings()
        assert settings["default_max_vaults"] == 10
        assert settings["default_max_vault_size_bytes"] == 5_000_000
        # cleanup
        couchdb_client.set_server_settings(None, None)

    def test_update_settings(self, couchdb_client: CouchDB):
        couchdb_client.set_server_settings(default_max_vaults=5, default_max_vault_size_bytes=None)
        couchdb_client.set_server_settings(default_max_vaults=20, default_max_vault_size_bytes=None)
        settings = couchdb_client.get_server_settings()
        assert settings["default_max_vaults"] == 20
        # cleanup
        couchdb_client.set_server_settings(None, None)


# ---------------------------------------------------------------------------
# Effective limits tests (per-user overrides server defaults)
# ---------------------------------------------------------------------------

class TestEffectiveLimits:
    def test_falls_back_to_server_default(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_server_settings(default_max_vaults=3, default_max_vault_size_bytes=None)
        # No per-user limit set
        effective = couchdb_client.get_effective_limits(username)
        assert effective["max_vaults"] == 3
        # cleanup
        couchdb_client.set_server_settings(None, None)

    def test_per_user_limit_overrides_server_default(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_server_settings(default_max_vaults=3, default_max_vault_size_bytes=None)
        couchdb_client.set_user_limits(username, max_vaults=10, max_vault_size_bytes=None)
        effective = couchdb_client.get_effective_limits(username)
        assert effective["max_vaults"] == 10
        # cleanup
        couchdb_client.set_server_settings(None, None)

    def test_no_limits_anywhere_returns_none(self, couchdb_client: CouchDB, managed_user):
        username, _ = managed_user
        couchdb_client.set_server_settings(None, None)
        effective = couchdb_client.get_effective_limits(username)
        assert effective["max_vaults"] is None
        assert effective["max_vault_size_bytes"] is None


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
