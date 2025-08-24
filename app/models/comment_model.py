from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class CommentBase(BaseModel):
    content: str
    post_id: Optional[str]  # Ahora viene en el cuerpo

class CommentCreate(CommentBase):
    pass

class Comment(CommentBase):
    id: str = Field(alias="_id")
    author_id: str
    author_username: str
    author_profile_picture: Optional[str] = ""  # ← Nuevo campo
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            "_id": str,
            "author_id": str,
            "post_id": str
        }
        allow_population_by_field_name = True