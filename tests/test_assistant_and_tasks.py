from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.assistant import answer_question, dispatch_report
from app.models import Ingredient, InventoryCheck, utc_now
from app.services import DomainError
from app.tasks import celery_app, check_inventory, run_daily_report, run_inventory_check


class FakeResponses:
    """Return a report tool call followed by a fixed answer for the adapter tests."""

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = SimpleNamespace(
                type="function_call", name="cost_summary", arguments="{}", call_id="test-call"
            )
            return SimpleNamespace(output=[call], output_text="")
        return SimpleNamespace(output=[], output_text="No sales are recorded.")


def test_assistant_can_read_reports_but_cannot_change_inventory(client, menu):
    fake = FakeResponses()
    with client.app.state.session_factory() as session:
        before = session.get(Ingredient, menu["ingredients"][0]).on_hand
        result = answer_question(
            session,
            "What are our costs?",
            client=SimpleNamespace(responses=fake),
            model="test-model",
        )
        assert result["reports"][0]["tool"] == "cost_summary"
        assert session.get(Ingredient, menu["ingredients"][0]).on_hand == before
        with pytest.raises(DomainError):
            dispatch_report(session, "record_sale", {})
        with pytest.raises(DomainError):
            dispatch_report(session, "cost_summary", {"sql": "DELETE FROM ingredients"})
    assert fake.calls[0]["tool_choice"] == "required"
    assert fake.calls[1]["input"][-1]["type"] == "function_call_output"


def test_missing_live_model_configuration_is_clear(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert client.post("/assistant", json={"question": "Show inventory"}).status_code == 503


def test_inventory_check_is_saved_once_per_hour(client, menu):
    factory = client.app.state.session_factory
    client.post(f"/inventory/{menu['ingredients'][0]}/counts", json={"counted": "1"})
    now = utc_now()
    assert run_inventory_check(factory, now)["new_records"] == 1
    assert run_inventory_check(factory, now)["new_records"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(InventoryCheck)) == 1


def test_celery_task_body_eagerly_without_a_broker(client, menu, monkeypatch):
    # Run eagerly to test the task body without starting Redis or a worker.
    monkeypatch.setattr(
        "app.tasks.make_database",
        lambda: (
            client.app.state.engine,
            client.app.state.session_factory,
        ),
    )
    result = check_inventory.apply(throw=True)
    assert result.successful()
    assert result.result["low_stock_items"] == 0
    assert celery_app.conf.beat_schedule["hourly-inventory-check"]["task"] == (
        "app.tasks.check_inventory"
    )


def test_daily_report_is_reproducible_and_saved_once(client, menu):
    factory = client.app.state.session_factory
    now = utc_now()
    assert run_daily_report(factory, now)["duplicate"] is False
    assert run_daily_report(factory, now)["duplicate"] is True
    rows = client.get("/reports/daily").json()
    assert len(rows) == 1
    assert rows[0]["content"]["costs_last_30_days"]["cogs"] == "0.00"
    assert rows[0]["content"]["forecast"][0]["days_with_sales"] == 0
