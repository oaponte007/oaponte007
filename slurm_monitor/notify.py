"""Optional outbound notification when the agent force-drains a node or
flags one for manual review. Off by default; configure a webhook_url to
enable. Kept dependency-free (urllib) since this is the one place the
agent talks to the outside world."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional

log = logging.getLogger("slurm_monitor.notify")


class Notifier:
    def __init__(self, webhook_url: Optional[str], timeout: int = 5):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def notify(self, title: str, body: str) -> None:
        log.info("%s\n%s", title, body)
        if not self.webhook_url:
            return
        payload = json.dumps({"text": f"*{title}*\n```{body}```"}).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=self.timeout)
        except Exception as exc:  # pragma: no cover - best-effort notification
            log.warning("failed to send notification: %s", exc)
