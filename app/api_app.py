# app/api_app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.routers import auth, chat, history, limits
from app.routers.mobile import router as mobile_router

app = FastAPI(
    title="Ollama Proxy API",
    description="Основной API: чат, модели и история",
    version="1.0.0",
)

# Создать таблицы
Base.metadata.create_all(bind=engine)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем только API-роутеры
app.include_router(auth.router)
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(history.router, prefix="/history", tags=["History"])
app.include_router(limits.router, prefix="/limits", tags=["Limits"])
app.include_router(mobile_router, tags=["Mobile"])
