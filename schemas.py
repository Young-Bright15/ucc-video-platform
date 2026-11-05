from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class AdminResetPasswordRequest(BaseModel):
    new_password: str
    
# --- User Schemas ---
class UserCreate(BaseModel):
    Username: str
    Email: str
    Password: str
    RoleID: int  # 1: Admin, 2: Lecturer, 3: TA, 4: Student

class UserResponse(BaseModel):
    UserID: int
    Username: str
    Email: str
    RoleID: int

    class Config:
        from_attributes = True

# --- Course Schemas ---
class CourseCreate(BaseModel):
    CourseCode: str
    CourseName: str
    Description: Optional[str] = None

class CourseResponse(CourseCreate):
    CourseID: int
    CreatedBy: int

    class Config:
        from_attributes = True

# --- Topic & Subtopic Schemas ---
class TopicCreate(BaseModel):
    CourseID: int
    TopicName: str

class TopicResponse(TopicCreate):
    TopicID: int

    class Config:
        from_attributes = True

class SubtopicCreate(BaseModel):
    TopicID: int
    SubtopicName: str

class SubtopicResponse(SubtopicCreate):
    SubtopicID: int

    class Config:
        from_attributes = True

# --- Video Schemas ---
class VideoResponse(BaseModel):
    VideoID: int
    Title: str
    Description: Optional[str] = None
    FilePath: str
    SubtopicID: int
    UploadedBy: int

    class Config:
        from_attributes = True

# --- Video Interaction Schemas ---
class VideoInteractionCreate(BaseModel):
    VideoID: int
    IsHelpful: bool

class VideoInteractionResponse(VideoInteractionCreate):
    InteractionID: int
    UserID: int
    WatchedAt: datetime

    class Config:
        from_attributes = True

