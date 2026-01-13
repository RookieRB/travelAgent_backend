# src/agents/chat_agent.py

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# 导入工具
from src.tools.tools import get_all_tools

from src.models.llm import Myllm

# ============ 系统提示词 ============

SYSTEM_PROMPT = """你是一位专业的旅行规划助手，名叫"小游"。你热情、专业、善于倾听用户需求。

## 你的能力
1. **查询天气** - 使用 query_weather 工具查询目的地天气
2. **搜索攻略** - 使用 search_xiaohongshu 工具搜索小红书上的旅行攻略和真实体验
3. **周边搜索** - 使用 search_nearby 工具搜索周边设施
4. **POI搜索** - 使用 search_poi 工具搜索具体地点
5. **路线规划** - 使用 plan_route 工具规划交通路线
6. **地理编码** - 使用 geo_code 工具将地址转换为坐标
7. **生成计划** - 使用 generate_travel_plan 工具生成完整的旅行计划

## 工作流程
1. 主动询问用户的旅行需求（目的地、天数、人数、偏好等）
2. 收集到足够信息后，主动查询目的地天气
3. 搜索小红书获取真实攻略和避坑指南
4. 综合所有信息，生成个性化旅行计划

## 交互原则
- 友好热情，像朋友一样交流
- 主动询问缺失的关键信息
- 用 emoji 让对话更生动 🎉✈️🏖️
- 给出专业建议时说明理由
- 如果信息不足，先询问再规划

## 关键信息收集清单
- 目的地 ✈️（必须）
- 出行天数 📅（必须）
- 出发城市 🏠
- 出行时间 ⏰
- 同行人员（家庭/情侣/朋友/独自）👥
- 偏好（美食/购物/自然/历史/网红打卡）💝
- 预算范围 💰

当用户表达想要规划行程时，检查是否收集了以上关键信息。如果缺少必要信息，友好地询问用户。

当前时间：{current_time}
"""


