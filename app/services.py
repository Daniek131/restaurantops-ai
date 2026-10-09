"""Record inventory movements within the caller's transaction."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, update

from app.models import (
    Ingredient,
    Movement,
    Recipe,
    RecipeIngredient,
    Sale,
    SaleLine,
    StockCount,
    utc_now,
)
from app.schemas import SaleInput


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def require(session, model, object_id):
    value = session.get(model, object_id)
    if value is None:
        raise DomainError(f"{model.__name__} {object_id} not found", 404)
    return value


def payload_hash(payload: SaleInput) -> str:
    value = payload.model_dump(mode="json")
    value["lines"] = sorted(value["lines"], key=lambda line: line["recipe_id"])
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def record_sale(session, payload: SaleInput) -> dict:
    fingerprint = payload_hash(payload)
    previous = session.scalar(select(Sale).where(Sale.external_id == payload.external_id))
    if previous:
        if previous.payload_hash != fingerprint:
            raise DomainError("external_id already belongs to a different sale payload")
        return {"sale_id": previous.id, "duplicate": True}

    ids = [line.recipe_id for line in payload.lines]
    recipes = {row.id: row for row in session.scalars(select(Recipe).where(Recipe.id.in_(ids)))}
    if len(recipes) != len(ids):
        raise DomainError("Sale contains an unknown recipe", 404)
    parts = session.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(ids)))
    portions = {line.recipe_id: line.quantity for line in payload.lines}
    usage = defaultdict(lambda: Decimal("0"))
    mapped_recipes = set()
    for part in parts:
        mapped_recipes.add(part.recipe_id)
        usage[part.ingredient_id] += part.quantity * portions[part.recipe_id]
    if mapped_recipes != set(ids):
        raise DomainError("Recipes have no ingredient mapping")

    sale = Sale(
        external_id=payload.external_id, payload_hash=fingerprint, occurred_at=payload.occurred_at
    )
    session.add(sale)
    # I reserve the sale ID before changing stock so retries cannot deplete it twice.
    session.flush()
    for ingredient_id in sorted(usage):
        used = usage[ingredient_id]
        row = session.execute(
            update(Ingredient)
            .where(Ingredient.id == ingredient_id, Ingredient.on_hand >= used)
            .values(on_hand=Ingredient.on_hand - used)
            .returning(Ingredient.unit_cost)
            .execution_options(synchronize_session=False)
        ).first()
        if row is None:
            raise DomainError(f"Insufficient stock for ingredient {ingredient_id}")
        session.add(
            Movement(
                ingredient_id=ingredient_id,
                sale_id=sale.id,
                kind="sale",
                quantity=-used,
                unit_cost=row.unit_cost,
                occurred_at=payload.occurred_at,
            )
        )
    session.add_all(
        [
            SaleLine(
                sale_id=sale.id,
                recipe_id=line.recipe_id,
                quantity=line.quantity,
                unit_price=recipes[line.recipe_id].price,
            )
            for line in payload.lines
        ]
    )
    return {"sale_id": sale.id, "duplicate": False}


def receive_stock(session, ingredient_id, quantity):
    row = session.execute(
        update(Ingredient)
        .where(Ingredient.id == ingredient_id)
        .values(on_hand=Ingredient.on_hand + quantity)
        .returning(Ingredient.on_hand, Ingredient.unit_cost)
        .execution_options(synchronize_session=False)
    ).first()
    if row is None:
        raise DomainError("Ingredient not found", 404)
    session.add(
        Movement(
            ingredient_id=ingredient_id,
            kind="receipt",
            quantity=quantity,
            unit_cost=row.unit_cost,
            occurred_at=utc_now(),
        )
    )
    return {"ingredient_id": ingredient_id, "on_hand": row.on_hand}


def count_stock(session, ingredient_id, counted):
    ingredient = require(session, Ingredient, ingredient_id)
    expected = ingredient.on_hand
    row = session.execute(
        update(Ingredient)
        .where(Ingredient.id == ingredient_id, Ingredient.on_hand == expected)
        .values(on_hand=counted)
        .returning(Ingredient.id)
        .execution_options(synchronize_session=False)
    ).first()
    if row is None:
        raise DomainError("Inventory changed during the count; refresh and recount")
    variance = counted - expected
    session.add(
        StockCount(
            ingredient_id=ingredient_id, expected=expected, counted=counted, variance=variance
        )
    )
    session.add(
        Movement(
            ingredient_id=ingredient_id,
            kind="count",
            quantity=variance,
            unit_cost=ingredient.unit_cost,
            occurred_at=utc_now(),
        )
    )
    return {
        "expected": expected,
        "counted": counted,
        "variance": variance,
        "flagged": abs(variance) > max(Decimal("0.001"), expected * Decimal("0.10")),
    }
