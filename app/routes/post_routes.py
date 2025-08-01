from fastapi import APIRouter, Depends, HTTPException, status, Query, WebSocket
from bson import ObjectId
from app.auth import require_role, UserRole, optional_auth
from app.database import db
from app.models.post_model import Post, UserPostsResponse
from typing import List, Optional
from ..websocket_manager import manager  # Importa el manager de WebSocket
from datetime import datetime
import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/posts", response_model=List[dict])
async def get_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, le=100),
    current_user: Optional[dict] = Depends(optional_auth)
):
    # Usar agregación para hacer JOIN con users en una sola consulta
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "users",
                "localField": "author_id",
                "foreignField": "_id",
                "as": "author_info"
            }
        },
        {
            "$addFields": {
                "profile_picture": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$author_info.profile_picture", 0]},
                        ""
                    ]
                },
                "username": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$author_info.username", 0]},
                        ""
                    ]
                }
            }
        },
        {"$unset": "author_info"}  # Remover el array temporal
    ]
    
    posts = []
    async for post in db.posts.aggregate(pipeline):
        # Convertir ObjectId a string
        post["_id"] = str(post["_id"])
        post["author_id"] = str(post["author_id"])
        
        # Verificar likes si hay usuario autenticado
        liked_by = [str(user) for user in post.get("liked_by", [])]
        post["has_liked"] = current_user and str(current_user["_id"]) in liked_by
        post["liked_by"] = liked_by
        
        posts.append(post)
    
    return posts

@router.get("/posts/user/{user_id}", response_model=UserPostsResponse)
async def get_user_posts(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, le=100),
    current_user: Optional[dict] = Depends(optional_auth)
):
    try:
        user_object_id = ObjectId(user_id)
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de usuario inválido"
        )
    
    # Verificar si el usuario existe y obtener posts en una sola agregación
    pipeline = [
        {"$match": {"_id": user_object_id}},
        {
            "$lookup": {
                "from": "posts",
                "let": {"user_id_str": {"$toString": "$_id"}},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$author_id", "$$user_id_str"]}}},
                    {"$sort": {"created_at": -1}},
                    {"$skip": skip},
                    {"$limit": limit}
                ],
                "as": "user_posts"
            }
        },
        {
            "$lookup": {
                "from": "posts",
                "let": {"user_id_str": {"$toString": "$_id"}},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$author_id", "$$user_id_str"]}}},
                    {"$count": "total"}
                ],
                "as": "total_count"
            }
        }
    ]
    
    result = await db.users.aggregate(pipeline).to_list(1)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    user_data = result[0]
    posts = []
    
    for post in user_data.get("user_posts", []):
        liked_by = [str(user) for user in post.get("liked_by", [])]
        post_dict = {
            "_id": str(post["_id"]),
            "title": post["title"],
            "content": post["content"],
            "author_id": str(post.get("author_id", "")),
            "author_username": user_data["username"],
            "created_at": post["created_at"],
            "likes_count": post.get("likes_count", 0),
            "liked_by": liked_by,
            "comments_count": post.get("comments_count", 0),
            "author_profile_picture": user_data.get("profile_picture", ""),
            "has_liked": current_user and str(current_user["_id"]) in liked_by
        }
        posts.append(post_dict)
    
    total_count_data = user_data.get("total_count", [])
    total_posts = total_count_data[0].get("total", 0) if total_count_data else 0
    
    return {
        "posts": posts,
        "total_posts": total_posts,
        "skip": skip,
        "limit": limit
    }

@router.get("/posts/{post_id}", response_model=dict)
async def get_post(post_id: str):
    """
    Obtiene un post específico por su ID.
    """
    try:
        post_object_id = ObjectId(post_id)
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de post inválido"
        )
    
    post = await db.posts.find_one({"_id": post_object_id})
    
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post no encontrado"
        )
    
    # Convertir ObjectId a string para la respuesta
    post["id"] = str(post["_id"])
    post["author_id"] = str(post["author_id"])
    
    return post

