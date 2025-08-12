# models/image_model.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from bson import ObjectId
from typing import Optional



class ImageType(str, Enum):
    PROFILE_PICTURE = "profile_picture"
    COVER_PHOTO = "cover_photo"

class ImageBase(BaseModel):
    url: str
    image_type: ImageType
    owner_id: str
    created_at: Optional[datetime] = None  # Hacerlo opcional


class ImageCreate(ImageBase):
    pass

class Image(ImageBase):
    id: str = Field(alias="_id")
    
    class Config:
        json_encoders = {
            "_id": str,
            "owner_id": str,
            "created_at": lambda v: v.isoformat() if v else None
        }
        allow_population_by_field_name = True