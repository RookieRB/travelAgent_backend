from sqlalchemy import Column, String, Date, Enum, DECIMAL, Integer, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from src.services.mysql_service import Base
import uuid


class BudgetItem(Base):
    __tablename__ = "budget_items"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = Column(String(36), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(50), nullable=False)
    category_type = Column(
        Enum('transport', 'accommodation', 'food', 'tickets', 'shopping', 'other'), 
        default='other'
    )
    amount = Column(DECIMAL(12, 2), default=0)
    spent = Column(DECIMAL(12, 2), default=0)
    color = Column(String(20), default='#3B82F6')
    icon = Column(String(50), default='Wallet')
    sort_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关联
    trip = relationship("Trip", back_populates="budget_items")
    expenses = relationship("Expense", back_populates="budget_item", cascade="all, delete-orphan")


class Expense(Base):
    __tablename__ = "expenses"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = Column(String(36), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    budget_item_id = Column(String(36), ForeignKey("budget_items.id", ondelete="CASCADE"), nullable=False)
    amount = Column(DECIMAL(12, 2), nullable=False)
    note = Column(String(255))
    expense_date = Column(Date, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    # 关联
    trip = relationship("Trip", back_populates="expenses")
    budget_item = relationship("BudgetItem", back_populates="expenses")