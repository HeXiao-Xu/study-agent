"""S3-7 用量统计：llm_call_logs 按 UTC 日 × scene × model 聚合。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.llm_call_log import LLMCallLog
from app.schemas.usage import UsageItem, UsageReport, UsageTotals

RANGE_DAYS = {"1d": 1, "7d": 7, "30d": 30}


def get_usage(
    session: Session,
    *,
    range_key: str,
    today: date | None = None,
) -> UsageReport:
    days = RANGE_DAYS.get(range_key)
    if days is None:
        raise ValueError(f"非法 range：{range_key}")
    end_date = today or datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)
    start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)

    day = func.date(LLMCallLog.created_at).label("day")
    failed = func.coalesce(
        func.sum(case((LLMCallLog.status == "failed", 1), else_=0)),
        0,
    ).label("failed_calls")
    statement = (
        select(
            day,
            LLMCallLog.scene.label("scene"),
            LLMCallLog.model.label("model"),
            func.count().label("calls"),
            failed,
            func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0).label(
                "prompt_tokens"
            ),
            func.coalesce(func.sum(LLMCallLog.completion_tokens), 0).label(
                "completion_tokens"
            ),
            (
                func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0)
                + func.coalesce(func.sum(LLMCallLog.completion_tokens), 0)
            ).label("total_tokens"),
            func.coalesce(func.sum(LLMCallLog.cost), 0).label("cost"),
            func.coalesce(func.sum(LLMCallLog.latency_ms), 0).label("latency"),
        )
        .where(LLMCallLog.created_at >= start_at)
        .group_by(day, LLMCallLog.scene, LLMCallLog.model)
        .order_by(day.asc(), LLMCallLog.scene.asc(), LLMCallLog.model.asc())
    )
    items: list[UsageItem] = []
    total_latency = 0
    for row in session.execute(statement).all():
        (
            day_value,
            scene,
            model,
            raw_calls,
            raw_failed,
            raw_prompt,
            raw_completion,
            raw_total,
            raw_cost,
            raw_latency,
        ) = row
        calls = int(raw_calls)
        latency = int(raw_latency or 0)
        total_latency += latency
        items.append(
            UsageItem(
                date=day_value,
                scene=scene,
                model=model,
                calls=calls,
                failed_calls=int(raw_failed or 0),
                prompt_tokens=int(raw_prompt or 0),
                completion_tokens=int(raw_completion or 0),
                total_tokens=int(raw_total or 0),
                cost_yuan=float(raw_cost or 0),
                avg_latency_ms=round(latency / calls, 2) if calls else 0.0,
            )
        )

    calls = sum(item.calls for item in items)
    total_cost = sum((Decimal(str(item.cost_yuan)) for item in items), Decimal("0"))
    return UsageReport(
        range=range_key,
        start_date=start_date,
        end_date=end_date,
        totals=UsageTotals(
            calls=calls,
            failed_calls=sum(item.failed_calls for item in items),
            prompt_tokens=sum(item.prompt_tokens for item in items),
            completion_tokens=sum(item.completion_tokens for item in items),
            total_tokens=sum(item.total_tokens for item in items),
            cost_yuan=float(total_cost),
            avg_latency_ms=round(total_latency / calls, 2) if calls else 0.0,
        ),
        items=items,
    )