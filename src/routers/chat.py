from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import json

from src.services.mysql_service import get_db
from src.services.chat_service import ChatService
from src.models.user import User
from src.middleware.auth import get_current_user, get_optional_user
from src.schemas.chat import (
    ChatSessionResponse, ChatSessionWithMessages, 
    ChatHistoryResponse, ChatMessageResponse
)

router = APIRouter(prefix="/travelapi/chat", tags=["聊天"])


# ==================== 聊天历史接口 ====================

@router.get("/history/{session_id}", response_model=ChatHistoryResponse, summary="获取聊天历史")
async def get_chat_history(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db)
):
    """
    获取指定会话的聊天历史
    
    返回格式适配前端展示
    """
    messages = ChatService.get_session_history_for_frontend(db, session_id)
    
    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages
    )


@router.get("/sessions", summary="获取会话列表")
async def get_sessions(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户的所有聊天会话"""
    sessions = ChatService.get_user_sessions(db, current_user.id, limit)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}", response_model=ChatSessionWithMessages, summary="获取会话详情")
async def get_session_detail(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取会话详情（包含所有消息）"""
    from src.models.chat import ChatSession
    
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    messages = ChatService.get_session_messages(db, session_id)
    
    return ChatSessionWithMessages(
        id=session.id,
        user_id=session.user_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(messages),
        messages=messages
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除指定会话及其所有消息"""
    success = ChatService.delete_session(db, session_id, current_user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {"message": "删除成功"}


@router.post("/sessions/{session_id}/clear", summary="清空会话消息")
async def clear_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """清空会话的所有消息，保留会话本身"""
    success = ChatService.clear_session_messages(db, session_id, current_user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {"message": "清空成功"}


@router.patch("/sessions/{session_id}/title", summary="更新会话标题")
async def update_session_title(
    session_id: str,
    title: str = Query(..., min_length=1, max_length=255),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新会话标题"""
    session = ChatService.update_session_title(db, session_id, current_user.id, title)
    
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {"message": "更新成功", "title": session.title}