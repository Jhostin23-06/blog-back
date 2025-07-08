from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.auth import require_role, UserRole, optional_auth
from app.database import db
from app.models.comment_model import Comment, CommentCreate
from typing import List, Optional
from datetime import datetime
from app.websocket_manager import manager  # Importa el manager aquí


router = APIRouter(prefix="/comments", tags=["comments"])

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
        comment_dict = comment_data.dict()
        comment_dict.update({
            "author_id": str(current_user["_id"]),
            "author_username": current_user.get("username", ""),
            "created_at": datetime.utcnow()
        })
        
        # Insertar el comentario
        result = await db.comments.insert_one(comment_dict)
        
        # Obtener y devolver el comentario creado
        created_comment = await db.comments.find_one({"_id": result.inserted_id})
        created_comment["_id"] = str(created_comment["_id"])
        created_comment["created_at"] = created_comment["created_at"].isoformat()
        
        # Incrementar el contador de comentarios en el post
        await db.posts.update_one(
            {"_id": post_object_id},
            {"$inc": {"comments_count": 1}},
            upsert=True
        )
        
        # Crear notificación si no es comentario propio
        if str(post["author_id"]) != str(current_user["_id"]):
            notification = {
                "user_id": str(post["author_id"]),
                "emitter_id": str(current_user["_id"]),
                "emitter_username": current_user.get("username", "Usuario"),
                "post_id": str(post["_id"]),
                "comment_id": str(result.inserted_id),
                "type": "comment",
                "message": f"{current_user['username']} comentó en tu publicación: {comment_data.content[:30]}...",
                "read": False,
                "created_at": datetime.utcnow()
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
        
        # Obtener comentarios paginados
        cursor = db.comments.find({"post_id": post_id}) \
            .sort("created_at", -1) \
            .skip(skip) \
            .limit(limit)
        
        comments = []
        async for comment in cursor:
            comment["_id"] = str(comment["_id"])
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