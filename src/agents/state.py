# src/agents/state.py
from typing import TypedDict, Optional, List
from src.models.schemas import UserProfile, SearchResult, PlanningRules, TravelPlanResult


class AgentState(TypedDict, total=False):
    """Agent 状态定义"""
    
    # ✅ 确保包含 session_id
    session_id: str

    # 输入
    user_profile: UserProfile
    
    # 中间状态
    search_results: Optional[SearchResult]
    planning_rules: Optional[PlanningRules]
    draft_plan: Optional[dict]
    validated_plan: Optional[dict]
    weather_info: Optional[dict]
    
    # 输出
    final_result: Optional[TravelPlanResult]
    
    # ✅ 控制标志
    skip_map_validation: bool           # 是否跳过地图验证
    _search_count: int                  # 搜索计数器
    _max_searches: int                  # 最大搜索次数
    _search_queries: List[str]          # 已搜索的关键词（避免重复）