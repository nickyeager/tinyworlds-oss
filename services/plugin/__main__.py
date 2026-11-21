"""Run with python -m services.plugin from the repository root."""

import os

import uvicorn

from services.plugin.server import create_app

uvicorn.run(
    create_app(),
    host=os.getenv("PLUGIN_BIND_HOST", "127.0.0.1"),
    port=int(os.getenv("PLUGIN_PORT", "8787")),
    access_log=False,
)
