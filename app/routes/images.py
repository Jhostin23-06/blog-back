# routes/images.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from app.utils.util import upload_file_to_storage
from bson import ObjectId
from app.auth import require_role, UserRole
from app.database import db
from app.models.image_model import Image, ImageCreate, ImageType
from datetime import datetime
from app.websocket_manager import manager
from typing import List, Optional


router = APIRouter(prefix="/images", tags=["images"])

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
        created_at=datetime.utcnow()
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
        "updated_at": datetime.utcnow().isoformat()
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
    
    image_data = ImageCreate(
        url=file_url,
        image_type=ImageType.COVER_PHOTO,
        owner_id=str(current_user["_id"]),
        created_at=datetime.utcnow()
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