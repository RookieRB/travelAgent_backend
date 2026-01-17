from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional, Dict, Any
from datetime import datetime
from src.models.chat import ChatSession, ChatMessage
from src.schemas.chat import MessageRole


class ChatService:
    """聊天服务"""
    
    @staticmethod
    def get_or_create_session(
        db: Session, 
        session_id: str, 
        user_id: Optional[str] = None,
        title: Optional[str] = None
    ) -> ChatSession:
        """获取或创建会话"""
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        
        if not session:
            session = ChatSession(
                id=session_id,
                user_id=user_id,
                title=title or "新对话"
            )
            db.add(session)
            db.commit()
            db.refresh(session)
        
        return session
    
    @staticmethod
    def save_message(
        db: Session,
        session_id: str,
        role: str,
        content: str,
        extra_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> ChatMessage:
        """保存消息"""
        session = ChatService.get_or_create_session(db, session_id, user_id)
        

         # ✅ 只保存有内容的消息
        if not content or not content.strip():
            print(f"⚠️ 跳过保存空消息: role={role}")
            return
        
        # ✅ 只保存 user 和 assistant 的最终消息
        if role not in ["user", "assistant"]:
            print(f"⚠️ 跳过保存非对话消息: role={role}")
            return

        if not session:
          session = ChatSession(id=session_id, user_id=user_id, title="新对话")
          db.add(session)
        else:
          # 🔥 关键：如果 session 之前没绑定用户，现在有了 user_id，则绑定上去
          if session.user_id is None and user_id is not None:
              session.user_id = user_id
        
          # 更新最后更新时间
          session.updated_at = datetime.now()




        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            extra_data=extra_data 
        )
        db.add(message)
        
        if role == "user":
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session and session.title == "新对话":
                session.title = content[:30] + ("..." if len(content) > 30 else "")
        
        db.commit()
        db.refresh(message)
        
        return message


    @staticmethod
    def get_session_messages(
        db: Session,
        session_id: str,
        limit: int = 100
    ) -> List[ChatMessage]:
        """获取会话消息"""
        return db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.asc()).limit(limit).all()
    
    @staticmethod
    def get_session_history_for_frontend(
        db: Session,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """获取会话历史（前端格式）"""
        messages = ChatService.get_session_messages(db, session_id)

        result = []
        for msg in messages:
            result.append({
                "id": msg.id,
                "type": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "extra_data": msg.extra_data  # ✅ 改名
            })
        
        return result


    @staticmethod
    def get_user_sessions(
        db: Session,
        user_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取用户的所有会话列表"""
        sessions = db.query(ChatSession).filter(
            ChatSession.user_id == user_id
        ).order_by(desc(ChatSession.updated_at)).limit(limit).all()
        
        result = []
        for session in sessions:
            # 获取消息数量和最后一条消息
            message_count = db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.session_id == session.id
            ).scalar()
            
            last_message = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.id
            ).order_by(desc(ChatMessage.created_at)).first()
            
            result.append({
                "id": session.id,
                "title": session.title,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "message_count": message_count,
                "last_message": last_message.content[:50] if last_message else None
            })
        
        return result
    
    @staticmethod
    def delete_session(db: Session, session_id: str, user_id: str) -> bool:
        """删除会话"""
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id
        ).first()
        
        if not session:
            return False
        
        db.delete(session)
        db.commit()
        return True
    
    @staticmethod
    def clear_session_messages(db: Session, session_id: str, user_id: str) -> bool:
        """清空会话消息"""
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id
        ).first()
        
        if not session:
            return False
        
        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        db.commit()
        return True
    
    @staticmethod
    def update_session_title(
        db: Session, 
        session_id: str, 
        user_id: str, 
        title: str
    ) -> Optional[ChatSession]:
        """更新会话标题"""
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id
        ).first()
        
        if not session:
            return None
        
        session.title = title
        db.commit()
        db.refresh(session)
        return session