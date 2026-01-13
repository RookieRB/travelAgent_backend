# test_nodes.py
"""测试各个节点"""

import json
from src.models.schemas import UserProfile
from src.agents.nodes import (
    search_node,
    weather_node,
    summary_node,
    planning_node,
    map_node,
    refine_node
)


def test_search_node():
    """测试搜索节点"""
    print("\n" + "="*50)
    print("测试 search_node")
    print("="*50)
    
    state = {
        "user_profile": UserProfile(
            origin="上海",
            destination="杭州",
            days=3,
            group_type="情侣",
            preferences=["美食", "自然风光"],
            budget="中等"
        ),
        "search_results": None,
        "planning_rules": None,
        "draft_plan": None,
        "validated_plan": None,
        "final_result": None,
        "messages": []
    }
    
    result = search_node(state)
    print(f"\n搜索结果数量: {len(result['search_results'].notes)}")
    for note in result['search_results'].notes:
        print(f"  - {note.title}: {len(note.content)} 字符")
    
    return result


def test_weather_node():
    """测试天气节点"""
    print("\n" + "="*50)
    print("测试 weather_node")
    print("="*50)
    
    state = {
        "user_profile": UserProfile(
            origin="上海",
            destination="杭州",
            days=3,
            group_type="情侣",
            preferences=["美食"],
            budget="中等"
        ),
        "planning_rules": None,
    }
    
    result = weather_node(state)
    
    if result.get("weather_info"):
        print(f"\n天气信息: {json.dumps(result['weather_info'], ensure_ascii=False, indent=2)}")
    else:
        print("未获取到天气信息")
    
    return result


def test_full_workflow():
    """测试完整工作流"""
    print("\n" + "="*50)
    print("测试完整工作流")
    print("="*50)
    
    from src.agents.workflow import create_travel_agent_graph
    
    graph = create_travel_agent_graph()
    
    initial_state = {
        "user_profile": UserProfile(
            origin="上海",
            destination="杭州",
            days=2,
            group_type="情侣",
            preferences=["美食", "网红打卡"],
            budget="中等"
        ),
        "search_results": None,
        "planning_rules": None,
        "draft_plan": None,
        "validated_plan": None,
        "final_result": None,
        "messages": []
    }
    
    final_state = graph.invoke(initial_state)
    
    if final_state.get("final_result"):
        print(f"\n最终结果:")
        print(json.dumps(
            final_state["final_result"].dict() if hasattr(final_state["final_result"], 'dict') else final_state["final_result"],
            ensure_ascii=False,
            indent=2
        ))
    
    return final_state


if __name__ == "__main__":
    # 单独测试
    # test_search_node()
    # test_weather_node()
    
    # 完整测试
    test_full_workflow()