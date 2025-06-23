# app/admin_app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from app.routers.admin import router as admin_router

app = FastAPI(
    title="Ollama Admin Panel",
    description="Панель управления сервером",
    version="1.0.0",
)

# CORS (необязательно)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статика для CSS/JS
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Подключаем роутер админ-панели
app.include_router(admin_router)
