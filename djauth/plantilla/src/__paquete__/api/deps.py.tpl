"""Dependencias comunes de las rutas."""

from typing import Annotated

from djauth import AuthUser, current_user
from fastapi import Depends
from sqlalchemy.orm import Session

from __paquete__.db import get_session

SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[AuthUser, Depends(current_user)]
