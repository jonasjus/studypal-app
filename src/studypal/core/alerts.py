"""Sending the deadline alerts that are due. Used by `study notify` and by the TUI while it's open;
both record what they send in the same table, so an alert never arrives twice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from . import notifier
from .config import Config
from .logic.notify import Alert, pending_alerts
from .storage import Store


@dataclass(frozen=True)
class SendResult:
    sent: list[Alert]
    failed: list[Alert]


def due_alerts(store: Store, cfg: Config, now: datetime) -> list[Alert]:
    codes = {c.id: c.code for c in store.list_courses()}
    return pending_alerts(store.list_deadlines(active_only=True), now, cfg.thresholds, cfg.morning_time,
                          store.sent_keys(), codes)


def send_due(store: Store, cfg: Config, now: datetime | None = None,
             send: Callable[[str, str], bool] = notifier.send) -> SendResult:
    """Show every alert that's due. Only alerts that were actually shown are recorded as sent."""
    now = now or datetime.now()
    sent, failed = [], []
    for alert in due_alerts(store, cfg, now):
        if send(alert.title, alert.body):
            store.mark_sent(alert.deadline.id, list(alert.covers), alert.deadline.due_at, now)
            sent.append(alert)
        else:
            failed.append(alert)
    return SendResult(sent, failed)
