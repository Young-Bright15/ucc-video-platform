import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jwt  # PyJWT
from passlib.context import CryptContext

from database import get_db, engine
import models
import schemas

app = FastAPI(
    title="University of Cape Coast Video Platform API",
    version="2.2.0",
    description="Enterprise production-grade backend handling secure authentication, course structures, atomic streaming, and analytics."
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "error": str(exc)},
    )

@app.on_event("startup")
def startup_event():
    try:
        models.Base.metadata.create_all(bind=engine)
        print("Database tables verified/created successfully.")
    except Exception as e:
        print(f"Database initialization warning: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "your_super_secret_key_here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

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
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    safe_password = password[:72]
    return pwd_context.hash(safe_password)

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

@app.post("/setup-initial-admin")
def setup_initial_admin(data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_admin = db.query(models.User).filter(models.User.RoleID == 1).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="An admin account already exists in the system.")
    
    password_to_hash = getattr(data, "password", None) or getattr(data, "Password", None)
    if not password_to_hash:
        raise HTTPException(status_code=400, detail="Password is required.")
    
    initial_admin = models.User(
        Username=getattr(data, "Username", None) or getattr(data, "username", None),
        Email=getattr(data, "Email", None) or getattr(data, "email", None),
        PasswordHash=get_password_hash(password_to_hash),
        RoleID=1
    )
    db.add(initial_admin)
    db.commit()
    db.refresh(initial_admin)
    return {"message": "Initial admin created successfully!", "username": initial_admin.Username}

def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.RoleID != 1:
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user

def get_current_lecturer(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.RoleID not in [1, 2]:
        raise HTTPException(status_code=403, detail="Lecturer or Admin privileges required.")
    return current_user

def get_current_lecturer_or_ta(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.RoleID not in [1, 2, 3]:
        raise HTTPException(status_code=403, detail="Lecturer, TA, or Admin privileges required.")
    return current_user


# --- CORE ENDPOINTS ---

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

@app.post("/register")
def register_student(data: schemas.UserCreate, db: Session = Depends(get_db)):
    password_to_hash = getattr(data, "password", None) or getattr(data, "Password", None)
    if not password_to_hash:
        raise HTTPException(status_code=400, detail="Password is required.")
    
    username_val = getattr(data, "Username", None) or getattr(data, "username", None)
    email_val = getattr(data, "Email", None) or getattr(data, "email", None)
    
    existing_user = db.query(models.User).filter(
        (models.User.Username == username_val) | (models.User.Email == email_val)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or Email already registered.")

    # DYNAMIC LOOKUP: Fetch the 'Student' RoleID directly from the Roles table
    student_role = db.query(models.Role).filter(models.Role.RoleName == "Student").first()
    if not student_role:
        raise HTTPException(status_code=500, detail="Default student role not found in system.")

    new_user = models.User(
        Username=username_val,
        Email=email_val,
        PasswordHash=get_password_hash(password_to_hash),
        RoleID=student_role.RoleID  # Dynamically assigned, zero hardcoding!
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Student registered successfully!", "username": new_user.Username}

@app.post("/admin/create-user", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(user: schemas.UserCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    if user.RoleID not in [1, 2, 3]:
        raise HTTPException(status_code=400, detail="Invalid RoleID specified. Choose 1 (Admin), 2 (Student), or 3 (TA).")
        
    password_val = getattr(user, "password", None) or getattr(user, "Password", None)
    if not password_val:
        raise HTTPException(status_code=400, detail="Password is required for user creation.")

    new_user = models.User(
        Username=user.Username,
        Email=user.Email,
        PasswordHash=get_password_hash(password_val),
        RoleID=user.RoleID
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/lecturer/create-ta", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def create_ta(
    user: schemas.UserCreate, 
    course_code: str, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_lecturer)
):
    password_val = getattr(user, "password", None) or getattr(user, "Password", None)
    if not password_val:
        raise HTTPException(status_code=400, detail="Password is required for TA creation.")

    username_val = getattr(user, "Username", None) or getattr(user, "username", None)
    email_val = getattr(user, "Email", None) or getattr(user, "email", None)

    # 1. Verify that the course exists in the database
    course = db.query(models.Course).filter(models.Course.CourseCode == course_code).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course with code '{course_code}' does not exist.")

    # 2. DYNAMIC ROLE LOOKUP: Fetch 'Teaching Assistant' RoleID securely
    ta_role = db.query(models.Role).filter(models.Role.RoleName == "Teaching Assistant").first()
    if not ta_role:
        raise HTTPException(status_code=500, detail="Teaching Assistant role is not configured in the database.")

    # 3. Check for existing user
    existing_user = db.query(models.User).filter(
        (models.User.Username == username_val) | (models.User.Email == email_val)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or Email already registered.")

    # 4. Create the TA user
    new_user = models.User(
        Username=username_val,
        Email=email_val,
        PasswordHash=get_password_hash(password_val),
        RoleID=ta_role.RoleID  # Dynamic role ID lookup
    )
    
    # 5. Assign the course to the TA's relationship list
    new_user.assigned_courses.append(course)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.delete("/admin/users/delete")
def delete_user(
    payload: schemas.DeleteUserRequest, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_admin)
):
    # 1. Find the target user by both Username and Email to ensure precise matching
    target_user = db.query(models.User).filter(
        models.User.Username == payload.Username,
        models.User.Email == payload.Email
    ).first()
    
    if not target_user:
        raise HTTPException(
            status_code=404, 
            detail=f"User with username '{payload.Username}' and email '{payload.Email}' not found."
        )

    # 2. Prevent admin from deleting their own account
    if target_user.UserID == current_user.UserID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Action prohibited: You cannot delete your own active admin account."
        )

    # 3. Delete the user safely
    db.delete(target_user)
    db.commit()
    return {"message": f"User '{payload.Username}' has been deleted successfully."}

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
def create_course(course: schemas.CourseCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_lecturer)):
    existing = db.query(models.Course).filter(models.Course.CourseCode == course.CourseCode).first()
    if existing:
        raise HTTPException(status_code=400, detail="Course with this code already exists.")
    
    new_course = models.Course(
        CourseCode=course.CourseCode,
        CourseName=course.CourseName,
        Description=course.Description,
        CreatedBy=current_user.UserID
    )
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    return new_course

@app.get("/courses/")
def get_courses(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.query(models.Course).order_by(models.Course.CourseID).offset(skip).limit(limit).all()

@app.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    course = db.query(models.Course).filter(models.Course.CourseID == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    db.delete(course)
    db.commit()
    return {"message": "Course and all associated curriculum deleted successfully."}

@app.post("/topics/", status_code=status.HTTP_201_CREATED)
def create_topic(
    CourseCode: str = Form(...),
    TopicName: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_lecturer_or_ta)
):
    course = db.query(models.Course).filter(models.Course.CourseCode == CourseCode).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course with code '{CourseCode}' not found.")
    
    existing_topic = db.query(models.Topic).filter(
        models.Topic.CourseID == course.CourseID,
        models.Topic.TopicName == TopicName
    ).first()
    if existing_topic:
        raise HTTPException(status_code=400, detail="This topic already exists under this course.")

    new_topic = models.Topic(CourseID=course.CourseID, TopicName=TopicName)
    db.add(new_topic)
    db.commit()
    db.refresh(new_topic)
    return {"message": "Topic created successfully!", "TopicID": new_topic.TopicID, "CourseCode": CourseCode, "TopicName": new_topic.TopicName}


@app.post("/subtopics/", status_code=status.HTTP_201_CREATED)
def create_subtopic(
    CourseCode: str = Form(...),
    TopicName: str = Form(...),
    SubtopicName: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_lecturer_or_ta)
):
    course = db.query(models.Course).filter(models.Course.CourseCode == CourseCode).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course with code '{CourseCode}' not found.")

    topic = db.query(models.Topic).filter(
        models.Topic.CourseID == course.CourseID,
        models.Topic.TopicName == TopicName
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{TopicName}' not found under course '{CourseCode}'.")

    existing_sub = db.query(models.Subtopic).filter(
        models.Subtopic.TopicID == topic.TopicID,
        models.Subtopic.SubtopicName == SubtopicName
    ).first()
    if existing_sub:
        raise HTTPException(status_code=400, detail="This subtopic already exists under this topic.")

    new_sub = models.Subtopic(TopicID=topic.TopicID, SubtopicName=SubtopicName)
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)
    return {"message": "Subtopic created successfully!", "SubtopicID": new_sub.SubtopicID, "CourseCode": CourseCode, "TopicName": TopicName, "SubtopicName": new_sub.SubtopicName}


@app.get("/courses/{course_id}/topics")
def get_course_topics(course_id: int, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.query(models.Topic).filter(models.Topic.CourseID == course_id).order_by(models.Topic.TopicID).offset(skip).limit(limit).all()

@app.delete("/topics/{topic_id}")
def delete_topic(topic_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_admin)):
    topic = db.query(models.Topic).filter(models.Topic.TopicID == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found.")
    db.delete(topic)
    db.commit()
    return {"message": "Topic deleted successfully."}


@app.get("/topics/{topic_id}/subtopics")
def get_topic_subtopics(topic_id: int, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.query(models.Subtopic).filter(models.Subtopic.TopicID == topic_id).order_by(models.Subtopic.SubtopicID).offset(skip).limit(limit).all()

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
    CourseCode: str = Form(...),
    TopicName: str = Form(...),
    SubtopicName: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_lecturer_or_ta)
):
    course = db.query(models.Course).filter(models.Course.CourseCode == CourseCode).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course with code '{CourseCode}' not found.")

    topic = db.query(models.Topic).filter(
        models.Topic.CourseID == course.CourseID, 
        models.Topic.TopicName == TopicName
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{TopicName}' not found under course '{CourseCode}'. Create topic first.")

    subtopic = db.query(models.Subtopic).filter(
        models.Subtopic.TopicID == topic.TopicID, 
        models.Subtopic.SubtopicName == SubtopicName
    ).first()
    if not subtopic:
        raise HTTPException(status_code=404, detail=f"Subtopic '{SubtopicName}' not found under topic '{TopicName}'. Create subtopic first.")

    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    
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
        SubtopicID=subtopic.SubtopicID,
        UploadedBy=current_user.UserID
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)
    
    return {
        "message": "Video uploaded successfully!",
        "VideoID": new_video.VideoID,
        "Title": new_video.Title,
        "CourseCode": CourseCode,
        "TopicName": TopicName,
        "SubtopicName": SubtopicName,
        "FilePath": file_path
    }

@app.get("/subtopics/{subtopic_id}/videos")
def get_subtopic_videos(subtopic_id: int, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Video).filter(models.Video.SubtopicID == subtopic_id).order_by(models.Video.VideoID).offset(skip).limit(limit).all()

@app.get("/videos/{video_id}/stream")
def stream_video(video_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    video = db.query(models.Video).filter(models.Video.VideoID == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    
    # Atomic view update to prevent race conditions under heavy traffic
    db.query(models.Video).filter(models.Video.VideoID == video_id).update(
        {"ViewsCount": models.Video.ViewsCount + 1}
    )
    db.commit()
    
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