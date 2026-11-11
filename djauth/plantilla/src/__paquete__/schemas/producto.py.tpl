"""Esquemas de entrada y salida: la API nunca expone los modelos de la base directamente."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductoBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0)


class ProductoCreate(ProductoBase):
    codigo: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")


class ProductoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    precio: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)


class ProductoOut(ProductoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    creado: datetime
    modificado: datetime


class ProductoPage(BaseModel):
    items: list[ProductoOut]
    total: int
