from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.routes import user_routes, post_routes, comment_routes, notifications
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
from app.websocket_manager import manager
from app.auth import get_current_user_websocket
from fastapi import status
from fastapi import Query
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

# Configuración CORS actualizada
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",  # Alternativa para localhost
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
            
# WebSocket Endpoint
@app.websocket("/ws/{post_id}")
async def websocket_endpoint(websocket: WebSocket, post_id: str):
    await manager.connect(websocket, post_id)
    try:
        while True:
            await websocket.receive_text()  # Mantener conexión abierta
    except WebSocketDisconnect:
        manager.disconnect(websocket, post_id)
        
# WebSocket para notificaciones
@app.websocket("/ws/notifications/{user_id}")
async def notifications_websocket(websocket: WebSocket, user_id: str):
    print(f"🔵 Nueva conexión WebSocket para usuario {user_id}")
    await websocket.accept()
    
    try:
        # 1. Esperar mensaje de autenticación
        auth_message = await websocket.receive_json()
        print(f"🔵 Mensaje de autenticación recibido: {auth_message}")
        
        # 2. Validar formato
        if not all(key in auth_message for key in ["type", "token", "userId"]):
            error_msg = "Formato de mensaje inválido"
            print(f"❌ {error_msg}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=error_msg)
            return
            
        # 3. Verificar coincidencia de user_id
        if auth_message["userId"] != user_id:
            error_msg = "ID de usuario no coincide"
            print(f"❌ {error_msg}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=error_msg)
            return
            
        # 4. Validar token JWT
        try:
            user = await get_current_user_websocket(auth_message["token"])
            if str(user["_id"]) != user_id:
                error_msg = "Token inválido para este usuario"
                print(f"❌ {error_msg}")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=error_msg)
                return
        except Exception as auth_error:
            error_msg = "Token inválido"
            print(f"❌ {error_msg}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=error_msg)
            return
        
        # 5. Registrar conexión
        await manager.connect_user(websocket, user_id)
        print(f"✅ Usuario {user_id} autenticado correctamente")
            
        # 6. Confirmar autenticación
        await websocket.send_json({"status": "authenticated"})
        
        # 7. Mantener conexión
        while True:
            try:
                data = await websocket.receive_json()
                print(f"📨 Mensaje recibido: {data}")
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                print(f"❌ WebSocket desconectado para usuario {user_id}")
                await manager.disconnect_user(websocket, user_id)
                break
            except Exception as e:
                print(f"❌ Error en WebSocket: {str(e)}")
                await manager.disconnect_user(websocket, user_id)
                break
                
    except json.JSONDecodeError:
        print(f"❌ Error: Mensaje JSON inválido de {user_id}")
        await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA, reason="Formato de mensaje inválido")
    except Exception as e:
        print(f"❌ Error inesperado en WebSocket: {str(e)}")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Error interno del servidor")
        except:
            pass

app.include_router(user_routes.router, prefix="/api")
app.include_router(post_routes.router, prefix="/api")
app.include_router(comment_routes.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")