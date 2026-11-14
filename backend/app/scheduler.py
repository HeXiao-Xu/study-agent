"""S5-5 复习清单定时生成（独立进程）。

启动：cd backend && python -m app.scheduler
一次：python -m app.scheduler --once
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import setup_logging
from app.models.mastery import Mastery
from app.services import review_service

logger = logging.getLogger(__name__)

LOCK_KEY = 5505


def _try_lock(session) -> bool:
    return bool(
        session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
    )


def _unlock(session) -> None:
    session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})


def generate_daily(
    *, now: datetime | None = None, session_factory=None
) -> dict[str, int]:
    factory = session_factory or get_session_factory()
    users = 0
    items = 0
    failed = 0
    with factory() as lock_session:
        if not _try_lock(lock_session):
            logger.info("review_daily_skipped_locked")
            return {"users": 0, "items": 0, "failed": 0}
        try:
            user_ids = list(
                lock_session.scalars(
                    select(Mastery.user_id).distinct().order_by(Mastery.user_id)
                )
            )
            for user_id in user_ids:
                users += 1
                with factory() as session:
                    try:
                        result = review_service.refresh_user(
                            session, user_id=int(user_id), now=now
                        )
                        session.commit()
                        items += result.item_count
                    except Exception:
                        session.rollback()
                        failed += 1
                        logger.exception(
                            "review_daily_user_failed user_id=%s", user_id
                        )
        finally:
            _unlock(lock_session)
            lock_session.commit()
    return {"users": users, "items": items, "failed": failed}


def main(argv: list[str] | None = None) -> None:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(description="S5-5 复习清单调度器")
    parser.add_argument("--once", action="store_true", help="只生成一次后退出")
    args = parser.parse_args(argv)
    if args.once:
        print(json.dumps(generate_daily(), ensure_ascii=False))
        return
    tz = ZoneInfo(get_settings().review_timezone)
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        generate_daily,
        CronTrigger(hour=0, minute=5, timezone=tz),
        id="review_daily",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("review_scheduler_started timezone=%s", tz)
    scheduler.start()


if __name__ == "__main__":
    main()