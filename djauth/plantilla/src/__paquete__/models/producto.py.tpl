from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from __paquete__.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)  # id del usuario (djauth)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    modificado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
