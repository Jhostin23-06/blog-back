from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.database import db
from app.auth import require_role, UserRole
from app.models.notification_model import NotificationCreate, NotificationType
from app.websocket_manager import manager
from datetime import datetime
from typing import List


router = APIRouter(prefix="/friends", tags=["Friends"])

@router.post("/request/{user_id}")
async def send_friend_request(
    user_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        # Validación de IDs
        current_user_id = ObjectId(current_user["_id"])
        target_oid = ObjectId(user_id)
        
        print(f"DEBUG - Current user ID: {current_user_id}, Target ID: {target_oid}")

        # Verificaciones previas
        if target_oid == current_user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes enviarte solicitud a ti mismo")

        
        # Verificar si ya existe alguna relación
        current_user_data = await db.users.find_one({"_id": current_user_id})
        target_user_data = await db.users.find_one({"_id": target_oid})
        
        # Verificar relaciones existentes
        current_rels = current_user_data.get("relationships", {})
        target_rels = target_user_data.get("relationships", {})
        
        if str(target_oid) in current_rels:
            if current_rels[str(target_oid)] == "friend":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya son amigos")
            elif current_rels[str(target_oid)] == "request_sent":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya enviaste solicitud a este usuario")
        
        # Actualizar relaciones
        await db.users.update_one(
            {"_id": current_user_id},
            {"$set": {f"relationships.{str(target_oid)}": "request_sent"}}
        )
        
        await db.users.update_one(
            {"_id": target_oid},
            {"$set": {f"relationships.{str(current_user_id)}": "request_received"}}
        )

        # Notificación
        notification = {
            "_id": str(ObjectId()),  # Asegúrate de incluir un ID
            "user_id": str(target_oid),
            "emitter_id": str(current_user_id),
            "emitter_username": current_user["username"],
            "type": NotificationType.FRIEND_REQUEST.value,
            "message": f"{current_user['username']} te envió una solicitud de amistad",
            "read": False,
            "created_at": datetime.utcnow()
        }

        await db.notifications.insert_one(notification)
        await manager.broadcast_notification(str(target_oid), notification)

        return {
            "message": "Solicitud enviada exitosamente",
            "relationships": (await db.users.find_one({"_id": current_user_id})).get("relationships", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR DETAIL: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Error interno: {str(e)}")

@router.post("/accept/{user_id}")
async def accept_friend_request(
    user_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        requester_oid = ObjectId(user_id)
        current_user_oid = ObjectId(current_user["_id"])
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de usuario inválido"
        )
    
    # Obtener datos actuales del usuario
    current_user_data = await db.users.find_one({"_id": current_user_oid})
    if not current_user_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    
    # Debug: Mostrar relaciones actuales
    print(f"Relaciones del usuario actual: {current_user_data.get('relationships')}")
    
    # Verificar que existe la solicitud en relationships
    relationships = current_user_data.get("relationships", {})
    if str(requester_oid) not in relationships:
        print(f"No existe relación con el usuario {requester_oid}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No existe relación con este usuario"
        )
    
    if relationships.get(str(requester_oid)) != "request_received":
        print(f"Relación existente: {relationships.get(str(requester_oid))} (se esperaba 'request_received')")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay solicitud pendiente de este usuario o ya fue procesada"
        )
    
    # Verificar que el remitente existe
    requester_data = await db.users.find_one({"_id": requester_oid})
    if not requester_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario remitente no encontrado")
    
    # Debug: Mostrar relaciones del remitente
    print(f"Relaciones del remitente: {requester_data.get('relationships')}")
    
    # Actualizar relaciones en ambos usuarios
    async with await db.client.start_session() as session:
        try:
            async with session.start_transaction():
                # Actualizar usuario actual (aceptante)
                await db.users.update_one(
                    {"_id": current_user_oid},
                    {
                        "$set": {f"relationships.{str(requester_oid)}": "friend"},
                        "$pull": {"friend_requests": str(requester_oid)}  # Limpiar array antiguo
                    },
                    session=session
                )
                
                # Actualizar remitente
                await db.users.update_one(
                    {"_id": requester_oid},
                    {
                        "$set": {f"relationships.{str(current_user_oid)}": "friend"},
                        "$pull": {"sent_requests": str(current_user_oid)}  # Limpiar array antiguo
                    },
                    session=session
                )
                
                # Crear notificación
                notification = {
                    "user_id": str(requester_oid),
                    "emitter_id": str(current_user_oid),
                    "emitter_username": current_user["username"],
                    "type": NotificationType.FRIEND_ACCEPTED.value,
                    "message": f"{current_user['username']} aceptó tu solicitud de amistad",
                    "read": False,
                    "created_at": datetime.utcnow()
                }
                
                await db.notifications.insert_one(notification, session=session)
                await manager.broadcast_notification(str(requester_oid), notification)
                
        except Exception as e:
            await session.abort_transaction()
            logger.error(f"Error en transacción: {str(e)}")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error en la transacción")
    
    # Obtener y devolver estado actualizado
    updated_user = await db.users.find_one({"_id": current_user_oid})
    return {
        "message": "Solicitud aceptada. ¡Ahora son amigos!",
        "relationships": updated_user.get("relationships", {})
    }

@router.post("/reject/{user_id}")
async def reject_friend_request(
    user_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        requester_oid = ObjectId(user_id)
        current_user_oid = ObjectId(current_user["_id"])
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de usuario inválido"
        )
    
    # Verificar que existe la solicitud
    current_user_data = await db.users.find_one({"_id": current_user_oid})
    if not current_user_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    
    relationships = current_user_data.get("relationships", {})
    if str(requester_oid) not in relationships or relationships[str(requester_oid)] != "request_received":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay solicitud pendiente de este usuario"
        )
    
    # Actualizar ambos usuarios
    await db.users.update_one(
        {"_id": current_user_oid},
        {
            "$unset": {f"relationships.{str(requester_oid)}": ""},
            "$pull": {"friend_requests": user_id}  # Mantener por compatibilidad
        }
    )
    
    await db.users.update_one(
        {"_id": requester_oid},
        {
            "$unset": {f"relationships.{str(current_user_oid)}": ""},
            "$pull": {"sent_requests": str(current_user["_id"])}  # Mantener por compatibilidad
        }
    )
    
    return {
        "message": "Solicitud rechazada",
        "relationships": (await db.users.find_one({"_id": current_user_oid})).get("relationships", {})
    }

@router.get("/", response_model=List[dict])
async def get_friends(
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        current_user_oid = ObjectId(current_user["_id"])
        current_user_data = await db.users.find_one({"_id": current_user_oid})
        
        if not current_user_data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
        
        # Obtener todos los amigos (donde la relación es "friend")
        relationships = current_user_data.get("relationships", {})
        friend_ids = [
            user_id for user_id, rel_type in relationships.items()
            if rel_type == "friend"
        ]
        
        if not friend_ids:
            return []
        
        # Obtener información de los amigos
        friends = await db.users.find(
            {"_id": {"$in": [ObjectId(id) for id in friend_ids]}},
            {"username": 1, "profile_picture": 1, "bio": 1, "cover_photo": 1}
        ).to_list(None)
        
        return [{
            "id": str(friend["_id"]),
            "username": friend["username"],
            "profile_picture": friend.get("profile_picture", ""),
            "bio": friend.get("bio", ""),
            "cover_photo": friend.get("cover_photo", "")
        } for friend in friends]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_friends: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener la lista de amigos"
        )

@router.get("/requests", response_model=List[dict])
async def get_friend_requests(
    skip: int = 0,
    limit: int = 10,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        user_data = await db.users.find_one(
            {"_id": ObjectId(current_user["_id"])},
            {"relationships": 1}  # Solo obtenemos el campo relationships
        )
        
        if not user_data:
            return []
            
        # Buscar relaciones donde el valor es "request_received"
        request_ids = [
            user_id for user_id, rel_type in user_data.get("relationships", {}).items()
            if rel_type == "request_received"
        ]
        
        if not request_ids:
            return []
            
        # Obtener información básica de los usuarios
        users = await db.users.find(
            {"_id": {"$in": [ObjectId(id) for id in request_ids]}},
            {"username": 1, "profile_picture": 1, "bio": 1, "cover_photo": 1}
        ).skip(skip).limit(limit).to_list(None)
        
        return [{
            "id": str(user["_id"]),
            "username": user["username"],
            "profile_picture": user.get("profile_picture", ""),
            "bio": user.get("bio", ""),
            "cover_photo": user.get("cover_photo", "")
        } for user in users]
        
    except Exception as e:
        logger.error(f"Error en get_friend_requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# @router.get("/requests", response_model=List[dict])
# async def get_friend_requests(
#     skip: int = 0,
#     limit: int = 10,
#     current_user: dict = Depends(require_role(UserRole.USER))
# ):
#     try:
#         # Obtener el usuario actual con sus relaciones
#         user_id = current_user["_id"]
#         user_data = await db.users.find_one({"_id": ObjectId(user_id)})
        
#         if not user_data:
#             raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
#         # Extraer IDs de usuarios que han enviado solicitudes (donde el valor es "request_received")
#         request_relations = {
#             user_id: rel_type 
#             for user_id, rel_type in user_data.get("relationships", {}).items()
#             if rel_type == "request_received"
#         }
        
#         request_ids = list(request_relations.keys())
        
#         if not request_ids:
#             return []
        
#         # Convertir a ObjectId y buscar los usuarios
#         object_ids = [ObjectId(id) for id in request_ids]
#         users = await db.users.find(
#             {"_id": {"$in": object_ids}},
#             {"username": 1, "profile_picture": 1}  # Solo obtener los campos necesarios
#         ).skip(skip).limit(limit).to_list(None)
        
#         # Construir la respuesta
#         requests = []
#         for user in users:
#             requests.append({
#                 "id": str(user["_id"]),
#                 "username": user["username"],
#                 "profile_picture": user.get("profile_picture", ""),
#                 # Puedes añadir más campos si los necesitas
#                 "bio": user.get("bio", ""),
#                 "cover_photo": user.get("cover_photo", "")
#             })
        
#         return requests
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error en get_friend_requests: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail="Error al obtener solicitudes de amistad"
#         )