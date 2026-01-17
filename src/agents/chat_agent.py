# src/agents/chat_agent.py

import os
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import create_react_agent

# 导入工具
from src.tools.tools import get_all_tools

# ✅ 只使用 LLMFactory
from src.models.llm import LLMFactory


# ============ 确认信号识别 ============

CONFIRM_KEYWORDS = [
    "开始", "确认", "可以", "没问题", "对的", "是的", 
    "好的", "ok", "OK", "Go", "go", "出发", "开始规划",
    "确认无误", "没有问题", "正确", "对", "嗯", "行",
    "就这样", "可以了", "好", "yes", "YES", "生成",
    "生成行程", "帮我生成", "开始生成", "确定", "没错",
    "对的对的", "是", "行吧", "可以的", "gogogo",
    "冲", "走起", "安排", "就这么定了", "定了"
]

DENY_KEYWORDS = [
    "不对", "不是", "修改", "改一下", "错了", "重新",
    "不行", "换", "改", "no", "NO", "不", "有问题",
    "等等", "稍等", "暂停", "取消", "错", "改改"
]


def is_confirmation(user_input: str) -> bool:
    """判断用户输入是否为确认"""
    text = user_input.strip()
    text_lower = text.lower()
    
    # 🛑 新增：显式排除打招呼词汇
    GREETING_KEYWORDS = ["你好", "您好", "hi", "hello", "hey", "在吗", "嗨"]
    if any(text_lower == g for g in GREETING_KEYWORDS) or \
       any(text_lower.startswith(g) and len(text) < 5 for g in GREETING_KEYWORDS):
        return False  # 如果是打招呼，绝对不是确认
    
    # ... 原有的逻辑 ...
    if len(text) <= 10:
        for keyword in CONFIRM_KEYWORDS:
            if text_lower == keyword.lower() or text == keyword:
                return True
    
    has_confirm = any(k.lower() in text_lower or k in text for k in CONFIRM_KEYWORDS)
    has_deny = any(k.lower() in text_lower or k in text for k in DENY_KEYWORDS)
    
    return has_confirm and not has_deny


def is_denial(user_input: str) -> bool:
    """判断用户输入是否为否定"""
    text = user_input.strip().lower()
    return any(k.lower() in text for k in DENY_KEYWORDS)


def detect_confirmation_context(chat_history: List[Dict], current_message: str) -> bool:
    """检测是否处于确认上下文"""
    if not chat_history:
        return False
    
    last_ai_message = None
    for msg in reversed(chat_history):
        if msg.get("role") == "assistant":
            last_ai_message = msg.get("content", "")
            break
    
    if not last_ai_message:
        return False
    
    confirm_request_keywords = [
        "确认无误", "确认后", "以上信息", "确认吗",
        "没问题吗", "对吗", "是否正确", "信息确认",
        "确定吗", "可以吗", "行程信息确认", "确认没问题"
    ]
    
    has_confirm_request = any(k in last_ai_message for k in confirm_request_keywords)
    is_short_confirm = len(current_message.strip()) <= 20 and is_confirmation(current_message)
    
    return has_confirm_request and is_short_confirm


# ============ 系统提示词 ============

# ============ 系统提示词 ============

