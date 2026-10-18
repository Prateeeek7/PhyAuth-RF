from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.hub import hub

router = APIRouter(tags=["Live"])


@router.websocket("/api/ws")
async def live(ws: WebSocket):
    """One shared live stream: frame, decision, rx_stats, recording, training, status."""
    await ws.accept()
    hub.clients.add(ws)
    try:
        await ws.send_json({"type": "status", **hub.status()})
        while True:
            await ws.receive_text()   # keep-alive; client messages are ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
