from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from enum import Enum
from datetime import datetime
from typing import List, Dict

class UserRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    USER = "user"

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    # Campos completamente opcionales con valores por defecto None
    bio: Optional[str] = Field(None, max_length=500)
    profile_picture: Optional[str] = Field(None)
    cover_photo: Optional[str] = Field(None)
    relationships: Dict[str, str] = Field(default_factory=dict)
    
class UserLogin(BaseModel):
    username: str
    password: str

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.USER

class UserInDB(UserBase):
    id: str
    hashed_password: Optional[str] = None
    role: UserRole
    created_at: datetime
    updated_at: Optional[datetime] = None
    relationships: Optional[Dict[str, str]] = Field(default_factory=dict)  # Añade este campo
    
    @validator('hashed_password')
    def validate_hashed_password(cls, v):
        if v is None:  # Permitir explícitamente None
            return v
        if not v.startswith(("$2a$", "$2b$", "$2y$")):
            raise ValueError("Invalid password hash format")
        return v
    
class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    bio: Optional[str] = Field(None, max_length=500)
    profile_picture: Optional[str] = None
    cover_photo: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6)
    new_token: Optional[str] = None