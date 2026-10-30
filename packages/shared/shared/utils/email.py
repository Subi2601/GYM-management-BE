from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str


# â”€â”€ Brand constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_BRAND   = "STAG FITNESS"
_PRIMARY = "#1D4ED8"   # blue-700
_BG      = "#F8FAFC"   # slate-50  (email background)
_CARD_BG = "#FFFFFF"
_TEXT    = "#1F2937"   # gray-800
_MUTED   = "#6B7280"   # gray-500
_BORDER  = "#E5E7EB"   # gray-200
_SUCCESS = "#059669"   # emerald-600
_DANGER  = "#DC2626"   # red-600


def _base_template(title: str, body: str) -> str:
    """Wraps body HTML in the TESS branded email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{_BG};padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">

          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:24px;">
              <span style="font-size:26px;font-weight:800;color:{_PRIMARY};letter-spacing:-0.5px;">
                {_BRAND}
              </span>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td style="background-color:{_CARD_BG};border-radius:12px;border:1px solid {_BORDER};padding:40px 36px;">
              {body}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding-top:24px;">
              <p style="margin:0;font-size:12px;color:{_MUTED};">
                &copy; 2026 {_BRAND}. All rights reserved.
              </p>
              <p style="margin:6px 0 0;font-size:12px;color:{_MUTED};">
                If you did not expect this email, you can safely ignore it.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _heading(text: str) -> str:
    return f'<h2 style="margin:0 0 16px;font-size:22px;font-weight:700;color:{_TEXT};">{text}</h2>'


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:{_TEXT};">{text}</p>'


def _muted(text: str) -> str:
    return f'<p style="margin:16px 0 0;font-size:13px;color:{_MUTED};">{text}</p>'


def _divider() -> str:
    return f'<hr style="border:none;border-top:1px solid {_BORDER};margin:24px 0;" />'


def _otp_box(otp: str) -> str:
    return (
        f'<div style="margin:24px 0;text-align:center;">'
        f'<span style="display:inline-block;padding:14px 32px;background-color:{_BG};'
        f'border:1px solid {_BORDER};border-radius:8px;font-size:28px;font-weight:700;'
        f'letter-spacing:8px;color:{_TEXT};">{otp}</span></div>'
    )


class EmailSender:
    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    async def send(self, to: str, subject: str, html_body: str, text_body: str = "") -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self._config.from_email
        msg["To"]      = to

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # SMTP TLS cert verification. Disabled ONLY when SMTP_VALIDATE_CERTS is explicitly
        # false (e.g. dev behind a TLS-inspecting corporate proxy whose root CA the
        # host doesn't trust). Defaults to ON so production stays strict.
        validate_certs = os.getenv("SMTP_VALIDATE_CERTS", "true").strip().lower() not in ("false", "0", "no", "off")
        try:
            await aiosmtplib.send(
                msg,
                hostname=self._config.host,
                port=self._config.port,
                username=self._config.username,
                password=self._config.password,
                use_tls=False,
                start_tls=True,
                validate_certs=validate_certs,
            )
        except Exception:
            logger.exception("Failed to send email to %s", to[:3] + "***@" + to.split("@")[-1])
            raise

    # â”€â”€ OTP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def send_otp(self, to: str, otp: str, purpose: str) -> None:
        body = (
            _heading("Verification Code")
            + _paragraph(f"Use the code below to complete your <strong>{purpose}</strong>.")
            + _otp_box(otp)
            + _divider()
            + _muted("This code expires in <strong>10 minutes</strong> and can only be used once.")
            + _muted("If you did not request this code, please ignore this email.")
        )
        await self.send(
            to=to,
            subject=f"Your {_BRAND} verification code",
            html_body=_base_template("Verification Code", body),
        )
