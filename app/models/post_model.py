from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from bson.objectid import ObjectId
from pydantic import Field
from typing import List

class Post(BaseModel):
    title: str
    content: str
    author_id: Optional[str] = None  # Añade este campo
    author_profile_picture: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    likes_count: int = Field(default=0)
    liked_by: List[str] = Field(default_factory=list)
    
    class Config:
        json_encoders = {ObjectId: str}
        
class UserPostsResponse(BaseModel):
    posts: List[Post]
    total_posts: int
    skip: int
    limit: int