from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from src.services.mysql_service import get_db
from src.models.user import User
from src.utils.security import decode_token

security = HTTPBearer()


class AuthMiddleware:
    """认证中间件"""
    
    @staticmethod
    async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db)
    ) -> User:
        """获取当前登录用户"""
        token = credentials.credentials
        
        # 解码 token
        payload = decode_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="无效的访问令牌")
        
        # 检查 token 类型
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="请使用访问令牌")
        
        # 获取用户ID
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效的令牌载荷")
        
        # 查询用户
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        
        if user.status != "active":
            raise HTTPException(status_code=403, detail="账号已被禁用")
        
        return user
    
    @staticmethod
    async def get_optional_user(
        request: Request,
        db: Session = Depends(get_db)
    ) -> Optional[User]:
        """可选的用户认证（用于公开接口）"""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        payload = decode_token(token)
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        return db.query(User).filter(User.id == user_id).first()


# 快捷依赖
get_current_user = AuthMiddleware.get_current_user
get_optional_user = AuthMiddleware.get_optional_user