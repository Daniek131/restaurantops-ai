from datetime import timedelta
from decimal import Decimal

from app.analytics import anomalies, evaluate_forecast, forecast
from app.models import Movement, utc_now


def add_daily_usage(factory, ingredient_id, quantities, now):
    with factory.begin() as session:
        for days_ago, quantity in enumerate(reversed(quantities), start=1):
            session.add(
                Movement(
                    ingredient_id=ingredient_id,
                    kind="sale",
                    quantity=-Decimal(str(quantity)),
                    unit_cost=Decimal("2"),
                    occurred_at=now - timedelta(days=days_ago),
                )
            )


def test_forecast_uses_complete_days_and_includes_zero_sale_days(client, menu):
    now = utc_now().replace(hour=12)
    factory = client.app.state.session_factory
    add_daily_usage(factory, menu["ingredients"][0], [0, 2, 0, 2], now)
    with factory() as session:
        result = forecast(session, horizon=7, window=4, now=now)[0]
    assert result["predicted_usage"] == Decimal("7.000")
    assert result["days_with_sales"] == 2
    assert result["average_daily_usage"] == 1


def test_evaluation_has_no_future_leakage_and_usage_spike_is_flagged(client, menu):
    now = utc_now().replace(hour=12)
    factory = client.app.state.session_factory
    add_daily_usage(factory, menu["ingredients"][0], [2] * 27 + [30], now)
    with factory() as session:
        evaluation = evaluate_forecast(session, now=now)[0]
        flags = anomalies(session, now=now)
    assert evaluation["mean_baseline_mae"] == 4.0
    assert evaluation["last_day_baseline_mae"] == 4.0
    assert flags["usage_spikes"][0]["latest_usage"] == 30


def test_empty_history_returns_explicit_zero_baseline(client, menu):
    result = client.get("/reports/forecast").json()[0]
    assert result["days_with_sales"] == 0
    assert Decimal(str(result["predicted_usage"])) == 0
