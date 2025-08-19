# routes/images.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from app.utils.util import upload_file_to_storage
from bson import ObjectId
from app.auth import require_role, UserRole
from app.database import db 
from app.models.image_model import Image, ImageCreate, ImageType, ImageComment, ImageCommentCreate
from datetime import datetime
from app.websocket_manager import manager
from typing import List, Optional
import logging
import pytz

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PERU_TIMEZONE = pytz.timezone('America/Lima')

router = APIRouter(prefix="/images", tags=["images"])

def get_peru_time():
    return datetime.now(PERU_TIMEZONE)

def format_peru_time(dt: datetime):
    """Formatea datetime para mantener la zona horaria de Perú"""
    if dt.tzinfo is None:
        # Si no tiene zona horaria, asumimos que es UTC y convertimos
        dt = pytz.utc.localize(dt).astimezone(PERU_TIMEZONE)
    return dt.isoformat()

@router.post("/profile-picture", response_model=Image, status_code=status.HTTP_201_CREATED)
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role(UserRole.USER))
):
    # 1. Subir el archivo a tu servicio de almacenamiento
    file_url = await upload_file_to_storage(file, "profile_pictures")
    
    # 2. Crear registro en base de datos
    image_data = ImageCreate(
        url=file_url,
        image_type=ImageType.PROFILE_PICTURE,
        owner_id=str(current_user["_id"]),
        created_at=  get_peru_time()
    )
    
    # 3. Insertar nueva imagen
    result = await db.images.insert_one(image_data.dict())
    new_image_id = str(result.inserted_id)
    
    # 4. Actualizar usuario para apuntar a esta imagen
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"current_profile_picture": new_image_id, "profile_picture": file_url}}  # Asegúrate de guardar también la URL directa
    )

    # 5. Actualizar todos los posts del usuario con la nueva imagen de perfil
    await db.posts.update_many(
        {"author_id": str(current_user["_id"])},
        {"$set": {
            "author_profile_picture": file_url
        }}
    )

    # 6. Obtener el usuario actualizado para la notificación
    updated_user = await db.users.find_one({"_id": ObjectId(current_user["_id"])})

    # 7. Preparar datos para la notificación
    user_data = {
        "id": str(updated_user["_id"]),
        "username": updated_user["username"],
        "profile_picture": file_url,
        "current_profile_picture": new_image_id,
        "updated_at":  get_peru_time()
    }

    # 8. Enviar notificación a través de WebSocket
    await manager.broadcast_profile_update(str(updated_user["_id"]), user_data)
    
    # 5. Devolver la imagen creada
    created_image = await db.images.find_one({"_id": result.inserted_id})
    created_image["_id"] = str(created_image["_id"])
    return created_image

@router.post("/cover-photo", response_model=Image, status_code=status.HTTP_201_CREATED)
async def upload_cover_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_role(UserRole.USER))
):
    # Similar al anterior pero para cover photo
    file_url = await upload_file_to_storage(file, "cover_photos")
    date = datetime.utcnow()
    
    image_data = ImageCreate(
        url=file_url,
        image_type=ImageType.COVER_PHOTO,
        owner_id=str(current_user["_id"]),
        created_at= get_peru_time()
    )
    
    result = await db.images.insert_one(image_data.dict())
    new_image_id = str(result.inserted_id)
    
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"current_cover_photo": new_image_id}}
    )
    
    created_image = await db.images.find_one({"_id": result.inserted_id})
    created_image["_id"] = str(created_image["_id"])
    return created_image


