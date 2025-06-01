# app/main.py
"""
Основная точка входа для документации OpenAPI и (при необходимости) монолитного запуска.
Обычно теперь используется через cli.py с разделением admin_app и api_app.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base
from app.routers import auth, models, chat, history, admin

app = FastAPI(
    title="Ollama Proxy API",
    description="Proxy server for Ollama with auth, rate limits, chat history and admin panel",
    version="1.0.0",
)

Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(models.router, prefix="/models", tags=["Models"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(history.router, prefix="/history", tags=["History"])
app.include_router(admin.router)
