# models/image_model.py
from pydantic import BaseModel, Field, ConfigDict

from datetime import datetime
from enum import Enum
from bson import ObjectId
from typing import Optional, List



class ImageType(str, Enum):
    PROFILE_PICTURE = "profile_picture"
    COVER_PHOTO = "cover_photo"

class ImageBase(BaseModel):
    url: str
    image_type: ImageType
    owner_id: str
    created_at: Optional[datetime] = None  # Hacerlo opcional
    likes_count: int = Field(default=0)
    liked_by: List[str] = Field(default_factory=list)
    comments_count: int = Field(default=0)

class ImageCreate(ImageBase):
    pass

class ImageCommentBase(BaseModel):
    content: str

class ImageCommentCreate(ImageCommentBase):
    pass

class ImageComment(ImageCommentBase):
    id: str = Field(alias="_id")
    author_id: str
    author_username: str
    image_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    profile_picture: Optional[str] = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

class Image(ImageBase):
    id: str = Field(alias="_id")
    
    class Config:
        json_encoders = {
            "_id": str,
            "owner_id": str,
            "created_at": lambda v: v.isoformat() if v else None,
            "liked_by": lambda v: [str(user_id) for user_id in v]
        }
        allow_population_by_field_name = True