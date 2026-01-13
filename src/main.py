import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import FastAPI, HTTPException,Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from dotenv import load_dotenv
import os
load_dotenv()  # 自动读取当前目录或父目录的 .env



from src.agents.chat_agent import TravelChatAgent
from src.utils.context import set_session_id, get_session_id
from src.services.redis_service import redis_service
from src.services.chat_service import ChatService
from src.services.mysql_service import get_db


from src.services.mysql_service import engine, Base
from src.routers import auth, trips, budget
from src.middleware.auth import AuthMiddleware


# ============ 请求/响应模型 ============
class ChatRequest(BaseModel):
    session_id: str = Field(default="default")
    message: str
    stream: bool = Field(default=False)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    error: Optional[str] = None

class PlanResponse(BaseModel):
    success: bool
    session_id: str
    data: Optional[dict] = None
    message: Optional[str] = None


class PlanStatusResponse(BaseModel):
    session_id: str
    status: str  # pending, processing, completed, failed
    progress: int
    message: str



class HistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]


# 创建数据库表
Base.metadata.create_all(bind=engine)


# ============ FastAPI 应用 ============
app = FastAPI(title="Travel Planner API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 注册路由
app.include_router(auth.router)
app.include_router(trips.router)
app.include_router(budget.router)


# 初始化聊天 Agent
chat_agent: Optional[TravelChatAgent] = None




@app.on_event("startup")
async def startup():
    """应用启动时初始化"""
    global chat_agent
    
    print("\n" + "=" * 50)
    print("🚀 Travel Planner API 启动中...")
    print("=" * 50)
    
    # ✅ 检查 Redis 连接状态
    if redis_service.is_connected():
        stats = redis_service.get_stats()
        print(f"✅ Redis 连接正常:")
        print(f"   - 版本: {stats.get('redis_version')}")
        print(f"   - 内存使用: {stats.get('used_memory_human')}")
        print(f"   - 已存储计划数: {stats.get('travel_plans_count')}")
    else:
        print("⚠️ Redis 未连接，缓存功能不可用")
    
    # 初始化 Agent
    try:
        from src.agents.workflow import create_travel_agent_graph
        travel_graph = create_travel_agent_graph()
        chat_agent = TravelChatAgent(travel_graph=travel_graph)
        print("✅ Chat Agent 初始化成功")
    except Exception as e:
        print(f"❌ Chat Agent 初始化失败: {e}")
    
    print("=" * 50)
    print("🎉 服务启动完成!")
    print("=" * 50 + "\n")



@app.post("/travelapi/chat")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """智能聊天接口"""
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")

    session_id = req.session_id if req.session_id else f"session_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    print(f"📌 API 收到请求，session_id: {session_id}")

    # ✅ 保存用户消息
    ChatService.save_message(
        db=db,
        session_id=session_id,
        role="user",
        content=req.message,
        user_id=req.user_id if hasattr(req, 'user_id') else None
    )

    set_session_id(session_id)

    for tool in chat_agent.tools:
        if hasattr(tool, 'set_session_id'):
            tool.set_session_id(session_id)

    try:
        if req.stream:
            async def generate():
                set_session_id(session_id)
                full_reply = ""  # 收集完整回复
                
                try:
                    async for chunk in chat_agent.achat(req.message, session_id, stream=True):
                        full_reply += chunk
                        yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                    
                    # ✅ 流式结束后保存 AI 回复
                    ChatService.save_message(
                        db=db,
                        session_id=session_id,
                        role="assistant",
                        content=full_reply
                    )
                    
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            
            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            reply = ""
            async for content in chat_agent.achat(req.message, session_id, stream=False):
                reply = content
            
            # ✅ 保存 AI 回复
            ChatService.save_message(
                db=db,
                session_id=session_id,
                role="assistant",
                content=reply
            )
            
            return ChatResponse(
                session_id=session_id,
                reply=reply,
                error=None
            )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/travelapi/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    流式聊天接口（SSE）
    """
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")

    session_id = req.session_id if req.session_id else f"session_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    async def generate():
        try:
            async for chunk in chat_agent.achat(req.message, session_id, stream=True):
                yield f"data: {json.dumps({'content': chunk, 'session_id': session_id}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/travelapi/chat/sync")
async def chat_sync(req: ChatRequest):
    """
    同步聊天接口（使用线程池运行同步方法）
    """
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")

    session_id = req.session_id if req.session_id else f"session_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    try:
        # 使用线程池运行同步的 chat 方法
        reply = await run_in_threadpool(
            chat_agent.chat, 
            req.message, 
            session_id, 
            False  # stream=False
        )
        
        return ChatResponse(
            session_id=session_id,
            reply=reply,
            error=None
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/travelapi/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str):
    """获取会话历史"""
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")
    
    history = chat_agent.get_history(session_id)
    return HistoryResponse(
        session_id=session_id,
        messages=[ChatMessage(**msg) for msg in history]
    )


@app.delete("/travelapi/history/{session_id}")
async def clear_history(session_id: str):
    """清除会话历史"""
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")
    
    chat_agent.clear_history(session_id)
    return {"message": f"History cleared for session: {session_id}"}


@app.get("/travelapi/tools")
async def list_tools():
    """列出所有可用工具"""
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")

    tools_info = []
    for tool in chat_agent.tools:
        tools_info.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.args_schema.schema() if tool.args_schema else {}
        })

    return {"tools": tools_info}


@app.post("/travelapi/tool/call")
async def call_tool_directly(tool_name: str, arguments: Dict[str, Any]):
    """直接调用指定工具（调试用）"""
    if not chat_agent:
        raise HTTPException(status_code=500, detail="Chat agent not initialized")

    tool = next((t for t in chat_agent.tools if t.name == tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    try:
        result = await run_in_threadpool(tool.run, **arguments)
        return {"tool": tool_name, "result": json.loads(result) if isinstance(result, str) else result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))









# ===================== 新增：计划获取接口 =====================

@app.get("/travelapi/plan/{session_id}", response_model=PlanResponse)
async def get_plan(session_id: str):
    """
    获取指定 session 的旅行计划
    
    Args:
        session_id: 会话ID
        
    Returns:
        旅行计划数据
    """
    plan = redis_service.get_plan(session_id)
    
    if plan:
        return PlanResponse(
            success=True,
            session_id=session_id,
            data=plan,
            message="获取成功"
        )
    else:
        raise HTTPException(
            status_code=404, 
            detail=f"Plan not found for session: {session_id}"
        )


@app.get("/travelapi/plan/{session_id}/status", response_model=PlanStatusResponse)
async def get_plan_status(session_id: str):
    """
    获取计划生成状态（用于前端轮询）
    
    Args:
        session_id: 会话ID
        
    Returns:
        状态信息
    """
    status = redis_service.get_plan_status(session_id)
    
    if status:
        return PlanStatusResponse(
            session_id=session_id,
            status=status.get("status", "unknown"),
            progress=status.get("progress", 0),
            message=status.get("message", "")
        )
    else:
        return PlanStatusResponse(
            session_id=session_id,
            status="not_found",
            progress=0,
            message="该会话没有正在进行的计划生成任务"
        )


@app.delete("/travelapi/plan/{session_id}")
async def delete_plan(session_id: str):
    """删除指定 session 的旅行计划"""
    success = redis_service.delete_plan(session_id)
    
    if success:
        return {"success": True, "message": f"Plan deleted: {session_id}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete plan")


@app.get("/travelapi/plans")
async def list_plans(limit: int = 100):
    """列出所有计划（管理接口）"""
    plans = redis_service.list_plans(limit=limit)
    return {
        "success": True,
        "count": len(plans),
        "plans": plans
    }



# ============ 健康检查 ============
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "agent_initialized": chat_agent is not None,
        "tools_count": len(chat_agent.tools) if chat_agent else 0,
        "model": chat_agent.model_name if chat_agent else None
    }


@app.get("/")
async def root():
    """API 根路径"""
    return {
        "name": "Travel Planner API",
        "version": "1.0.0",
        "endpoints": {
            "chat": "POST /travelapi/chat",
            "chat_stream": "POST /travelapi/chat/stream", 
            "chat_sync": "POST /travelapi/chat/sync",
            "history": "GET /travelapi/history/{session_id}",
            "clear_history": "DELETE /travelapi/history/{session_id}",
            "tools": "GET /travelapi/tools",
            "tool_call": "POST /travelapi/tool/call",
            "health": "GET /health"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)