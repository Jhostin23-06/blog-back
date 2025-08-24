from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.auth import require_role, UserRole, optional_auth
from app.database import db
from app.models.comment_model import Comment, CommentCreate
from typing import List, Optional
from datetime import datetime, timezone
import pytz
import logging
from app.websocket_manager import manager  # Importa el manager aquí

logger = logging.getLogger(__name__)

# Configura la zona horaria de Perú
PERU_TIMEZONE = pytz.timezone('America/Lima')

router = APIRouter(prefix="/comments", tags=["comments"])

def get_peru_time():
    return datetime.now(PERU_TIMEZONE)

def format_peru_time(dt: datetime):
    """Formatea datetime para mantener la zona horaria de Perú"""
    if dt.tzinfo is None:
        # Si no tiene zona horaria, asumimos que es UTC y convertimos
        dt = pytz.utc.localize(dt).astimezone(PERU_TIMEZONE)
    return dt.isoformat()



@router.post("/", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_data: CommentCreate,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        post_id = comment_data.post_id
        post_object_id = ObjectId(post_id)
        
        # Verificar si el post existe
        post = await db.posts.find_one({"_id": post_object_id})
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post no encontrado"
            )
        
        # Crear el comentario con los datos del usuario
        peru_time = get_peru_time()
        comment_dict = comment_data.dict()
        comment_dict.update({
            "author_id": str(current_user["_id"]),
            "author_username": current_user.get("username", ""),
            "author_profile_picture": current_user.get("profile_picture", ""),
            "created_at": peru_time
        })
        
        # Insertar el comentario
        result = await db.comments.insert_one(comment_dict)
        
        # Obtener y devolver el comentario creado
        created_comment = await db.comments.find_one({"_id": result.inserted_id})
        created_comment["_id"] = str(created_comment["_id"])
        created_comment["created_at"] = format_peru_time(created_comment["created_at"])
        
        # Incrementar el contador de comentarios en el post
        await db.posts.update_one(
            {"_id": post_object_id},
            {"$inc": {"comments_count": 1}},
            upsert=True
        )

        # Emitir el comentario via WebSocket - SOLO SI HAY CONEXIONES
        try:
            await manager.broadcast_comment(post_id, created_comment)
            logger.info(f"Comentario broadcasted para post {post_id}")
        except Exception as e:
            logger.error(f"Error en broadcast_comment: {str(e)}")
            # NO relanzar la excepción - permitir que la operación continue 
        
        # Crear notificación si no es comentario propio
        if str(post["author_id"]) != str(current_user["_id"]):
            post_author = await db.users.find_one({"_id": ObjectId(post["author_id"])})

            notification = {
                "user_id": str(post["author_id"]),
                "emitter_id": str(current_user["_id"]),
                "emitter_username": current_user.get("username", "Usuario"),
                "post_id": str(post["_id"]),
                "comment_id": str(result.inserted_id),
                "type": "comment",
                "message": f"{current_user['username']} comentó en tu publicación: {comment_data.content[:30]}...",
                "read": False,
                "created_at": get_peru_time(),  # ← También usar hora Perú aquí
                # AGREGAR TODA LA INFORMACIÓN DEL POST (igual que para likes)
                "post_id": post_id,
                "post_title": post.get("title", ""),
                "post_content": post.get("content", ""),
                "post_author_id": str(post["author_id"]),
                "post_author_username": post_author.get("username", "Usuario") if post_author else "Usuario",
                "post_author_profile_picture": post_author.get("profile_picture", "") if post_author else "",
                "post_image_url": post.get("image_url", ""),
                "post_likes_count": post.get("likes_count", 0),
                "post_comments_count": post.get("comments_count", 0) + 1,  # +1 porque acabamos de agregar un comentario
                "post_liked_by": post.get("liked_by", []),
                "post_created_at": post.get("created_at", datetime.utcnow()),
                "post_updated_at": post.get("updated_at", datetime.utcnow())
            }
        
            notification_result = await db.notifications.insert_one(notification)
            notification["_id"] = str(notification_result.inserted_id)  # Convertir _id a string
            await manager.broadcast_notification(
                str(post["author_id"]),
                notification
            )
        
        # Emitir el comentario via WebSocket
        await manager.broadcast_comment(post_id, created_comment)
        
        return created_comment
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de post inválido"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/post/{post_id}", response_model=List[Comment])
async def get_comments(
    post_id: str,
    skip: int = 0,
    limit: int = 100,
    current_user: Optional[dict] = Depends(optional_auth)
):
    try:
        post_object_id = ObjectId(post_id)
        # Verificar si el post existe
        post = await db.posts.find_one({"_id": post_object_id})
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Post no encontrado"
            )
        
        # Usar agregación para obtener comentarios con información del autor
        pipeline = [
            {"$match": {"post_id": post_id}},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"author_id_str": "$author_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$eq": [
                                        {"$toString": "$_id"},
                                        "$$author_id_str"
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "author_info"
                }
            },
            {
                "$addFields": {
                    "author_profile_picture": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$author_info.profile_picture", 0]},
                            ""
                        ]
                    }
                }
            },
            {"$unset": "author_info"}  # Remover el array temporal
        ]
        
        # Obtener comentarios paginados
        cursor = db.comments.find({"post_id": post_id}) \
            .sort("created_at", -1) \
            .skip(skip) \
            .limit(limit)
        
        comments = []
        async for comment in db.comments.aggregate(pipeline):
            comment["_id"] = str(comment["_id"])
            # Aplicar formato de hora Perú a cada comentario ← ¡ESTA LÍNEA FALTABA!
            comment["created_at"] = format_peru_time(comment["created_at"])
            comments.append(comment)
            
        return comments
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de post inválido"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        comment_object_id = ObjectId(comment_id)
            
        # Verificar si el comentario existe
        comment = await db.comments.find_one({"_id": comment_object_id})
        
        if not comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comentario no encontrado"
            )
            
        # Verificar permisos (solo el autor o un admin puede borrar)
        is_author = str(comment.get("author_id")) == str(current_user["_id"])
        is_admin = current_user.get("role") == UserRole.ADMIN
        
        if not (is_author or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para eliminar este comentario"
            )
        
        # Eliminar el comentario
        result = await db.comments.delete_one({"_id": comment_object_id})
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo eliminar el comentario"
            )
        
        # Decrementar el contador de comentarios en el post
        post_id = comment.get("post_id")
        if post_id:
            await db.posts.update_one(
                {"_id": ObjectId(post_id)},
                {"$inc": {"comments_count": -1}}
            )
        
        return None
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID inválido"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )