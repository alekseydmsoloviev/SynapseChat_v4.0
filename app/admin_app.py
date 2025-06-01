# app/admin_app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
app.mount("/static", StaticFiles(directory="static"), name="static")

# Подключаем роутер админ-панели
app.include_router(admin_router)
