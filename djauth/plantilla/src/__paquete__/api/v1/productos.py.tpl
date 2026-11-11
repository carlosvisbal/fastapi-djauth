"""Ejemplo de módulo completo: rutas delgadas que validan, piden permiso y delegan en el servicio."""

from typing import Annotated

from djauth import AuthUser, require_perm
from fastapi import APIRouter, Depends, HTTPException, Query, status

from __paquete__.api.deps import SessionDep
from __paquete__.schemas.producto import ProductoCreate, ProductoOut, ProductoPage, ProductoUpdate
from __paquete__.services import productos as service

router = APIRouter(prefix="/productos", tags=["productos"])


def _not_found(producto_id: int) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el producto {producto_id}.")


@router.get("", summary="Listar productos")
def listar(
    session: SessionDep,
    _: Annotated[AuthUser, Depends(require_perm("inventario.view_producto"))],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductoPage:
    items, total = service.listar(session, q=q, limit=limit, offset=offset)
    return ProductoPage(items=[ProductoOut.model_validate(p) for p in items], total=total)


@router.get("/{producto_id}", summary="Detalle de un producto")
def obtener(
    producto_id: int, session: SessionDep, _: Annotated[AuthUser, Depends(require_perm("inventario.view_producto"))]
) -> ProductoOut:
    producto = service.obtener(session, producto_id)
    if producto is None:
        raise _not_found(producto_id)
    return ProductoOut.model_validate(producto)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Crear un producto")
def crear(
    datos: ProductoCreate,
    session: SessionDep,
    user: Annotated[AuthUser, Depends(require_perm("inventario.add_producto"))],
) -> ProductoOut:
    try:
        producto = service.crear(session, datos, creado_por=user.id)
    except service.CodigoRepetido as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ProductoOut.model_validate(producto)


@router.patch("/{producto_id}", summary="Modificar un producto")
def actualizar(
    producto_id: int,
    datos: ProductoUpdate,
    session: SessionDep,
    _: Annotated[AuthUser, Depends(require_perm("inventario.change_producto"))],
) -> ProductoOut:
    producto = service.obtener(session, producto_id)
    if producto is None:
        raise _not_found(producto_id)
    return ProductoOut.model_validate(service.actualizar(session, producto, datos))


@router.delete("/{producto_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar un producto")
def eliminar(
    producto_id: int, session: SessionDep, _: Annotated[AuthUser, Depends(require_perm("inventario.delete_producto"))]
) -> None:
    producto = service.obtener(session, producto_id)
    if producto is None:
        raise _not_found(producto_id)
    service.eliminar(session, producto)
