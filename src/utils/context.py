# src/utils/context.py
from contextvars import ContextVar
from typing import Optional

# 上下文变量 - 用于在异步调用链中传递 session_id
_session_id_var: ContextVar[str] = ContextVar('session_id', default='')

def set_session_id(session_id: str) -> None:
    """设置当前上下文的 session_id"""
    _session_id_var.set(session_id)
    print(f"📌 Context session_id set: {session_id}")

def get_session_id() -> str:
    """获取当前上下文的 session_id"""
    return _session_id_var.get()

def clear_session_id() -> None:
    """清除 session_id"""
    _session_id_var.set('')