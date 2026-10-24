"""Application factory."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, seed
from .hub import Hub
from .routers import auth, content, game, games, media, sensor, settings
from .sensor.service import SensorService

STATIC = Path(__file__).resolve().parent.parent / "static"

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self' ws: wss:; font-src 'self' data: blob:; media-src 'self' data: blob:; "
       "frame-ancestors 'self'; base-uri 'self'; form-action 'self'")


def create_app(start_sensor: bool = True, sensor_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect()
        try:
            db.migrate(conn)
            seed.run_all(conn)
            sensor.active_config_row(conn)
        finally:
            conn.close()
        loop = asyncio.get_running_loop()
        app.state.input_hub.loop = loop
        app.state.diag_hub.loop = loop
        if start_sensor:
            app.state.sensor.start()
        try:
            yield
        finally:
            app.state.sensor.stop()

    app = FastAPI(title="Football Challenge Platform", lifespan=lifespan, docs_url="/api/docs" if config.is_dev() else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if config.is_dev() else None)
    app.state.input_hub = Hub()
    app.state.diag_hub = Hub()
    kwargs = {"source_factory": sensor_factory} if sensor_factory else {}
    app.state.sensor = SensorService(sensor.load_service_config, app.state.input_hub.publish_threadsafe,
                                     app.state.diag_hub.publish_threadsafe, app.state.diag_hub.count, **kwargs)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith(("/media/", "/api/docs", "/api/openapi")):
            resp.headers.setdefault("Content-Security-Policy", CSP)
            resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    for r in (auth.router, content.router, media.router, settings.router, sensor.router, games.router, game.router):
        app.include_router(r)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return RedirectResponse("/static/brand/favicon.ico")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/game/")

    for sub in ("game", "admin"):
        app.mount(f"/{sub}", StaticFiles(directory=STATIC / sub, html=True), name=sub)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()
