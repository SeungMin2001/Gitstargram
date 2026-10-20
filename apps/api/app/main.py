from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import router as api_router
from .ai import router as ai_router
from .auth import router as auth_router
from .config import settings
from .database import engine
from .dm import router as dm_router
from .social import router as social_router


app = FastAPI(title="Gitstargram API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(auth_router)
app.include_router(api_router)
app.include_router(ai_router)
app.include_router(social_router)
app.include_router(dm_router)


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}

