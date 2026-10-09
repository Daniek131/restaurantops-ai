import json
import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import select

from app.analytics import anomalies, cost_summary, forecast, low_stock
from app.db import make_database
from app.models import DailyReport, InventoryCheck, utc_now

celery_app = Celery("restaurantops", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_ignore_result=True,
    beat_schedule={
        "hourly-inventory-check": {
            "task": "app.tasks.check_inventory",
            "schedule": crontab(minute=0),
        },
        "daily-analytics-report": {
            "task": "app.tasks.prepare_daily_report",
            "schedule": crontab(hour=0, minute=5),
        },
    },
)


def run_inventory_check(factory, now=None):
    hour = (now or utc_now()).replace(minute=0, second=0, microsecond=0)
    with factory.begin() as session:
        rows = low_stock(session)
        saved = 0
        for row in rows:
            existing = session.scalar(
                select(InventoryCheck.id).where(
                    InventoryCheck.hour == hour,
                    InventoryCheck.ingredient_id == row["ingredient_id"],
                )
            )
            if existing is None:
                session.add(
                    InventoryCheck(
                        hour=hour,
                        ingredient_id=row["ingredient_id"],
                        on_hand=row["on_hand"],
                        reorder_quantity=row["reorder_quantity"],
                    )
                )
                saved += 1
    return {"hour": hour.isoformat(), "low_stock_items": len(rows), "new_records": saved}


@celery_app.task(name="app.tasks.check_inventory")
def check_inventory():
    engine, factory = make_database()
    try:
        return run_inventory_check(factory)
    finally:
        engine.dispose()


def run_daily_report(factory, now=None):
    cutoff = (now or utc_now()).replace(hour=0, minute=0, second=0, microsecond=0)
    day = (cutoff - timedelta(days=1)).date()
    with factory.begin() as session:
        if session.get(DailyReport, day) is not None:
            return {"day": day.isoformat(), "duplicate": True}
        report = {
            "cutoff_utc": cutoff.isoformat(),
            "costs_last_30_days": cost_summary(session, now=cutoff),
            "forecast": forecast(session, now=cutoff),
            "anomalies": anomalies(session, now=cutoff),
        }
        # Keep monetary decimals exact in stored JSON.
        content = json.loads(json.dumps(report, default=str))
        session.add(DailyReport(day=day, content=content))
    return {"day": day.isoformat(), "duplicate": False}


@celery_app.task(name="app.tasks.prepare_daily_report")
def prepare_daily_report():
    engine, factory = make_database()
    try:
        return run_daily_report(factory)
    finally:
        engine.dispose()
