"""
WebSocket Connection Manager for Ron
Handles multiple WebSocket connections and message broadcasting with user awareness
"""
from fastapi import WebSocket
from typing import List, Dict, Set
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # Dictionary mapping username to a set of active WebSockets
        self.user_connections: Dict[str, Set[WebSocket]] = {}
        # Keep track of all active connections for global broadcasts if needed
        self.all_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        
        if username not in self.user_connections:
            self.user_connections[username] = set()
        
        self.user_connections[username].add(websocket)
        self.all_connections.add(websocket)
        
        logger.info(f"🔌 WebSocket connected for user '{username}'. User connections: {len(self.user_connections[username])}, Total: {len(self.all_connections)}")

    def disconnect(self, websocket: WebSocket, username: str = None):
        # Remove from all_connections
        if websocket in self.all_connections:
            self.all_connections.remove(websocket)
        
        # If username is known, remove from specific user set
        if username and username in self.user_connections:
            if websocket in self.user_connections[username]:
                self.user_connections[username].remove(websocket)
            if not self.user_connections[username]:
                del self.user_connections[username]
        else:
            # Fallback: search all users if username not provided
            for user, connections in list(self.user_connections.items()):
                if websocket in connections:
                    connections.remove(websocket)
                    if not connections:
                        del self.user_connections[user]
                    break
                    
        logger.info(f"🔌 WebSocket disconnected. Total connections: {len(self.all_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast_to_user(self, username: str, message: dict):
        """Broadcast message to all sessions of a specific user"""
        if username not in self.user_connections:
            return

        disconnected = []
        connections = self.user_connections[username]
        
        # Create a copy to iterate safely
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to user '{username}': {e}")
                disconnected.append(connection)
        
        # Cleanup disconnected
        for conn in disconnected:
            self.disconnect(conn, username)

    async def broadcast_all(self, message: dict):
        """Broadcast message to ALL connected clients across all users"""
        disconnected = []
        for connection in list(self.all_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting all: {e}")
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)


# Global instance
manager = ConnectionManager()
