from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database import Base

datetime_utc = datetime.utcnow

class User(Base):
    __tablename__ = "Users"
    UserID = Column(Integer, primary_key=True, index=True)
    Username = Column(String(50), unique=True, index=True, nullable=False)
    Email = Column(String(100), unique=True, index=True, nullable=False)
    PasswordHash = Column(String(255), nullable=False)
    RoleID = Column(Integer, index=True, nullable=False)
    
    courses = relationship("Course", back_populates="creator", cascade="all, delete-orphan")
    videos = relationship("Video", back_populates="uploader", cascade="all, delete-orphan")
    interactions = relationship("VideoInteraction", back_populates="user", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "Courses"
    CourseID = Column(Integer, primary_key=True, index=True)
    CourseCode = Column(String(20), unique=True, index=True, nullable=False)
    CourseName = Column(String(100), nullable=False)
    Description = Column(Text, nullable=True)
    CreatedBy = Column(Integer, ForeignKey("Users.UserID"), index=True, nullable=False)

    creator = relationship("User", back_populates="courses")
    topics = relationship("Topic", back_populates="course", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "Topics"
    TopicID = Column(Integer, primary_key=True, index=True)
    CourseID = Column(Integer, ForeignKey("Courses.CourseID"), index=True, nullable=False)
    TopicName = Column(String(100), nullable=False)

    course = relationship("Course", back_populates="topics")
    subtopics = relationship("Subtopic", back_populates="topic", cascade="all, delete-orphan")


class Subtopic(Base):
    __tablename__ = "Subtopics"
    SubtopicID = Column(Integer, primary_key=True, index=True)
    TopicID = Column(Integer, ForeignKey("Topics.TopicID"), index=True, nullable=False)
    SubtopicName = Column(String(100), nullable=False)

    topic = relationship("Topic", back_populates="subtopics")
    videos = relationship("Video", back_populates="subtopic", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "Videos"
    VideoID = Column(Integer, primary_key=True, index=True)
    Title = Column(String(150), nullable=False)
    Description = Column(Text, nullable=True)
    FilePath = Column(String(255), nullable=False)
    SubtopicID = Column(Integer, ForeignKey("Subtopics.SubtopicID"), index=True, nullable=False)
    UploadedBy = Column(Integer, ForeignKey("Users.UserID"), index=True, nullable=False)
    ViewsCount = Column(Integer, default=0, nullable=False)

    subtopic = relationship("Subtopic", back_populates="videos")
    uploader = relationship("User", back_populates="videos")
    interactions = relationship("VideoInteraction", back_populates="video", cascade="all, delete-orphan")


class VideoInteraction(Base):
    __tablename__ = "VideoInteractions"
    InteractionID = Column(Integer, primary_key=True, index=True)
    UserID = Column(Integer, ForeignKey("Users.UserID"), index=True, nullable=False)
    VideoID = Column(Integer, ForeignKey("Videos.VideoID"), index=True, nullable=False)
    IsHelpful = Column(Boolean, nullable=True)
    WatchedAt = Column(DateTime, default=datetime_utc)

    user = relationship("User", back_populates="interactions")
    video = relationship("Video", back_populates="interactions")