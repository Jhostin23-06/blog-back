# app/websocket_manager.py
from fastapi import WebSocket
from typing import Dict, List, Union
import asyncio
from app.models.notification_model import Notification
from fastapi import WebSocketDisconnect
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.active_user_connections: Dict[str, List[WebSocket]] = {}  # Para notificaciones
        self._lock = asyncio.Lock()  # Para evitar race conditions
        self.accepted_websockets = set()  # Para rastrear websockets ya aceptados
        self.image_connections: Dict[str, List[WebSocket]] = defaultdict(list)
    
    def _serialize_for_websocket(self, data: dict) -> dict:
        """Convierte datos a formato JSON serializable para WebSocket"""
        from datetime import datetime
        from bson import ObjectId
        import json
        
        def serialize_value(value):
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, ObjectId):
                return str(value)
            elif hasattr(value, 'isoformat'):  # Para otros objetos con método isoformat
                return value.isoformat()
            elif isinstance(value, dict):
                return self._serialize_for_websocket(value)
            elif isinstance(value, list):
                return [serialize_value(item) for item in value]
            else:
                return value
        
        serialized = {}
        for key, value in data.items():
            try:
                serialized[key] = serialize_value(value)
            except (TypeError, AttributeError) as e:
                logger.warning(f"Error serializing key {key}: {str(e)}")
                serialized[key] = str(value)  # Fallback a string
        
        return serialized

    async def connect(self, websocket: WebSocket, post_id: str):
        await websocket.accept()
        self.active_connections[post_id].append(websocket)
    
    def is_connected(self, websocket: WebSocket, channel_id: str) -> bool:
        """Verifica si ya existe una conexión para este websocket y channel_id"""
        if channel_id not in self.active_connections:
            return False
        return websocket in self.active_connections[channel_id]

    async def connect_image(self, websocket: WebSocket, image_id: str):
        await websocket.accept()
        self.image_connections[image_id].append(websocket)

    async def connect(self, websocket: WebSocket, channel_id: str):
        """Acepta la conexión solo si no ha sido aceptada antes"""
        if id(websocket) not in self.accepted_websockets:
            await websocket.accept()
            self.accepted_websockets.add(id(websocket))
        
        async with self._lock:
            if channel_id not in self.active_connections:
                self.active_connections[channel_id] = []
            self.active_connections[channel_id].append(websocket)
    
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
    
    async def disconnect_image(self, websocket: WebSocket, image_id: str):
        """Desconecta un websocket de una imagen específica"""
        try:
            if image_id in self.image_connections:
                # Remover el websocket de la lista
                if websocket in self.image_connections[image_id]:
                    self.image_connections[image_id].remove(websocket)
                    logger.info(f"🔌 Websocket desconectado de imagen {image_id}")
                    
                    # Cerrar la conexión si está abierta
                    try:
                        await websocket.close()
                        logger.info(f"🚪 Conexión WebSocket cerrada para imagen {image_id}")
                    except Exception as e:
                        logger.error(f"⚠️ Error cerrando WebSocket: {str(e)}")
                    
                    # Eliminar la lista si está vacía
                    if not self.image_connections[image_id]:
                        del self.image_connections[image_id]
                        logger.info(f"🧹 Lista de conexiones para imagen {image_id} eliminada (vacía)")
        except Exception as e:
            logger.error(f"❌ Error en disconnect_image: {str(e)}")
            raise
    
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
                try:
                    await connection.send_json(event_data)
                    logger.info(f"Evento enviado para post {post_id}: {event_data}")
                except Exception as e:
                    logger.error(f"Error enviando evento para post {post_id}: {str(e)}")
                
    async def broadcast_notification(self, user_id: str, notification: Union[Notification, dict]):
        print(f"🔔 Intentando enviar notificación a usuario {user_id}")
        if user_id in self.active_user_connections:
            try:
                print(f"✅ Usuario {user_id} tiene {len(self.active_user_connections[user_id])} conexiones activas") 
                # Conversión segura a Notification
                if isinstance(notification, dict):
                    notification["_id"] = str(notification["_id"])  # Convertir ObjectId a string
                    notification["user_id"] = str(notification.get("user_id", ""))
                    notification["emitter_id"] = str(notification.get("emitter_id", ""))
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
                        
    async def broadcast_profile_update(self, user_id: str, user_data: dict):
        """Envía una actualización de perfil a todos los clientes conectados"""
        try:
            print(f"🔄 Enviando actualización de perfil para usuario {user_id} a todas las conexiones")
            for current_user_id in list(self.active_user_connections.keys()):
                for connection in self.active_user_connections[current_user_id].copy():
                    try:
                        await connection.send_json({
                            "event": "profile_updated",
                            "data": user_data
                        })
                        print(f"✅ Actualización de perfil enviada a conexión de usuario {current_user_id}")
                    except Exception as e:
                        logger.error(f"Error enviando actualización de perfil: {str(e)}")
                        await self.disconnect_user(connection, current_user_id)
        except Exception as e:
            logger.error(f"Error procesando actualización de perfil: {str(e)}")
    
    async def broadcast_image_comment(self, image_id: str, comment: dict):
        if image_id in self.image_connections:
            # Serialización segura
            serializable_comment = self._serialize_for_websocket(comment)
            
            for connection in self.image_connections[image_id]:
                try:
                    await connection.send_json({
                        "event": "new_image_comment",
                        "data": serializable_comment
                    })
                except Exception as e:
                    logger.error(f"Error broadcasting comment to image {image_id}: {str(e)}")
                    await self.disconnect_image(connection, image_id)

    async def broadcast_image_update(self, image_id: str, data: dict):
        logger.info(f"🔵 Iniciando broadcast_image_update para imagen {image_id}")
        logger.info(f"📡 Datos a transmitir: {data}")
        
        if image_id not in self.image_connections:
            logger.warning(f"⚠️ No hay conexiones activas para la imagen {image_id}")
            return
            
        # Convertir datetimes a strings ISO format
        serializable_data = {
            **data,
            'created_at': data['created_at'].isoformat() if 'created_at' in data else None,
            'updated_at': data['updated_at'].isoformat() if 'updated_at' in data else None
        }
        
        logger.info(f"🔄 Datos serializados: {serializable_data}")
        
        for i, connection in enumerate(self.image_connections[image_id]):
            try:
                message = {
                    "event": "image_updated",
                    "data": {
                        "image_id": image_id,
                        "likes_count": serializable_data.get("likes_count", 0),
                        "liked_by": serializable_data.get("liked_by", []),
                        "timestamp": serializable_data.get("updated_at")
                    }
                }
                logger.info(f"📤 Enviando mensaje {i+1}/{len(self.image_connections[image_id])}")
                await connection.send_json(message)
                logger.info("✅ Mensaje enviado exitosamente")
            except Exception as e:
                logger.error(f"❌ Error enviando actualización: {str(e)}")
                self.disconnect_image(connection, image_id)

# Instancia global para ser usada en otros archivos
manager = WebSocketManager()