@router.get("/{image_id}", response_model=Image)
async def get_image_details(image_id: str):
    """
    Obtiene los detalles de una imagen (acceso público de solo lectura)
    """
    try:
        image = await db.images.find_one({"_id": ObjectId(image_id)})
        
        if not image:
            raise HTTPException(status_code=404, detail="Imagen no encontrada")
        
        image["_id"] = str(image["_id"])
        return image
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/user/{user_id}", response_model=List[Image])
async def get_user_images(
    user_id: str,
    image_type: Optional[ImageType] = None
):
    """
    Obtiene todas las imágenes de un usuario (público)
    Puede filtrarse por tipo de imagen si se especifica
    """
    try:
        query = {"owner_id": user_id}
        if image_type:
            query["image_type"] = image_type
            
        images = []
        async for image in db.images.find(query).sort("created_at", -1):
            image["_id"] = str(image["_id"])
            images.append(image)
            
        return images
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    image_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    """
    Elimina una imagen (solo el propietario puede hacerlo)
    """
    try:
        # 1. Verificar que la imagen existe y pertenece al usuario
        image = await db.images.find_one({"_id": ObjectId(image_id)})
        if not image:
            raise HTTPException(status_code=404, detail="Imagen no encontrada")
            
        if image["owner_id"] != str(current_user["_id"]):
            raise HTTPException(status_code=403, detail="No tienes permiso para eliminar esta imagen")
            
        # 2. Eliminar la imagen de la base de datos
        await db.images.delete_one({"_id": ObjectId(image_id)})
        
        # 3. Verificar si es la imagen de perfil o portada actual del usuario
        user = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
        
        if user.get("current_profile_picture") == image_id:
            await db.users.update_one(
                {"_id": ObjectId(current_user["_id"])},
                {"$unset": {"current_profile_picture": "", "profile_picture": ""}}
            )
            
        if user.get("current_cover_photo") == image_id:
            await db.users.update_one(
                {"_id": ObjectId(current_user["_id"])},
                {"$unset": {"current_cover_photo": ""}}
            )
            
        return Response(status_code=204)
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

### SECCION DE COMENTARIOS PARA LAS IMAGENES 

