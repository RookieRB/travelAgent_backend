from sqlalchemy import Column, String, Date, Enum, DECIMAL, Integer, Text, JSON, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from src.services.mysql_service import Base
import uuid


class Trip(Base):
    __tablename__ = "trips"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    budget = Column(DECIMAL(12, 2), default=0)
    spent = Column(DECIMAL(12, 2), default=0)
    participants = Column(Integer, default=1)
    status = Column(Enum('upcoming', 'ongoing', 'completed', 'cancelled'), default='upcoming')
    rating = Column(Integer, nullable=True)
    image = Column(String(500))
    highlights = Column(JSON, default=list)
    notes = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关联
    user = relationship("User", back_populates="trips")
    budget_items = relationship("BudgetItem", back_populates="trip", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="trip", cascade="all, delete-orphan")