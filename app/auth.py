from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from enum import Enum
from pydantic import BaseModel
from typing import Optional
from app.database import db
import logging
from bson import ObjectId
from fastapi import Request
import os

logger = logging.getLogger(__name__)
# Configuración 
SECRET_KEY = os.getenv("SECRET_KEY", "NegdgE{=1BX_|,E>,qG14h@q%")  # Cambia esto en producción!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Esquema de seguridad
security = HTTPBearer()

# Contexto para hashing de contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    USER = "user"

# Esquemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
    

class OptionalHTTPBearer(HTTPBearer):
    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        try:
            return await super().__call__(request)
        except HTTPException:
            return None

optional_security = OptionalHTTPBearer()

# Funciones de utilidad
def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Funciones de verificación
async def get_current_user_websocket(token: str):
    """Versión especial para WebSockets que devuelve el usuario o None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
            
        user = await db.users.find_one({"username": username})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except Exception as e:
        print(f"Error decoding WS token: {str(e)}")
        return None

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = await get_user_from_db(username)  # Implementa esta función
    if user is None:
        raise credentials_exception
    
    return user

# Para endpoints que pueden ser públicos
async def optional_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)):
    if not credentials:
        return None
        
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = await db.users.find_one({"username": payload["sub"]})
        if user:
            user["_id"] = str(user["_id"])
        return user
    except:
        return None

# Para endpoints que requieren autenticación y rol específico
def require_role(required_role: UserRole):
    async def dependency(credentials: HTTPAuthorizationCredentials = Depends(security)):
        try:
            token = credentials.credentials
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            
            
            # Verificar rol
            if UserRole(payload.get("role")) != required_role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Se requiere rol de {required_role.value}"
                )
            
            # Buscar por ID en lugar de username
            user = await db.users.find_one({"_id": ObjectId(payload.get("id"))})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Usuario no encontrado"
                )
                
            # Preparar datos del usuario
            current_user = {
                "username": user["username"],
                "id": str(user["_id"]),  # ID como string
                "role": user.get("role", UserRole.USER.value),
                "_id": user["_id"]  # Conservar ObjectId para consultas
            }
            
            return current_user
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expirado")
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="Token inválido")
        except Exception as e:
            logger.error(f"Error en autenticación: {str(e)}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")
    return dependency