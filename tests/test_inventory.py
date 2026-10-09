from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import Movement, Sale, utc_now


def sale_payload(menu, quantity=2, external_id="test-sale"):
    return {
        "external_id": external_id,
        "occurred_at": utc_now().isoformat(),
        "lines": [{"recipe_id": menu["recipe_id"], "quantity": quantity}],
    }


def test_sale_depletes_and_retry_does_not_double_count(client, menu):
    payload = sale_payload(menu)
    assert client.post("/sales", json=payload).json()["duplicate"] is False
    assert client.post("/sales", json=payload).json()["duplicate"] is True
    stock = client.get("/inventory").json()
    assert Decimal(str(stock[0]["on_hand"])) == Decimal("9.5")
    assert Decimal(str(stock[1]["on_hand"])) == Decimal("4.8")
    costs = client.get("/reports/costs").json()
    assert Decimal(str(costs["revenue"])) == Decimal("24")
    assert Decimal(str(costs["cogs"])) == Decimal("2.60")


def test_id_reuse_with_changed_payload_is_conflict(client, menu):
    payload = sale_payload(menu)
    client.post("/sales", json=payload)
    payload["lines"][0]["quantity"] = 3
    assert client.post("/sales", json=payload).status_code == 409
    assert Decimal(str(client.get("/inventory").json()[0]["on_hand"])) == Decimal("9.5")


def test_stock_shortage_rolls_back_every_ingredient_and_sale(client, menu):
    cheese = menu["ingredients"][1]
    client.post(f"/inventory/{cheese}/counts", json={"counted": "0.1"})
    assert client.post("/sales", json=sale_payload(menu, quantity=2)).status_code == 409
    stock = client.get("/inventory").json()
    assert Decimal(str(stock[0]["on_hand"])) == Decimal("10")
    assert Decimal(str(stock[1]["on_hand"])) == Decimal("0.1")
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Sale)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(Movement).where(Movement.kind == "sale")
            )
            == 0
        )


def test_cogs_keeps_historical_unit_cost(client, menu):
    client.post("/sales", json=sale_payload(menu))
    flour = menu["ingredients"][0]
    assert client.put(f"/inventory/{flour}/unit-cost", json={"unit_cost": "100"}).status_code == 200
    assert Decimal(str(client.get("/reports/costs").json()["cogs"])) == Decimal("2.60")


def test_counts_receipts_and_reorder_recommendation(client, menu):
    flour = menu["ingredients"][0]
    result = client.post(f"/inventory/{flour}/counts", json={"counted": "1"}).json()
    assert result["flagged"] is True
    assert Decimal(str(result["variance"])) == Decimal("-9")
    low = client.get("/reports/low-stock").json()
    assert low[0]["vendor"] == "Test supplier"
    assert Decimal(str(low[0]["reorder_quantity"])) == Decimal("9")
    client.post(f"/inventory/{flour}/receipts", json={"quantity": "2"})
    assert client.get("/reports/low-stock").json() == []
    assert client.get("/reports/anomalies").json()["stock_count_variances"]


@pytest.mark.parametrize(
    "change",
    [
        {"lines": [{"recipe_id": 1, "quantity": 0}]},
        {"lines": [{"recipe_id": 1, "quantity": -1}]},
        {"occurred_at": "2026-01-01T12:00:00"},
        {"occurred_at": (utc_now() + timedelta(days=1)).isoformat()},
        {"lines": [{"recipe_id": 1, "quantity": 1}, {"recipe_id": 1, "quantity": 1}]},
        {"unexpected": "field"},
    ],
)
def test_invalid_sale_rejected(client, menu, change):
    payload = sale_payload(menu)
    payload.update(change)
    assert client.post("/sales", json=payload).status_code == 422


def test_unknown_reference_and_duplicate_name_do_not_create_bad_rows(client, menu):
    payload = sale_payload(menu)
    payload["lines"][0]["recipe_id"] = 999
    assert client.post("/sales", json=payload).status_code == 404
    assert client.post("/vendors", json={"name": "Test supplier"}).status_code == 409
    assert len(client.get("/vendors").json()) == 1


def test_shared_ingredient_usage_is_added_across_recipes(client, menu):
    recipe = client.post(
        "/recipes",
        json={
            "name": "Bread",
            "price": "4",
            "ingredients": [
                {"ingredient_id": menu["ingredients"][0], "quantity": "0.5"},
            ],
        },
    ).json()["recipe_id"]
    value = sale_payload(menu, quantity=2)
    value["lines"].append({"recipe_id": recipe, "quantity": 3})
    assert client.post("/sales", json=value).status_code == 200
    flour = client.get("/inventory").json()[0]
    assert Decimal(str(flour["on_hand"])) == Decimal("8.0")


def test_api_token_blocks_mutation():
    with TestClient(create_app("sqlite:///:memory:", api_token="test-only-token")) as client:
        assert client.post("/vendors", json={"name": "Blocked"}).status_code == 401
        assert (
            client.post(
                "/vendors", json={"name": "Allowed"}, headers={"X-API-Key": "test-only-token"}
            ).status_code
            == 201
        )
