from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime
from typing import List, Optional
from app.database import db
from app.auth import require_role, UserRole
from app.models.notification_model import Notification, NotificationCreate, NotificationType
from fastapi.encoders import jsonable_encoder
from app.websocket_manager import manager

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/", response_model=List[Notification])
async def get_user_notifications(
    current_user: dict = Depends(require_role(UserRole.USER)),
    limit: int = 100,
    unread_only: bool = False
):
    """
    Obtiene las notificaciones del usuario actual.
    Parámetros:
    - limit: Límite de notificaciones a devolver (default: 100)
    - unread_only: Si True, devuelve solo las no leídas
    """
    query = {"user_id": str(current_user["_id"])}
    
    if unread_only:
        query["read"] = False
    
    notifications = []
    async for notif in db.notifications.find(query).sort("created_at", -1).limit(limit):
        # Asegurarse de que todos los campos requeridos estén presentes
        if "message" not in notif:
            notif["message"] = ""  # O algún valor por defecto
        if "emitter_username" not in notif:
            # Obtener el username del emisor si no está en la notificación
            emitter = await db.users.find_one({"_id": ObjectId(notif["emitter_id"])})
            notif["emitter_username"] = emitter.get("username", "Usuario") if emitter else "Usuario"
        
        # Asegurar campos opcionales para imágenes
        notif.setdefault("image_id", None)
        notif.setdefault("image_url", None)
        notif.setdefault("image_owner_id", None)
        notif.setdefault("image_created_at", None)
        notif.setdefault("post_id", None)
        notif.setdefault("comment_id", None)

        # Asegurar campos del post
        notif.setdefault("post_title", "")
        notif.setdefault("post_content", "")
        notif.setdefault("post_author_id", "")
        notif.setdefault("post_author_username", "Usuario")
        notif.setdefault("post_author_profile_picture", "")
        notif.setdefault("post_image_url", "")
        notif.setdefault("post_likes_count", 0)
        notif.setdefault("post_comments_count", 0)
        notif.setdefault("post_liked_by", [])
        notif.setdefault("post_created_at", datetime.utcnow())
        notif.setdefault("post_updated_at", datetime.utcnow())

        # Convertir ObjectId a string
        notif["_id"] = str(notif["_id"])
        
        # Asegurarse de que los campos opcionales estén presentes
        notif.setdefault("post_id", None)
        notif.setdefault("comment_id", None)
        
        notifications.append(notif)
    
    return jsonable_encoder(notifications)

@router.post("/mark-as-read", response_model=dict)
async def mark_notifications_as_read(
    notification_ids: List[str],
    current_user: dict = Depends(require_role(UserRole.USER))
):
    """
    Marca notificaciones como leídas.
    """
    if not notification_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar al menos un ID de notificación"
        )
    
    try:
        object_ids = [ObjectId(id) for id in notification_ids]
        
        update_result = await db.notifications.update_many(
            {
                "_id": {"$in": object_ids},
                "user_id": str(current_user["_id"])  # Asegurar que pertenecen al usuario
            },
            {"$set": {"read": True, "read_at": datetime.utcnow()}}
        )
        
        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontraron notificaciones para marcar"
            )
            
        return {
            "status": "success",
            "message": f"{update_result.modified_count} notificaciones marcadas como leídas"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al procesar los IDs: {str(e)}"
        )

@router.get("/unread-count", response_model=dict)
async def get_unread_count(
    current_user: dict = Depends(require_role(UserRole.USER))
):
    """
    Obtiene el conteo de notificaciones no leídas del usuario
    """
    count = await db.notifications.count_documents({
        "user_id": str(current_user["_id"]),
        "read": False
    })
    
    return {"count": count}