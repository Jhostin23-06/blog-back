from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class NotificationType(str, Enum):
    LIKE = "like"
    COMMENT = "comment"
    NEW_FOLLOWER = "new_follower"

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

class Notification(NotificationBase):
    id: str = Field(alias="_id")
    user_id: str
    emitter_id: str
    emitter_username: str
    post_id: Optional[str] = None
    comment_id: Optional[str] = None
    
    # Configuración para Pydantic v2
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda dt: dt.isoformat(),
        },
        populate_by_name=True  # Equivalente a allow_population_by_field_name
    )