# app/websocket_manager.py
from fastapi import WebSocket
from typing import Dict, List, Union
import asyncio
from app.models.notification_model import Notification
from fastapi import WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.active_user_connections: Dict[str, List[WebSocket]] = {}  # Para notificaciones
        self._lock = asyncio.Lock()  # Para evitar race conditions

    async def connect(self, websocket: WebSocket, post_id: str):
        await websocket.accept()
        if post_id not in self.active_connections:
            self.active_connections[post_id] = []
        self.active_connections[post_id].append(websocket)
    
    async def connect_user(self, websocket: WebSocket, user_id: str):
        
        async with self._lock:
            if user_id not in self.active_user_connections:
                self.active_user_connections[user_id] = []
            self.active_user_connections[user_id].append(websocket)
            logger.info(f"Usuario {user_id} conectado. Conexiones: {len(self.active_user_connections[user_id])}")

        # Mantener la conexión activa
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            await self.disconnect_user(websocket, user_id)
        except Exception as e:
            logger.error(f"Error en conexión: {str(e)}")
            await self.disconnect_user(websocket, user_id)

    def disconnect(self, websocket: WebSocket, post_id: str):
        if post_id in self.active_connections:
            self.active_connections[post_id].remove(websocket)
            if not self.active_connections[post_id]:
                del self.active_connections[post_id]
    
    async def disconnect_user(self, websocket: WebSocket, user_id: str):
        async with self._lock:
            if user_id in self.active_user_connections:
                if websocket in self.active_user_connections[user_id]:
                    self.active_user_connections[user_id].remove(websocket)
                    logger.info(f"Usuario {user_id} desconectado. Restantes: {len(self.active_user_connections.get(user_id, []))}")
                if not self.active_user_connections[user_id]:
                    del self.active_user_connections[user_id]

    async def broadcast_comment(self, post_id: str, comment: dict):
        if post_id in self.active_connections:
            for connection in self.active_connections[post_id]:
                await connection.send_json({
                    "event": "new_comment",
                    "data": comment
                })
                
    async def broadcast_event(self, post_id: str, event_data: dict):
        if post_id in self.active_connections:
            for connection in self.active_connections[post_id]:
                await connection.send_json(event_data)
                
    async def broadcast_notification(self, user_id: str, notification: Union[Notification, dict]):
        print(f"🔔 Intentando enviar notificación a usuario {user_id}")
        if user_id in self.active_user_connections:
            try:
                print(f"✅ Usuario {user_id} tiene {len(self.active_user_connections[user_id])} conexiones activas")
                # Conversión segura a Notification
                if isinstance(notification, dict):
                    notification = Notification.model_validate(notification)
                
                notification_dict = notification.model_dump(by_alias=True, mode='json')
            
                for connection in self.active_user_connections[user_id]:
                    try:
                        print(f"📤 Enviando notificación a conexión: {notification}")
                        await connection.send_json({
                            "event": "new_notification",
                            "data": notification_dict
                        })
                        print(f"✅ Notificación enviada exitosamente")
                    except Exception as e:
                        logger.error(f"Error enviando notificación: {str(e)}")
                        await self.disconnect_user(connection, user_id)
            except Exception as e:
                logger.error(f"Error procesando notificación: {str(e)}")
                
    async def broadcast_new_post(self, post: dict):
        """Transmite un nuevo post a todos los usuarios conectados"""
        async with self._lock:
            # Preparar datos para serialización
            serializable_post = {
                **post,
                "created_at": post["created_at"].isoformat() if "created_at" in post else None,
            "_id": str(post["_id"]),
            "author_id": str(post["author_id"])
        }
        
        # Enviar a todas las conexiones de usuario
        for user_id in list(self.active_user_connections.keys()):
            for connection in self.active_user_connections[user_id].copy():
                try:
                    await connection.send_json({
                        "event": "new_post",
                        "data": serializable_post
                    })
                except Exception as e:
                    logger.error(f"Error broadcasting new post: {str(e)}")
                    await self.disconnect_user(connection, user_id)

    async def broadcast_deleted_post(self, post_id: str):
        """Notifica sobre un post eliminado"""
        async with self._lock:
            # Notificar a conexiones específicas del post (si las hay)
            if post_id in self.active_connections:
                for connection in self.active_connections[post_id].copy():
                    try:
                        await connection.send_json({
                            "event": "post_deleted",
                            "data": {"post_id": post_id}
                        })
                    except Exception as e:
                        logger.error(f"Error broadcasting to post connections: {str(e)}")
            
            # Notificar a todas las conexiones de usuario
            for user_id in list(self.active_user_connections.keys()):
                for connection in self.active_user_connections[user_id].copy():
                    try:
                        await connection.send_json({
                            "event": "post_deleted",
                            "data": {"post_id": post_id}
                        })
                    except Exception as e:
                        logger.error(f"Error broadcasting to user {user_id}: {str(e)}")
                        await self.disconnect_user(connection, user_id)
                

# Instancia global para ser usada en otros archivos
manager = WebSocketManager()