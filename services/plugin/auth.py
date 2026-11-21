"""OAuth-code/PKCE account linking using the official MCP SDK routes."""

from __future__ import annotations

import asyncio
import html
import secrets
import time
from urllib.parse import urlsplit

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from services.plugin.config import Config
from services.plugin.store import Store

SCOPES = ["games:read", "games:write", "games:play"]


class PluginAccess(AccessToken):
    backend_access: str
    grant_id: str


class PluginRefresh(RefreshToken):
    grant_id: str


class Provider:
    def __init__(self, config: Config, store: Store, backend: httpx.AsyncClient):
        self.config, self.store, self.backend = config, store, backend
        self.exchange_lock = asyncio.Lock()

    async def get_client(self, client_id: str):
        record = self.store.get("client", client_id)
        return OAuthClientInformationFull.model_validate(record) if record else None

    async def register_client(self, client_info: OAuthClientInformationFull):
        if len(client_info.redirect_uris or []) > 5:
            raise RegistrationError("invalid_redirect_uri", "At most five redirects")
        for uri in client_info.redirect_uris or []:
            value = str(uri)
            parsed = urlsplit(value)
            loopback = parsed.scheme == "http" and parsed.hostname in {
                "127.0.0.1",
                "localhost",
                "::1",
            }
            chatgpt = (
                parsed.scheme == "https"
                and parsed.netloc == "chatgpt.com"
                and (
                    parsed.path == "/connector_platform_oauth_redirect"
                    or parsed.path.startswith("/connector/oauth/")
                )
            )
            if (
                parsed.username
                or parsed.password
                or parsed.fragment
                or not (loopback or chatgpt or value in self.config.extra_redirect_uris)
            ):
                raise RegistrationError(
                    "invalid_redirect_uri",
                    "Use a ChatGPT callback, loopback callback, or configured URI",
                )
        self.store.put(
            "client", client_info.client_id, client_info.model_dump(mode="json")
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ):
        if params.resource != self.config.resource:
            raise AuthorizeError(
                "invalid_request", "The resource must identify this MCP endpoint"
            )
        if (
            not params.scopes
            or not set(params.scopes).issubset(SCOPES)
            or "games:read" not in params.scopes
        ):
            raise AuthorizeError(
                "invalid_scope", "games:read is required; games:write and games:play are optional"
            )
        ticket = secrets.token_urlsafe(32)
        self.store.put(
            "consent",
            ticket,
            {
                "client_id": client.client_id,
                "client_name": (client.client_name or "MCP client")[:100],
                "params": params.model_dump(mode="json"),
            },
            ttl=600,
        )
        return self.config.public_url + "/connect?ticket=" + ticket

    async def load_authorization_code(self, client, authorization_code):
        record = self.store.get("code", authorization_code)
        if not record or record["code"]["client_id"] != client.client_id:
            return None
        return AuthorizationCode.model_validate(record["code"])

    def issue(self, grant: dict) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        lifetime = min(1800, int(grant["backend_expires"] - time.time()))
        if lifetime < 1:
            raise TokenError("invalid_grant", "Account login expired; reconnect")
        prior = grant.get("access")
        if prior:
            self.store.remove("access", prior)
        grant["access"] = access
        self.store.put(
            "grant", grant["id"], grant, ttl=max(1, grant["expires"] - time.time())
        )
        self.store.put(
            "access",
            access,
            PluginAccess(
                token=access,
                client_id=grant["client_id"],
                scopes=grant["scopes"],
                expires_at=int(time.time()) + lifetime,
                resource=self.config.resource,
                subject=grant["subject"],
                backend_access=grant["backend_access"],
                grant_id=grant["id"],
            ).model_dump(mode="json"),
            ttl=lifetime,
        )
        self.store.put(
            "refresh",
            refresh,
            PluginRefresh(
                token=refresh,
                client_id=grant["client_id"],
                scopes=grant["scopes"],
                expires_at=int(grant["expires"]),
                resource=self.config.resource,
                subject=grant["subject"],
                grant_id=grant["id"],
            ).model_dump(mode="json"),
            ttl=max(1, grant["expires"] - time.time()),
        )
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_in=lifetime,
            scope=" ".join(grant["scopes"]),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        record = self.store.get("code", authorization_code.code, consume=True)
        if not record or record["code"]["client_id"] != client.client_id:
            raise TokenError("invalid_grant", "Code has already been used")
        return self.issue(record["grant"])

    async def load_refresh_token(self, client, refresh_token):
        used = self.store.get("used_refresh", refresh_token)
        if used and used["client_id"] == client.client_id:
            self.store.remove("grant", used["grant_id"])
            return None
        record = self.store.get("refresh", refresh_token)
        if (
            not record
            or record["client_id"] != client.client_id
            or not self.store.get("grant", record["grant_id"])
        ):
            return None
        return PluginRefresh.model_validate(record)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        async with self.exchange_lock:
            record = self.store.get("refresh", refresh_token.token, consume=True)
            if not record:
                self.store.remove("grant", refresh_token.grant_id)
                raise TokenError("invalid_grant", "Refresh token has already been used")
            grant = self.store.get("grant", refresh_token.grant_id)
            if (
                not grant
                or not set(scopes).issubset(grant["scopes"])
                or "games:read" not in scopes
            ):
                raise TokenError("invalid_grant", "Reconnect this account")
            self.store.put(
                "used_refresh",
                refresh_token.token,
                {
                    "client_id": client.client_id,
                    "grant_id": grant["id"],
                },
                ttl=max(1, grant["expires"] - time.time()),
            )
            # Backend refresh rotation preserves account/session revocation checks.
            response = await self.backend.post(
                "/api/v1/auth/refresh", json={"refresh_token": grant["backend_refresh"]}
            )
            if response.status_code != 200:
                self.store.remove("grant", grant["id"])
                raise TokenError("invalid_grant", "Account session expired; reconnect")
            pair = response.json()
            grant.update(
                backend_access=pair["access_token"],
                backend_refresh=pair["refresh_token"],
                backend_expires=time.time() + pair["expires_in"],
                scopes=scopes,
            )
            return self.issue(grant)

    async def load_access_token(self, token):
        record = self.store.get("access", token)
        if (
            not record
            or not self.store.get("grant", record["grant_id"])
            or record["resource"] != self.config.resource
        ):
            return None
        return PluginAccess.model_validate(record)

    async def revoke_token(self, token):
        self.store.remove("grant", token.grant_id)

    async def revocation(self, request: Request):
        """RFC 7009 revocation, including public clients with no client secret.

        MCP 1.30's RevocationRequest makes client_secret nullable but required.
        Keep SDK client authentication, while accepting omission for public clients.
        """
        try:
            client = await ClientAuthenticator(self).authenticate_request(request)
        except AuthenticationError as error:
            return JSONResponse(
                {"error": "unauthorized_client", "error_description": error.message},
                status_code=401,
            )
        form = await request.form()
        value = form.get("token")
        if not isinstance(value, str) or not value:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        token = await self.load_access_token(value)
        if token is None:
            token = await self.load_refresh_token(client, value)
        if token is not None and token.client_id == client.client_id:
            await self.revoke_token(token)
        # Unknown tokens and unsupported type hints are intentionally harmless.
        return Response(status_code=200, headers={"Pragma": "no-cache"})

    def consent_html(self, ticket: str, record: dict, csrf: str, error: str = ""):
        escape = html.escape
        scopes = record["params"]["scopes"]
        permissions = "Read games and progress"
        if "games:write" in scopes:
            permissions += "; create, modify, and cancel games"
        if "games:play" in scopes:
            permissions += "; start, play, and close arena rounds"
        return HTMLResponse(f'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect TinyWorlds</title><style>
body{{margin:0;background:#fff9e9;color:#171717;font:17px system-ui,sans-serif}}
main{{max-width:460px;margin:8vh auto;padding:30px;border:3px solid #171717;background:white;box-shadow:7px 7px #171717}}
h1{{font-size:32px;margin:12px 0}}.brand{{font-weight:800;letter-spacing:.08em}}p{{line-height:1.5}}
label{{display:block;font-weight:650;margin-top:18px}}input{{box-sizing:border-box;width:100%;padding:12px;font:inherit;border:2px solid #171717;margin-top:6px}}
button{{font:inherit;font-weight:700;padding:12px 18px;border:2px solid #171717;cursor:pointer;background:#d5f9ad;margin:24px 12px 0 0}}
button[value=deny]{{background:white}}.error{{color:#a21c16}}small{{display:block;margin-top:22px;line-height:1.5}}
@media(max-width:540px){{main{{margin:24px 16px;padding:22px}}}}</style></head><body><main>
<div class="brand">TINYWORLDS</div><h1>Connect your account</h1>
<p><strong>{escape(record["client_name"])}</strong> is requesting access to your TinyWorlds account.</p>
<p>Permissions: {escape(permissions)}. Game ownership rules still apply.</p>
<p class="error" role="alert">{escape(error)}</p>
<form method="post" action="/connect">
<input type="hidden" name="ticket" value="{escape(ticket)}"><input type="hidden" name="csrf" value="{escape(csrf)}">
<label for="email">Email</label><input id="email" name="email" type="email" autocomplete="username" required maxlength="255">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="1024">
<button name="decision" value="allow">Connect account</button><button name="decision" value="deny" formnovalidate>Cancel</button>
</form><small>Your password is checked by TinyWorlds and is never sent to the MCP client. Paid assets require an explicit budget; new games default to private.</small>
</main></body></html>''')

    async def consent(self, request: Request):
        if request.method == "GET":
            ticket = request.query_params.get("ticket", "")
            record = self.store.get("consent", ticket)
            if not record:
                return HTMLResponse(
                    "Connection request expired. Start account linking again.",
                    status_code=400,
                )
            csrf = secrets.token_urlsafe(32)
            self.store.put("csrf", csrf, {"ticket": ticket}, ttl=600)
            response = self.consent_html(ticket, record, csrf)
            response.set_cookie(
                "tw_plugin_csrf",
                csrf,
                httponly=True,
                secure=not self.config.local,
                samesite="lax",
                max_age=600,
                path="/connect",
            )
            return response
        if request.headers.get("origin") != self.config.public_url:
            return JSONResponse({"error": "Invalid consent origin"}, status_code=403)
        form = await request.form()
        ticket, csrf = str(form.get("ticket", "")), str(form.get("csrf", ""))
        proof = self.store.get("csrf", csrf)
        if (
            not csrf
            or not secrets.compare_digest(
                csrf, request.cookies.get("tw_plugin_csrf", "")
            )
            or not proof
            or proof["ticket"] != ticket
        ):
            return JSONResponse({"error": "Invalid consent request"}, status_code=403)
        record = self.store.get("consent", ticket)
        if not record:
            return JSONResponse({"error": "Consent expired"}, status_code=400)
        params = AuthorizationParams.model_validate(record["params"])
        if form.get("decision") == "deny":
            self.store.get("consent", ticket, consume=True)
            self.store.remove("csrf", csrf)
            return RedirectResponse(
                construct_redirect_uri(
                    str(params.redirect_uri),
                    error="access_denied",
                    state=params.state,
                    iss=self.config.issuer,
                ),
                status_code=303,
            )
        if form.get("decision") != "allow":
            return JSONResponse({"error": "Choose whether to connect"}, status_code=400)
        email, password = str(form.get("email", "")), str(form.get("password", ""))
        if not email or not password or len(email) > 255 or len(password) > 1024:
            return self.consent_html(
                ticket, record, csrf, "Enter your email and password."
            )
        response = await self.backend.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        )
        if response.status_code != 200:
            return self.consent_html(
                ticket,
                record,
                csrf,
                "Sign-in failed. Check your credentials or try again later.",
            )
        pair = response.json()
        # Consume only after a successful login; failed attempts use the backend limiter.
        if not self.store.get("consent", ticket, consume=True):
            return JSONResponse({"error": "Consent already completed"}, status_code=400)
        self.store.remove("csrf", csrf)
        code, grant_id = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        grant = {
            "id": grant_id,
            "client_id": record["client_id"],
            "scopes": params.scopes,
            "subject": pair["user_id"],
            "backend_access": pair["access_token"],
            "backend_refresh": pair["refresh_token"],
            "backend_expires": time.time() + pair["expires_in"],
            "expires": time.time() + 30 * 86400,
        }
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes,
            expires_at=time.time() + 300,
            client_id=record["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.config.resource,
            subject=pair["user_id"],
        )
        self.store.put(
            "code",
            code,
            {"code": auth_code.model_dump(mode="json"), "grant": grant},
            ttl=300,
        )
        result = RedirectResponse(
            construct_redirect_uri(
                str(params.redirect_uri),
                code=code,
                state=params.state,
                iss=self.config.issuer,
            ),
            status_code=303,
        )
        result.delete_cookie("tw_plugin_csrf", path="/connect")
        return result
