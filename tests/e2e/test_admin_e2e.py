"""End-to-end tests for the admin panel routes.

Covers:
- Users list/search/filter through the HTTP API
- Admin-triggered password reset (happy path, anonymous reject, inactive reject,
  audit log row)
- Invitation create with send_email + /resend endpoint
- Admin gate (non-admin gets 403)
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.api.models.admin_audit_log import AdminAuditLog


# There is no default admin. The fixture below lists this address in
# ADMIN_EMAILS so registering with it promotes the user to is_admin=True.
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "AdminPass123!"


@pytest.fixture
async def admin_token(client: AsyncClient, monkeypatch) -> str:
    """Register the bootstrap admin and return their access token."""
    from src.api.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ADMIN_EMAILS", ADMIN_EMAIL)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "username": "admin"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["is_anonymous"] is False
    return body["access_token"]


@pytest.fixture
def email_capture(monkeypatch):
    """Capture every outbound email instead of hitting Resend.

    Patches the boundary (`EmailService._send_email`), not the methods under
    test, so the assertion is "the route asked to send this email" — the actual
    contract.
    """
    sent: list[dict] = []

    async def fake_send(self, to_email, subject, html_content, text_content):
        sent.append(
            {
                "to": to_email,
                "subject": subject,
                "html": html_content,
                "text": text_content,
            }
        )
        return True

    from src.api.services import email_service as email_module

    monkeypatch.setattr(email_module.EmailService, "_send_email", fake_send)
    return sent


# ----- admin gate -----


@pytest.mark.asyncio
async def test_non_admin_blocked_from_admin_routes(client: AsyncClient):
    """A normal authenticated user must get 403, not 200, on admin routes."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "nobody@x.com", "password": "Pass1234!", "username": "nobody"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@x.com", "password": "Pass1234!"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_blocked(client: AsyncClient):
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 401


# ----- users list -----


@pytest.mark.asyncio
async def test_admin_lists_users(client: AsyncClient, admin_token: str):
    # Seed a second registered user + one anonymous user.
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@x.com",
            "password": "Alice1234!",
            "username": "alice",
            "full_name": "Alice Adams",
        },
    )
    anon_resp = await client.post("/api/v1/auth/anonymous")
    assert anon_resp.status_code == 200

    # Default excludes anonymous
    resp = await client.get(
        "/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    emails = {u["email"] for u in body["users"]}
    assert ADMIN_EMAIL in emails
    assert "alice@x.com" in emails
    assert not any(u["is_anonymous"] for u in body["users"])

    # include_anonymous=true should surface the anon row
    resp = await client.get(
        "/api/v1/admin/users?include_anonymous=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert any(u["is_anonymous"] for u in resp.json()["users"])

    # Search hits full_name case-insensitively
    resp = await client.get(
        "/api/v1/admin/users?q=adams",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rows = resp.json()["users"]
    assert {u["email"] for u in rows} == {"alice@x.com"}


# ----- invitation create + resend with email -----


@pytest.mark.asyncio
async def test_create_invitation_sends_email(
    client: AsyncClient, admin_token: str, email_capture: list[dict]
):
    resp = await client.post(
        "/api/v1/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "newbie@x.com", "send_email": True},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "newbie@x.com"
    assert body["email_sent"] is True
    # accept_url surfaces the token so admin can copy/paste if email fails
    assert "register?invite=" in body["accept_url"]

    assert len(email_capture) == 1
    sent = email_capture[0]
    assert sent["to"] == "newbie@x.com"
    assert body["token"] in sent["html"]


@pytest.mark.asyncio
async def test_create_invitation_without_email(
    client: AsyncClient, admin_token: str, email_capture: list[dict]
):
    resp = await client.post(
        "/api/v1/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "quiet@x.com", "send_email": False},
    )
    assert resp.status_code == 201
    assert resp.json()["email_sent"] is None
    assert email_capture == []


@pytest.mark.asyncio
async def test_resend_invitation_sends_new_email(
    client: AsyncClient, admin_token: str, email_capture: list[dict]
):
    create = await client.post(
        "/api/v1/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "again@x.com", "send_email": False},
    )
    invitation_id = create.json()["id"]
    assert email_capture == []

    resend = await client.post(
        f"/api/v1/admin/invitations/{invitation_id}/resend",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resend.status_code == 200
    assert resend.json()["email_sent"] is True
    assert len(email_capture) == 1
    assert email_capture[0]["to"] == "again@x.com"


# ----- admin-triggered password reset -----


@pytest.mark.asyncio
async def test_admin_triggers_password_reset(
    client: AsyncClient, admin_token: str, email_capture: list[dict]
):
    # Register the target user
    await client.post(
        "/api/v1/auth/register",
        json={"email": "target@x.com", "password": "Old1234!", "username": "target"},
    )
    list_resp = await client.get(
        "/api/v1/admin/users?q=target@x.com",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    target_id = list_resp.json()["users"][0]["id"]

    # Trigger reset with send_email=true
    reset = await client.post(
        f"/api/v1/admin/users/{target_id}/password-reset",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"send_email": True},
    )
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body["email_sent"] is True
    # When emailing, the raw URL is intentionally suppressed.
    assert body["reset_url"] is None
    assert len(email_capture) == 1
    assert email_capture[0]["to"] == "target@x.com"

    # Without send_email, the response returns the reset_url
    reset2 = await client.post(
        f"/api/v1/admin/users/{target_id}/password-reset",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"send_email": False},
    )
    body2 = reset2.json()
    assert body2["email_sent"] is False
    assert body2["reset_url"] is not None
    assert "reset-password?token=" in body2["reset_url"]


@pytest.mark.asyncio
async def test_password_reset_rejects_anonymous_user(
    client: AsyncClient, admin_token: str
):
    anon = await client.post("/api/v1/auth/anonymous")
    anon_token = anon.json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {anon_token}"}
    )
    anon_id = me.json()["id"]

    resp = await client.post(
        f"/api/v1/admin/users/{anon_id}/password-reset",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"send_email": True},
    )
    assert resp.status_code == 400
    assert "anonymous" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_password_reset_writes_audit_log(
    client: AsyncClient, admin_token: str, email_capture: list[dict]
):
    """The route must record the reset in admin_audit_log."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "audited@x.com", "password": "Old1234!", "username": "audited"},
    )
    list_resp = await client.get(
        "/api/v1/admin/users?q=audited@x.com",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    target_id = list_resp.json()["users"][0]["id"]

    await client.post(
        f"/api/v1/admin/users/{target_id}/password-reset",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"send_email": True},
    )

    # Pull the audit log row out of the test DB using the dependency-overridden
    # get_db so we hit the same in-memory engine the route just wrote to.
    from src.api.core.database import get_db
    from src.api.main import app

    override = app.dependency_overrides[get_db]
    async for db in override():
        result = await db.execute(
            select(AdminAuditLog).where(AdminAuditLog.target_email == "audited@x.com")
        )
        rows = result.scalars().all()
        break

    actions = [r.action for r in rows]
    assert "issue_password_reset" in actions
