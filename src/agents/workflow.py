# src/agents/workflow.py
from typing import Literal
from langgraph.graph import StateGraph, END
from src.agents.state import AgentState
from src.agents.nodes import (
    search_node,
    summary_node,
    planning_node,
    map_node,
    weather_node,
    refine_node
)


def check_summary_quality(state: AgentState) -> Literal["continue_search", "proceed"]:
    """
    检查总结质量，决定是否继续搜索
    
    返回:
        - "continue_search": 信息不足，继续搜索
        - "proceed": 信息充足，进入下一阶段
    """
    planning_rules = state.get("planning_rules")
    search_count = state.get("_search_count", 1)
    max_searches = state.get("_max_searches", 2)
    
    print(f"--- CHECK SUMMARY QUALITY (搜索次数: {search_count}/{max_searches}) ---")
    
    # 条件1: 达到最大搜索次数
    if search_count >= max_searches:
        print("✅ 达到最大搜索次数，进入规划阶段")
        return "proceed"
    
    # 条件2: 没有规划规则
    if not planning_rules:
        print("⚠️ 未生成规划规则，继续搜索")
        return "continue_search"
    
    # 条件3: 检查规则质量（✅ 修复：检查多个字段）
    # 路线：优先检查 daily_routes，其次 common_routes
    has_routes = bool(
        (planning_rules.daily_routes and len(planning_rules.daily_routes) > 0) or
        (planning_rules.common_routes and len(planning_rules.common_routes) > 0)
    )
    
    # 必去景点
    has_must_visit = bool(planning_rules.must_visit and len(planning_rules.must_visit) > 0)
    
    # 交通建议
    has_tips = bool(planning_rules.transport_tips and len(planning_rules.transport_tips) > 0)
    
    # ✅ 新增：避坑建议（可选加分项）
    has_avoid = bool(
        (planning_rules.avoid_list and len(planning_rules.avoid_list) > 0) or
        (planning_rules.avoid and len(planning_rules.avoid) > 0)
    )
    
    # ✅ 新增：美食住宿
    has_food = bool(
        planning_rules.food_accommodation and 
        (planning_rules.food_accommodation.recommendations or 
         planning_rules.food_accommodation.food_areas)
    )
    
    quality_score = sum([has_routes, has_must_visit, has_tips, has_avoid, has_food])
    
    print(f"   规则质量检查:")
    print(f"     - 路线规划: {'✅' if has_routes else '❌'} (daily_routes: {len(planning_rules.daily_routes)}, common_routes: {len(planning_rules.common_routes)})")
    print(f"     - 必去景点: {'✅' if has_must_visit else '❌'} ({len(planning_rules.must_visit)} 个)")
    print(f"     - 交通建议: {'✅' if has_tips else '❌'} ({len(planning_rules.transport_tips)} 条)")
    print(f"     - 避坑指南: {'✅' if has_avoid else '❌'}")
    print(f"     - 美食住宿: {'✅' if has_food else '❌'}")
    print(f"   质量分数: {quality_score}/5")
    
    # ✅ 调整阈值：5项中有3项即可
    if quality_score >= 3:
        print("✅ 信息充足，进入规划阶段")
        return "proceed"
    else:
        print("⚠️ 信息不足，继续搜索")
        return "continue_search"

def search_node_with_counter(state: AgentState) -> AgentState:
    """带计数器的搜索节点"""
    # 增加搜索计数
    count = state.get("_search_count", 0)
    state["_search_count"] = count + 1
    
    print(f"--- SEARCH AGENT (第 {state['_search_count']} 次搜索) ---")
    
    # 调用原始搜索逻辑
    return search_node(state)


def should_query_weather(state: AgentState) -> Literal["weather", "planning"]:
    """判断是否需要查询天气"""
    if state.get("weather_info"):
        print("⏭️ 天气信息已存在，跳过查询")
        return "planning"
    return "weather"


def should_validate_map(state: AgentState) -> Literal["map", "refine"]:
    """判断是否需要地图验证"""
    if state.get("skip_map_validation"):
        print("⏭️ 跳过地图验证")
        return "refine"
    if state.get("validated_plan"):
        print("⏭️ 路线已验证，跳过")
        return "refine"
    return "map"


def create_travel_agent_graph():
    """
    创建旅行规划工作流图（带搜索循环）
    
    流程:
    search → summary → check_quality
       ↑                    ↓
       ←←←←←←← (需要更多信息)
                            ↓ (信息充足)
                       weather? → planning → map? → refine → END
    """
    
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("search", search_node_with_counter)
    workflow.add_node("summary", summary_node)
    workflow.add_node("check_quality", lambda state: state)  # 纯检查节点，不修改状态
    workflow.add_node("weather", weather_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("map", map_node)
    workflow.add_node("refine", refine_node)
    
    # 设置入口
    workflow.set_entry_point("search")
    
    # search → summary
    workflow.add_edge("search", "summary")
    
    # summary → check_quality
    workflow.add_edge("summary", "check_quality")
    
    # ✅ 循环检查: check_quality → search 或 weather
    workflow.add_conditional_edges(
        "check_quality",
        check_summary_quality,
        {
            "continue_search": "search",   # 继续搜索
            "proceed": "weather"           # 进入下一阶段
        }
    )
    
    # weather（可选）→ planning
    workflow.add_conditional_edges(
        "weather",
        lambda state: "planning",  # 天气后总是进入规划
        {"planning": "planning"}
    )
    
    # 也可以跳过天气直接规划（如果需要的话可以加条件）
    
    # planning → map（可选）
    workflow.add_conditional_edges(
        "planning",
        should_validate_map,
        {
            "map": "map",
            "refine": "refine"
        }
    )
    
    # map → refine
    workflow.add_edge("map", "refine")
    
    # refine → END
    workflow.add_edge("refine", END)
    
    return workflow.compile()


def create_simple_travel_graph():
    """简化版（无循环，固定执行一次搜索）"""
    
    workflow = StateGraph(AgentState)
    
    workflow.add_node("search", search_node)
    workflow.add_node("summary", summary_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("map", map_node)
    workflow.add_node("refine", refine_node)
    
    workflow.set_entry_point("search")
    
    workflow.add_edge("search", "summary")
    workflow.add_edge("summary", "planning")
    workflow.add_edge("planning", "map")
    workflow.add_edge("map", "refine")
    workflow.add_edge("refine", END)
    
    return workflow.compile()


def create_quick_planning_graph():
    """快速规划（跳过搜索，直接用已有规则）"""
    
    workflow = StateGraph(AgentState)
    
    workflow.add_node("planning", planning_node)
    workflow.add_node("refine", refine_node)
    
    workflow.set_entry_point("planning")
    
    workflow.add_edge("planning", "refine")
    workflow.add_edge("refine", END)
    
    return workflow.compile()