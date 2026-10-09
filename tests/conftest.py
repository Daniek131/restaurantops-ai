import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app("sqlite:///:memory:", api_token="")) as connection:
        yield connection


@pytest.fixture
def menu(client):
    vendor = client.post("/vendors", json={"name": "Test supplier"}).json()["id"]
    ids = []
    for name, stock, cost in [("Flour", "10", "2"), ("Cheese", "5", "8")]:
        response = client.post(
            "/inventory",
            json={
                "name": name,
                "unit": "kg",
                "on_hand": stock,
                "par_level": "2",
                "target_level": "10",
                "unit_cost": cost,
                "vendor_id": vendor,
            },
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    response = client.post(
        "/recipes",
        json={
            "name": "Flatbread",
            "price": "12",
            "ingredients": [
                {"ingredient_id": ids[0], "quantity": "0.25"},
                {"ingredient_id": ids[1], "quantity": "0.10"},
            ],
        },
    )
    assert response.status_code == 201
    return {"recipe_id": response.json()["recipe_id"], "ingredients": ids}
