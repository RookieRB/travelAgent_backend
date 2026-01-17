# src/agents/state.py

from typing import TypedDict, Optional, List, Dict, Any
from src.models.schemas import UserProfile, SearchResult, TravelPlanResult


class AgentState(TypedDict, total=False):
    """
    Agent 状态定义（优化版）
    
    工作流:
    ┌─────────────────────────────────────────────────────────────┐
    │                                                             │
    │  user_profile ──▶ search_results ──▶ extracted_info        │
    │                         ↑                   │               │
    │                         │              [check]              │
    │                         │                   │               │
    │                    need_more ◀──────────────┘               │
    │                                             │               │
    │                                         enough              │
    │                                             ▼               │
    │                                       final_result          │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
    """
    
    # ============ 会话标识 ============
    session_id: str
    current_plan_id: Optional[str]  # 🆕 保存生成的 plan_id
    # ============ 用户输入 ============
    user_profile: UserProfile
    
    # ============ 搜索阶段 ============
    search_results: Optional[SearchResult]      # 搜索到的笔记
    
    # ============ 提取阶段 ============
    extracted_info: Optional[Dict[str, Any]]    # 提取的结构化信息
    # 结构:
    # {
    #     "places": [...],           # 景点信息
    #     "transportation": {...},   # 交通信息
    #     "accommodation": {...},    # 住宿信息
    #     "food": {...},             # 美食信息
    #     "avoid": [...],            # 避坑事项
    #     "tips": [...]              # 实用贴士
    # }
    
    # ============ 最终输出 ============
    final_result: Optional[TravelPlanResult]
    
    # ============ 搜索控制 ============
    _search_count: int                  # 当前搜索轮数
    _max_searches: int                  # 最大搜索轮数
    _searched_queries: List[str]        # 已搜索的关键词
    _missing_info: List[str]            # 缺失的信息类型
    # 可能的值: ["places", "food", "transportation", "accommodation", "avoid"]
    
    # ============ Token 控制 ============
    _token_budget: Any                  # TokenBudget 实例
    
    # ============ 调试信息 ============
    _error: Optional[str]
    _warnings: List[str]


# ============ 辅助函数 ============

def create_initial_state(
    user_profile: UserProfile,
    session_id: str = "",
    max_searches: int = 3,
    token_budget: Any = None,
) -> AgentState:
    """
    创建初始状态
    
    Args:
        user_profile: 用户画像
        session_id: 会话ID（用于缓存）
        max_searches: 最大搜索轮数
        token_budget: Token 预算
        
    Returns:
        初始化的 AgentState
    """
    from src.utils.token_budget import TokenBudget
    from datetime import datetime
    
    if not session_id:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    return AgentState(
        # 会话
        session_id=session_id,
        
        # 输入
        user_profile=user_profile,
        
        # 搜索
        search_results=None,
        
        # 提取
        extracted_info=None,
        
        # 输出
        final_result=None,
        
        # 搜索控制
        _search_count=0,
        _max_searches=max_searches,
        _searched_queries=[],
        _missing_info=[],
        
        # Token
        _token_budget=token_budget or TokenBudget(),
        
        # 调试
        _error=None,
        _warnings=[],
    )


def get_state_summary(state: AgentState) -> Dict[str, Any]:
    """获取状态摘要"""
    user = state.get("user_profile")
    budget = state.get("_token_budget")
    extracted = state.get("extracted_info", {})
    
    # 统计提取信息
    places_count = len(extracted.get("places", []))
    food = extracted.get("food", {})
    food_count = (
        len(food.get("specialties", [])) + 
        len(food.get("restaurants", []))
    ) if isinstance(food, dict) else 0
    
    return {
        "session_id": state.get("session_id", "")[:12],
        "destination": user.destination if user else "未知",
        "days": user.days if user else 0,
        "preferences": user.preferences if user else [],
        
        # 搜索状态
        "search_count": state.get("_search_count", 0),
        "max_searches": state.get("_max_searches", 3),
        "notes_count": len(state.get("search_results").notes) if state.get("search_results") else 0,
        
        # 提取状态
        "places_count": places_count,
        "food_count": food_count,
        "has_transport": bool(extracted.get("transportation")),
        "has_accommodation": bool(extracted.get("accommodation")),
        "avoid_count": len(extracted.get("avoid", [])),
        
        # 缺失信息
        "missing_info": state.get("_missing_info", []),
        
        # 完成状态
        "is_complete": state.get("final_result") is not None,
        
        # Token
        "token_consumed": budget.get_total_consumed() if budget and hasattr(budget, 'get_total_consumed') else 0,
        
        # 错误
        "error": state.get("_error"),
        "warnings": state.get("_warnings", []),
    }


def print_state_status(state: AgentState, stage: str = ""):
    """打印状态概况"""
    summary = get_state_summary(state)
    
    print(f"\n{'─' * 50}")
    if stage:
        print(f"📍 阶段: {stage}")
    
    print(f"📊 状态概况:")
    print(f"   会话: {summary['session_id']}")
    print(f"   目的地: {summary['destination']} ({summary['days']}天)")
    print(f"   偏好: {summary['preferences']}")
    
    print(f"\n📚 搜索:")
    print(f"   轮数: {summary['search_count']}/{summary['max_searches']}")
    print(f"   笔记: {summary['notes_count']} 条")
    
    print(f"\n📋 提取信息:")
    print(f"   景点: {summary['places_count']} 个")
    print(f"   美食: {summary['food_count']} 个")
    print(f"   交通: {'✓' if summary['has_transport'] else '○'}")
    print(f"   住宿: {'✓' if summary['has_accommodation'] else '○'}")
    print(f"   避坑: {summary['avoid_count']} 条")
    
    if summary['missing_info']:
        print(f"\n⚠️ 缺失: {summary['missing_info']}")
    
    print(f"\n📈 Token: {summary['token_consumed']}")
    
    if summary['is_complete']:
        print(f"\n✅ 状态: 已完成")
    else:
        print(f"\n⏳ 状态: 进行中")
    
    if summary['error']:
        print(f"\n❌ 错误: {summary['error']}")
    
    if summary['warnings']:
        print(f"\n⚠️ 警告: {len(summary['warnings'])} 条")
    
    print(f"{'─' * 50}\n")


def get_progress(state: AgentState) -> Dict[str, Any]:
    """
    获取进度信息（用于前端展示）
    
    Returns:
        {
            "stage": "search|extract|plan|complete",
            "progress": 0-100,
            "message": "当前状态描述"
        }
    """
    if state.get("final_result"):
        return {
            "stage": "complete",
            "progress": 100,
            "message": "行程生成完成"
        }
    
    if state.get("extracted_info"):
        missing = state.get("_missing_info", [])
        if missing:
            return {
                "stage": "extract",
                "progress": 50,
                "message": f"信息不足，继续搜索: {missing}"
            }
        return {
            "stage": "plan",
            "progress": 70,
            "message": "正在生成行程..."
        }
    
    if state.get("search_results"):
        return {
            "stage": "extract",
            "progress": 40,
            "message": "正在提取信息..."
        }
    
    search_count = state.get("_search_count", 0)
    if search_count > 0:
        return {
            "stage": "search",
            "progress": 20 + search_count * 10,
            "message": f"第 {search_count} 轮搜索中..."
        }
    
    return {
        "stage": "search",
        "progress": 10,
        "message": "开始搜索..."
    }