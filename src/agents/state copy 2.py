# src/agents/state.py
from typing import TypedDict, Optional, List, Dict, Any
from src.models.schemas import UserProfile, SearchResult, PlanningRules, TravelPlanResult


class AgentState(TypedDict, total=False):
    """
    Agent 状态定义
    
    状态流转:
    ┌─────────────────────────────────────────────────────────────┐
    │  user_profile ──▶ search_results ──▶ planning_rules        │
    │                                            │                │
    │                      ┌─────────────────────┘                │
    │                      ▼                                      │
    │               draft_plan ──▶ validated_plan ──▶ final_result│
    └─────────────────────────────────────────────────────────────┘
    """
    
    # ============ 会话标识 ============
    session_id: str                     # 会话ID，用于缓存和状态追踪
    
    # ============ 用户输入 ============
    user_profile: UserProfile           # 用户画像（目的地、天数、偏好等）
    
    # ============ 工作流中间状态 ============
    search_results: Optional[SearchResult]      # 搜索结果
    planning_rules: Optional[PlanningRules]     # 规划规则（从搜索结果提取）
    draft_plan: Optional[Dict]                  # 行程草案
    validated_plan: Optional[Dict]              # 验证后的行程（含路线信息）
    weather_info: Optional[Dict]                # 天气信息
    
    # ============ 最终输出 ============
    final_result: Optional[TravelPlanResult]    # 最终旅行计划
    
    # ============ 流程控制 ============
    skip_map_validation: bool           # 是否跳过地图验证
    skip_weather: bool                  # 是否跳过天气查询
    
    # ============ 搜索控制 ============
    _search_count: int                  # 当前搜索次数
    _max_searches: int                  # 最大搜索次数限制
    _search_queries: List[str]          # 已搜索的关键词（避免重复）
    
    # ============ Token 优化 ============
    _token_budget: Any                  # TokenBudget 实例
    _summarizer: Any                    # IncrementalSummarizer 实例（增量摘要）
    _note_scores: List[Dict]            # 笔记评分结果（用于调试）
    
    # ============ 调试/元信息 ============
    _error: Optional[str]               # 错误信息
    _warnings: List[str]                # 警告信息
    _debug_info: Dict[str, Any]         # 调试信息


# ============ 状态初始化辅助函数 ============

def create_initial_state(
    user_profile: UserProfile,
    session_id: str = "",
    max_searches: int = 2,
    skip_map: bool = True,
    skip_weather: bool = False,
    token_budget: Any = None,
) -> AgentState:
    """
    创建初始状态
    
    Args:
        user_profile: 用户画像
        session_id: 会话ID
        max_searches: 最大搜索次数
        skip_map: 是否跳过地图验证
        skip_weather: 是否跳过天气查询
        token_budget: Token 预算配置
        
    Returns:
        初始化的 AgentState
    """
    from src.utils.token_budget import TokenBudget
    
    return AgentState(
        # 会话
        session_id=session_id,
        
        # 用户输入
        user_profile=user_profile,
        
        # 中间状态（初始为空）
        search_results=None,
        planning_rules=None,
        draft_plan=None,
        validated_plan=None,
        weather_info=None,
        
        # 输出
        final_result=None,
        
        # 流程控制
        skip_map_validation=skip_map,
        skip_weather=skip_weather,
        
        # 搜索控制
        _search_count=0,
        _max_searches=max_searches,
        _search_queries=[],
        
        # Token 优化
        _token_budget=token_budget or TokenBudget(),
        _summarizer=None,
        _note_scores=[],
        
        # 调试
        _error=None,
        _warnings=[],
        _debug_info={},
    )


def get_state_summary(state: AgentState) -> Dict[str, Any]:
    """
    获取状态摘要（用于日志和调试）
    
    Args:
        state: 当前状态
        
    Returns:
        状态摘要字典
    """
    user = state.get("user_profile")
    budget = state.get("_token_budget")
    
    return {
        "session_id": state.get("session_id", "")[:8] + "...",
        "destination": user.destination if user else "未知",
        "days": user.days if user else 0,
        "search_count": state.get("_search_count", 0),
        "max_searches": state.get("_max_searches", 2),
        "has_search_results": state.get("search_results") is not None,
        "has_planning_rules": state.get("planning_rules") is not None,
        "has_draft_plan": state.get("draft_plan") is not None,
        "has_final_result": state.get("final_result") is not None,
        "token_consumed": budget.get_total_consumed() if budget and hasattr(budget, 'get_total_consumed') else 0,
        "errors": state.get("_error"),
        "warnings_count": len(state.get("_warnings", [])),
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
    print(f"   搜索: {summary['search_count']}/{summary['max_searches']}")
    print(f"   进度: {'搜索✓' if summary['has_search_results'] else '搜索○'} → "
          f"{'规则✓' if summary['has_planning_rules'] else '规则○'} → "
          f"{'草案✓' if summary['has_draft_plan'] else '草案○'} → "
          f"{'完成✓' if summary['has_final_result'] else '完成○'}")
    print(f"   Token: {summary['token_consumed']}")
    if summary['errors']:
        print(f"   ❌ 错误: {summary['errors']}")
    print(f"{'─' * 50}\n")