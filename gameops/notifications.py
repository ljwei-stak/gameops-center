"""Notification integrations for alerts and releases."""

from __future__ import annotations

from email.message import EmailMessage
import json
import os
import smtplib
from typing import Any
from urllib import request


class NotificationDispatcher:
    """Send messages to Webhook, WeCom, DingTalk, or email.

    All channels are configured with environment variables so the project stays
    safe to run locally.  Missing configuration simply becomes a skipped channel
    and is reflected in the returned delivery report.
    """

    def __init__(self) -> None:
        self.webhook_url = os.environ.get("GAMEOPS_WEBHOOK_URL", "")
        self.wecom_url = os.environ.get("GAMEOPS_WECOM_WEBHOOK", "")
        self.dingtalk_url = os.environ.get("GAMEOPS_DINGTALK_WEBHOOK", "")
        self.smtp_host = os.environ.get("GAMEOPS_SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("GAMEOPS_SMTP_PORT", "25"))
        self.smtp_user = os.environ.get("GAMEOPS_SMTP_USER", "")
        self.smtp_password = os.environ.get("GAMEOPS_SMTP_PASSWORD", "")
        self.mail_from = os.environ.get("GAMEOPS_MAIL_FROM", self.smtp_user)
        self.mail_to = [
            item.strip()
            for item in os.environ.get("GAMEOPS_MAIL_TO", "").split(",")
            if item.strip()
        ]

    def notify_event(self, title: str, body: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = payload or {}
        results = []
        for name, url, message in [
            ("webhook", self.webhook_url, {"title": title, "body": body, "payload": payload}),
            ("wecom", self.wecom_url, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}),
            ("dingtalk", self.dingtalk_url, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}),
        ]:
            if url:
                results.append(self._post_json(name, url, message))
            else:
                results.append({"channel": name, "ok": False, "skipped": True, "reason": "not configured"})
        results.append(self._send_mail(title, body))
        return results

    def _post_json(self, channel: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with request.urlopen(req, timeout=8) as response:
                return {
                    "channel": channel,
                    "ok": 200 <= response.status < 300,
                    "status": response.status,
                }
        except Exception as exc:  # pragma: no cover - network environment dependent
            return {"channel": channel, "ok": False, "error": str(exc)}

    def _send_mail(self, title: str, body: str) -> dict[str, Any]:
        if not self.smtp_host or not self.mail_from or not self.mail_to:
            return {"channel": "mail", "ok": False, "skipped": True, "reason": "not configured"}
        message = EmailMessage()
        message["From"] = self.mail_from
        message["To"] = ", ".join(self.mail_to)
        message["Subject"] = title
        message.set_content(body)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=8) as smtp:
                if self.smtp_user and self.smtp_password:
                    smtp.starttls()
                    smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(message)
            return {"channel": "mail", "ok": True}
        except Exception as exc:  # pragma: no cover - network environment dependent
            return {"channel": "mail", "ok": False, "error": str(exc)}

