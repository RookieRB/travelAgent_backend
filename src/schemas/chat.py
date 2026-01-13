from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessageCreate(BaseModel):
    """创建消息"""
    role: MessageRole
    content: str
    extra_data: Optional[Dict[str, Any]] = None  # ✅ 改名


class ChatMessageResponse(BaseModel):
    """消息响应"""
    id: int
    session_id: str
    role: str
    content: str
    extra_data: Optional[Dict[str, Any]] = None  # ✅ 改名
    created_at: datetime
    
    class Config:
        from_attributes = True


class ChatSessionCreate(BaseModel):
    """创建会话"""
    session_id: Optional[str] = None
    title: Optional[str] = "新对话"


class ChatSessionResponse(BaseModel):
    """会话响应"""
    id: str
    user_id: Optional[str] = None
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class ChatSessionWithMessages(ChatSessionResponse):
    """会话响应（包含消息）"""
    messages: List[ChatMessageResponse] = []


class ChatHistoryResponse(BaseModel):
    """聊天历史响应（前端格式）"""
    session_id: str
    messages: List[Dict[str, Any]]  # 前端需要的格式