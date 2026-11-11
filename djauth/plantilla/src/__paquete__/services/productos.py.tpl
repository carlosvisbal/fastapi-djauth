"""Lógica del negocio, sin FastAPI: se puede usar desde rutas, tareas o scripts y probar por separado."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from __paquete__.models.producto import Producto
from __paquete__.schemas.producto import ProductoCreate, ProductoUpdate


class CodigoRepetido(Exception):
    pass


def listar(session: Session, *, q: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[Producto], int]:
    stmt = select(Producto)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Producto.nombre).like(like), func.lower(Producto.codigo).like(like)))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = session.scalars(stmt.order_by(Producto.nombre, Producto.id).limit(limit).offset(offset)).all()
    return list(items), total


def obtener(session: Session, producto_id: int) -> Producto | None:
    return session.get(Producto, producto_id)


def crear(session: Session, datos: ProductoCreate, *, creado_por: int | None = None) -> Producto:
    if session.scalar(select(Producto.id).where(Producto.codigo == datos.codigo)) is not None:
        raise CodigoRepetido(f"Ya existe un producto con el código {datos.codigo}.")
    producto = Producto(**datos.model_dump(), creado_por=creado_por)
    session.add(producto)
    session.flush()
    return producto


def actualizar(session: Session, producto: Producto, datos: ProductoUpdate) -> Producto:
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(producto, campo, valor)
    session.flush()
    return producto


def eliminar(session: Session, producto: Producto) -> None:
    session.delete(producto)
    session.flush()
