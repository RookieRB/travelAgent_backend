from sqlalchemy import Column, String, Enum, TIMESTAMP, func
from sqlalchemy.orm import relationship
from src.services.mysql_service import Base
import uuid


class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50))
    avatar = Column(String(500))
    phone = Column(String(20))
    status = Column(Enum('active', 'inactive', 'banned'), default='active')
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    last_login_at = Column(TIMESTAMP, nullable=True)
    
    # 关联
    trips = relationship("Trip", back_populates="user", cascade="all, delete-orphan")