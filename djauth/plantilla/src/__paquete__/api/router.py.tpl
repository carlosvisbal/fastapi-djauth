"""Rutas de la API. Cada módulo nuevo se registra aquí."""

from fastapi import APIRouter

from __paquete__.api.v1 import productos

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(productos.router)
