from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


class BudgetCategoryType(str, Enum):
    TRANSPORT = "transport"
    ACCOMMODATION = "accommodation"
    FOOD = "food"
    TICKETS = "tickets"
    SHOPPING = "shopping"
    OTHER = "other"


class BudgetItemCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    category_type: BudgetCategoryType = BudgetCategoryType.OTHER
    amount: float = Field(default=0, ge=0)
    color: str = Field(default="#3B82F6")
    icon: str = Field(default="Wallet")


class BudgetItemUpdate(BaseModel):
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    amount: Optional[float] = Field(None, ge=0)
    spent: Optional[float] = Field(None, ge=0)
    color: Optional[str] = None
    icon: Optional[str] = None


class BudgetItemResponse(BaseModel):
    id: str
    trip_id: str
    category: str
    category_type: str
    amount: float
    spent: float
    color: str
    icon: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class BudgetSummary(BaseModel):
    total_budget: float = 0
    total_spent: float = 0
    remaining: float = 0
    spent_percentage: float = 0
    items: List[BudgetItemResponse] = []
    insights: List[str] = []
    warnings: List[str] = []


class ExpenseCreate(BaseModel):
    """创建支出"""
    budget_item_id: str
    amount: float = Field(..., gt=0, description="支出金额必须大于0")
    note: Optional[str] = Field(None, max_length=255)
    expense_date: Optional[date] = None


class ExpenseUpdate(BaseModel):
    """更新支出"""
    budget_item_id: Optional[str] = Field(None, description="更改所属预算项")
    amount: Optional[float] = Field(None, gt=0, description="支出金额必须大于0")
    note: Optional[str] = Field(None, max_length=255)
    expense_date: Optional[date] = None


class ExpenseResponse(BaseModel):
    """支出响应"""
    id: str
    trip_id: str
    budget_item_id: str
    amount: float
    note: Optional[str]
    expense_date: date
    created_at: datetime
    
    class Config:
        from_attributes = True


class ExpenseWithCategory(ExpenseResponse):
    """支出响应（包含分类信息）"""
    category_name: Optional[str] = None
    category_color: Optional[str] = None
    category_icon: Optional[str] = None