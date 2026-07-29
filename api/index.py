"""Vercel ASGI entrypoint for Elegance Cloud 2 RC2."""

from __future__ import annotations

import os

os.environ.setdefault("ELEGANCE_SERVERLESS", "1")
os.environ.setdefault("ELEGANCE_DATA_DIR", "/tmp/elegance")

from server import app

__all__ = ["app"]
