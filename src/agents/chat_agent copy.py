# src/agents/chat_agent.py

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage,ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# 导入工具
from src.tools.tools import get_all_tools

from src.models.llm import LLMFactory

# ============ 系统提示词 ============

SYSTEM_PROMPT = """你是一位专业的旅行规划助手，名叫"小游"。你热情、细致，善于倾听和挖掘用户需求。

    ═══════════════════════════════════════════
    ⛔ 核心禁令（最高优先级）
    ═══════════════════════════════════════════
    1. **禁止自行生成任何具体行程安排**：你不能自己编写"第一天去哪、第二天去哪"这样的内容。
    2. **所有行程必须通过工具生成**：当信息收集完毕并获得用户确认后，你必须调用 `generate_travel_plan` 工具，由工具返回行程。
    3. **禁止编造信息**：所有景点、价格、时间等必须基于真实数据。

    ═══════════════════════════════════════════
    🔧 工具说明
    ═══════════════════════════════════════════
    你**唯一**可用的工具是 `generate_travel_plan`

    ⚠️ 调用时机：必须在完成信息收集 + 用户确认后，才能调用此工具。

    ═══════════════════════════════════════════
    📋 工作流程
    ═══════════════════════════════════════════

    阶段1：初步接触与范围确认

    热情问候
    如果用户说省份/国家，必须引导到具体城市
    示例："云南很大哦！3天建议聚焦一个城市：昆明🌸、大理🌊、还是丽江🏔️？"

    阶段2：深度挖掘（分批自然询问）

    基础信息：出发地、日期、天数、人员构成
    预算标准：预算范围、住宿偏好
    风格偏好：节奏、兴趣点、避雷项
    阶段3：信息确认 ⭐关键步骤
    在调用工具前，必须输出确认摘要：

    text

    📋 【行程信息确认】
    🏙️ 目的地：XXX
    🚀 出发地：XXX
    📅 时间：X月X日 - X月X日，共X天
    👥 人员：X人，XXX出行
    💰 预算：XXX
    🎯 偏好：XXX
    ❌ 避雷：XXX

    以上信息确认无误吗？确认后我将为您生成详细行程！
    阶段4：调用工具生成方案

    用户确认后，立即调用 generate_travel_plan 工具
    绝对禁止自己编写行程内容
    等待工具返回结果后，友好地呈现给用户
    ═══════════════════════════════════════════
    🚫 目的地约束
    ═══════════════════════════════════════════
    必须限定在【城市】级别（如：成都、杭州、苏梅岛）
    ❌ 拒绝接受：省级/国家级范围（如：云南、日本、欧洲）

    当用户给出宽泛区域时：

    解释原因（太大、体验不好）
    给出该区域内 2-3 个热门城市选项
    请用户选择
    ═══════════════════════════════════════════
    💬 交互原则
    ═══════════════════════════════════════════

    拒绝机械问答，分批次自然追问
    对"随便"类回答，给出具体选项引导
    多用 emoji 保持轻松氛围 🎉✈️🍜🏞️
    对不合理计划（如3天玩新疆），明确指出并建议
    ═══════════════════════════════════════════
    ✅ 正确示例
    ═══════════════════════════════════════════
    用户：确认没问题，帮我生成吧。
    AI：好的！正在为您生成行程... ✨
    [调用 generate_travel_plan 工具]
    （等待工具返回结果后展示）

    ❌ 错误示例
    ═══════════════════════════════════════════
    用户：确认没问题。
    AI：好的，以下是您的行程：
    第一天：上午游览XXX，下午前往XXX...
    （❌ 错误：自己编写了行程，没有调用工具）

    当前时间：{current_time}
    """

