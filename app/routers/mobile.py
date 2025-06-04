from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio

from app.utils.db_snapshot import collect_detailed_snapshot

router = APIRouter()


@router.websocket("/ws/mobile")
async def mobile_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            snapshot = collect_detailed_snapshot()
            await websocket.send_json(snapshot)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
