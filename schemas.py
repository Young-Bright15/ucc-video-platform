from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# --- USER SCHEMAS ---

class UserCreate(BaseModel):
    Username: str = Field(..., min_length=3, max_length=50)
    Email: str
    password: Optional[str] = Field(None, min_length=6, alias="Password")
    RoleID: Optional[int] = Field(4, description="Optional; defaults to Student for public registrations.")

    model_config = {
        "populate_by_name": True
    }

class UserResponse(BaseModel):
    UserID: int
    Username: str
    Email: str
    RoleID: int

    model_config = {
        "from_attributes": True
    }


class DeleteUserRequest(BaseModel):
    Username: str
    Email: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)

class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6)


# --- COURSE SCHEMAS ---

class CourseCreate(BaseModel):
    CourseCode: str = Field(..., min_length=2, max_length=20)
    CourseName: str = Field(..., min_length=2, max_length=100)
    Description: Optional[str] = None

class CourseResponse(BaseModel):
    CourseID: int
    CourseCode: str
    CourseName: str
    Description: Optional[str] = None
    CreatedBy: int

    model_config = {
        "from_attributes": True
    }


# --- TOPIC & SUBTOPIC SCHEMAS ---

class TopicCreate(BaseModel):
    CourseCode: str
    TopicName: str = Field(..., min_length=2, max_length=100)

class TopicResponse(BaseModel):
    TopicID: int
    CourseID: int
    TopicName: str

    model_config = {
        "from_attributes": True
    }


class SubtopicCreate(BaseModel):
    CourseCode: str
    TopicName: str
    SubtopicName: str = Field(..., min_length=2, max_length=100)

class SubtopicResponse(BaseModel):
    SubtopicID: int
    TopicID: int
    SubtopicName: str

    model_config = {
        "from_attributes": True
    }


# --- VIDEO & INTERACTION SCHEMAS ---

class VideoResponse(BaseModel):
    VideoID: int
    Title: str
    Description: Optional[str] = None
    FilePath: str
    SubtopicID: int
    UploadedBy: int
    ViewsCount: int

    model_config = {
        "from_attributes": True
    }

class VideoInteractionCreate(BaseModel):
    VideoID: int
    IsHelpful: bool  # True for helpful, False for unhelpful

class VideoInteractionResponse(BaseModel):
    InteractionID: int
    UserID: int
    VideoID: int
    IsHelpful: Optional[bool] = None
    WatchedAt: datetime

    model_config = {
        "from_attributes": True
    }