class TravelChatAgent:
    """旅行规划对话 Agent"""
    
    def __init__(self, model_name: str = None, travel_graph: Any = None, temperature: float = 0.7):
        self.model_name = os.getenv("OPENAI_MODEL", "qwen-plus")
        self.temperature = temperature
        self.llm = LLMFactory.get_smart_model()
        self.tools = get_all_tools(travel_graph)
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
        )
        
        return agent
    
    # ==================== 核心修复 ====================
    
    def _build_messages_from_history(self, chat_history: List[Dict]) -> List[BaseMessage]:
        """
        从聊天历史构建消息列表
        
        ✅ 只保留有效的用户和助手最终回复
        ✅ 过滤掉工具调用过程中的中间消息
        ✅ 确保所有 content 都不为空
        """
        messages = []
        
        if not chat_history:
            return messages
        
        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # ✅ 跳过空内容
            if not content or not content.strip():
                continue
            
            # ✅ 跳过工具相关消息（这些不应该存入历史）
            if role == "tool":
                continue
            
            # ✅ 跳过系统消息（系统消息由 prompt 模板提供）
            if role == "system":
                continue
            
            # 构建消息
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # ✅ 只保留有实际内容的助手消息
                messages.append(AIMessage(content=content))
        
        return messages
    
    def _validate_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        验证消息列表，确保所有 content 都不为空
        """
        validated = []
        
        for i, msg in enumerate(messages):
            content = getattr(msg, 'content', None)
            
            # 检查空值
            if content is None:
                print(f"⚠️ 消息 {i} content 为 None，类型: {type(msg).__name__}")
                continue
            
            if isinstance(content, str) and not content.strip():
                print(f"⚠️ 消息 {i} content 为空字符串，类型: {type(msg).__name__}")
                continue
            
            # 如果是列表类型的 content（某些模型支持），转换为字符串
            if isinstance(content, list):
                content = str(content)
                msg = type(msg)(content=content)
            
            validated.append(msg)
        
        return validated

    async def achat(
        self, 
        message: str, 
        session_id: str = "default",
        chat_history: list = None,
        stream: bool = False
    ):
        """
        异步发送消息并获取回复 (无状态模式)
        """
        # ✅ 使用新的方法构建历史消息
        messages_payload = self._build_messages_from_history(chat_history)
        
        # 添加当前用户的新消息
        messages_payload.append(HumanMessage(content=message))
        
        # ✅ 验证所有消息
        messages_payload = self._validate_messages(messages_payload)
        
        # 调试日志
        if os.getenv("DEBUG_MESSAGES"):
            print(f"\n{'='*50}")
            print(f"📨 发送给 Agent 的消息 ({len(messages_payload)} 条):")
            for i, msg in enumerate(messages_payload):
                content_preview = str(msg.content)[:100] if msg.content else "None"
                print(f"  [{i}] {type(msg).__name__}: {content_preview}...")
            print(f"{'='*50}\n")
        
        # 构造输入字典
        input_message = {"messages": messages_payload}
        config = {"configurable": {"thread_id": session_id}}
        
        if stream:
            async for chunk in self._astream_chat(input_message, config):
                yield chunk
        else:
            result = await self._async_chat(input_message, config)
            yield result

    async def _async_chat(self, input_message: Dict, config: Dict) -> str:
        """异步对话（非流式）- 支持工具调用标记"""
        try:
            result = await self.agent.ainvoke(input_message, config)
            messages = result.get("messages", [])
            
            # 🔧 工具名称配置
            ROUTE_TOOLS = {"generate_travel_plan"}
            
            # ====== 检测是否调用了路线相关工具 ======
            route_tool_called = False
            plain_id = ""
            session_id = ""


            for msg in messages:
                # 检查 AIMessage 的 tool_calls
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tool_name = tool_call.get('name', '') if isinstance(tool_call, dict) else getattr(tool_call, 'name', '')
                        if tool_name in ROUTE_TOOLS:
                            route_tool_called = True
                            break
                
                # 检查 ToolMessage
                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, 'name', '')
                    if tool_name in ROUTE_TOOLS:
                        route_tool_called = True
                       # 解析工具返回的 JSON
                    try:
                        tool_result = json.loads(msg.content)
                        plan_id = tool_result.get("plan_id", "")
                        session_id = tool_result.get("session_id", "")
                    except:
                        pass
            
            # ====== 获取最终回复 ======
            final_response = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    if content and content.strip():
                        # 确保不是工具调用的中间消息
                        if not (hasattr(msg, 'tool_calls') and msg.tool_calls):
                            final_response = content
                            break
            
            if not final_response:
                return "抱歉，我没有理解您的意思，请再说一遍？"
            
            # 🔥 添加标记前缀
            if route_tool_called:
                return f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>" + final_response
            
            return final_response
            
        except Exception as e:
            print(f"Async chat error: {e}")
            import traceback
            traceback.print_exc()
            return f"抱歉，发生了一些错误：{str(e)}"



    async def _astream_chat(self, input_message: Dict, config: Dict):
        """
        异步流式对话
        
        ✅ 检测特定工具调用后，在最终回复前插入 <<<ACTION:MAP>>> 标记
        """
        try: 
             # ====== 状态追踪 ======
            route_tool_called = False   # 是否调用了路线相关工具
            marker_sent = False         # 是否已发送标记
            
            plan_id = ""      # 🆕
            session_id = ""   # 🆕


            # 🔧 需要触发地图标记的工具名称（根据你的实际工具调整）
            ROUTE_TOOLS = {
                "generate_travel_plan",   # 生成行程
            }

            async for chunk in self.agent.astream(input_message, config, stream_mode="messages"):
                if isinstance(chunk, tuple):
                    message, metadata = chunk
                    if isinstance(message, AIMessage):
                        # 检查是否有 tool_calls
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            for tool_call in message.tool_calls:
                                # tool_call 可能是 dict 或对象
                                if isinstance(tool_call, dict):
                                    tool_name = tool_call.get('name', '')
                                else:
                                    tool_name = getattr(tool_call, 'name', '')
                                
                                if tool_name in ROUTE_TOOLS:
                                    route_tool_called = True
                                    print(f"🗺️ 检测到地图相关工具调用: {tool_name}")
                        
                            # 带有 tool_calls 的消息，跳过（不输出给用户）
                            continue

                        # ====== 2. 处理最终回复的 AIMessage ======
                        content = message.content
                        if content and content.strip():
                            # 🔥 关键：在输出第一个内容前，发送标记
                            if route_tool_called and not marker_sent:
                                yield f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>"
                                marker_sent = True
                            yield content

                        # ====== 3. 检测 ToolMessage（工具执行结果） ======
                    elif isinstance(message, ToolMessage):
                        tool_name = getattr(message, 'name', '')
                        if tool_name in ROUTE_TOOLS:
                            route_tool_called = True
                            try:
                                tool_result = json.loads(message.content)
                                plan_id = tool_result.get("plan_id", "")
                                session_id = tool_result.get("session_id", "")
                                print(f"🗺️ 工具完成: plan_id={plan_id}")
                            except:
                                pass
                 # 处理其他格式的 chunk（兼容性）
                elif hasattr(chunk, 'content'):
                    content = chunk.content
                    if content and content.strip():
                        if route_tool_called and not marker_sent:
                            yield f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>"
                            marker_sent = True
                        yield content
                    
        except Exception as e:
            print(f"Async stream error: {e}")
            import traceback
            traceback.print_exc()
            yield f"抱歉，发生了一些错误：{str(e)}"
    
    # ==================== 同步方法也需要修复 ====================
    
    def chat(
        self, 
        message: str, 
        session_id: str = "default",
        chat_history: list = None,  # ✅ 添加 chat_history 参数
        stream: bool = False
    ) -> str | Any:
        """发送消息并获取回复"""
        
        # ✅ 构建消息
        messages_payload = self._build_messages_from_history(chat_history)
        messages_payload.append(HumanMessage(content=message))
        messages_payload = self._validate_messages(messages_payload)
        
        input_message = {"messages": messages_payload}
        config = {"configurable": {"thread_id": session_id}}
        
        if stream:
            return self._stream_chat(input_message, config)
        else:
            return self._sync_chat(input_message, config)
    
    def _sync_chat(self, input_message: Dict, config: Dict) -> str:
        """同步对话"""
        try:
            result = self.agent.invoke(input_message, config)
            
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    if content and content.strip():
                        return content
            
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
                if isinstance(chunk, tuple):
                    message, metadata = chunk
                    if isinstance(message, AIMessage):
                        content = message.content
                        if content and content.strip():
                            yield content
                elif hasattr(chunk, 'content'):
                    content = chunk.content
                    if content and content.strip():
                        yield content
                    
        except Exception as e:
            print(f"Stream chat error: {e}")
            import traceback
            traceback.print_exc()
            yield f"抱歉，发生了一些错误：{str(e)}"
