from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from src.services.mysql_service import get_db
from src.models.user import User
from src.schemas.user import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh,
    UserResponse, UserUpdate, PasswordChange
)
from src.utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token
)
from src.middleware.auth import get_current_user
from src.services.config import settings

router = APIRouter(prefix="/api/auth", tags=["认证"])


# ==================== 认证相关 ====================

@router.post("/register", response_model=UserResponse, summary="用户注册")
async def register(data: UserRegister, db: Session = Depends(get_db)):
    """
    注册新用户
    
    - **username**: 用户名（3-50字符，唯一）
    - **email**: 邮箱（唯一）
    - **password**: 密码（6位以上）
    - **nickname**: 昵称（可选）
    """
    # 检查用户名是否存在
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已被使用")
    
    # 检查邮箱是否存在
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")
    
    # 创建用户
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        nickname=data.nickname or data.username
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(data: UserLogin, db: Session = Depends(get_db)):
    """
    用户登录
    
    - **username**: 用户名或邮箱
    - **password**: 密码
    """
    # 查找用户（支持用户名或邮箱登录）
    user = db.query(User).filter(
        (User.username == data.username) | (User.email == data.username)
    ).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    
    # 更新最后登录时间
    user.last_login_at = datetime.now()
    db.commit()
    
    # 生成 token
    token_data = {"sub": user.id, "username": user.username}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/refresh", response_model=TokenResponse, summary="刷新令牌")
async def refresh_token(data: TokenRefresh, db: Session = Depends(get_db)):
    """使用刷新令牌获取新的访问令牌"""
    payload = decode_token(data.refresh_token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="无效的刷新令牌")
    
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="请使用刷新令牌")
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    
    # 生成新 token
    token_data = {"sub": user.id, "username": user.username}
    access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/logout", summary="退出登录")
async def logout(current_user: User = Depends(get_current_user)):
    """退出登录（客户端清除token即可）"""
    return {"message": "退出成功"}


# ==================== 用户信息管理 ====================

@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user


@router.put("/me", response_model=UserResponse, summary="更新用户信息")
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新当前用户信息
    
    - **nickname**: 昵称
    - **avatar**: 头像URL
    - **phone**: 手机号
    """
    # 获取更新的字段（排除None值）
    update_data = data.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="没有提供要更新的字段")
    
    # 更新用户信息
    for key, value in update_data.items():
        setattr(current_user, key, value)
    
    current_user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


@router.patch("/me/avatar", response_model=UserResponse, summary="更新头像")
async def update_avatar(
    avatar_url: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    单独更新用户头像
    
    - **avatar_url**: 头像图片URL
    """
    current_user.avatar = avatar_url
    current_user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


@router.patch("/me/nickname", response_model=UserResponse, summary="更新昵称")
async def update_nickname(
    nickname: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    单独更新用户昵称
    
    - **nickname**: 新昵称（1-50字符）
    """
    if not nickname or len(nickname) > 50:
        raise HTTPException(status_code=400, detail="昵称长度应在1-50字符之间")
    
    current_user.nickname = nickname
    current_user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


@router.patch("/me/phone", response_model=UserResponse, summary="更新手机号")
async def update_phone(
    phone: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    单独更新用户手机号
    
    - **phone**: 手机号
    """
    # 简单的手机号格式验证
    if phone and (len(phone) < 10 or len(phone) > 20):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    
    current_user.phone = phone
    current_user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


# ==================== 密码管理 ====================

@router.post("/change-password", summary="修改密码")
async def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改当前用户密码
    
    - **old_password**: 原密码
    - **new_password**: 新密码（6位以上）
    """
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    
    if data.old_password == data.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    
    current_user.password_hash = hash_password(data.new_password)
    current_user.updated_at = datetime.now()
    
    db.commit()
    
    return {"message": "密码修改成功"}


@router.post("/reset-password-request", summary="请求重置密码")
async def reset_password_request(
    email: str,
    db: Session = Depends(get_db)
):
    """
    请求重置密码（发送重置链接到邮箱）
    
    - **email**: 注册邮箱
    """
    user = db.query(User).filter(User.email == email).first()
    
    # 无论用户是否存在，都返回成功（防止邮箱枚举攻击）
    if user:
        # TODO: 生成重置token并发送邮件
        # reset_token = create_reset_token(user.id)
        # send_reset_email(email, reset_token)
        pass
    
    return {"message": "如果该邮箱已注册，您将收到密码重置邮件"}


# ==================== 账号管理 ====================

@router.delete("/me", summary="注销账号")
async def delete_account(
    password: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    注销当前账号（需要验证密码）
    
    - **password**: 当前密码（用于验证身份）
    """
    if not verify_password(password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="密码验证失败")
    
    # 软删除：标记为已禁用
    current_user.status = "inactive"
    current_user.updated_at = datetime.now()
    
    db.commit()
    
    return {"message": "账号已注销"}


@router.get("/check-username/{username}", summary="检查用户名是否可用")
async def check_username(
    username: str,
    db: Session = Depends(get_db)
):
    """检查用户名是否已被使用"""
    exists = db.query(User).filter(User.username == username).first() is not None
    return {
        "username": username,
        "available": not exists,
        "message": "用户名已被使用" if exists else "用户名可用"
    }


@router.get("/check-email/{email}", summary="检查邮箱是否可用")
async def check_email(
    email: str,
    db: Session = Depends(get_db)
):
    """检查邮箱是否已被注册"""
    exists = db.query(User).filter(User.email == email).first() is not None
    return {
        "email": email,
        "available": not exists,
        "message": "邮箱已被注册" if exists else "邮箱可用"
    }