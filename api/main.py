"""
just-agentic FastAPI backend

Run:
  uvicorn api.main:app --reload --port 8000

Or via Docker:
  docker compose up api
"""

import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from api.routers import auth, agent
from api.routers.admin import router as admin_router
from api.routers.knowledge import router as knowledge_router

app = FastAPI(title="just-agentic", version="1.0.0", docs_url="/api/docs")

# ── CORS ──────────────────────────────────────────────────────────────────────
_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router,   prefix="/api/auth",  tags=["auth"])
app.include_router(agent.router,  prefix="/api/agent", tags=["agent"])
app.include_router(admin_router)
app.include_router(knowledge_router)


# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/healthz", tags=["health"])
def health():
    return {"status": "ok"}
