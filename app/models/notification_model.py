from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List  # Añade List para manejar arrays
from bson import ObjectId  # Añade esto para manejar ObjectId en serialización

class NotificationType(str, Enum):
    LIKE = "like"
    COMMENT = "comment"
    NEW_FOLLOWER = "new_follower"
    FRIEND_REQUEST = "friend_request"
    FRIEND_ACCEPTED = "friend_accepted"
    IMAGE_LIKE = "image_like"          # Nuevo
    IMAGE_COMMENT = "image_comment"    # Nuevo

class NotificationBase(BaseModel):
    type: NotificationType
    message: str
    read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class NotificationCreate(NotificationBase):
    user_id: str  # ID del usuario que recibe la notificación
    emitter_id: str  # ID del usuario que genera la notificación
    post_id: Optional[str] = None  # ID del post relacionado (opcional)
    comment_id: Optional[str] = None  # ID del comentario (opcional)
    image_id: Optional[str] = None  # Nuevo
    image_url: Optional[str] = None  # Nuevo campo
    image_owner_id: Optional[str] = None  # Nuevo campo
    image_created_at: Optional[datetime] = None  # Nuevo campo

    # Campos adicionales para información del post
    post_title: Optional[str] = None
    post_content: Optional[str] = None
    post_author_id: Optional[str] = None
    post_author_username: Optional[str] = None
    post_author_profile_picture: Optional[str] = None
    post_image_url: Optional[str] = None
    post_likes_count: Optional[int] = 0
    post_comments_count: Optional[int] = 0
    post_liked_by: Optional[List[str]] = []
    post_created_at: Optional[datetime] = None
    post_updated_at: Optional[datetime] = None

class Notification(NotificationBase):
    id: str = Field(alias="_id")
    user_id: str
    emitter_id: str
    emitter_username: str
    post_id: Optional[str] = None
    comment_id: Optional[str] = None
    relationship: Optional[str] = None
    image_id: Optional[str] = None  # Nuevo
    image_url: Optional[str] = None  # Nuevo campo
    image_owner_id: Optional[str] = None  # Nuevo campo
    image_created_at: Optional[datetime] = None  # Nuevo campo

    # Campos adicionales para información del post
    post_title: Optional[str] = None
    post_content: Optional[str] = None
    post_author_id: Optional[str] = None
    post_author_username: Optional[str] = None
    post_author_profile_picture: Optional[str] = None
    post_image_url: Optional[str] = None
    post_likes_count: Optional[int] = 0
    post_comments_count: Optional[int] = 0
    post_liked_by: Optional[List[str]] = []
    post_created_at: Optional[datetime] = None
    post_updated_at: Optional[datetime] = None
    
    # Configuración para Pydantic v2
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda dt: dt.isoformat(),
            ObjectId: str  # Añade esto para manejar ObjectId en serialización
        },
        populate_by_name=True  # Equivalente a allow_population_by_field_name
    )