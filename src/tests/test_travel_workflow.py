# tests/test_travel_workflow.py

import os
import sys
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.travel_workflow import create_travel_graph
from src.agents.state import AgentState
from src.models.schemas import UserProfile
from src.utils.token_budget import TokenBudget


def test_basic_workflow():
    """基础测试 - 简单的旅行规划"""
    
    print("\n" + "="*60)
    print("🧪 测试: 基础工作流")
    print("="*60)
    
    # 创建用户画像
    user_profile = UserProfile(
        destination="南京",
        days=3,
        origin="上海",
        preferences=["美食", "历史"],
        group_type="couple",
        budget="中等"
    )
    
    # 初始化状态
    initial_state = AgentState(
        user_profile=user_profile,
        session_id=f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        _token_budget=TokenBudget(total_budget=15000),
        _search_count=0,
        _searched_queries=[],
        _missing_info=[],
    )
    
    # 创建并运行工作流
    graph = create_travel_graph()
    
    print(f"\n📋 用户需求:")
    print(f"   目的地: {user_profile.destination}")
    print(f"   天数: {user_profile.days}")
    print(f"   偏好: {user_profile.preferences}")
    print(f"   人群: {user_profile.group_type}")
    
    print("\n🚀 开始执行工作流...\n")
    
    # 执行
    try:
        final_state = graph.invoke(initial_state)
        
        # 输出结果
        print("\n" + "="*60)
        print("✅ 工作流执行完成")
        print("="*60)
        
        result = final_state.get("final_result")
        if result:
            print(f"\n📍 目的地: {result.destination}")
            print(f"📝 概述: {result.overview}")
            print(f"⭐ 亮点: {result.highlights}")
            print(f"📅 天数: {len(result.days)}")
            
            for day in result.days:
                print(f"\n--- Day {day.get('day', '?')}: {day.get('theme', '')} ---")
                for item in day.get("schedule", [])[:3]:
                    print(f"   {item.get('time', '')} {item.get('poi', '')} - {item.get('activity', '')}")
                if len(day.get("schedule", [])) > 3:
                    print(f"   ... 共 {len(day.get('schedule', []))} 个活动")
        
        # 统计信息
        print(f"\n📊 执行统计:")
        print(f"   搜索轮数: {final_state.get('_search_count', 0)}")
        print(f"   搜索关键词: {final_state.get('_searched_queries', [])}")
        
        budget = final_state.get("_token_budget")
        if budget:
            print(f"   Token 消耗: {budget.get_total_consumed()}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_different_destinations():
    """测试不同目的地"""
    
    destinations = [
        {"dest": "北京", "days": 4, "prefs": ["历史", "文化"]},
        {"dest": "成都", "days": 3, "prefs": ["美食", "休闲"]},
        {"dest": "杭州", "days": 2, "prefs": ["拍照", "自然"]},
    ]
    
    for config in destinations:
        print("\n" + "="*60)
        print(f"🧪 测试: {config['dest']} {config['days']}天游")
        print("="*60)
        
        user_profile = UserProfile(
            destination=config["dest"],
            days=config["days"],
            preferences=config["prefs"],
        )
        
        initial_state = AgentState(
            user_profile=user_profile,
            session_id=f"test_{config['dest']}_{datetime.now().strftime('%H%M%S')}",
            _token_budget=TokenBudget(total_budget=15000),
        )
        
        graph = create_travel_graph()
        
        try:
            final_state = graph.invoke(initial_state)
            result = final_state.get("final_result")
            
            if result and result.days:
                print(f"✅ {config['dest']}: 生成 {len(result.days)} 天行程")
            else:
                print(f"⚠️ {config['dest']}: 未生成有效行程")
                
        except Exception as e:
            print(f"❌ {config['dest']}: 失败 - {e}")


def test_with_mock_search():
    """使用 Mock 数据测试（不依赖真实搜索）"""
    
    print("\n" + "="*60)
    print("🧪 测试: Mock 数据")
    print("="*60)
    
    from src.models.schemas import SearchResult, SearchNote
    
    # 创建 Mock 笔记
    mock_notes = [
        SearchNote(
            title="南京3天攻略保姆级",
            content="""
            DAY1: 南京大屠杀遇难同胞纪念馆 → 夫子庙 → 秦淮河
            DAY2: 南京博物院 → 总统府 → 鸡鸣寺 → 玄武湖
            DAY3: 中山陵 → 明孝陵 → 音乐台
            
            住宿推荐新街口附近，地铁方便。
            
            必吃：鸭血粉丝汤、盐水鸭、汤包
            推荐：尹氏汤包、小李汤包
            美食街：夫子庙、明瓦廊
            
            总统府 8:30-18:00 周一闭馆 门票32元
            南京博物院 免费 需预约 周一闭馆
            中山陵 免费 需预约 周一闭馆
            """,
            likes=5000
        ),
        SearchNote(
            title="南京本地人美食推荐",
            content="""
            早餐：尹氏汤包、秦虹汤包鸭血粉丝
            午餐：巴子皮肚面、方记面馆
            小吃街：明瓦廊、红庙、丰富路
            夜市：下马坊夜市
            
            鸭血粉丝汤是南京必吃！
            盐水鸭皮白肉嫩，强烈推荐
            """,
            likes=3000
        ),
    ]
    
    # 创建状态（直接注入搜索结果）
    user_profile = UserProfile(
        destination="南京",
        days=3,
        preferences=["美食"],
    )
    
    initial_state = AgentState(
        user_profile=user_profile,
        session_id="test_mock",
        search_results=SearchResult(notes=mock_notes),  # 直接注入
        _token_budget=TokenBudget(total_budget=15000),
        _search_count=1,  # 跳过搜索
    )
    
    # 只测试 extract → plan
    from src.agents.travel_workflow import extract_node, plan_node, check_info_quality
    
    print("\n📋 执行 Extract...")
    state = extract_node(initial_state)
    
    print("\n📋 检查信息质量...")
    result = check_info_quality(state)
    print(f"   结果: {result}")
    
    print("\n📋 执行 Plan...")
    state = plan_node(state)
    
    final_result = state.get("final_result")
    if final_result:
        print(f"\n✅ 生成行程:")
        print(f"   概述: {final_result.overview}")
        print(f"   天数: {len(final_result.days)}")
        print(json.dumps(final_result.model_dump(), ensure_ascii=False, indent=2)[:1000])


def test_single_node():
    """单独测试某个节点"""
    
    print("\n" + "="*60)
    print("🧪 测试: 单节点 (Search)")
    print("="*60)
    
    from src.agents.travel_workflow import search_node
    
    user_profile = UserProfile(
        destination="南京",
        days=3,
        preferences=["美食"],
    )
    
    state = AgentState(
        user_profile=user_profile,
        _token_budget=TokenBudget(),
        _search_count=0,
        _searched_queries=[],
    )
    
    # 只测试搜索
    result_state = search_node(state)
    
    search_results = result_state.get("search_results")
    if search_results and search_results.notes:
        print(f"\n✅ 搜索成功: {len(search_results.notes)} 条笔记")
        for note in search_results.notes[:3]:
            print(f"   - {note.title[:40]}...")
    else:
        print("\n⚠️ 无搜索结果")


# ==================== 运行测试 ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="测试旅行规划工作流")
    parser.add_argument("--test", type=str, default="basic",
                       choices=["basic", "multi", "mock", "search", "all"],
                       help="选择测试类型")
    
    args = parser.parse_args()
    
    if args.test == "basic":
        test_basic_workflow()
        
    # elif args.test == "multi":
    #     test_different_destinations()
        
    # elif args.test == "mock":
    #     test_with_mock_search()
        
    # elif args.test == "search":
    #     test_single_node()
        
    # elif args.test == "all":
    #     print("\n🚀 运行所有测试...\n")
    #     test_basic_workflow()
    #     test_with_mock_search()
    #     test_single_node()
    #     print("\n✅ 所有测试完成")