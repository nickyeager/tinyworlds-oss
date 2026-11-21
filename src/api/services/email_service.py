"""Email service using Resend for transactional emails."""
import html
import logging
from typing import Optional

import certifi
import httpx

from src.api.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RESEND_API_URL = "https://api.resend.com/emails"


class EmailService:
    """Send transactional emails via the Resend HTTP API."""

    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.frontend_url = settings.FRONTEND_URL

    async def send_invitation_email(
        self,
        email: str,
        accept_url: str,
        inviter_name: Optional[str] = None,
    ) -> bool:
        inviter_line = (
            f"{inviter_name} invited you to TinyWorlds."
            if inviter_name
            else "You've been invited to TinyWorlds."
        )
        subject = "You're invited to TinyWorlds"
        html_content = f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>You're invited to TinyWorlds</title>
</head>
<body style="margin:0;padding:0;background-color:#fef9c3;font-family:'Helvetica Neue',Arial,sans-serif;color:#0a0a0a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#fef9c3;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          <tr>
            <td style="background-color:#facc15;border:2px solid #0a0a0a;box-shadow:4px 4px 0 0 #0a0a0a;width:44px;height:44px;text-align:center;vertical-align:middle;border-radius:6px;">
              <span style="font-size:22px;font-weight:900;color:#0a0a0a;line-height:44px;">T</span>
            </td>
            <td style="padding-left:14px;font-size:28px;font-weight:900;letter-spacing:-0.5px;color:#0a0a0a;">TinyWorlds</td>
          </tr>
        </table>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="max-width:560px;width:100%;background-color:#ffffff;border:2px solid #0a0a0a;border-radius:10px;box-shadow:6px 6px 0 0 #0a0a0a;">
          <tr>
            <td style="padding:32px 28px 8px 28px;">
              <p style="margin:0 0 6px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Invitation</p>
              <h1 style="margin:0 0 16px 0;font-size:30px;font-weight:900;letter-spacing:-0.5px;color:#0a0a0a;">You're In</h1>
              <p style="margin:0 0 12px 0;font-size:15px;font-weight:600;line-height:1.5;color:#171717;">
                {inviter_line}
              </p>
              <p style="margin:0 0 24px 0;font-size:15px;font-weight:600;line-height:1.5;color:#171717;">
                Build playable games from text. Hit the button below to claim your account.
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 28px 28px 28px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background-color:#facc15;border:2px solid #0a0a0a;border-radius:8px;box-shadow:4px 4px 0 0 #0a0a0a;">
                    <a href="{accept_url}"
                       style="display:inline-block;padding:14px 28px;font-size:13px;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">
                      Accept Invite
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 28px 28px 28px;border-top:2px solid #0a0a0a;">
              <p style="margin:18px 0 8px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Or copy this link</p>
              <p style="margin:0;font-size:12px;font-family:'Courier New',monospace;font-weight:700;line-height:1.5;color:#0a0a0a;word-break:break-all;">
                <a href="{accept_url}" style="color:#0a0a0a;text-decoration:underline;">{accept_url}</a>
              </p>
            </td>
          </tr>
        </table>

        <p style="margin:20px 0 0 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">
          TinyWorlds &mdash; Build games with your voice
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_content = (
            "YOU'RE INVITED TO TINYWORLDS\n"
            "============================\n\n"
            f"{inviter_line}\n\n"
            f"Accept your invite:\n{accept_url}\n\n"
            "-- TinyWorlds // Build games with your voice"
        )

        return await self._send_email(email, subject, html_content, text_content)

    async def send_password_reset_email(self, email: str, token: str) -> bool:
        reset_link = f"{self.frontend_url}/reset-password?token={token}"
        subject = "Reset your TinyWorlds password"
        # Neobrutalist palette: solid black 2px borders, hard offset shadow,
        # pop-yellow CTA, monospace uppercase tracking on labels. Inline styles
        # because most email clients strip <style> blocks.
        html_content = f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Reset your TinyWorlds password</title>
