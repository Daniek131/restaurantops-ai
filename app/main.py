import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from openai import APIError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import analytics
from app.assistant import answer_question
from app.db import initialize, make_database
from app.models import (
    DailyReport,
    Ingredient,
    InventoryCheck,
    Movement,
    Recipe,
    RecipeIngredient,
    Vendor,
    utc_now,
)
from app.schemas import (
    CostInput,
    CountInput,
    IngredientInput,
    QuestionInput,
    ReceiptInput,
    RecipeInput,
    SaleInput,
    VendorInput,
)
from app.services import DomainError, count_stock, receive_stock, record_sale, require


def item_dict(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


def create_app(database_url=None, api_token=None):
    engine, factory = make_database(database_url)
    token = api_token if api_token is not None else os.getenv("API_TOKEN")

    def authorize(x_api_key: str | None = Header(default=None)):
        if token and not secrets.compare_digest(x_api_key or "", token):
            raise HTTPException(401, "Invalid API key")

    @asynccontextmanager
    async def lifespan(app):
        initialize(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="RestaurantOps", version="0.1.0", lifespan=lifespan, dependencies=[Depends(authorize)]
    )
    app.state.session_factory = factory
    app.state.engine = engine

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.message})

    @app.exception_handler(IntegrityError)
    async def constraint_error(request: Request, error: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Database constraint conflict. Check duplicates and references; "
                "retry if racing."
            },
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/vendors", status_code=201)
    def add_vendor(payload: VendorInput):
        with factory.begin() as session:
            vendor = Vendor(**payload.model_dump())
            session.add(vendor)
            session.flush()
            return item_dict(vendor)

    @app.get("/vendors")
    def vendors():
        with factory() as session:
            return [item_dict(item) for item in session.scalars(select(Vendor).order_by(Vendor.id))]

    @app.post("/inventory", status_code=201)
    def add_ingredient(payload: IngredientInput):
        with factory.begin() as session:
            if payload.vendor_id:
                require(session, Vendor, payload.vendor_id)
            item = Ingredient(**payload.model_dump())
            session.add(item)
            session.flush()
            session.add(
                Movement(
                    ingredient_id=item.id,
                    kind="opening",
                    quantity=item.on_hand,
                    unit_cost=item.unit_cost,
                    occurred_at=utc_now(),
                )
            )
            return item_dict(item)

    @app.get("/inventory")
    def inventory():
        with factory() as session:
            return [
                item_dict(item)
                for item in session.scalars(select(Ingredient).order_by(Ingredient.id))
            ]

    @app.post("/inventory/{ingredient_id}/receipts")
    def receipt(ingredient_id: int, payload: ReceiptInput):
        with factory.begin() as session:
            return receive_stock(session, ingredient_id, payload.quantity)

    @app.post("/inventory/{ingredient_id}/counts")
    def count(ingredient_id: int, payload: CountInput):
        with factory.begin() as session:
            return count_stock(session, ingredient_id, payload.counted)

    @app.put("/inventory/{ingredient_id}/unit-cost")
    def set_cost(ingredient_id: int, payload: CostInput):
        with factory.begin() as session:
            item = require(session, Ingredient, ingredient_id)
            item.unit_cost = payload.unit_cost
            return {"ingredient_id": ingredient_id, "unit_cost": item.unit_cost}

    @app.post("/recipes", status_code=201)
    def add_recipe(payload: RecipeInput):
        with factory.begin() as session:
            ids = {part.ingredient_id for part in payload.ingredients}
            found = set(session.scalars(select(Ingredient.id).where(Ingredient.id.in_(ids))))
            if found != ids:
                raise DomainError("Recipe contains an unknown ingredient", 404)
            recipe = Recipe(name=payload.name, price=payload.price)
            session.add(recipe)
            session.flush()
            session.add_all(
                [
                    RecipeIngredient(recipe_id=recipe.id, **part.model_dump())
                    for part in payload.ingredients
                ]
            )
            return {"recipe_id": recipe.id, "name": recipe.name}

    @app.get("/recipes")
    def recipes():
        with factory() as session:
            parts = session.scalars(select(RecipeIngredient)).all()
            by_recipe = {}
            for part in parts:
                by_recipe.setdefault(part.recipe_id, []).append(item_dict(part))
            return [
                {
                    **item_dict(recipe),
                    "ingredients": by_recipe.get(recipe.id, []),
                }
                for recipe in session.scalars(select(Recipe).order_by(Recipe.id))
            ]

    @app.post("/sales")
    def sale(payload: SaleInput):
        with factory.begin() as session:
            return record_sale(session, payload)

    @app.get("/reports/low-stock")
    def stock_report():
        with factory() as session:
            return analytics.low_stock(session)

    @app.get("/reports/costs")
    def costs(days: int = Query(30, ge=1, le=365)):
        with factory() as session:
            return analytics.cost_summary(session, days=days)

    @app.get("/reports/forecast")
    def demand(horizon: int = Query(7, ge=1, le=30), window: int = Query(14, ge=1, le=90)):
        with factory() as session:
            return analytics.forecast(session, horizon=horizon, window=window)

    @app.get("/reports/forecast/evaluation")
    def evaluation():
        with factory() as session:
            return analytics.evaluate_forecast(session)

    @app.get("/reports/anomalies")
    def anomaly_report():
        with factory() as session:
            return analytics.anomalies(session)

    @app.get("/reports/inventory-checks")
    def checks():
        with factory() as session:
            return [
                item_dict(row)
                for row in session.scalars(
                    select(InventoryCheck).order_by(InventoryCheck.id.desc()).limit(100)
                )
            ]

    @app.get("/reports/daily")
    def daily_reports():
        with factory() as session:
            return [
                item_dict(row)
                for row in session.scalars(
                    select(DailyReport).order_by(DailyReport.day.desc()).limit(30)
                )
            ]

    def enqueue_task(task):
        from kombu.exceptions import OperationalError

        try:
            result = task.apply_async(retry=False)
        except OperationalError as error:
            raise DomainError("Redis is unavailable; start the worker stack", 503) from error
        return {"task_id": result.id, "status": "queued"}

    @app.post("/jobs/inventory-check", status_code=202)
    def enqueue_check():
        from app.tasks import check_inventory

        return enqueue_task(check_inventory)

    @app.post("/jobs/daily-report", status_code=202)
    def enqueue_report():
        from app.tasks import prepare_daily_report

        return enqueue_task(prepare_daily_report)

    @app.post("/assistant")
    def assistant(payload: QuestionInput):
        try:
            with factory() as session:
                return answer_question(session, payload.question)
        except APIError as error:
            raise DomainError("The model provider request failed", 502) from error

    return app


app = create_app()
