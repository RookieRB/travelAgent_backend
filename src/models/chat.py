from sqlalchemy import Column, String, Text, BigInteger, Enum, JSON, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from src.services.mysql_service import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(String(100), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), default="新对话")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    # 关联
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum('user', 'assistant', 'system'), nullable=False)
    content = Column(Text, nullable=False)
    extra_data = Column(JSON, nullable=True)  # ✅ 改名：metadata -> extra_data
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    # 关联
    session = relationship("ChatSession", back_populates="messages")