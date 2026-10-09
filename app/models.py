from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        CheckConstraint("on_hand >= 0 AND par_level >= 0 AND target_level >= par_level"),
        CheckConstraint("unit_cost >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    unit: Mapped[str] = mapped_column(String(20))
    on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    par_level: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    target_level: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (CheckConstraint("price >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (CheckConstraint("quantity > 0"),)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SaleLine(Base):
    __tablename__ = "sale_lines"
    __table_args__ = (CheckConstraint("quantity > 0 AND unit_price >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Movement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (CheckConstraint("unit_cost >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class StockCount(Base):
    __tablename__ = "stock_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    expected: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    counted: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    variance: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InventoryCheck(Base):
    __tablename__ = "inventory_checks"
    __table_args__ = (UniqueConstraint("hour", "ingredient_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class DailyReport(Base):
    __tablename__ = "daily_reports"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
