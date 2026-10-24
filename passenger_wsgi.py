"""Entry point for shared hosting that runs Python through Passenger/CloudLinux ("Setup Python App").
FastAPI is ASGI, so it is wrapped with a2wsgi. Limits: no WebSockets (the live LiDAR feed and the
admin accuracy test need a VPS or a local PC); the game, admin, uploads and results all work.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("FQ_ENV", "production")
os.environ.setdefault("FQ_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))

from a2wsgi import ASGIMiddleware  # noqa: E402
from app.main import create_app  # noqa: E402

application = ASGIMiddleware(create_app(start_sensor=False))