@router.post("/posts")
async def create_post(
    post: Post,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    # Obtener el usuario completo para acceder al username
    user = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Crear el diccionario del post con el author_username
    post_data = post.dict()
    post_data["author_id"] = str(current_user["_id"])
    post_data["author_username"] = user["username"]
    post_data["author_profile_picture"] = user["profile_picture"]
    
    # Insertar el post en la base de datos
    result = await db.posts.insert_one(post_data)
    
    # Obtener el post creado para devolverlo
    created_post = await db.posts.find_one({"_id": result.inserted_id})
    
    # Convertir ObjectId a string para la respuesta
    created_post["_id"] = str(created_post["_id"])
    created_post["author_id"] = str(created_post["author_id"])
    
    # Broadcast del nuevo post a todos los usuarios conectados
    await manager.broadcast_new_post(created_post)
    
    return {
        "message": "Post creado exitosamente",
        "post": created_post
    }

@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    token_data: dict = Depends(require_role(UserRole.USER))
):
    try:
        post_object_id = ObjectId(post_id)
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de post inválido"
        )
        
    # Primero verificar si el post existe
    post = await db.posts.find_one({"_id": post_object_id})
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post no encontrado"
        )
        
    # Eliminar todos los comentarios asociados al post
    delete_comments_result = await db.comments.delete_many({"post_id": post_id})
    print(f"Eliminados {delete_comments_result.deleted_count} comentarios del post {post_id}")
    
    # Eliminar todas las notificaciones relacionadas con el post
    delete_notifications_result = await db.notifications.delete_many({
        "$or": [
            {"related_post_id": post_id},  # Notificaciones directas sobre el post
            {"post_id": post_id}          # Notificaciones sobre comentarios en el post
        ]
    })
    print(f"Eliminadas {delete_notifications_result.deleted_count} notificaciones relacionadas con el post {post_id}")
    
    delete_result = await db.posts.delete_one({"_id": post_object_id})
    
    if delete_result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post no encontrado"
        )
    
    # Broadcast del post eliminado a todos los usuarios conectados
    await manager.broadcast_deleted_post(post_id)
    
    return {
        "message": "Post y sus comentarios eliminados exitosamente",
        "deleted_comments": delete_comments_result.deleted_count,
        "deleted_notifications": delete_notifications_result.deleted_count
    }

@router.post("/posts/{post_id}/like")
async def like_post(
    post_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        post_object_id = ObjectId(post_id)
        user_id = str(current_user["_id"])
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID inválido"
        )
    
    # Verificar si el post existe
    post = await db.posts.find_one({"_id": post_object_id})
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post no encontrado"
        )
    
    # Verificar si el usuario ya dio like
    if user_id in post.get("liked_by", []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya has dado like a este post"
        )
    
    # Actualizar el post
    update_result = await db.posts.update_one(
        {"_id": post_object_id},
        {
            "$inc": {"likes_count": 1},
            "$push": {"liked_by": user_id}
        }
    )
    
    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo actualizar el post"
        )
    
    # Obtener el post actualizado
    updated_post = await db.posts.find_one({"_id": post_object_id})
    updated_post["_id"] = str(updated_post["_id"])
    
    
    # Emitir evento WebSocket
    await manager.broadcast_event(
        post_id,
        {
            "event": "post_updated",
            "data": {
                "post_id": post_id,
                "likes_count": updated_post["likes_count"],
                "liked_by": updated_post.get("liked_by", [])
            }
        }
    )
    
    # Crear notificación si no es like propio
    if str(post["author_id"]) != str(current_user["_id"]):
        notification = {
            "user_id": str(post["author_id"]),
            "emitter_id": str(current_user["_id"]),
            "type": "like",
            "message": f"A {current_user['username']} le gusta tu publicación",
            "related_post_id": post_id,
            "created_at": datetime.now(),
            "read": False
        }
        
        try:
            # Guardar en base de datos
            result = await db.notifications.insert_one(notification)
            print(result)
            notification["_id"] = str(result.inserted_id)
            
            # Asegurarse de que el emisor tenga un username
            emitter = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
            notification["emitter_username"] = emitter.get("username", "Usuario")
        
            # Enviar por WebSocket
            await manager.broadcast_notification(
                str(post["author_id"]),
                notification
            )
            print("Notificación enviada exitosamente")
        except Exception as e:
            print(f"Error al enviar notificación: {str(e)}")
    
    return {"message": "Like agregado exitosamente"}

@router.post("/posts/{post_id}/unlike")
async def unlike_post(
    post_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        post_object_id = ObjectId(post_id)
        user_id = str(current_user["_id"])
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID inválido"
        )
    
    post = await db.posts.find_one({"_id": post_object_id})
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post no encontrado"
        )
    
    if user_id not in post.get("liked_by", []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No has dado like a este post"
        )
    
    update_result = await db.posts.update_one(
        {"_id": post_object_id},
        {
            "$inc": {"likes_count": -1},
            "$pull": {"liked_by": user_id}
        }
    )
    
    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo actualizar el post"
        )
    
    # Obtener el post actualizado
    updated_post = await db.posts.find_one({"_id": post_object_id})
    updated_post["_id"] = str(updated_post["_id"])
    
    # Emitir evento WebSocket
    await manager.broadcast_event(
        post_id,
        {
            "event": "post_updated",
            "data": {
                "post_id": post_id,
                "likes_count": updated_post["likes_count"],
                "liked_by": updated_post.get("liked_by", [])
            }
        }
    )
    
    return {"message": "Like removido exitosamente"}