# src/agents/optimized_workflow.py
from langgraph.graph import StateGraph, END
from src.agents.state import AgentState
from src.agents.optimized_nodes import (
    optimized_search_node,
    optimized_summary_node,
    optimized_planning_node,
    optimized_refine_node
)
from src.utils.token_budget import TokenBudget
from typing import Literal


def check_info_quality(state: AgentState) -> Literal["continue", "proceed"]:
    """快速检查信息质量（无需LLM）"""
    rules = state.get("planning_rules")
    search_count = state.get("_search_count", 1)
    max_searches = state.get("_max_searches", 2)
    
    # 达到最大搜索次数
    if search_count >= max_searches:
        return "proceed"
    
    # 检查规则质量
    if rules:
        has_routes = bool(rules.daily_routes) or bool(rules.common_routes)
        has_must_visit = bool(rules.must_visit)
        
        if has_routes and has_must_visit:
            return "proceed"
    
    return "continue"


def create_optimized_travel_graph():
    """创建优化后的工作流"""
    
    workflow = StateGraph(AgentState)
    
    # 注册节点
    workflow.add_node("search", optimized_search_node)
    workflow.add_node("summary", optimized_summary_node)
    workflow.add_node("planning", optimized_planning_node)
    workflow.add_node("refine", optimized_refine_node)
    
    # 设置入口
    workflow.set_entry_point("search")
    
    # 搜索 → 摘要
    workflow.add_edge("search", "summary")
    
    # 摘要 → 检查 → 继续搜索或规划
    workflow.add_conditional_edges(
        "summary",
        check_info_quality,
        {
            "continue": "search",
            "proceed": "planning"
        }
    )
    
    # 规划 → 润色 → 结束
    workflow.add_edge("planning", "refine")
    workflow.add_edge("refine", END)
    
    return workflow.compile()


def create_budget_aware_graph(budget: TokenBudget = None):
    """创建带预算感知的工作流"""
    
    if budget is None:
        budget = TokenBudget()
    
    def inject_budget(state: AgentState) -> AgentState:
        state["_token_budget"] = budget
        return state
    
    workflow = StateGraph(AgentState)
    
    # 预算注入节点
    workflow.add_node("init", inject_budget)
    workflow.add_node("search", optimized_search_node)
    workflow.add_node("summary", optimized_summary_node)
    workflow.add_node("planning", optimized_planning_node)
    workflow.add_node("refine", optimized_refine_node)
    
    workflow.set_entry_point("init")
    
    workflow.add_edge("init", "search")
    workflow.add_edge("search", "summary")
    workflow.add_conditional_edges(
        "summary",
        check_info_quality,
        {"continue": "search", "proceed": "planning"}
    )
    workflow.add_edge("planning", "refine")
    workflow.add_edge("refine", END)
    
    return workflow.compile()