</head>
<body style="margin:0;padding:0;background-color:#fef9c3;font-family:'Helvetica Neue',Arial,sans-serif;color:#0a0a0a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#fef9c3;padding:40px 16px;">
    <tr>
      <td align="center">
        <!-- Logo lockup -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          <tr>
            <td style="background-color:#facc15;border:2px solid #0a0a0a;box-shadow:4px 4px 0 0 #0a0a0a;width:44px;height:44px;text-align:center;vertical-align:middle;border-radius:6px;">
              <span style="font-size:22px;font-weight:900;color:#0a0a0a;line-height:44px;">T</span>
            </td>
            <td style="padding-left:14px;font-size:28px;font-weight:900;letter-spacing:-0.5px;color:#0a0a0a;">TinyWorlds</td>
          </tr>
        </table>

        <!-- Card -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="max-width:560px;width:100%;background-color:#ffffff;border:2px solid #0a0a0a;border-radius:10px;box-shadow:6px 6px 0 0 #0a0a0a;">
          <tr>
            <td style="padding:32px 28px 8px 28px;">
              <p style="margin:0 0 6px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Account Recovery</p>
              <h1 style="margin:0 0 16px 0;font-size:30px;font-weight:900;letter-spacing:-0.5px;color:#0a0a0a;">Reset Your Password</h1>
              <p style="margin:0 0 12px 0;font-size:15px;font-weight:600;line-height:1.5;color:#171717;">
                You requested to reset your password for your TinyWorlds account.
              </p>
              <p style="margin:0 0 24px 0;font-size:15px;font-weight:600;line-height:1.5;color:#171717;">
                Hit the button below to set a new one.
              </p>
            </td>
          </tr>

          <!-- CTA button -->
          <tr>
            <td align="center" style="padding:0 28px 28px 28px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background-color:#facc15;border:2px solid #0a0a0a;border-radius:8px;box-shadow:4px 4px 0 0 #0a0a0a;">
                    <a href="{reset_link}"
                       style="display:inline-block;padding:14px 28px;font-size:13px;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">
                      Reset Password
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Fine print -->
          <tr>
            <td style="padding:0 28px 28px 28px;border-top:2px solid #0a0a0a;">
              <p style="margin:18px 0 8px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Heads up</p>
              <p style="margin:0 0 14px 0;font-size:13px;font-weight:500;line-height:1.55;color:#404040;">
                This link will expire in <strong style="color:#0a0a0a;">1 hour</strong>. If you didn&rsquo;t request a reset, you can safely ignore this email.
              </p>
              <p style="margin:0 0 6px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Or copy this link</p>
              <p style="margin:0;font-size:12px;font-family:'Courier New',monospace;font-weight:700;line-height:1.5;color:#0a0a0a;word-break:break-all;">
                <a href="{reset_link}" style="color:#0a0a0a;text-decoration:underline;">{reset_link}</a>
              </p>
            </td>
          </tr>
        </table>

        <!-- Footer -->
        <p style="margin:20px 0 0 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">
          TinyWorlds &mdash; Build games with your voice
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_content = (
            "RESET YOUR PASSWORD\n"
            "===================\n\n"
            "You requested to reset your password for your TinyWorlds account.\n\n"
            f"Open this link to set a new one:\n{reset_link}\n\n"
            "HEADS UP: this link expires in 1 hour. If you didn't request a "
            "reset, you can safely ignore this email.\n\n"
            "-- TinyWorlds // Build games with your voice"
        )

        return await self._send_email(email, subject, html_content, text_content)

    async def send_game_created_email(
        self,
        email: str,
        game_id: str,
        engine: str,
        game_name: Optional[str] = None,
    ) -> bool:
        game_url = f"{self.frontend_url.rstrip('/')}/games/{game_id}"
        title = html.escape(game_name or game_id)
        text_title = game_name or game_id
        engine_label = html.escape(engine)
        subject = "Your TinyWorlds game is ready"
        return await self._send_game_job_email(
            email=email,
            subject=subject,
            label="Game Created",
            heading="Your Game Is Ready",
            body=(
                f"TinyWorlds finished creating <strong>{title}</strong> "
                f"with the {engine_label} engine."
            ),
            action="Play Game",
            game_url=game_url,
            text_content=(
                "YOUR GAME IS READY\n"
                "==================\n\n"
                f"TinyWorlds finished creating {text_title} with the {engine} engine.\n\n"
                f"Play it here:\n{game_url}\n\n"
                "-- TinyWorlds // Build games with your voice"
            ),
        )

    async def send_game_modified_email(
        self,
        email: str,
        game_id: str,
        engine: str,
        game_name: Optional[str] = None,
    ) -> bool:
        game_url = f"{self.frontend_url.rstrip('/')}/games/{game_id}"
        title = html.escape(game_name or game_id)
        text_title = game_name or game_id
        engine_label = html.escape(engine)
        subject = "Your TinyWorlds game was updated"
        return await self._send_game_job_email(
            email=email,
            subject=subject,
            label="Game Modified",
            heading="Your Game Was Updated",
            body=(
                f"TinyWorlds finished modifying <strong>{title}</strong> "
                f"with the {engine_label} engine."
            ),
            action="Open Game",
            game_url=game_url,
            text_content=(
                "YOUR GAME WAS UPDATED\n"
                "=====================\n\n"
                f"TinyWorlds finished modifying {text_title} with the {engine} engine.\n\n"
                f"Open it here:\n{game_url}\n\n"
                "-- TinyWorlds // Build games with your voice"
            ),
        )

    async def _send_game_job_email(
        self,
        *,
        email: str,
        subject: str,
        label: str,
        heading: str,
        body: str,
        action: str,
        game_url: str,
        text_content: str,
    ) -> bool:
        safe_game_url = html.escape(game_url, quote=True)
        html_content = f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#fef9c3;font-family:'Helvetica Neue',Arial,sans-serif;color:#0a0a0a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#fef9c3;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          <tr>
            <td style="background-color:#facc15;border:2px solid #0a0a0a;box-shadow:4px 4px 0 0 #0a0a0a;width:44px;height:44px;text-align:center;vertical-align:middle;border-radius:6px;">
              <span style="font-size:22px;font-weight:900;color:#0a0a0a;line-height:44px;">T</span>
            </td>
            <td style="padding-left:14px;font-size:28px;font-weight:900;color:#0a0a0a;">TinyWorlds</td>
          </tr>
        </table>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="max-width:560px;width:100%;background-color:#ffffff;border:2px solid #0a0a0a;border-radius:10px;box-shadow:6px 6px 0 0 #0a0a0a;">
          <tr>
            <td style="padding:32px 28px 8px 28px;">
              <p style="margin:0 0 6px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">{label}</p>
              <h1 style="margin:0 0 16px 0;font-size:30px;font-weight:900;color:#0a0a0a;">{heading}</h1>
              <p style="margin:0 0 24px 0;font-size:15px;font-weight:600;line-height:1.5;color:#171717;">
                {body}
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:0 28px 28px 28px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background-color:#facc15;border:2px solid #0a0a0a;border-radius:8px;box-shadow:4px 4px 0 0 #0a0a0a;">
                    <a href="{safe_game_url}"
                       style="display:inline-block;padding:14px 28px;font-size:13px;font-weight:900;letter-spacing:0.12em;text-transform:uppercase;color:#0a0a0a;text-decoration:none;">
                      {action}
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 28px 28px 28px;border-top:2px solid #0a0a0a;">
              <p style="margin:18px 0 8px 0;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#525252;">Or copy this link</p>
              <p style="margin:0;font-size:12px;font-family:'Courier New',monospace;font-weight:700;line-height:1.5;color:#0a0a0a;word-break:break-all;">
                <a href="{safe_game_url}" style="color:#0a0a0a;text-decoration:underline;">{safe_game_url}</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
        return await self._send_email(email, subject, html_content, text_content)

    async def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str,
    ) -> bool:
        if not self.api_key:
            logger.warning(f"Email not sent (RESEND_API_KEY not set): {subject} to {to_email}")
            if settings.DEBUG:
                logger.info(f"Would send email to {to_email}:\nSubject: {subject}\n{text_content}")
            return False

        payload = {
            "from": self.from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=certifi.where()) as client:
                response = await client.post(RESEND_API_URL, json=payload, headers=headers)

            if response.status_code in (200, 201, 202):
                logger.info(f"Email sent successfully to {to_email}: {subject}")
                return True

            logger.error(
                f"Resend send failed: {response.status_code} - {response.text}"
            )
            return False

        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {e}")
            return False


email_service = EmailService()
