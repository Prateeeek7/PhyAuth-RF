"""
PhyAuth-RF API server.

    PYTHONPATH=. .venv/bin/uvicorn backend.main:app --port 8000
or  .venv/bin/python -m backend.main
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from backend.database import init_db
from backend.hub import hub
from backend.routers import attack, devices, events, hardware, models, recordings, ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await hub.start()
    yield
    await hub.stop()


app = FastAPI(
    title="PhyAuth-RF",
    description="Physical-layer RF fingerprint authentication with ESP32 + SRX882 (433 MHz ASK/OOK).",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

for r in (devices, hardware, recordings, models, events, attack, ws):
    app.include_router(r.router)


@app.get("/")
def root():
    return {"status": "online", "platform": "PhyAuth-RF", "version": "2.0.0",
            "receiver": hub.rx.status()["mode"], "model_ready": hub.engine.ready}


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host=config.API_HOST, port=config.API_PORT, reload=False)
