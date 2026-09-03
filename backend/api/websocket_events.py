"""WebSocket live streaming for real-time updates."""
import asyncio
import json
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header

from api.auth import decode_token

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


@router.websocket("/ws/v1/live")
async def websocket_endpoint(websocket: WebSocket, authorization: str = Header(None)):
    """WebSocket endpoint for live streaming events.
    
    Authentication via Authorization header (Bearer token).
    
    Events broadcast:
    - token.update: {agent_id, tokens, cost, timestamp}
    - agent.stage: {agent_id, old_stage, new_stage}
    - budget.alert: {agent_id, threshold, spend_pct}
    - anomaly.alert: {agent_id, anomaly_type, severity}
    - discovery.new: {discovery_id, name, confidence}
    """
    # Validate token from Authorization header
    if not authorization or not authorization.startswith("Bearer "):
        await websocket.close(code=4001, reason="Missing or invalid authorization header")
        return
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(websocket)
    try:
        # Send initial connection success
        await manager.send_personal_message({
            "type": "connection.established",
            "timestamp": datetime.utcnow().isoformat(),
            "user_role": payload.get("role", "unknown")
        }, websocket)

        # Keep connection alive and handle client messages
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                # Handle subscription requests
                if message.get("action") == "subscribe":
                    await manager.send_personal_message({
                        "type": "subscription.confirmed",
                        "channels": message.get("channels", ["all"]),
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)
                elif message.get("action") == "ping":
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)
            except json.JSONDecodeError:
                await manager.send_personal_message({
                    "type": "error",
                    "detail": "Invalid JSON"
                }, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all connected WebSocket clients."""
    await manager.broadcast({
        "type": event_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    })
