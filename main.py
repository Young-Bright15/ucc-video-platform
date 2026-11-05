import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jwt  # PyJWT

# Project dependencies (assumes database.py, models.py, and schemas.py exist)
from database import get_db, engine
import models
import schemas

app = FastAPI(
    title="University of Cape Coast Video Platform API",
    version="1.0.0",
    description="Enterprise backend handling secure authentication, course structures, video streaming, and analytics."
)

#This creates the tables in the sql database if they don't exist yet.
models.Base.metadata.create_all(bind=engine)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your teammate's frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT Security Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your_super_secret_key_here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Azure Blob Storage Configuration (with local file fallback)
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
CONTAINER_NAME = "uploaded-videos"

blob_service_client = None
if AZURE_STORAGE_CONNECTION_STRING:
    try:
        from azure.storage.blob import BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    except Exception as e:
        print(f"Warning: Could not initialize Azure Blob Storage client: {e}")


# --- AUTHENTICATION & ROLE HELPERS ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Use passlib / bcrypt hash checking logic matching your setup
    pass

def get_password_hash(password: str) -> str:
    # Use passlib / bcrypt hashing logic matching your setup
    pass

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.Username == username).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.RoleID != 1:
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user

def get_current_lecturer_or_ta(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.RoleID not in [1, 2, 3]:
        raise HTTPException(status_code=403, detail="Lecturer or TA privileges required.")
    return current_user


# --- ROOT & AUTHENTICATION ENDPOINTS ---

@app.get("/")
def root():
    return {"message": "UCC Video Platform API is live and operational."}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.Username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.PasswordHash):
        raise HTTPException(status_code=400, detail="Incorrect username or password.")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.Username, "role": user.RoleID}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register_student(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(
        or_(models.User.Username == user.Username, models.User.Email == user.Email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered.")
    
    new_user = models.User(
        Username=user.Username,
        Email=user.Email,
        PasswordHash=get_password_hash(user.Password),
        RoleID=4  # Default Student Role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/admin/create-user", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(user: schemas.UserCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    new_user = models.User(
        Username=user.Username,
        Email=user.Email,
        PasswordHash=get_password_hash(user.Password),
        RoleID=user.RoleID
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/lecturer/create-ta", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_ta(user: schemas.UserCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer_or_ta)):
    if current_user.RoleID != 2:
        raise HTTPException(status_code=403, detail="Only lecturers can create Teaching Assistants.")
    
    new_user = models.User(
        Username=user.Username,
        Email=user.Email,
        PasswordHash=get_password_hash(user.Password),
        RoleID=3  # TA Role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.delete("/admin/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.UserID == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    db.delete(user)
    db.commit()
    return {"message": f"User ID {user_id} deleted successfully."}

@app.post("/auth/change-password")
def change_password(data: schemas.ChangePasswordRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if not verify_password(data.old_password, current_user.PasswordHash):
        raise HTTPException(status_code=400, detail="Incorrect old password.")
    current_user.PasswordHash = get_password_hash(data.new_password)
    db.commit()
    return {"message": "Password updated successfully."}

@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, data: schemas.AdminResetPasswordRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.UserID == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.PasswordHash = get_password_hash(data.new_password)
    db.commit()
    return {"message": f"Password for user ID {user_id} reset successfully."}


# --- COURSE, TOPIC & SUBTOPIC ENDPOINTS ---

@app.post("/courses/", status_code=status.HTTP_201_CREATED)
def create_course(course: schemas.CourseCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer_or_ta)):
    new_course = models.Course(**course.dict())
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return new_course

@app.get("/courses/")
def get_courses(db: Session = Depends(get_db)):
    return db.query(models.Course).order_by(models.Course.CourseID).all()

@app.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    course = db.query(models.Course).filter(models.Course.CourseID == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    db.delete(course)
    db.commit()
    return {"message": "Course deleted successfully."}

@app.post("/topics/", status_code=status.HTTP_201_CREATED)
def create_topic(topic: schemas.TopicCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer_or_ta)):
    new_topic = models.Topic(**topic.dict())
    db.add(new_topic)
    db.commit()
    db.refresh(new_topic)
    return new_topic

@app.get("/courses/{course_id}/topics")
def get_course_topics(course_id: int, db: Session = Depends(get_db)):
    return db.query(models.Topic).filter(models.Topic.CourseID == course_id).order_by(models.Topic.TopicID).all()

@app.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    topic = db.query(models.Topic).filter(models.Topic.TopicID == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found.")
    db.delete(topic)
    db.commit()
    return {"message": "Topic deleted successfully."}

@app.post("/subtopics/", status_code=status.HTTP_201_CREATED)
def create_subtopic(subtopic: schemas.SubtopicCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer_or_ta)):
    new_sub = models.Subtopic(**subtopic.dict())
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)
    return new_sub

@app.get("/topics/{topic_id}/subtopics")
def get_topic_subtopics(topic_id: int, db: Session = Depends(get_db)):
    return db.query(models.Subtopic).filter(models.Subtopic.TopicID == topic_id).order_by(models.Subtopic.SubtopicID).all()

@app.delete("/subtopics/{subtopic_id}")
def delete_subtopic(subtopic_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    sub = db.query(models.Subtopic).filter(models.Subtopic.SubtopicID == subtopic_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subtopic not found.")
    db.delete(sub)
    db.commit()
    return {"message": "Subtopic deleted successfully."}


# --- VIDEO UPLOADS, STREAMING, ANALYTICS & SEARCH ---

@app.post("/videos/", status_code=status.HTTP_201_CREATED)
def upload_video(
    Title: str = Form(...),
    Description: str = Form(None),
    SubtopicID: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_lecturer_or_ta)
):
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    
    # Upload to Azure Blob Storage if configured, otherwise fallback to local folder
    if blob_service_client:
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=unique_filename)
        blob_client.upload_blob(file.file, overwrite=True)
        file_path = blob_client.url
    else:
        os.makedirs("uploaded_videos", exist_ok=True)
        local_path = os.path.join("uploaded_videos", unique_filename)
        with open(local_path, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
        file_path = local_path

    new_video = models.Video(
        Title=Title,
        Description=Description,
        FilePath=file_path,
        SubtopicID=SubtopicID,
        UploadedBy=current_user.UserID
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)
    return new_video

@app.get("/subtopics/{subtopic_id}/videos")
def get_subtopic_videos(subtopic_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Video).filter(models.Video.SubtopicID == subtopic_id).order_by(models.Video.VideoID).all()

@app.get("/videos/{video_id}/stream")
def stream_video(video_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    video = db.query(models.Video).filter(models.Video.VideoID == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    
    # Increment view counter atomically
    video.ViewsCount = (video.ViewsCount or 0) + 1
    db.commit()
    
    # Redirect client to the Blob URL (or local path)
    return RedirectResponse(url=video.FilePath)

@app.get("/videos/{video_id}/analytics")
def get_video_analytics(video_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer_or_ta)):
    video = db.query(models.Video).filter(models.Video.VideoID == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    
    helpful_count = db.query(models.VideoInteraction).filter(
        models.VideoInteraction.VideoID == video_id, 
        models.VideoInteraction.IsHelpful == True
    ).count()
    
    unhelpful_count = db.query(models.VideoInteraction).filter(
        models.VideoInteraction.VideoID == video_id, 
        models.VideoInteraction.IsHelpful == False
    ).count()

    return {
        "VideoID": video.VideoID,
        "Title": video.Title,
        "ViewsCount": video.ViewsCount,
        "HelpfulCount": helpful_count,
        "UnhelpfulCount": unhelpful_count
    }

@app.post("/videos/interact")
def interact_video(interaction: schemas.VideoInteractionCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    existing = db.query(models.VideoInteraction).filter(
        models.VideoInteraction.VideoID == interaction.VideoID,
        models.VideoInteraction.UserID == current_user.UserID
    ).first()

    if existing:
        existing.IsHelpful = interaction.IsHelpful
    else:
        new_interaction = models.VideoInteraction(
            VideoID=interaction.VideoID,
            UserID=current_user.UserID,
            IsHelpful=interaction.IsHelpful
        )
        db.add(new_interaction)
    db.commit()
    return {"message": "Interaction saved successfully."}

@app.get("/search/")
def search_platform(
    q: str = Query(..., min_length=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    search_pattern = f"%{q}%"
    
    # Explicit .order_by() included to satisfy SQL Server OFFSET/LIMIT requirements
    courses = db.query(models.Course).filter(
        or_(models.Course.CourseCode.ilike(search_pattern), models.Course.CourseName.ilike(search_pattern))
    ).order_by(models.Course.CourseID).offset(skip).limit(limit).all()

    videos = db.query(models.Video).filter(
        or_(models.Video.Title.ilike(search_pattern), models.Video.Description.ilike(search_pattern))
    ).order_by(models.Video.VideoID).offset(skip).limit(limit).all()

    return {
        "query": q,
        "courses": courses,
        "videos": videos
    }