SYSTEM_PROMPT = """你是一位专业的旅行规划助手，名叫"小游"。你性格热情、活泼，不仅善于倾听，还是一位**排版美学专家**。

═══════════════════════════════════════════
🛑 防误触与状态重置（必须严格执行）
═══════════════════════════════════════════
**在调用工具前，必须进行二次逻辑校验：**

1. **识别打招呼/新话题**：
   - 如果用户输入 "你好"、"在吗"、"Hello"、"Hi"、"重新开始" 等开场白。
   - 🚨 **禁止调用工具**！
   - 必须 **清空之前的确认状态**，把你当成第一次见到用户，重新开始【阶段1：信息收集】。
   - 回复示例："👋 嗨！我是小游，又见面啦！这次想去哪里玩呢？"

2. **识别上下文过期**：
   - 如果上一条消息已经是生成的行程结果（而不是询问"确认无误吗"），用户的新回复应被视为对行程的反馈或新对话。
   - 此时 **禁止重复调用工具** 生成完全一样的行程。

═══════════════════════════════════════════
🎨 回复风格与排版规范（美化核心）
═══════════════════════════════════════════
1. **Emoji 必须使用**：
   - 所有的标题、重点词汇前必须加上贴切的 Emoji（如 📍, 📅, 💰, 🍜, 🏨）。
   - 让对话气氛轻松愉快。

2. **信息确认表格化**：
   - 在【阶段2：信息确认】时，**必须使用 Markdown 表格**来展示收集到的信息，严禁只列文本。
   - 格式参考：
     | 📋 需求项 | 📝 详细内容 |
     | :--- | :--- |
     | 📍 **目的地** | **城市名** ✨ |

3. **结构清晰**：
   - 多使用 **加粗** 来强调关键信息。
   - 适当使用分割线（---）区分板块。

═══════════════════════════════════════════
⛔ 核心禁令（最高优先级）
═══════════════════════════════════════════
1. **禁止自行生成任意具体行程安排**：你不能自己编写"第一天去哪"这样的内容。
2. **所有行程必须通过工具生成**：只有在用户明确确认信息后，才能调用 `generate_travel_plan`。
3. **禁止编造信息**。

═══════════════════════════════════════════
⚙️ 工具参数提取规范
═══════════════════════════════════════════
在调用 `generate_travel_plan` 时：
1. **绝对禁止扩大地理范围**：用户说"开封"就是"开封"，不能传"河南"。
2. **保持原词**。

═══════════════════════════════════════════
🎯 确认信号识别（仅在询问确认时有效）
═══════════════════════════════════════════
**只有当你上一句话是「👀 以上信息确认无误吗？」时**，以下回复才算确认信号：

✅ 确认信号词：
「开始」「确认」「可以」「没问题」「对的」「是的」「好的」「OK」「Go」
「出发」「确认无误」「正确」「对」「嗯」「行」「就这样」「可以了」
「生成」「生成行程」「帮我生成」「确定」「走起」「冲」「安排」

🚨 **特别注意**：如果用户说 "你好" 或 "Hi"，这是打招呼，不是确认！

收到真正的确认后，直接回复："🎉 收到！正在为您生成专属行程，请稍候..."，然后调用工具。

═══════════════════════════════════════════
📋 工作流程
═══════════════════════════════════════════

**阶段1：信息收集**
- 👋 热情问候，配合 Emoji，了解目的地。
- 🕵️ 收集要素：出发地、天数、人数、预算、偏好。

**阶段2：信息确认**
- 输出 **Markdown 表格** 形式的确认摘要。
- 询问用户："👀 以上信息确认无误吗？"

**阶段3：调用工具**
- 用户确认后，立即调用工具。

当前时间：{current_time}
"""


CONFIRM_DETECTED_PROMPT = """
【系统提示】检测到用户的确认信号"{user_input}"。
用户已经确认了之前的行程信息，请立即调用 generate_travel_plan 工具生成行程。
不要再询问任何问题，直接调用工具！
"""


