"""APScheduler wrapper: one interval job per enabled source."""
from __future__ import annotations

import logging
import threading
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .scanner.engine import scan_source
from .settings import get_setting

logger = logging.getLogger(__name__)


class ScanScheduler:
    def __init__(self) -> None:
        tz = self._timezone()
        self.scheduler = BackgroundScheduler(
            timezone=tz,
            executors={"default": ThreadPoolExecutor(max_workers=3)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 180},
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _timezone() -> str:
        try:
            return str(get_setting("general", mask=False).get("timezone") or "Asia/Shanghai")
        except Exception:  # noqa: BLE001
            return "Asia/Shanghai"

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.start()
        self._thread = threading.Thread(target=self._maintenance, name="radar-maintenance", daemon=True)
        self._thread.start()
        logger.info("scheduler started (timezone=%s)", self.scheduler.timezone)

    def shutdown(self) -> None:
        self._stop.set()
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler shutdown failed")

    def _maintenance(self) -> None:
        db.run_maintenance()
        while not self._stop.is_set():
            try:
                self.reconcile()
            except Exception:  # noqa: BLE001
                logger.exception("scheduler reconcile failed")
            self._stop.wait(30)

    def reconcile(self) -> None:
        with db.get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, enabled, interval_minutes FROM sources ORDER BY id"
            ).fetchall()]
        wanted = {
            int(r["id"]): max(5, int(r["interval_minutes"] or 60))
            for r in rows if r["enabled"]
        }
        for job in self.scheduler.get_jobs():
            if not job.id.startswith("scan:"):
                continue
            try:
                source_id = int(job.id.split(":", 1)[1])
            except ValueError:
                continue
            if source_id not in wanted:
                self.scheduler.remove_job(job.id)
                logger.info("removed job for disabled source %s", source_id)
                continue
            minutes = wanted.pop(source_id)
            interval = getattr(job.trigger, "interval", None)
            if interval is None or int(interval.total_seconds() // 60) != minutes:
                self.scheduler.reschedule_job(job.id, trigger="interval", minutes=minutes)
                logger.info("rescheduled source %s every %s min", source_id, minutes)
        for source_id, minutes in wanted.items():
            self.scheduler.add_job(
                scan_source,
                trigger="interval",
                minutes=minutes,
                id=f"scan:{source_id}",
                args=[source_id],
                next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
                replace_existing=True,
            )
            logger.info("added job for source %s every %s min", source_id, minutes)

    def scan_now(self, source_id: int) -> bool:
        with db.get_conn() as conn:
            row = conn.execute("SELECT id FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return False
        threading.Thread(target=scan_source, args=(source_id,), daemon=True).start()
        return True

    def scan_all_now(self) -> int:
        with db.get_conn() as conn:
            ids = [int(r[0]) for r in conn.execute("SELECT id FROM sources WHERE enabled=1 ORDER BY id")]
        for source_id in ids:
            threading.Thread(target=scan_source, args=(source_id,), daemon=True).start()
        return len(ids)


scheduler = ScanScheduler()
