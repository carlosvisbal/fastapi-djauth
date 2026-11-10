"""Integración con FastAPI: rutas, dependencias, middleware de protección y páginas.

kit = AuthKit(AuthSettings(database_url="sqlite:///auth.sqlite3")).init()
kit.install(app)                          # rutas /auth/… y páginas de login y administración
kit.install(app, protect=True, rules=[…]) # además exige sesión o token en toda la aplicación

@app.get("/pedidos")
def pedidos(user: AuthUser = Depends(require_perm("ventas.view_pedido"))): ...
"""

# Sin `from __future__ import annotations`: FastAPI evalúa las anotaciones de las rutas, y estas nombran
# dependencias locales de `build_router` (`Me`, `staff(...)`) que no se pueden resolver como texto.
import hmac
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from djauth.core import SERVICE_USER, AuthKit, AuthUser
from djauth.errors import (
    AuthError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    TooManyAttemptsError,
    ValidationError,
)
from djauth.validators import password_help_texts

logger = logging.getLogger("djauth")
STATIC_DIR = Path(__file__).parent / "static"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Cabeceras de las páginas del módulo: no se pueden incrustar en otro sitio, no cargan nada externo
# y no filtran la URL (el enlace de restablecimiento lleva un token).
PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
API_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

# Solo documenta el esquema en /docs (botón "Authorize"); la validación real la hace `identify`.
_oauth2_docs = OAuth2PasswordBearer(tokenUrl="/auth/api/token", auto_error=False)


# ====================================================================== identificación
def _kit(conn: HTTPConnection) -> AuthKit:
    kit = getattr(conn.app.state, "djauth", None)
    if kit is None:
        raise RuntimeError("AuthKit no está instalado en esta aplicación: llame a kit.install(app)")
    return kit