@router.post("/{image_id}/comments", response_model=ImageComment, status_code=status.HTTP_201_CREATED)
async def create_image_comment(
    image_id: str,
    comment_data: ImageCommentCreate,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        # Verificar si la imagen existe
        image = await db.images.find_one({"_id": ObjectId(image_id)})
        if not image:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Imagen no encontrada")

        # OBTENER USUARIO COMPLETO
        user = await db.users.find_one({"_id": ObjectId(current_user["id"])})

        profile_picture_url = None
        if user and user.get("current_profile_picture"):
            # Verificar si el ObjectId es válido
            try:
                profile_image_id = ObjectId(user["current_profile_picture"])
                
                profile_image = await db.images.find_one({"_id": profile_image_id})
                
                if profile_image:
                    profile_picture_url = profile_image.get("url")
                else:
                    print("❌ PROFILE IMAGE NOT FOUND")

                    
            except Exception as e:
                print(f"❌ ERROR CONVERTING TO ObjectId: {e}")
        else:
            print("❌ USER HAS NO current_profile_picture FIELD")
        
        # Crear el comentario
        created_at = get_peru_time()
        comment_dict = {
            "content": comment_data.content,
            "author_id": str(current_user["_id"]),
            "author_username": current_user.get("username", ""),
            "profile_picture": profile_picture_url,
            "image_id": image_id,
            "created_at": created_at
        }
        
        # Insertar el comentario
        result = await db.image_comments.insert_one(comment_dict)
        created_comment = await db.image_comments.find_one({"_id": result.inserted_id})
        
        # Convertir a modelo Pydantic para serialización automática
        comment_model = ImageComment(
            _id=str(created_comment["_id"]),
            content=created_comment["content"],
            author_id=created_comment["author_id"],
            author_username=created_comment["author_username"],
            profile_picture=created_comment.get("profile_picture"),
            image_id=created_comment["image_id"],
            created_at=created_comment["created_at"]
        )

        # Crear versión serializada para WebSocket
        serialized_comment = {
            "_id": str(created_comment["_id"]),
            "content": created_comment["content"],
            "author_id": created_comment["author_id"],
            "author_username": created_comment["author_username"],
            "profile_picture": created_comment.get("profile_picture"),
            "image_id": created_comment["image_id"],
            "created_at": created_at.isoformat()  # Asegurar que es string
        }
        
        # Incrementar el contador de comentarios
        await db.images.update_one(
            {"_id": ObjectId(image_id)},
            {"$inc": {"comments_count": 1}}
        )
        
        # Crear notificación si no es comentario propio
        if str(image["owner_id"]) != str(current_user["_id"]):
            notification = {
                "user_id": str(image["owner_id"]),
                "emitter_id": str(current_user["_id"]),
                "emitter_username": current_user.get("username", "Usuario"),
                "image_id": image_id,
                "comment_id": str(result.inserted_id),
                "type": "image_comment",
                "message": f"{current_user['username']} comentó tu foto: {comment_data.content[:30]}...",
                "read": False,
                "created_at": datetime.utcnow()
            }
            
            await db.notifications.insert_one(notification)
            await manager.broadcast_notification(str(image["owner_id"]), notification)
        
        # Emitir evento WebSocket - usar model_dump para serialización automática
        await manager.broadcast_image_comment(image_id, serialized_comment)
        
        return comment_model
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ID de imagen inválido")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get("/{image_id}/comments", response_model=List[ImageComment])
async def get_image_comments(
    image_id: str,
    skip: int = 0,
    limit: int = 100
):
    try:
        # Verificar si la imagen existe
        if not await db.images.find_one({"_id": ObjectId(image_id)}):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Imagen no encontrada")
        
        # Obtener comentarios
        comments = []
        async for comment in db.image_comments.find({"image_id": image_id}).sort("created_at", -1).skip(skip).limit(limit):
            comment["_id"] = str(comment["_id"])
            comment["created_at"] = format_peru_time(comment["created_at"])
            comments.append(comment)
            
        return comments
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ID de imagen inválido")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

@router.post("/{image_id}/like", response_model=Image)
async def like_image(
    image_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        user_id = str(current_user["_id"])
        image_oid = ObjectId(image_id)
        
        # Verificar si la imagen existe
        image = await db.images.find_one({"_id": image_oid})
        if not image:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Imagen no encontrada")
        
        # Verificar si ya dio like
        if user_id in image.get("liked_by", []):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya has dado like a esta imagen")
        
        # Actualizar la imagen
        update_time = datetime.utcnow()  # Definir update_time aquí
        await db.images.update_one(
            {"_id": image_oid},
            {
                "$inc": {"likes_count": 1},
                "$push": {"liked_by": user_id},
                "$set": {"updated_at": update_time}
            }
        )
        
        # Obtener imagen actualizada
        updated_image = await db.images.find_one({"_id": image_oid})
        updated_image["_id"] = str(updated_image["_id"])

        # Preparar datos para el broadcast
        broadcast_data = {
            "image_id": image_id,
            "likes_count": updated_image.get("likes_count", 0),
            "liked_by": updated_image.get("liked_by", []),
            "timestamp": update_time.isoformat()  # Asegurar que es string
        }

        # Emitir evento WebSocket
        await manager.broadcast_image_update(image_id, broadcast_data)
        
        # Crear notificación si no es like propio
        if str(image["owner_id"]) != user_id:
            notification = {
                "user_id": str(image["owner_id"]),
                "emitter_id": user_id,
                "emitter_username": current_user.get("username", "Usuario"),
                "image_id": image_id,
                "type": "image_like",
                "message": f"A {current_user['username']} le gusta tu foto",
                "read": False,
                "created_at": get_peru_time()
            }
            
            await db.notifications.insert_one(notification)
            await manager.broadcast_notification(str(image["owner_id"]), notification)
        
        return updated_image
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ID de imagen inválido")
        logger.error(f"Error en like_image: {str(e)}")  # Log detallado del error
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno del servidor")

@router.post("/{image_id}/unlike", response_model=Image)
async def unlike_image(
    image_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        user_id = str(current_user["_id"])
        image_oid = ObjectId(image_id)
        
        # Verificar si la imagen existe
        image = await db.images.find_one({"_id": image_oid})
        if not image:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Imagen no encontrada")
        
        # Verificar si no ha dado like
        if user_id not in image.get("liked_by", []):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No has dado like a esta imagen")
        
        # Actualizar la imagen
        update_time = datetime.utcnow()  # Definir update_time aquí
        await db.images.update_one(
            {"_id": image_oid},
            {
                "$inc": {"likes_count": -1},
                "$pull": {"liked_by": user_id},
                "$set": {"updated_at": update_time}
            }
        )
        
        # Obtener imagen actualizada
        updated_image = await db.images.find_one({"_id": image_oid})
        updated_image["_id"] = str(updated_image["_id"])

        # Preparar datos para el broadcast (similar a like_image)
        broadcast_data = {
            "image_id": image_id,
            "likes_count": updated_image.get("likes_count", 0),
            "liked_by": updated_image.get("liked_by", []),
            "timestamp": update_time.isoformat()  # Asegurar que es string
        }

        # Emitir evento WebSocket con datos formateados
        await manager.broadcast_image_update(image_id, broadcast_data)
        
        return updated_image
        
    except Exception as e:
        if "invalid object id" in str(e).lower():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ID de imagen inválido")
        logger.error(f"Error en unlike_image: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno del servidor")