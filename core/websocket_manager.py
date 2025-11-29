"""
WebSocket Connection Manager for Ron
Handles multiple WebSocket connections and message broadcasting
"""
from fastapi import WebSocket
from typing import List
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔌 WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"🔌 WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast(self, message: dict, exclude: WebSocket = None):
        """Broadcast message to all connected clients except the excluded one"""
        disconnected = []
        for connection in self.active_connections:
            if connection == exclude:
                continue
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_all(self, message: dict):
        """Broadcast message to ALL connected clients"""
        await self.broadcast(message, exclude=None)


# Global instance
manager = ConnectionManager()