class TravelChatAgent:
    """旅行规划对话 Agent - 使用 LLMFactory"""
    
    def __init__(
        self, 
        travel_graph: Any = None, 
        model_type: str = "smart"  # ✅ 使用 model_type 参数
    ):
        """
        初始化 Agent
        
        Args:
            travel_graph: 旅行规划图（用于工具）
            model_type: LLM 类型 - "light" | "smart" | "default"
        """
        self.model_type = model_type
        self.travel_graph = travel_graph
        
        # ✅ 使用 LLMFactory 获取 LLM
        self._llm = None
        self._agent = None
        self._tools = None
        
        print(f"🤖 TravelChatAgent 初始化，模型类型: {model_type}")
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            print(f"🔄 正在获取 LLM ({self.model_type})...")
            try:
                self._llm = LLMFactory.get(self.model_type)
                print(f"✅ LLM 获取成功: {self._llm}")
            except Exception as e:
                print(f"❌ LLM 获取失败: {e}")
                raise
        return self._llm
    
    @property
    def tools(self):
        """懒加载工具"""
        if self._tools is None:
            self._tools = get_all_tools(self.travel_graph)
            print(f"🔧 加载了 {len(self._tools)} 个工具")
        return self._tools
    
    @property
    def agent(self):
        """懒加载 Agent"""
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent
    
    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return SYSTEM_PROMPT.format(current_time=current_time)
    
    def _create_agent(self):
        """创建 ReAct Agent"""
        print("🔄 正在创建 Agent...")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        try:
            agent = create_react_agent(
                model=self.llm,  # ✅ 使用 LLMFactory 的 LLM
                tools=self.tools,
                prompt=prompt,
            )
            print("✅ Agent 创建成功")
            return agent
        except Exception as e:
            print(f"❌ Agent 创建失败: {e}")
            raise
    
    # ==================== 消息构建 ====================
    
    def _build_messages_from_history(
        self, 
        chat_history: List[Dict],
        inject_confirm_hint: bool = False,
        user_input: str = ""
    ) -> List[BaseMessage]:
        """从聊天历史构建消息列表"""
        messages = []
        
        if not chat_history:
            return messages
        
        for msg in chat_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if not content or not content.strip():
                continue
            
            if role in ("tool", "system"):
                continue
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        
        if inject_confirm_hint and user_input:
            hint = CONFIRM_DETECTED_PROMPT.format(user_input=user_input)
            messages.append(SystemMessage(content=hint))
        
        return messages
    
    def _validate_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """验证消息列表"""
        validated = []
        
        for msg in messages:
            content = getattr(msg, 'content', None)
            
            if content is None:
                continue
            
            if isinstance(content, str) and not content.strip():
                continue
            
            if isinstance(content, list):
                content = str(content)
                msg = type(msg)(content=content)
            
            validated.append(msg)
        
        return validated

    # ==================== 测试连接 ====================
    
    def test_connection(self) -> bool:
        """测试 LLM 连接"""
        print("\n" + "="*50)
        print("🔍 测试 LLM 连接...")
        print("="*50)
        
        try:
            # 获取 LLM
            llm = self.llm
            print(f"✅ LLM 实例: {llm}")
            
            # 简单测试
            test_message = [HumanMessage(content="你好，请回复'连接成功'")]
            response = llm.invoke(test_message)
            
            print(f"✅ LLM 响应: {response.content[:100]}...")
            print("="*50 + "\n")
            return True
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            import traceback
            traceback.print_exc()
            print("="*50 + "\n")
            return False

    # ==================== 核心对话方法 ====================

    async def achat(
        self, 
        message: str, 
        session_id: str = "default",
        chat_history: list = None,
        stream: bool = False
    ):
        """异步发送消息并获取回复"""
        
        # 检测确认信号
        is_confirm_context = detect_confirmation_context(chat_history or [], message)
        is_confirm_signal = is_confirmation(message)
        inject_hint = is_confirm_context or (is_confirm_signal and len(message.strip()) <= 15)
        
        if inject_hint:
            print(f"🎯 检测到确认信号: '{message}'")
        
        # 构建消息
        messages_payload = self._build_messages_from_history(
            chat_history,
            inject_confirm_hint=inject_hint,
            user_input=message
        )
        messages_payload.append(HumanMessage(content=message))
        messages_payload = self._validate_messages(messages_payload)
        
        # 调试
        if os.getenv("DEBUG_MESSAGES"):
            print(f"\n📨 消息数量: {len(messages_payload)}")
            for i, msg in enumerate(messages_payload):
                print(f"  [{i}] {type(msg).__name__}: {str(msg.content)[:60]}...")
        
        input_message = {"messages": messages_payload}
        config = {"configurable": {"thread_id": session_id}}
        
        if stream:
            async for chunk in self._astream_chat(input_message, config):
                yield chunk
        else:
            result = await self._async_chat(input_message, config)
            yield result

    async def _async_chat(self, input_message: Dict, config: Dict) -> str:
        """异步对话（非流式）"""
        try:
            result = await self.agent.ainvoke(input_message, config)
            messages = result.get("messages", [])
            
            ROUTE_TOOLS = {"generate_travel_plan"}
            route_tool_called = False
            plan_id = ""
            session_id = ""

            for msg in messages:
                if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tool_name = tool_call.get('name', '') if isinstance(tool_call, dict) else getattr(tool_call, 'name', '')
                        if tool_name in ROUTE_TOOLS:
                            route_tool_called = True
                            break
                
                if isinstance(msg, ToolMessage):
                    tool_name = getattr(msg, 'name', '')
                    if tool_name in ROUTE_TOOLS:
                        route_tool_called = True
                        try:
                            tool_result = json.loads(msg.content)
                            plan_id = tool_result.get("plan_id", "")
                            session_id = tool_result.get("session_id", "")
                        except:
                            pass
            
            final_response = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    if content and content.strip():
                        if not (hasattr(msg, 'tool_calls') and msg.tool_calls):
                            final_response = content
                            break
            
            if not final_response:
                return "抱歉，我没有理解您的意思，请再说一遍？"
            
            if route_tool_called:
                return f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>" + final_response
            
            return final_response
            
        except Exception as e:
            print(f"❌ Async chat error: {e}")
            import traceback
            traceback.print_exc()
            return f"抱歉，发生了一些错误：{str(e)}"

    async def _astream_chat(self, input_message: Dict, config: Dict):
        """异步流式对话"""
        try: 
            route_tool_called = False
            marker_sent = False
            plan_id = ""
            session_id = ""

            ROUTE_TOOLS = {"generate_travel_plan"}

            async for chunk in self.agent.astream(input_message, config, stream_mode="messages"):
                if isinstance(chunk, tuple):
                    message, metadata = chunk
                    
                    if isinstance(message, AIMessage):
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            for tool_call in message.tool_calls:
                                if isinstance(tool_call, dict):
                                    tool_name = tool_call.get('name', '')
                                else:
                                    tool_name = getattr(tool_call, 'name', '')
                                
                                if tool_name in ROUTE_TOOLS:
                                    route_tool_called = True
                            continue

                        content = message.content
                        if content and content.strip():
                            if route_tool_called and not marker_sent:
                                yield f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>"
                                marker_sent = True
                            yield content

                    elif isinstance(message, ToolMessage):
                        tool_name = getattr(message, 'name', '')
                        if tool_name in ROUTE_TOOLS:
                            route_tool_called = True
                            try:
                                tool_result = json.loads(message.content)
                                plan_id = tool_result.get("plan_id", "")
                                session_id = tool_result.get("session_id", "")
                            except:
                                pass
                                
                elif hasattr(chunk, 'content'):
                    content = chunk.content
                    if content and content.strip():
                        if route_tool_called and not marker_sent:
                            yield f"<<<ACTION:MAP|session_id={session_id}|plan_id={plan_id}>>>"
                            marker_sent = True
                        yield content
                    
        except Exception as e:
            print(f"❌ Stream error: {e}")
            import traceback
            traceback.print_exc()
            yield f"抱歉，发生了一些错误：{str(e)}"
    
    # ==================== 同步方法 ====================
    
    def chat(
        self, 
        message: str, 
        session_id: str = "default",
        chat_history: list = None,
        stream: bool = False
    ) -> str | Any:
        """同步发送消息"""
        
        is_confirm_context = detect_confirmation_context(chat_history or [], message)
        is_confirm_signal = is_confirmation(message)
        inject_hint = is_confirm_context or (is_confirm_signal and len(message.strip()) <= 15)
        
        messages_payload = self._build_messages_from_history(
            chat_history,
            inject_confirm_hint=inject_hint,
            user_input=message
        )
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
            print(f"❌ Chat error: {e}")
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
            print(f"❌ Stream error: {e}")
            yield f"抱歉，发生了一些错误：{str(e)}"