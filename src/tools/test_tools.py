#!/usr/bin/env python3
"""
工具测试脚本
运行方式: python test_tools.py
"""

import json
import asyncio
from typing import Any
from src.tools.tools import get_amap_mcp_client

# ============ 测试配置 ============
TEST_CITY = "杭州"
TEST_LOCATION = "120.153576,30.287459"  # 杭州西湖坐标
TEST_ADDRESS = "浙江省杭州市西湖区灵隐寺"


def print_result(tool_name: str, result: Any):
    """格式化打印结果"""
    print(f"\n{'='*60}")
    print(f"🔧 工具: {tool_name}")
    print(f"{'='*60}")
    
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result)


def test_weather_tool():
    """测试天气查询工具"""
    from src.tools.tools import WeatherTool
    
    tool = WeatherTool()
    print(f"\n📍 测试城市: {TEST_CITY}")
    
    result = tool._run(city=TEST_CITY)
    print_result("query_weather", result)
    
    return result


def test_nearby_search_tool():
    """测试周边搜索工具"""
    from src.tools.tools import NearbySearchTool
    
    tool = NearbySearchTool()
    print(f"\n📍 测试位置: {TEST_LOCATION}")
    print(f"🔍 搜索关键词: 餐厅")
    
    result = tool._run(
        location=TEST_LOCATION,
        keywords="餐厅",
        radius=1000
    )
    print_result("search_nearby", result)
    
    return result


def test_poi_search_tool():
    """测试POI搜索工具"""
    from src.tools.tools import KeywordSearchTool
    
    tool = KeywordSearchTool()
    print(f"\n📍 测试城市: {TEST_CITY}")
    print(f"🔍 搜索关键词: 西湖景区")
    
    result = tool._run(
        keywords="西湖景区",
        city=TEST_CITY
    )
    print_result("search_poi", result)
    
    return result


def test_route_plan_tool():
    """测试路线规划工具"""
    from src.tools.tools import RoutePlanTool
    
    tool = RoutePlanTool()
    origin = "杭州东站"
    destination = "西湖风景区"
    
    print(f"\n📍 起点: {origin}")
    print(f"📍 终点: {destination}")
    
    # 测试驾车路线
    print("\n🚗 驾车路线:")
    result_driving = tool._run(origin=origin, destination=destination, mode="driving")
    print_result("plan_route (driving)", result_driving)
    
    # 测试公交路线
    # print("\n🚌 公交路线:")
    # result_transit = tool._run(origin=origin, destination=destination, mode="transit")
    # print_result("plan_route (transit)", result_transit)
    
    return result_driving


def test_geocode_tool():
    """测试地理编码工具"""
    from src.tools.tools import GeoCodeTool
    
    tool = GeoCodeTool()
    print(f"\n📍 测试地址: {TEST_ADDRESS}")
    
    result = tool._run(address=TEST_ADDRESS, city=TEST_CITY)
    print_result("geo_code", result)
    
    return result


def test_xiaohongshu_search():
    """测试小红书搜索工具"""
    from src.tools.search import get_search_tool
    
    tool = get_search_tool()
    query = "杭州旅游攻略"
    
    print(f"\n🔍 搜索关键词: {query}")
    
    result = tool._run(query=query)
    print_result("search_xiaohongshu", result)
    
    return result


def test_travel_plan_tool():
    """测试旅行计划生成工具"""
    from src.tools.tools import TravelPlanTool
    from src.agents.workflow import create_travel_agent_graph
    
    # 创建旅行规划图
    travel_graph = create_travel_agent_graph()
    tool = TravelPlanTool(travel_graph=travel_graph)
    
    print(f"\n📍 目的地: {TEST_CITY}")
    print(f"📅 天数: 3天")
    
    result = tool._run(
        destination=TEST_CITY,
        days=3,
        origin="上海",
        group_type="情侣",
        preferences=["美食", "自然风光", "网红打卡"],
        budget="中等"
    )
    print_result("generate_travel_plan", result)
    
    return result


def test_all_tools():
    """测试所有工具"""
    from src.tools.tools import get_all_tools
    from src.agents.workflow import create_travel_agent_graph
    
    print("\n" + "="*60)
    print("📋 可用工具列表")
    print("="*60)
    
    travel_graph = create_travel_agent_graph()
    tools = get_all_tools(travel_graph)
    
    for i, tool in enumerate(tools, 1):
        print(f"{i}. {tool.name}: {tool.description[:60]}...")
    
    return tools


# ============ 单个工具快速测试 ============

def quick_test_weather(city: str = "杭州"):
    """快速测试天气"""
    from src.tools.tools import WeatherTool
    tool = WeatherTool()
    return tool._run(city=city)


def quick_test_poi(keywords: str = "美食", city: str = "杭州"):
    """快速测试POI搜索"""
    from src.tools.tools import KeywordSearchTool
    tool = KeywordSearchTool()
    return tool._run(keywords=keywords, city=city)


def quick_test_xiaohongshu(query: str = "杭州三天游攻略"):
    """快速测试小红书搜索"""
    from src.tools.search import get_search_tool
    tool = get_search_tool()
    return tool._run(query=query)

def test_geocode():
    client = get_amap_mcp_client()
    
    # 测试地理编码
    test_addresses = ["杭州东站", "西湖风景区", "杭州市西湖区"]
    
    for addr in test_addresses:
        print(f"\n{'='*50}")
        print(f"测试地址: {addr}")
        print(f"{'='*50}")
        
        try:
            # 测试1: 只传 address
            result1 = client.call_tool("maps_geo", {"address": addr})
            print(f"参数 {{address}}: {type(result1)}")
            print(f"返回值: {result1}")
        except Exception as e:
            print(f"错误1: {e}")
        
        # try:
        #     # 测试2: 传 address + city
        #     result2 = client.call_tool("maps_geo", {"address": addr, "city": "杭州"})
        #     print(f"\n参数 {{address, city}}: {type(result2)}")
        #     print(f"返回值: {result2}")
        # except Exception as e:
        #     print(f"错误2: {e}")

# ============ 主函数 ============

def main():
    """运行所有测试"""
    print("\n" + "🚀"*30)
    print("          开始工具测试")
    print("🚀"*30)
    
    tests = [
        # ("工具列表", test_all_tools),
        # ("天气查询", test_weather_tool),
        # ("地理编码", test_geocode_tool),
        # ("POI搜索", test_poi_search_tool),
        # ("周边搜索", test_nearby_search_tool),

        ("路线规划", test_route_plan_tool),
        # ("小红书搜索", test_xiaohongshu_search),
        # ("旅行计划", test_travel_plan_tool),  # 这个比较慢，可选
    ]
   
    results = {}
    
    for name, test_func in tests:
        try:
            print(f"\n\n{'#'*60}")
            print(f"# 测试: {name}")
            print(f"{'#'*60}")
            result = test_func()
            results[name] = {"status": "✅ 成功", "result": result}
        except Exception as e:
            import traceback
            print(f"\n❌ 测试失败: {name}")
            print(f"错误: {e}")
            traceback.print_exc()
            results[name] = {"status": "❌ 失败", "error": str(e)}
    
    # 打印测试摘要
    print("\n\n" + "="*60)
    print("📊 测试摘要")
    print("="*60)
    
    for name, result in results.items():
        print(f"  {result['status']} {name}")
    
    success_count = sum(1 for r in results.values() if "成功" in r["status"])
    print(f"\n总计: {success_count}/{len(results)} 通过")
#    test_geocode()

if __name__ == "__main__":
    main()