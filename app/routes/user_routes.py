from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.auth import (
    create_access_token,
    get_password_hash,
    verify_password,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    require_role,
)
from app.database import db
from app.models.user_model import UserCreate, UserInDB, UserLogin, UserRole, UserUpdate
from datetime import datetime,  timedelta
from bson import ObjectId
from typing import Optional
import logging
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

class UserUpdateResponse(BaseModel):
    message: str
    user: UserInDB

@router.post("/register", response_model=UserInDB)
async def register(user: UserCreate):
    # Verificar si el usuario ya existe
    existing_user = await db.users.find_one({
        "$or": [
            {"username": user.username},
            {"email": user.email}
        ]
    })
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario o correo ya registrado"
        )
    
    # Hashear la contraseña
    hashed_password = get_password_hash(user.password)
    
    # Crear documento para la base de datos
    db_user = {
        "username": user.username,
        "email": user.email,
        "hashed_password": hashed_password,
        "role": user.role.value,
        "bio": user.bio or "",  # Cadena vacía si no se proporciona
        "profile_picture": user.profile_picture or "https://ejemplo.com/default-profile.jpg",
        "cover_photo": user.cover_photo or "https://ejemplo.com/default-cover.jpg",
        "created_at": datetime.utcnow()
    }
    
    try:
        result = await db.users.insert_one(db_user)
        if result.inserted_id:
            # Retornar el usuario sin la contraseña en texto plano
            return UserInDB(
                id=str(result.inserted_id),
                username=user.username,
                email=user.email,
                hashed_password=hashed_password,
                role=user.role,
                bio=user.bio,
                profile_picture=user.profile_picture,
                cover_photo=user.cover_photo,
                created_at=datetime.utcnow()
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al crear usuario"
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )

@router.post("/login")
async def login(login_data: UserLogin):
    try:
        # Buscar usuario en la base de datos
        db_user = await db.users.find_one({"username": login_data.username})
        
        if not db_user:
            logger.warning(f"Usuario no encontrado: {login_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Verificar contraseña
        if not verify_password(login_data.password, db_user.get("hashed_password", "")):
            logger.warning(f"Contraseña incorrecta para el usuario: {login_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Crear token de acceso
        access_token = create_access_token(
            data={
                "sub": db_user["username"],
                "role": db_user.get("role", UserRole.USER.value)
            },
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_info": {
                "id": str(db_user["_id"]),
                "username": db_user["username"],
                "email": db_user["email"],
                "role": db_user.get("role", UserRole.USER.value),
                "bio": db_user.get("bio", ""),
                "profile_picture": db_user.get("profile_picture"),
                "cover_photo": db_user.get("cover_photo")
            }
        }
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )
        
@router.patch("/users/{user_id}", response_model=UserUpdateResponse)
async def update_user_profile(
    user_id: str,
    update_data: UserUpdate,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        # Convertir ambos IDs a string para comparación segura
        current_user_id = str(current_user.get("id", ""))
        requested_user_id = str(user_id)
        
        # Verificar permisos (admin puede editar cualquier perfil)
        if current_user_id != requested_user_id and current_user.get("role") != UserRole.USER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para actualizar este perfil"
            )
        
        # Convertir a ObjectId para la consulta a MongoDB
        try:
            user_oid = ObjectId(user_id)
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )
        
        # Preparar datos de actualización
        update_values = {}
        
        # Validar username único si se está actualizando
        if update_data.username:
            existing_user = await db.users.find_one({
                "username": update_data.username,
                "_id": {"$ne": user_oid}
            })
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Nombre de usuario ya en uso"
                )
            update_values["username"] = update_data.username
        
        # Validar email único si se está actualizando
        if update_data.email:
            existing_email = await db.users.find_one({
                "email": update_data.email,
                "_id": {"$ne": user_oid}
            })
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Correo electrónico ya en uso"
                )
            update_values["email"] = update_data.email
        
        # Campos opcionales
        if update_data.bio is not None:
            update_values["bio"] = update_data.bio or ""
        
        if update_data.profile_picture:
            update_values["profile_picture"] = update_data.profile_picture
        
        if update_data.cover_photo:
            update_values["cover_photo"] = update_data.cover_photo
        
        # Manejo de contraseña
        if update_data.password:
            update_values["hashed_password"] = get_password_hash(update_data.password)
        
        if not update_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron datos para actualizar"
            )
        
        # Actualizar con marca de tiempo
        update_values["updated_at"] = datetime.utcnow()
        
        # Ejecutar actualización
        result = await db.users.update_one(
            {"_id": user_oid},
            {"$set": update_values}
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario o no hubo cambios"
            )
        
        # Obtener usuario actualizado
        updated_user = await db.users.find_one({"_id": user_oid})
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado después de actualización"
            )
            
        # Convertir a modelo Pydantic
        user_response = UserInDB(
            id=str(updated_user["_id"]),
            username=updated_user["username"],
            email=updated_user["email"],
            hashed_password=updated_user["hashed_password"],
            role=UserRole(updated_user["role"]),
            bio=updated_user.get("bio", ""),
            profile_picture=updated_user.get("profile_picture"),
            cover_photo=updated_user.get("cover_photo"),
            created_at=updated_user["created_at"],
            updated_at=updated_user.get("updated_at")
        )
        
        return {
            "message": "Perfil actualizado correctamente",
            "user": user_response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al actualizar perfil: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar la solicitud"
        )
        
@router.get("/users/{user_id}", response_model=UserInDB)
async def get_user_profile(
    user_id: str,
    current_user: dict = Depends(require_role(UserRole.USER))
):
    try:
        user_oid = ObjectId(user_id)
        user = await db.users.find_one({"_id": user_oid})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )
            
        return UserInDB(
            id=str(user["_id"]),
            username=user["username"],
            email=user["email"],
            hashed_password=user["hashed_password"],
            role=UserRole(user["role"]),
            bio=user.get("bio", ""),
            profile_picture=user.get("profile_picture"),
            cover_photo=user.get("cover_photo")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )