"""SQL aggregates for costs; Pandas/NumPy for simple demand baselines."""

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from app.models import Ingredient, Movement, Sale, SaleLine, StockCount, Vendor, utc_now


def low_stock(session):
    rows = session.execute(
        select(Ingredient, Vendor.name)
        .outerjoin(Vendor)
        .where(Ingredient.on_hand <= Ingredient.par_level)
        .order_by(Ingredient.id)
    )
    return [
        {
            "ingredient_id": item.id,
            "name": item.name,
            "unit": item.unit,
            "on_hand": item.on_hand,
            "par_level": item.par_level,
            "vendor": vendor,
            "reorder_quantity": item.target_level - item.on_hand,
        }
        for item, vendor in rows
    ]


def cost_summary(session, days=30, now=None):
    now = now or utc_now()
    since = now - timedelta(days=days)
    revenue = session.scalar(
        select(func.sum(SaleLine.quantity * SaleLine.unit_price))
        .join(Sale)
        .where(Sale.occurred_at >= since, Sale.occurred_at <= now)
    ) or Decimal("0")
    cogs = session.scalar(
        select(func.sum(-Movement.quantity * Movement.unit_cost)).where(
            Movement.kind == "sale", Movement.occurred_at >= since, Movement.occurred_at <= now
        )
    ) or Decimal("0")
    return {
        "days": days,
        "revenue": revenue.quantize(Decimal("0.01")),
        "cogs": cogs.quantize(Decimal("0.01")),
        "gross_profit": (revenue - cogs).quantize(Decimal("0.01")),
    }


def daily_usage(session, days=28, now=None):
    now = now or utc_now()
    end = pd.Timestamp(now).normalize() - pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=days - 1)
    rows = session.execute(
        select(Movement.ingredient_id, Movement.occurred_at, Movement.quantity).where(
            Movement.kind == "sale",
            Movement.occurred_at >= start.to_pydatetime(),
            Movement.occurred_at < (end + pd.Timedelta(days=1)).to_pydatetime(),
        )
    ).all()
    items = session.scalars(select(Ingredient).order_by(Ingredient.id)).all()
    dates = pd.date_range(start, end, freq="D")
    frame = pd.DataFrame(rows, columns=["ingredient_id", "occurred_at", "quantity"])
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["occurred_at"], utc=True).dt.normalize()
        frame["used"] = -frame["quantity"].astype(float)
        grouped = frame.groupby(["ingredient_id", "date"])["used"].sum()
    result = []
    for item in items:
        if frame.empty or item.id not in grouped.index.get_level_values(0):
            values = pd.Series(0.0, index=dates)
        else:
            values = grouped.loc[item.id].reindex(dates, fill_value=0.0)
        result.append((item, values))
    return result


def forecast(session, horizon=7, window=14, now=None):
    result = []
    for item, usage in daily_usage(session, days=window, now=now):
        average = float(usage.mean())
        demand = Decimal(str(average * horizon)).quantize(Decimal("0.001"))
        # Hold at least the configured target or horizon demand, whichever is larger.
        reorder = max(Decimal("0"), max(item.target_level, demand) - item.on_hand)
        result.append(
            {
                "ingredient_id": item.id,
                "name": item.name,
                "unit": item.unit,
                "method": "trailing_calendar_day_mean",
                "window_days": window,
                "horizon_days": horizon,
                "average_daily_usage": round(average, 3),
                "predicted_usage": demand,
                "reorder_quantity": reorder,
                "days_with_sales": int((usage > 0).sum()),
            }
        )
    return result


def evaluate_forecast(session, now=None):
    """Walk forward: predict each of the last 7 days using only preceding days."""
    results = []
    for item, usage in daily_usage(session, days=28, now=now):
        observed = usage.to_numpy()
        predictions = np.array([observed[i - 14 : i].mean() for i in range(21, 28)])
        naive = observed[20:27]
        actual = observed[21:28]
        results.append(
            {
                "ingredient_id": item.id,
                "name": item.name,
                "test_days": 7,
                "mean_baseline_mae": round(float(np.mean(np.abs(actual - predictions))), 3),
                "last_day_baseline_mae": round(float(np.mean(np.abs(actual - naive))), 3),
            }
        )
    return results


def anomalies(session, now=None):
    result = []
    for item, usage in daily_usage(session, days=15, now=now):
        previous = usage.iloc[:-1].to_numpy()
        latest = float(usage.iloc[-1])
        mean, std = float(np.mean(previous)), float(np.std(previous))
        flagged = latest > mean + 3 * std and latest > 0
        if flagged:
            result.append(
                {
                    "ingredient_id": item.id,
                    "name": item.name,
                    "latest_usage": latest,
                    "baseline_mean": round(mean, 3),
                    "rule": "above_previous_14_day_mean_plus_3_std",
                }
            )
    counts = session.scalars(select(StockCount).order_by(StockCount.id.desc()).limit(100))
    count_flags = [
        {"count_id": row.id, "ingredient_id": row.ingredient_id, "variance": row.variance}
        for row in counts
        if abs(row.variance) > max(Decimal("0.001"), row.expected * Decimal("0.10"))
    ]
    return {"usage_spikes": result, "stock_count_variances": count_flags}
