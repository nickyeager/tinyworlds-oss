"""End-to-end tests for authentication flows."""
import pytest
from httpx import AsyncClient


class TestAuthenticationE2E:
    """E2E tests for complete authentication flows."""

    @pytest.mark.asyncio
    async def test_complete_registration_login_flow(self, client: AsyncClient):
        """Test complete flow: register -> login -> access protected -> refresh -> logout."""
        # 1. Register
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "e2e@example.com",
                "password": "SecureP@ss123",
                "username": "e2euser",
            }
        )
        assert register_response.status_code == 201, f"Register failed: {register_response.json()}"
        tokens = register_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["is_anonymous"] is False
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # 2. Access protected endpoint
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "e2e@example.com"

        # 3. Refresh token
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        assert refresh_response.status_code == 200, f"Refresh failed: {refresh_response.json()}"
        new_tokens = refresh_response.json()
        assert new_tokens["access_token"] != access_token
        assert new_tokens["refresh_token"] != refresh_token

        # 4. Old refresh token should be invalid (rotation)
        old_refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        assert old_refresh_response.status_code == 401

        # 5. Logout
        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_tokens['access_token']}"}
        )
        assert logout_response.status_code == 200

        # 6. New refresh token should also be invalid after logout
        post_logout_refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_tokens["refresh_token"]}
        )
        assert post_logout_refresh.status_code == 401

    @pytest.mark.asyncio
    async def test_login_flow_existing_user(self, client: AsyncClient):
        """Test login flow for existing user."""
        # Register first
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logintest@example.com",
                "password": "testpass123",
                "username": "loginuser",
            }
        )
        assert register_response.status_code == 201

        # Now login
        login_response = await client.post(
            "/api/v1/auth/login",
            data={"username": "logintest@example.com", "password": "testpass123"}
        )
        assert login_response.status_code == 200
        tokens = login_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["is_anonymous"] is False

        # Access /me
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "logintest@example.com"

    @pytest.mark.asyncio
    async def test_anonymous_user_flow(self, client: AsyncClient):
        """Test anonymous user creation and access."""
        # 1. Get anonymous token
        anon_response = await client.post("/api/v1/auth/anonymous")
        assert anon_response.status_code == 200, f"Anonymous failed: {anon_response.json()}"
        anon_tokens = anon_response.json()
        assert anon_tokens["access_token"]
        assert anon_tokens["refresh_token"]
        assert anon_tokens["is_anonymous"] is True

        # 2. Access protected endpoint as anonymous
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {anon_tokens['access_token']}"}
        )
        assert me_response.status_code == 200
        user_data = me_response.json()
        assert user_data["is_anonymous"] is True
        assert user_data["email"].startswith("anon_")

        # 3. Can refresh anonymous token
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": anon_tokens["refresh_token"]}
        )
        assert refresh_response.status_code == 200
        new_tokens = refresh_response.json()
        assert new_tokens["access_token"] != anon_tokens["access_token"]

    @pytest.mark.asyncio
    async def test_session_management_flow(self, client: AsyncClient):
        """Test multi-device session management."""
        # Register user
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "sessions@example.com",
                "password": "testpass123",
                "username": "sessionuser",
            }
        )
        assert register_response.status_code == 201
        token1 = register_response.json()["access_token"]

        # Login from "Device 2"
        login2 = await client.post(
            "/api/v1/auth/login",
            data={"username": "sessions@example.com", "password": "testpass123"}
        )
        assert login2.status_code == 200

        # Verify 2 sessions exist
        sessions_response = await client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token1}"}
        )
        assert sessions_response.status_code == 200
        sessions_data = sessions_response.json()
        assert sessions_data["total"] == 2
        assert len(sessions_data["sessions"]) == 2

        # Get session IDs
        session_ids = [s["id"] for s in sessions_data["sessions"]]

        # Revoke one session (not the current one)
        revoke_response = await client.delete(
            f"/api/v1/auth/sessions/{session_ids[1]}",
            headers={"Authorization": f"Bearer {token1}"}
        )
        assert revoke_response.status_code == 200

        # Verify only 1 session remains
        sessions_after = await client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token1}"}
        )
        assert sessions_after.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_logout_all_sessions(self, client: AsyncClient):
        """Test logging out from all devices."""
        # Register user
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logoutall@example.com",
                "password": "testpass123",
                "username": "logoutalluser",
            }
        )
        assert register_response.status_code == 201
        token1 = register_response.json()["access_token"]

        # Create more sessions
        login2 = await client.post(
            "/api/v1/auth/login",
            data={"username": "logoutall@example.com", "password": "testpass123"}
        )
        refresh2 = login2.json()["refresh_token"]

        login3 = await client.post(
            "/api/v1/auth/login",
            data={"username": "logoutall@example.com", "password": "testpass123"}
        )
        refresh3 = login3.json()["refresh_token"]

        # Verify 3 sessions
        sessions = await client.get(
            "/api/v1/auth/sessions",
            headers={"Authorization": f"Bearer {token1}"}
        )
        assert sessions.json()["total"] == 3

        # Logout all
        logout_all = await client.post(
            "/api/v1/auth/logout/all",
            headers={"Authorization": f"Bearer {token1}"}
        )
        assert logout_all.status_code == 200

        # All refresh tokens should be invalid
        refresh2_result = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh2}
        )
        assert refresh2_result.status_code == 401

        refresh3_result = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh3}
        )
        assert refresh3_result.status_code == 401

    @pytest.mark.asyncio
    async def test_token_reuse_detection(self, client: AsyncClient):
        """Test that reusing a refresh token triggers security revocation."""
        # Register user
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "reuse@example.com",
                "password": "testpass123",
                "username": "reuseuser",
            }
        )
        assert register_response.status_code == 201
        original_refresh = register_response.json()["refresh_token"]

        # Use refresh token (token1 -> token2)
        refresh1 = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh}
        )
        assert refresh1.status_code == 200
        new_refresh = refresh1.json()["refresh_token"]

        # Try to reuse original token (should detect reuse)
        reuse_attempt = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh}
        )
        assert reuse_attempt.status_code == 401
        detail = reuse_attempt.json()["detail"].lower()
        assert "reuse" in detail or "compromised" in detail

        # The new token should also be revoked (entire family)
        new_token_attempt = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_refresh}
        )
        assert new_token_attempt.status_code == 401

    @pytest.mark.asyncio
    async def test_anonymous_cannot_regular_login(self, client: AsyncClient):
        """Test that anonymous users cannot use regular login."""
        # Create anonymous user
        anon_response = await client.post("/api/v1/auth/anonymous")
        assert anon_response.status_code == 200
        anon_tokens = anon_response.json()

        # Get anonymous user email
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {anon_tokens['access_token']}"}
        )
        anon_email = me_response.json()["email"]

        # Try to login with anonymous credentials (should fail)
        login_response = await client.post(
            "/api/v1/auth/login",
            data={"username": anon_email, "password": "anything"}
        )
        # Should fail because either password is wrong or anonymous users blocked
        assert login_response.status_code == 401

    @pytest.mark.asyncio
    async def test_upgrade_anonymous_account(self, client: AsyncClient):
        """Test upgrading anonymous account to registered."""
        # Create anonymous user
        anon_response = await client.post("/api/v1/auth/anonymous")
        assert anon_response.status_code == 200
        anon_tokens = anon_response.json()
        assert anon_tokens["is_anonymous"] is True

        # Upgrade to registered
        upgrade_response = await client.post(
            "/api/v1/auth/upgrade",
            json={
                "email": "upgraded@example.com",
                "username": "upgradeduser",
                "password": "newpassword123",
            },
            headers={"Authorization": f"Bearer {anon_tokens['access_token']}"}
        )
        assert upgrade_response.status_code == 200
        upgraded_tokens = upgrade_response.json()
        assert upgraded_tokens["is_anonymous"] is False

        # Verify user is no longer anonymous
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {upgraded_tokens['access_token']}"}
        )
        assert me_response.status_code == 200
        user_data = me_response.json()
        assert user_data["email"] == "upgraded@example.com"
        assert user_data["is_anonymous"] is False

        # Can login with new credentials
        login_response = await client.post(
            "/api/v1/auth/login",
            data={"username": "upgraded@example.com", "password": "newpassword123"}
        )
        assert login_response.status_code == 200