def _equal(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def identify(
    kit: AuthKit, headers: Any, query_string: bytes = b"", *, websocket: bool = False, api_key: str | None = None
) -> tuple[AuthUser | None, str | None]:
    """Quién hace la petición y por qué vía: ("session" | "bearer" | "api_key").

    Orden: `Authorization: Bearer`, `X-API-Key`, cookie de sesión. En un WebSocket (el navegador no
    puede enviar cabeceras) se acepta además `?access_token=` o `?api_key=`.
    """
    s = kit.settings
    auth = headers.get("authorization") or ""
    scheme, _, credential = auth.partition(" ")
    credential = credential.strip()
    if scheme.lower() == "bearer" and credential:
        if _equal(credential, api_key):
            return SERVICE_USER, "api_key"
        if s.enable_bearer and (user := kit.user_from_token(credential, "bearer")):
            return user, "bearer"
        return None, None  # una credencial explícita e inválida no cae a la cookie
    if _equal(headers.get("x-api-key"), api_key):
        return SERVICE_USER, "api_key"
    if s.enable_sessions:
        for part in (headers.get("cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == s.session_cookie_name and (user := kit.user_from_token(value, "session")):
                return user, "session"
    if websocket and query_string:
        query = parse_qs(query_string.decode("latin-1"))
        token = (query.get("access_token") or [None])[0]
        if s.enable_bearer and token and (user := kit.user_from_token(token, "bearer")):
            return user, "bearer"
        if _equal((query.get("api_key") or [None])[0], api_key):
            return SERVICE_USER, "api_key"
    return None, None


def same_origin(headers: Any, trusted: Iterable[str] = ()) -> bool:
    """Defensa CSRF para la autenticación por cookie: una petición que modifica datos debe venir de
    este mismo sitio. Los navegadores envían `Origin` (o `Sec-Fetch-Site`) en esas peticiones."""
    origin = headers.get("origin")
    if origin:
        if origin in trusted:
            return True
        return urlsplit(origin).netloc == (headers.get("host") or "")
    site = headers.get("sec-fetch-site")
    return site in (None, "same-origin", "none")


def _user_of(conn: HTTPConnection) -> tuple[AuthUser | None, str | None]:
    state = conn.scope.get("state") or {}
    if "user" in state:  # ya lo resolvió el middleware
        return state["user"], state.get("auth_via")
    kit = _kit(conn)
    return identify(kit, conn.headers, conn.scope.get("query_string", b""), websocket=conn.scope["type"] == "websocket")


# ====================================================================== dependencias públicas
def optional_user(conn: HTTPConnection) -> AuthUser | None:
    """El usuario si hay sesión o token válido; si no, None (para rutas públicas que se adaptan)."""
    return _user_of(conn)[0]


def current_user(request: Request, _docs: Annotated[str | None, Depends(_oauth2_docs)] = None) -> AuthUser:
    """Equivale a `@login_required`: 401 si no hay sesión ni token válido."""
    user, via = _user_of(request)
    if user is None:
        raise HTTPException(401, "No ha iniciado sesión.", headers={"WWW-Authenticate": "Bearer"})
    if (
        via == "session"
        and request.method in UNSAFE_METHODS
        and not same_origin(request.headers, _kit(request).settings.trusted_origins)
    ):
        raise HTTPException(403, "Petición rechazada: origen no permitido (CSRF).")
    return user


def require_perm(*perms: str) -> Callable[..., AuthUser]:
    """Equivale a `@permission_required`: 403 si falta alguno de los permisos (`app.codename`)."""

    def dependency(user: Annotated[AuthUser, Depends(current_user)]) -> AuthUser:
        missing = [p for p in perms if not user.has_perm(p)]
        if missing:
            raise HTTPException(403, f"No tiene permiso para esta acción (requiere {', '.join(missing)}).")
        return user

    return dependency


def require_staff(user: Annotated[AuthUser, Depends(current_user)]) -> AuthUser:
    """Equivale a `@staff_member_required`."""
    if not (user.is_staff or user.is_superuser):
        raise HTTPException(403, "Solo el personal de administración puede entrar aquí.")
    return user


def require_superuser(user: Annotated[AuthUser, Depends(current_user)]) -> AuthUser:
    if not user.is_superuser:
        raise HTTPException(403, "Solo un superusuario puede hacer esto.")
    return user


def ws_user(websocket: HTTPConnection) -> AuthUser | None:
    """Usuario de un WebSocket (cookie de sesión, o `?access_token=`). None si no está autenticado."""
    return _user_of(websocket)[0]


# ====================================================================== middleware de protección
@dataclass(frozen=True)
class Rule:
    """Permiso que exige una ruta. `pattern` es una expresión regular sobre el path; `methods` limita
    los métodos HTTP (None = todos; un WebSocket cuenta como "WEBSOCKET"). Gana la primera que coincide."""

    pattern: str
    perm: str | None
    methods: frozenset[str] | None = None

    def matches(self, method: str, path: str) -> bool:
        return (self.methods is None or method in self.methods) and re.match(self.pattern, path) is not None


def rule(pattern: str, perm: str | None, methods: Iterable[str] | None = None) -> Rule:
    return Rule(pattern, perm, frozenset(m.upper() for m in methods) if methods else None)


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class _Headers:
    """Acceso por nombre a las cabeceras de un scope ASGI."""

    def __init__(self, scope: Scope) -> None:
        self._h = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers") or ()}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._h.get(name, default)


class AuthMiddleware:
    """Exige autenticación en toda la aplicación (HTTP y WebSocket) y aplica las reglas de permiso.

    Sin credenciales: una navegación del navegador se redirige al inicio de sesión; cualquier otra
    petición recibe 401. Con credenciales pero sin el permiso de la regla: 403.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        kit: AuthKit,
        *,
        login_url: str = "/auth/login",
        exempt: Iterable[str] = (),
        exempt_prefixes: Iterable[str] = (),
        rules: Iterable[Rule] = (),
        api_key: str | None = None,
    ) -> None:
        self.app = app
        self.kit = kit
        self.login_url = login_url
        self.exempt = frozenset(exempt)
        self.exempt_prefixes = tuple(exempt_prefixes)
        self.rules = tuple(rules)
        self.api_key = api_key

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, status: int, detail: str, location: str | None = None
    ) -> None:
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008, "reason": detail[:120]})
            return
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
        headers = [(b"content-type", b"application/json; charset=utf-8"), (b"cache-control", b"no-store")]
        if location:
            body, headers = b"", [(b"location", location.encode("latin-1")), (b"cache-control", b"no-store")]
        elif status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        headers.append((b"content-length", str(len(body)).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "WEBSOCKET")
        if path in self.exempt or path.startswith(self.exempt_prefixes) or method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = _Headers(scope)
        # Consulta a la base (con caché): fuera del bucle de eventos.
        user, via = await run_in_threadpool(
            identify,
            self.kit,
            headers,
            scope.get("query_string", b""),
            websocket=scope["type"] == "websocket",
            api_key=self.api_key,
        )
        if user is None:
            wants_page = method == "GET" and "text/html" in (headers.get("accept") or "")
            if wants_page and self.kit.settings.enable_sessions:
                query = scope.get("query_string", b"").decode("latin-1")
                target = quote(path + (f"?{query}" if query else ""), safe="")
                await self._reject(scope, receive, send, 303, "", f"{self.login_url}?next={target}")
            else:
                await self._reject(scope, receive, send, 401, "No ha iniciado sesión.")
            return
        if via == "session" and method in UNSAFE_METHODS and not same_origin(headers, self.kit.settings.trusted_origins):
            await self._reject(scope, receive, send, 403, "Petición rechazada: origen no permitido (CSRF).")
            return
        for r in self.rules:
            if r.matches(method, path):
                if r.perm and not user.has_perm(r.perm):
                    logger.warning("403 %s %s: %s no tiene %s", method, path, user.username, r.perm)
                    await self._reject(scope, receive, send, 403, f"No tiene permiso para esta acción (requiere {r.perm}).")
                    return
                break
        scope.setdefault("state", {})
        scope["state"]["user"] = user
        scope["state"]["auth_via"] = via
        await self.app(scope, receive, send)


# ====================================================================== esquemas
Password = Annotated[str, Field(min_length=1, max_length=4096)]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: Password


class PasswordChangeIn(BaseModel):
    old_password: Password
    new_password: Password


class ResetConfirmIn(BaseModel):
    uid: int
    token: str = Field(max_length=200)
    new_password: Password


class ProfileIn(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    first_name: str | None = Field(default=None, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)


class UserCreateIn(BaseModel):
    username: str = Field(max_length=150)
    password: Password | None = Field(default=None, description="Sin contraseña, el usuario no puede entrar hasta asignarle una")
    email: str = Field(default="", max_length=254)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)
    is_active: bool = True
    is_staff: bool = False
    is_superuser: bool = False
    groups: list[int] = Field(default_factory=list)
    permissions: list[int] = Field(default_factory=list)
    extra: dict[str, Any] | None = None


class UserUpdateIn(BaseModel):
    username: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=254)
    first_name: str | None = Field(default=None, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)
    is_active: bool | None = None
    is_staff: bool | None = None
    is_superuser: bool | None = None
    groups: list[int] | None = None
    permissions: list[int] | None = None
    extra: dict[str, Any] | None = None


class SetPasswordIn(BaseModel):
    password: Password


class GroupIn(BaseModel):
    name: str = Field(max_length=150)
    permissions: list[int] = Field(default_factory=list)


class GroupUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    permissions: list[int] | None = None


# ====================================================================== rutas
class _AuthRoute(APIRoute):
    """Convierte los errores del núcleo en respuestas JSON (`detail` + `errors` por campo)."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                response = await handler(request)
            except ValidationError as exc:
                return JSONResponse({"detail": exc.first, "errors": exc.errors}, 400, headers=API_HEADERS)
            except NotFoundError as exc:
                return JSONResponse({"detail": str(exc)}, 404, headers=API_HEADERS)
            except PermissionDeniedError as exc:
                return JSONResponse({"detail": str(exc)}, 403, headers=API_HEADERS)
            except InvalidCredentialsError as exc:
                return JSONResponse({"detail": str(exc)}, 401, headers=API_HEADERS)
            except TooManyAttemptsError as exc:
                return JSONResponse({"detail": str(exc)}, 429, headers={**API_HEADERS, "Retry-After": str(exc.retry_after)})
            except AuthError as exc:
                return JSONResponse({"detail": str(exc)}, 400, headers=API_HEADERS)
            for name, value in API_HEADERS.items():
                response.headers.setdefault(name, value)
            return response

        return wrapped


def _client_ip(request: Request, kit: AuthKit) -> str:
    if kit.settings.trust_proxy_headers and (forwarded := request.headers.get("x-forwarded-for")):
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else ""


def build_router(kit: AuthKit) -> APIRouter:
    s = kit.settings
    router = APIRouter(route_class=_AuthRoute, tags=["auth"])

    def check_origin(request: Request) -> None:
        # También en el inicio de sesión: nadie debe poder iniciar una sesión ajena desde otro sitio.
        if (
            request.method in UNSAFE_METHODS
            and request.headers.get("cookie")
            and not same_origin(request.headers, s.trusted_origins)
        ):
            raise HTTPException(403, "Petición rechazada: origen no permitido (CSRF).")

    def staff(perm: str) -> Callable[..., AuthUser]:
        def dependency(user: Annotated[AuthUser, Depends(require_staff)]) -> AuthUser:
            if not user.has_perm(perm):
                raise HTTPException(403, f"No tiene permiso para esta acción (requiere {perm}).")
            return user

        return dependency

    def set_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            s.session_cookie_name,
            token,
            max_age=s.session_cookie_age,
            path="/",
            httponly=True,
            secure=s.session_cookie_secure,
            samesite=s.session_cookie_samesite,
        )

    # ------------------------------------------------------------------ público
    @router.get("/config", summary="Datos del sitio para las páginas de acceso")
    def config() -> dict[str, Any]:
        return {
            "site_name": s.site_name,
            "brand_color": s.brand_color,
            "home_url": s.home_url,
            "sessions": s.enable_sessions,
            "bearer": s.enable_bearer,
            "password_help": password_help_texts(s.password_min_length),
            "extra_fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type,
                    "choices": list(f.choices),
                    "required": f.required,
                    "help_text": f.help_text,
                }
                for f in s.extra_fields
            ],
        }

    @router.post("/login", summary="Iniciar sesión (cookie)", dependencies=[Depends(check_origin)])
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        if not s.enable_sessions:
            raise HTTPException(403, "La autenticación por sesión está desactivada: use /token.")
        ip = _client_ip(request, kit)
        user = kit.authenticate(body.username, body.password, ip=ip)
        kit.logout(request.cookies.get(s.session_cookie_name))  # nunca se reutiliza una sesión previa
        set_cookie(response, kit.login(user, kind="session", ip=ip, user_agent=request.headers.get("user-agent", "")))
        return {"user": user.to_dict()}

    @router.post("/token", summary="Obtener un token Bearer (JSON o formulario OAuth2)")
    async def token(request: Request) -> dict[str, Any]:
        if not s.enable_bearer:
            raise HTTPException(403, "La autenticación por token está desactivada: use /login.")
        raw = await request.body()
        if len(raw) > 16_384:
            raise HTTPException(413, "Petición demasiado grande.")
        try:
            if "json" in request.headers.get("content-type", ""):
                data = json.loads(raw or b"{}")
            else:  # application/x-www-form-urlencoded, el flujo "password" de OAuth2 (botón Authorize de /docs)
                data = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            body = LoginIn(username=data.get("username", ""), password=data.get("password", ""))
        except (ValueError, AttributeError) as exc:
            raise HTTPException(422, "Envíe username y password.") from exc
        ip = _client_ip(request, kit)

        def issue() -> dict[str, Any]:
            user = kit.authenticate(body.username, body.password, ip=ip)
            access = kit.login(user, kind="bearer", ip=ip, user_agent=request.headers.get("user-agent", ""))
            return {"access_token": access, "token_type": "bearer", "expires_in": s.bearer_token_age, "user": user.to_dict()}

        return await run_in_threadpool(issue)

    @router.post("/logout", summary="Cerrar la sesión o revocar el token presentado", dependencies=[Depends(check_origin)])
    def logout(request: Request, response: Response) -> dict[str, bool]:
        kit.logout(request.cookies.get(s.session_cookie_name))
        scheme, _, credential = (request.headers.get("authorization") or "").partition(" ")
        if scheme.lower() == "bearer":
            kit.logout(credential.strip())
        response.delete_cookie(s.session_cookie_name, path="/")
        return {"ok": True}

    @router.post("/reset/confirm", summary="Fijar una contraseña nueva con un enlace de restablecimiento")
    def reset_confirm(body: ResetConfirmIn) -> dict[str, bool]:
        kit.reset_password(body.uid, body.token, body.new_password)
        return {"ok": True}

    # ------------------------------------------------------------------ mi cuenta
    Me = Annotated[AuthUser, Depends(current_user)]

    @router.get("/me", summary="Usuario autenticado, con sus grupos y permisos")
    def me(user: Me) -> dict[str, Any]:
        return user.to_dict()

    @router.patch("/me", summary="Actualizar mis datos personales")
    def update_me(body: ProfileIn, user: Me) -> dict[str, Any]:
        if user.is_service:
            raise HTTPException(400, "Una llave de API no tiene perfil.")
        updated = kit.update_user(user.id, body.model_dump(exclude_none=True), actor=None)
        return {k: updated[k] for k in ("id", "username", "email", "first_name", "last_name", "full_name")}

    @router.post("/me/password", summary="Cambiar mi contraseña (cierra mis otras sesiones)")
    def change_my_password(body: PasswordChangeIn, user: Me, request: Request) -> dict[str, bool]:
        if user.is_service:
            raise HTTPException(400, "Una llave de API no tiene contraseña.")
        scheme, _, credential = (request.headers.get("authorization") or "").partition(" ")
        keep = credential.strip() if scheme.lower() == "bearer" else request.cookies.get(s.session_cookie_name)
        kit.change_password(user, body.old_password, body.new_password, keep_session=keep)
        return {"ok": True}

    # ------------------------------------------------------------------ administración: usuarios
    @router.get("/users", summary="Listar usuarios")
    def list_users(
        _: Annotated[AuthUser, Depends(staff("auth.view_user"))],
        q: Annotated[str | None, Query(max_length=150)] = None,
        is_active: bool | None = None,
        is_staff: bool | None = None,
        is_superuser: bool | None = None,
        group: int | None = None,
        order: Annotated[str, Query(max_length=30)] = "username",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        items, total = kit.list_users(
            q=q,
            is_active=is_active,
            is_staff=is_staff,
            is_superuser=is_superuser,
            group_id=group,
            order=order,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @router.post("/users", status_code=201, summary="Crear un usuario")
    def create_user(body: UserCreateIn, actor: Annotated[AuthUser, Depends(staff("auth.add_user"))]) -> dict[str, Any]:
        data = body.model_dump()
        return kit.create_user(data.pop("username"), data.pop("password"), actor=actor, **data)

    @router.get("/users/{user_id}", summary="Detalle de un usuario")
    def get_user(user_id: int, _: Annotated[AuthUser, Depends(staff("auth.view_user"))]) -> dict[str, Any]:
        return {**kit.get_user(user_id), "active_sessions": kit.count_sessions(user_id)}

    @router.patch("/users/{user_id}", summary="Modificar un usuario")
    def update_user(
        user_id: int, body: UserUpdateIn, actor: Annotated[AuthUser, Depends(staff("auth.change_user"))]
    ) -> dict[str, Any]:
        return kit.update_user(user_id, body.model_dump(exclude_unset=True), actor=actor)

    @router.delete("/users/{user_id}", status_code=204, summary="Eliminar un usuario")
    def delete_user(user_id: int, actor: Annotated[AuthUser, Depends(staff("auth.delete_user"))]) -> Response:
        kit.delete_user(user_id, actor=actor)
        return Response(status_code=204)

    @router.post("/users/{user_id}/password", summary="Asignar una contraseña a un usuario")
    def set_user_password(
        user_id: int, body: SetPasswordIn, actor: Annotated[AuthUser, Depends(staff("auth.change_user"))]
    ) -> dict[str, bool]:
        kit.set_password(user_id, body.password, actor=actor)
        return {"ok": True}

    @router.post("/users/{user_id}/reset-link", summary="Generar un enlace para que el usuario fije su contraseña")
    def reset_link(
        user_id: int, request: Request, actor: Annotated[AuthUser, Depends(staff("auth.change_user"))]
    ) -> dict[str, Any]:
        token_value = kit.make_reset_token(user_id, actor=actor)
        # El token va en el fragmento (#): el navegador no lo envía al servidor ni queda en los logs.
        base = str(request.url).split("/api/users/")[0]
        return {
            "uid": user_id,
            "token": token_value,
            "url": f"{base}/reset#uid={user_id}&token={token_value}",
            "expires_in": s.password_reset_timeout,
        }

    @router.post("/users/{user_id}/logout", summary="Cerrar todas las sesiones y tokens de un usuario")
    def logout_user(user_id: int, actor: Annotated[AuthUser, Depends(staff("auth.change_user"))]) -> dict[str, bool]:
        kit.logout_all(user_id, actor=actor)
        return {"ok": True}

    # ------------------------------------------------------------------ administración: grupos
    @router.get("/groups", summary="Listar grupos (roles)")
    def list_groups(_: Annotated[AuthUser, Depends(staff("auth.view_group"))]) -> dict[str, Any]:
        return {"items": kit.list_groups()}

    @router.post("/groups", status_code=201, summary="Crear un grupo")
    def create_group(body: GroupIn, actor: Annotated[AuthUser, Depends(staff("auth.add_group"))]) -> dict[str, Any]:
        return kit.create_group(body.name, body.permissions, actor=actor)

    @router.get("/groups/{group_id}", summary="Detalle de un grupo")
    def get_group(group_id: int, _: Annotated[AuthUser, Depends(staff("auth.view_group"))]) -> dict[str, Any]:
        return kit.get_group(group_id)

    @router.patch("/groups/{group_id}", summary="Modificar un grupo")
    def update_group(
        group_id: int, body: GroupUpdateIn, actor: Annotated[AuthUser, Depends(staff("auth.change_group"))]
    ) -> dict[str, Any]:
        return kit.update_group(group_id, body.model_dump(exclude_unset=True), actor=actor)

    @router.delete("/groups/{group_id}", status_code=204, summary="Eliminar un grupo")
    def delete_group(group_id: int, actor: Annotated[AuthUser, Depends(staff("auth.delete_group"))]) -> Response:
        kit.delete_group(group_id, actor=actor)
        return Response(status_code=204)

    # ------------------------------------------------------------------ administración: permisos y registro
    @router.get("/permissions", summary="Permisos disponibles")
    def list_permissions(_: Annotated[AuthUser, Depends(require_staff)]) -> dict[str, Any]:
        return {"items": kit.list_permissions()}

    @router.get("/log", summary="Registro de acciones de la administración")
    def list_log(
        _: Annotated[AuthUser, Depends(staff("auth.view_logentry"))],
        object_type: Annotated[str | None, Query(max_length=50)] = None,
        object_id: Annotated[str | None, Query(max_length=50)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        items, total = kit.list_log(limit=limit, offset=offset, object_type=object_type, object_id=object_id)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    return router


# ====================================================================== instalación
def install(
    kit: AuthKit,
    app: Any,
    *,
    prefix: str = "/auth",
    protect: bool = False,
    exempt: Iterable[str] = (),
    exempt_prefixes: Iterable[str] = (),
    rules: Iterable[Rule] = (),
    api_key: str | None = None,
) -> None:
    """Añade a la aplicación las rutas `{prefix}/api/*`, las páginas (`login`, `admin`, `account`,
    `reset`) y, con `protect=True`, el middleware que exige autenticación en todo lo demás.

    `rules` asocia rutas con permisos; `exempt` y `exempt_prefixes` dejan rutas públicas (sondas de
    salud, por ejemplo); `api_key` es una credencial de máquina opcional con acceso total.
    """
    prefix = "/" + prefix.strip("/")
    app.state.djauth = kit
    app.include_router(build_router(kit), prefix=f"{prefix}/api")

    def page(name: str) -> Callable[[], FileResponse]:
        def serve() -> FileResponse:
            return FileResponse(STATIC_DIR / f"{name}.html", headers=PAGE_HEADERS)

        return serve

    for name in ("login", "admin", "account", "reset"):
        app.add_api_route(f"{prefix}/{name}", page(name), methods=["GET"], include_in_schema=False)
    app.mount(f"{prefix}/static", StaticFiles(directory=STATIC_DIR), name="djauth-static")

    if protect:
        public = {
            f"{prefix}/login",
            f"{prefix}/reset",
            f"{prefix}/api/login",
            f"{prefix}/api/token",
            f"{prefix}/api/config",
            f"{prefix}/api/reset/confirm",
            f"{prefix}/api/logout",
        }
        if not kit.settings.enable_sessions:
            # Solo tokens: las páginas son cascarones estáticos; quien protege los datos es la API.
            public |= {f"{prefix}/admin", f"{prefix}/account"}
        app.add_middleware(
            AuthMiddleware,
            kit=kit,
            login_url=f"{prefix}/login",
            exempt={*public, *exempt},
            exempt_prefixes=(f"{prefix}/static/", *exempt_prefixes),
            rules=tuple(rules),
            api_key=api_key,
        )
