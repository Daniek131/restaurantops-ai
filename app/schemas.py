from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=100)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
Cost = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]
Price = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VendorInput(Input):
    name: Name


class IngredientInput(Input):
    name: Name
    unit: Annotated[str, Field(min_length=1, max_length=20)]
    on_hand: Quantity
    par_level: Quantity
    target_level: Quantity
    unit_cost: Cost
    vendor_id: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def check_levels(self):
        if self.target_level < self.par_level:
            raise ValueError("target_level must be at least par_level")
        return self


class RecipePart(Input):
    ingredient_id: Annotated[int, Field(gt=0)]
    quantity: PositiveQuantity


class RecipeInput(Input):
    name: Name
    price: Price
    ingredients: Annotated[list[RecipePart], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def no_duplicate_ingredients(self):
        ids = [part.ingredient_id for part in self.ingredients]
        if len(set(ids)) != len(ids):
            raise ValueError("An ingredient may appear only once per recipe")
        return self


class SalePart(Input):
    recipe_id: Annotated[int, Field(gt=0)]
    quantity: Annotated[int, Field(gt=0, le=10000)]


class SaleInput(Input):
    external_id: Name
    occurred_at: datetime
    lines: Annotated[list[SalePart], Field(min_length=1, max_length=100)]

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        if value > datetime.now(timezone.utc):
            raise ValueError("Sales cannot occur in the future")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def no_duplicate_recipes(self):
        ids = [line.recipe_id for line in self.lines]
        if len(set(ids)) != len(ids):
            raise ValueError("Combine repeated recipe lines before submitting")
        return self


class ReceiptInput(Input):
    quantity: PositiveQuantity


class CountInput(Input):
    counted: Quantity


class CostInput(Input):
    unit_cost: Cost


class QuestionInput(Input):
    question: Annotated[str, Field(min_length=1, max_length=1000)]