class TravelChatAgent:
    """旅行规划对话 Agent"""
    
    def __init__(self, model_name: str = None,travel_graph: Any = None, temperature: float = 0.7):
        """
        初始化对话 Agent
        
        Args:
            model_name: 模型名称，默认从环境变量读取
            temperature: 温度参数
        """
 
        self.model_name = os.getenv("OPENAI_MODEL", "qwen-plus")
        self.temperature = temperature
        
        # 1. 先初始化会话存储（必须在 _create_agent 之前）
        self.memory = MemorySaver()
        
        # 2. 初始化 LLM
        self.llm = Myllm
        
        # 3. 初始化工具
        self.tools = get_all_tools(travel_graph)
        
        # 4. 最后初始化 Agent（依赖上面的所有组件）
        self.agent = self._create_agent()
    
    def _create_llm(self) -> ChatOpenAI:
        """创建 LLM 实例"""
        api_key = os.getenv("OPENAI_API_KEY") 
        base_url = os.getenv("OPENAI_API_BASE")
        if not api_key:
            print("⚠️ OPENAI_API_KEY not set, using placeholder")
            api_key = "sk-placeholder"
        
        return ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            api_key=api_key,
            base_url=base_url,
        )
    def _get_system_prompt(self) -> str:
        """获取带当前时间的系统提示词"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return SYSTEM_PROMPT.format(current_time=current_time)
    
    def _create_agent(self):
        """创建 ReAct Agent"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=prompt,
            checkpointer=self.memory,
        )
        
        return agent
    
    def chat(
        self, 
        message: str, 
        session_id: str = "default",
        stream: bool = False
    ) -> str | Any:
        """
        发送消息并获取回复
        
        Args:
            message: 用户消息
            session_id: 会话 ID，用于保持对话历史
            stream: 是否流式输出
            
        Returns:
            AI 回复内容
        """
        config = {"configurable": {"thread_id": session_id}}
        
        input_message = {"messages": [HumanMessage(content=message)]}
        
        if stream:
            return self._stream_chat(input_message, config)
        else:
            return self._sync_chat(input_message, config)
    
    def _sync_chat(self, input_message: Dict, config: Dict) -> str:
        """同步对话"""
        try:
            result = self.agent.invoke(input_message, config)
            
            # 获取最后一条 AI 消息
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    return msg.content
            
            return "抱歉，我没有理解您的意思，请再说一遍？"
            
        except Exception as e:
            print(f"Chat error: {e}")
            import traceback
            traceback.print_exc()
            return f"抱歉，发生了一些错误：{str(e)}"
    
    def _stream_chat(self, input_message: Dict, config: Dict):
        """流式对话"""
        try:
            for chunk in self.agent.stream(input_message, config, stream_mode="messages"):
                # chunk 是 (message, metadata) 元组
                if isinstance(chunk, tuple):
                    message, metadata = chunk
                    if isinstance(message, AIMessage) and message.content:
                        yield message.content
                elif hasattr(chunk, 'content') and chunk.content:
                    yield chunk.content
                    
        except Exception as e:
            print(f"Stream chat error: {e}")
            import traceback
            traceback.print_exc()
            yield f"抱歉，发生了一些错误：{str(e)}"
    
    async def achat(
        self, 
        message: str, 
        session_id: str = "default",
        stream: bool = False
    ):
        """
        异步发送消息并获取回复
        
        Args:
            message: 用户消息
            session_id: 会话 ID
            stream: 是否流式输出
        """
        config = {"configurable": {"thread_id": session_id}}
        input_message = {"messages": [HumanMessage(content=message)]}
        
        if stream:
            async for chunk in self._astream_chat(input_message, config):
                yield chunk
        else:
            result = await self._async_chat(input_message, config)
            yield result
    
    async def _async_chat(self, input_message: Dict, config: Dict) -> str:
        """异步对话"""
        try:
            result = await self.agent.ainvoke(input_message, config)
            
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    return msg.content
            
            return "抱歉，我没有理解您的意思，请再说一遍？"
            
        except Exception as e:
            print(f"Async chat error: {e}")
            return f"抱歉，发生了一些错误：{str(e)}"
    
    async def _astream_chat(self, input_message: Dict, config: Dict):
        """异步流式对话"""
        try:
            async for chunk in self.agent.astream(input_message, config, stream_mode="messages"):
                if isinstance(chunk, tuple):
                    message, metadata = chunk
                    if isinstance(message, AIMessage) and message.content:
                        yield message.content
                elif hasattr(chunk, 'content') and chunk.content:
                    yield chunk.content
                    
        except Exception as e:
            print(f"Async stream error: {e}")
            yield f"抱歉，发生了一些错误：{str(e)}"
    
    def get_history(self, session_id: str = "default") -> List[Dict]:
        """
        获取对话历史
        
        Args:
            session_id: 会话 ID
            
        Returns:
            对话历史列表
        """
        try:
            config = {"configurable": {"thread_id": session_id}}
            state = self.agent.get_state(config)
            
            if state and state.values:
                messages = state.values.get("messages", [])
                history = []
                for msg in messages:
                    if isinstance(msg, HumanMessage):
                        history.append({"role": "user", "content": msg.content})
                    elif isinstance(msg, AIMessage):
                        history.append({"role": "assistant", "content": msg.content})
                return history
            
            return []
            
        except Exception as e:
            print(f"Get history error: {e}")
            return []
    
    def clear_history(self, session_id: str = "default"):
        """
        清除对话历史
        
        Args:
            session_id: 会话 ID
        """
        try:
            # MemorySaver 没有直接删除的方法
            # 实际项目中可使用支持删除的持久化存储
            print(f"Note: MemorySaver doesn't support clearing. Session: {session_id}")
        except Exception as e:
            print(f"Clear history error: {e}")


# ============ 简化版 Agent（不使用工具，用于测试） ============

class SimpleChatAgent:
    """简化版对话 Agent，不使用工具，用于测试"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "qwen-plus"),
            temperature=0.7,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE"),
        )
        self.history: List[BaseMessage] = []
    
    def chat(self, message: str) -> str:
        """简单对话"""
        system_msg = SystemMessage(content=SYSTEM_PROMPT.format(
            current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        
        self.history.append(HumanMessage(content=message))
        
        messages = [system_msg] + self.history
        
        try:
            response = self.llm.invoke(messages)
            self.history.append(response)
            return response.content
        except Exception as e:
            return f"Error: {e}"


# ============ 测试代码 ============

def test_agent():
    """测试 Agent"""
    print("=" * 60)
    print("Testing TravelChatAgent")
    print("=" * 60)
    
    try:
        agent = TravelChatAgent()
        print("✅ Agent created successfully")
        print(f"   Model: {agent.model_name}")
        print(f"   Tools: {[t.name for t in agent.tools]}")
        
        # 测试对话
        test_messages = [
            "你好，我想去杭州旅游",
            "大概3天时间，和女朋友一起",
        ]
        
        session_id = "test_session"
        
        for msg in test_messages:
            print(f"\n👤 User: {msg}")
            response = agent.chat(msg, session_id=session_id)
            print(f"🤖 Assistant: {response[:200]}..." if len(response) > 200 else f"🤖 Assistant: {response}")
        
        # 测试获取历史
        history = agent.get_history(session_id)
        print(f"\n📜 History length: {len(history)}")
        
        print("\n✅ All tests passed!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_agent()