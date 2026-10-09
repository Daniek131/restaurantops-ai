"""Seed synthetic sales and ingredients in an empty database."""

import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app import analytics
from app.db import initialize, make_database
from app.models import Ingredient, Movement, Recipe, RecipeIngredient, Vendor, utc_now
from app.schemas import SaleInput
from app.services import record_sale


def seed_demo(factory):
    with factory.begin() as session:
        if session.scalar(select(Ingredient.id).limit(1)) is not None:
            raise ValueError("Demo seed needs an empty inventory; use a separate database")
        vendor = Vendor(name="Synthetic Demo Supplier")
        session.add(vendor)
        session.flush()
        flour = Ingredient(
            name="Flour",
            unit="kg",
            on_hand=Decimal("150"),
            par_level=Decimal("10"),
            target_level=Decimal("30"),
            unit_cost=Decimal("2"),
            vendor_id=vendor.id,
        )
        cheese = Ingredient(
            name="Cheese",
            unit="kg",
            on_hand=Decimal("80"),
            par_level=Decimal("10"),
            target_level=Decimal("20"),
            unit_cost=Decimal("8"),
            vendor_id=vendor.id,
        )
        recipe = Recipe(name="Demo flatbread", price=Decimal("12"))
        session.add_all([flour, cheese, recipe])
        session.flush()
        session.add_all(
            [
                RecipeIngredient(
                    recipe_id=recipe.id, ingredient_id=flour.id, quantity=Decimal("0.25")
                ),
                RecipeIngredient(
                    recipe_id=recipe.id, ingredient_id=cheese.id, quantity=Decimal("0.10")
                ),
            ]
        )
        session.flush()
        now = utc_now().replace(hour=12, minute=0, second=0, microsecond=0)
        session.add_all(
            [
                Movement(
                    ingredient_id=item.id,
                    kind="opening",
                    quantity=item.on_hand,
                    unit_cost=item.unit_cost,
                    occurred_at=now - timedelta(days=29),
                )
                for item in [flour, cheese]
            ]
        )
        for days_ago in range(28, 0, -1):
            quantity = 8 + days_ago % 7
            record_sale(
                session,
                SaleInput(
                    external_id=f"synthetic-day-{days_ago}",
                    occurred_at=now - timedelta(days=days_ago),
                    lines=[{"recipe_id": recipe.id, "quantity": quantity}],
                ),
            )


if __name__ == "__main__":
    engine, factory = make_database()
    initialize(engine)
    seed_demo(factory)
    with factory() as session:
        print(
            json.dumps(
                {
                    "data_origin": "synthetic demo, not restaurant records",
                    "costs": analytics.cost_summary(session),
                    "forecast": analytics.forecast(session),
                    "evaluation": analytics.evaluate_forecast(session),
                },
                default=str,
                indent=2,
            )
        )
    engine.dispose()
