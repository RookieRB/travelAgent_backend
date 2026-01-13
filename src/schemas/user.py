from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


# ==================== 用户注册/登录 ====================

class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    nickname: Optional[str] = None


class UserLogin(BaseModel):
    username: str  # 可以是用户名或邮箱
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefresh(BaseModel):
    refresh_token: str


# ==================== 用户信息 ====================

class UserBase(BaseModel):
    username: str
    email: str
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    phone: Optional[str] = None


class UserResponse(UserBase):
    id: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """更新用户信息"""
    nickname: Optional[str] = Field(None, min_length=1, max_length=50)
    avatar: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=20)


class PasswordChange(BaseModel):
    """修改密码"""
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


class PasswordReset(BaseModel):
    """重置密码"""
    token: str
    new_password: str = Field(..., min_length=6, max_length=100)


# ==================== 用户统计信息 ====================

class UserStats(BaseModel):
    """用户统计"""
    total_trips: int = 0
    completed_trips: int = 0
    total_days: int = 0
    total_spent: float = 0
    cities_visited: int = 0
    member_days: int = 0  # 注册天数


class UserProfile(UserResponse):
    """用户详细资料（包含统计）"""
    stats: Optional[UserStats] = None