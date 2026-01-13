import json
import os
import re
from dotenv import load_dotenv

# Load environment variables FIRST to ensure LLM_MODEL is available
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import AgentState
from src.prompts import (
    XIAOHONGSHU_SUMMARY_PROMPT,
    PLANNING_PROMPT_TEMPLATE,
    AMAP_MCP_CONSTRAINT_PROMPT,
    POLISHING_PROMPT
)
from typing import Optional, List, Dict, Any, Union
from src.models.schemas import SearchResult, SearchNote, PlanningRules, TravelPlanResult

# 导入工具 - 从统一的 tools 模块
from src.tools.tools import (
    XiaohongshuSearchTool,
    RoutePlanTool,
    WeatherTool,
    GeoCodeTool,
)

from src.utils.context import get_session_id
from src.services.redis_service import redis_service
from src.models.llm import Myllm
from datetime import datetime, timedelta
from src.models.schemas import UserProfile
# Initialize LLM
# api_key = os.getenv("OPENAI_API_KEY")
# if not api_key:
#     print("Warning: OPENAI_API_KEY not found in environment. Using dummy key.")
#     api_key = "sk-dummy-key"

# llm = ChatOpenAI(
#     model=os.getenv("LLM_MODEL", "qwen-plus"),
#     temperature=0.7,
#     api_key=api_key,
#     base_url=os.getenv("OPENAI_API_BASE"),
#     timeout=60.0,
#     max_retries=3
# )

llm = Myllm
# src/agents/nodes.py

def generate_search_queries(user_profile: UserProfile, search_count: int, searched_queries: List[str]) -> List[str]:
    """使用 LLM 智能生成搜索关键词"""
    
    # ✅ 根据你的 UserProfile 字段构建 prompt
    preferences_str = "、".join(user_profile.preferences) if user_profile.preferences else "无特殊偏好"
    
    # 人群类型映射
    group_type_map = {
        "solo": "独自旅行/特种兵",
        "couple": "情侣/二人世界",
        "family": "亲子/家庭游",
        "friends": "朋友/闺蜜游"
    }
    group_desc = group_type_map.get(user_profile.group_type, user_profile.group_type)
    
    prompt = f"""你是一位旅行规划助手，需要在小红书上搜索旅行攻略。

    【用户需求】
    - 出发地: {user_profile.origin}
    - 目的地: {user_profile.destination}
    - 出行天数: {user_profile.days}天
    - 出行时间: {user_profile.date_range or "未指定"}
    - 人群类型: {group_desc}
    - 旅行偏好: {preferences_str}
    - 预算: {user_profile.budget}

    【当前搜索轮次】第 {search_count} 轮

    【已搜索过的关键词】（请勿重复）
    {json.dumps(searched_queries, ensure_ascii=False) if searched_queries else "无"}

    【任务】
    生成 2-3 个最有价值的小红书搜索关键词，用于获取旅行攻略。

    【要求】
    1. 关键词要具体、符合小红书搜索习惯
    2. 必须结合用户的人群类型和偏好
    3. 不要与已搜索的关键词重复或相似
    4. 搜索策略：
    - 第1轮：优先搜索路线规划、必去景点
    - 第2轮：优先搜索避坑攻略、美食住宿
    - 后续：小众推荐、省钱技巧、特殊需求

    【关键词生成技巧】
    - 如果是"特种兵"偏好，加入"一日游"、"暴走"、"高效"等词
    - 如果是"美食"偏好，加入"必吃"、"本地人推荐"等词
    - 如果是"拍照"偏��，加入"打卡"、"出片"、"网红"等词
    - 如果是"亲子"类型，加入"带娃"、"遛娃"、"儿童友好"等词
    - 如果是"情侣"类型，加入"约会"、"浪漫"、"二人游"等词

    【输出格式】
    直接输出关键词，每行一个，不要编号或其他多余内容：
    关键词1
    关键词2
    关键词3
    """

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        
        # 解析关键词
        lines = response.content.strip().split("\n")
        queries = []
        for line in lines:
            line = line.strip()
            # 过滤空行和格式字符
            if not line or line.startswith(("-", "*", "•", "#", "【")):
                continue
            # 移除可能的编号 (1. 2. 等)
            if len(line) > 2 and line[0].isdigit() and line[1] in ".、):：":
                line = line[2:].strip()
            if len(line) > 2:
                queries.append(line)
        
        # 过滤已搜索过的
        queries = [q for q in queries if q not in searched_queries]
        
        print(f"🤖 LLM 生成的搜索关键词: {queries}")
        
        return queries[:3]  # 最多返回3个
        
    except Exception as e:
        print(f"⚠️ LLM 生成关键词失败: {e}，使用兜底关键词")
        # 兜底关键词
        fallback = [
            f"{user_profile.destination} {user_profile.days}天攻略",
            f"{user_profile.destination} 必去景点"
        ]
        return [q for q in fallback if q not in searched_queries][:2]

def search_node(state: AgentState) -> AgentState:
    """搜索节点 - 使用小红书MCP搜索攻略"""
    search_count = state.get("_search_count", 1)
    print(f"--- SEARCH AGENT (第 {search_count} 次搜索) ---")
    
    # ✅ 保留 session_id
    session_id = state.get("session_id", "")
    print(f"📌 Search Node session_id: {session_id}")

    user_profile = state["user_profile"]
    destination = user_profile.destination
    
    # 获取已搜索的关键词
    searched_queries = state.get("_search_queries", [])
    
    # ✅ 使用 LLM 智能生成搜索关键词
    queries = generate_search_queries(user_profile, search_count, searched_queries)
    
    if not queries:
        print("⚠️ 没有新的搜索关键词")
        return state
    
    # 使用小红书搜索工具
    search_tool = XiaohongshuSearchTool()
    
    # 获取现有的笔记
    existing_notes = []
    if state.get("search_results"):
        existing_notes = state["search_results"].notes or []
    
    notes = list(existing_notes)  # 复制现有笔记
    
    for q in queries:
        try:
            print(f"🔍 搜索: {q}")
            res = search_tool._run(keyword=q)
            data = json.loads(res)
            
            if "error" in data:
                print(f"❌ 搜索失败 {q}: {data['error']}")
                continue
            
            # 提取笔记内容
            content_parts = []
            for note in data.get("notes", []):
                title = note.get("title", "无标题")
                desc = note.get("desc", "")
                author = note.get("author", "未知")
                likes = note.get("likes", 0)
                
                if desc:
                    note_text = f"""
                    📝 【{title}】
                    👤 作者: {author} | 👍 点赞: {likes}
                    📖 内容:
                    {desc}
                    """
                    content_parts.append(note_text)
            
            if content_parts:
                combined_content = "\n" + "="*50 + "\n".join(content_parts)
                notes.append(SearchNote(title=q, content=combined_content[:4000]))
                print(f"✅ 获取到 {len(content_parts)} 篇笔记")
            
            # 记录已搜索的关键词
            searched_queries.append(q)
                
        except Exception as e:
            print(f"❌ 搜索异常 {q}: {e}")
    
    state["search_results"] = SearchResult(notes=notes)
    state["_search_queries"] = searched_queries
    print(f"📊 搜索完成，累计 {len(notes)} 组结果")
    
    return state


# def search_node(state: AgentState) -> AgentState:
#     """搜索节点 - 使用小红书MCP搜索攻略"""
#     search_count = state.get("_search_count", 1)
#     print(f"--- SEARCH AGENT (第 {search_count} 次搜索) ---")
    
#      # ✅ 保留 session_id
#     session_id = state.get("session_id", "")
#     print(f"📌 Search Node session_id: {session_id}")

#     user_profile = state["user_profile"]
#     destination = user_profile.destination
    
#     # 获取已搜索的关键词
#     searched_queries = state.get("_search_queries", [])
    
#     # 使用小红书搜索工具
#     search_tool = XiaohongshuSearchTool()
    
#     # ✅ 根据搜索次数使用不同的关键词
#     if search_count == 1:
#         queries = [
#             f"{destination} {user_profile.days}天游玩路线",
#             f"{destination} 必去景点推荐",
#         ]
#     elif search_count == 2:
#         queries = [
#             f"{destination} 避坑攻略",
#             f"{destination} 美食推荐",
#         ]
#     else:
#         queries = [
#             f"{destination} 小众景点",
#             f"{destination} 交通攻略",
#         ]
    
#     # 过滤已搜索过的
#     queries = [q for q in queries if q not in searched_queries]
    
#     if not queries:
#         print("⚠️ 没有新的搜索关键词")
#         return state
    
#     # 获取现有的笔记
#     existing_notes = []
#     if state.get("search_results"):
#         existing_notes = state["search_results"].notes or []
    
#     notes = list(existing_notes)  # 复制现有笔记
    
#     for q in queries:
#         try:
#             print(f"🔍 搜索: {q}")
#             res = search_tool._run(keyword=q)
#             data = json.loads(res)
            
#             if "error" in data:
#                 print(f"❌ 搜索失败 {q}: {data['error']}")
#                 continue
            
#             # 提取笔记内容
#             content_parts = []
#             for note in data.get("notes", []):
#                 title = note.get("title", "无标题")
#                 desc = note.get("desc", "")
#                 author = note.get("author", "未知")
#                 likes = note.get("likes", 0)
                
#                 if desc:
#                     note_text = f"""
#                     📝 【{title}】
#                     👤 作者: {author} | 👍 点赞: {likes}
#                     📖 内容:
#                     {desc}
#                     """
#                     content_parts.append(note_text)
            
#             if content_parts:
#                 combined_content = "\n" + "="*50 + "\n".join(content_parts)
#                 notes.append(SearchNote(title=q, content=combined_content[:4000]))
#                 print(f"✅ 获取到 {len(content_parts)} 篇笔记")
            
#             # 记录已搜索的关键词
#             searched_queries.append(q)
                
#         except Exception as e:
#             print(f"❌ 搜索异常 {q}: {e}")
    
#     state["search_results"] = SearchResult(notes=notes)
#     state["_search_queries"] = searched_queries
#     print(f"📊 搜索完成，累计 {len(notes)} 组结果")
    
#     return state

def summary_node(state: AgentState) -> AgentState:
    """总结节点 - 整理搜索结果为规划规则"""
    print("--- SUMMARY AGENT ---")
    search_results = state.get("search_results")
    
    if not search_results or not search_results.notes:
        print("⚠️ 没有搜索结果可供总结")
        state["planning_rules"] = create_default_rules(
            state.get("user_profile").destination if state.get("user_profile") else ""
        )
        return state
    
    print(f"📚 共有 {len(search_results.notes)} 条笔记待总结")
    
    # Combine notes into context
    context = "\n\n".join([
        f"【笔记{i+1}】\n标题: {n.title}\n内容: {n.content}\n点赞: {n.likes or 0}" 
        for i, n in enumerate(search_results.notes)
    ])
    
    prompt = f"{XIAOHONGSHU_SUMMARY_PROMPT}\n\n【搜索结果】\n{context}"
    
    response = llm.invoke([HumanMessage(content=prompt)])
    
    # ✅ 调试：打印 LLM 原始响应
    print("\n" + "=" * 60)
    print("🔍 SUMMARY LLM 原始响应：")
    print("=" * 60)
    print(response.content[:2000])  # 只打印前2000字符
    if len(response.content) > 2000:
        print(f"\n... 还有 {len(response.content) - 2000} 字符 ...")
    print("=" * 60 + "\n")
    
    try:
        # Extract JSON from markdown code block if present
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        content = content.strip()
        
        # ✅ 调试：打印提取的 JSON
        print("📋 提取的 JSON 内容：")
        print(content[:1500])
        if len(content) > 1500:
            print(f"\n... 还有 {len(content) - 1500} 字符 ...")
        print()
        
        data = json.loads(content)
        
        # ✅ 调试：打印解析后的结构
        print("📊 解析后的 JSON 键：", list(data.keys()))
        
        # ✅ 数据预处理：修复类型问题
        data = normalize_planning_rules_data(data)
        
        rules = PlanningRules(**data)
        state["planning_rules"] = rules
        
        # ✅ 打印总结结果
        print("\n" + "=" * 60)
        print("✅ SUMMARY 结果：")
        print("=" * 60)
        print(f"📍 目的地: {rules.destination}")
        print(f"📅 推荐天数: {rules.get_recommended_days_str()}")
        print(f"🗺️ 每日路线数: {len(rules.daily_routes)}")
        print(f"⭐ 必去景点: {rules.get_must_visit_names()[:5]}...")  # 只显示前5个
        print(f"⚠️ 避坑建议: {rules.get_avoid_list()[:3]}...")  # 只显示前3个
        print(f"🚗 交通建议: {rules.transport_tips[:2]}...")  # 只显示前2个
        print(f"📝 实用贴士: {rules.practical_tips[:2]}...")
        print("=" * 60 + "\n")
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        print(f"   错误位置: 第 {e.lineno} 行, 第 {e.colno} 列")
        state["planning_rules"] = create_default_rules(
            state.get("user_profile").destination if state.get("user_profile") else ""
        )
        
    except Exception as e:
        print(f"❌ 验证失败: {type(e).__name__}: {e}. Using fallback.")
        import traceback
        traceback.print_exc()
        state["planning_rules"] = create_default_rules(
            state.get("user_profile").destination if state.get("user_profile") else ""
        )
        
    return state

def normalize_planning_rules_data(data: dict) -> dict:
    """标准化规划规则数据，修复类型问题"""
    
    # 1. 确保基本字段存在
    data.setdefault("destination", "")
    data.setdefault("recommended_days", "")
    data.setdefault("daily_routes", [])
    data.setdefault("common_routes", [])
    data.setdefault("must_visit", [])
    data.setdefault("avoid_list", [])
    data.setdefault("avoid", [])
    data.setdefault("transport_tips", [])
    data.setdefault("practical_tips", [])
    
    # 2. ✅ 修复 recommended_days 类型问题
    if isinstance(data.get("recommended_days"), int):
        data["recommended_days"] = f"{data['recommended_days']}天"
    elif data.get("recommended_days") is None:
        data["recommended_days"] = ""
    
    # 3. 从 daily_routes 生成 common_routes（如果为空）
    if data.get("daily_routes") and not data.get("common_routes"):
        routes = []
        for route in data["daily_routes"]:
            if isinstance(route, dict):
                day = route.get("day", "")
                theme = route.get("theme", "")
                schedule = route.get("schedule", [])
                if schedule:
                    places = []
                    for s in schedule:
                        if isinstance(s, dict):
                            places.append(s.get("place", s.get("name", "")))
                    if places:
                        route_str = f"Day{day} {theme}: {' -> '.join(filter(None, places))}"
                        routes.append(route_str)
        data["common_routes"] = routes
    
    # 4. 从 avoid_list 生成 avoid（如果为空）
    if data.get("avoid_list") and not data.get("avoid"):
        avoid_strs = []
        for item in data["avoid_list"]:
            if isinstance(item, str):
                avoid_strs.append(item)
            elif isinstance(item, dict):
                item_text = item.get("item", "")
                reason = item.get("reason", "")
                if item_text:
                    if reason:
                        avoid_strs.append(f"{item_text}（{reason}）")
                    else:
                        avoid_strs.append(item_text)
        data["avoid"] = avoid_strs
    
    # 5. 确保列表字段是列表
    list_fields = ["transport_tips", "practical_tips", "common_routes"]
    for field in list_fields:
        if isinstance(data.get(field), str):
            data[field] = [data[field]] if data[field] else []
    
    # 6. ✅✅✅ 处理 food_accommodation（关键修复！）
    if data.get("food_accommodation") is None:
        data["food_accommodation"] = {
            "food_areas": [],
            "stay_areas": [],
            "recommendations": []
        }
    elif isinstance(data["food_accommodation"], dict):
        fa = data["food_accommodation"]
        fa.setdefault("food_areas", [])
        fa.setdefault("stay_areas", [])
        fa.setdefault("recommendations", [])
        
        # ✅ 关键修复：将 recommendations 中的字典转为字符串
        if isinstance(fa.get("recommendations"), list):
            normalized_recs = []
            for item in fa["recommendations"]:
                if isinstance(item, str):
                    normalized_recs.append(item)
                elif isinstance(item, dict):
                    # 格式1: {"name": "鸭血粉丝汤", "place": "南京老字号"}
                    if "name" in item:
                        name = item.get("name", "")
                        place = item.get("place", "")
                        if place:
                            normalized_recs.append(f"{name} - {place}")
                        else:
                            normalized_recs.append(name)
                    # 格式2: {"住宿推荐": "如家酒店、汉庭酒店等"}
                    else:
                        for k, v in item.items():
                            normalized_recs.append(f"{k}: {v}")
                else:
                    normalized_recs.append(str(item))
            fa["recommendations"] = normalized_recs
        
        # ✅ 同样确保 food_areas 和 stay_areas 是字符串列表
        for field in ["food_areas", "stay_areas"]:
            if isinstance(fa.get(field), list):
                fa[field] = [str(x) if not isinstance(x, str) else x for x in fa[field]]
    
    # 7. 处理 crowd_specific
    if data.get("crowd_specific") is None:
        data["crowd_specific"] = {
            "family": [],
            "couple": [],
            "friends": [],
            "solo": []
        }
    elif isinstance(data["crowd_specific"], dict):
        cs = data["crowd_specific"]
        for field in ["family", "couple", "friends", "solo"]:
            cs.setdefault(field, [])
            # ✅ 确保每个字段都是字符串列表
            if isinstance(cs.get(field), list):
                cs[field] = [str(x) if not isinstance(x, str) else x for x in cs[field]]
    
    # 8. ✅ 新增：处理 must_visit（确保格式正确）
    if isinstance(data.get("must_visit"), list):
        normalized_must_visit = []
        for item in data["must_visit"]:
            if isinstance(item, str):
                normalized_must_visit.append({
                    "name": item,
                    "reason": "",
                    "best_time": "",
                    "duration": ""
                })
            elif isinstance(item, dict):
                normalized_must_visit.append({
                    "name": item.get("name", item.get("景点", "")),
                    "reason": item.get("reason", item.get("推荐理由", "")),
                    "best_time": item.get("best_time", item.get("最佳时间", "")),
                    "duration": item.get("duration", item.get("建议时长", ""))
                })
        data["must_visit"] = normalized_must_visit
    
    # 9. ✅ 新增：处理 avoid_list（确保格式正确）
    if isinstance(data.get("avoid_list"), list):
        normalized_avoid = []
        for item in data["avoid_list"]:
            if isinstance(item, str):
                normalized_avoid.append({
                    "item": item,
                    "reason": ""
                })
            elif isinstance(item, dict):
                normalized_avoid.append({
                    "item": item.get("item", item.get("避坑项", str(item))),
                    "reason": item.get("reason", item.get("原因", ""))
                })
        data["avoid_list"] = normalized_avoid
    
    return data

def create_default_rules(destination: str = "") -> PlanningRules:
    """创建默认规划规则"""
    return PlanningRules(
        destination=destination,
        recommended_days="3天",
        daily_routes=[],
        common_routes=[],
        must_visit=[],
        avoid_list=[],
        avoid=["节假日热门景点人多", "高峰期打车难"],
        transport_tips=["建议使用公共交通", "提前规划路线"],
        practical_tips=["提前预约热门景点", "注意天气变化"],
        sources_summary="使用默认规则"
    )

def planning_node(state: AgentState) -> AgentState:
    """规划节点 - 生成行程草案"""
    print("--- PLANNING AGENT ---")
    user = state["user_profile"]
    rules = state.get("planning_rules")
    
    # 如果没有规则，创建默认规则
    if not rules:
        print("⚠️ 没有规划规则，使用默认规则")
        rules = PlanningRules(
            common_routes=[],
            must_visit=[],
            avoid=[],
            transport_tips=[]
        )
    
    # ✅ 先序列化规则
    try:
        rules_str = rules.model_dump_json(ensure_ascii=False)
    except Exception:
        rules_str = "按照通用旅行规划原则进行安排"
    
    # ✅ Format the planning prompt - 添加 planning_rules 参数！
    prompt = PLANNING_PROMPT_TEMPLATE.format(
        origin=user.origin,
        destination=user.destination,
        days=user.days,
        date_range=user.date_range or "不限",
        group_type=user.group_type,
        preferences=", ".join(user.preferences) if user.preferences else "无特殊偏好",
        budget=user.budget or "不限",
        planning_rules=rules_str  # ✅✅✅ 添加这一行！
    )
    
    # 添加天气信息
    weather_context = ""
    weather_info = state.get("weather_info")
    if weather_info:
        weather_context = f"\n\n天气信息：{json.dumps(weather_info, ensure_ascii=False)}"
    
    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"请根据以上信息生成详细行程{weather_context}")
    ])
    
    # Ask LLM to structure the plan as JSON
    structure_prompt = "请将以上行程转换为 JSON 格式，包含 days 数组，每天有 schedule 列表。"
    
    json_res = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"请根据以上信息生成详细行程{weather_context}"),
        HumanMessage(content=response.content),
        HumanMessage(content=structure_prompt)
    ])
    
    try:
        content = json_res.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        plan_dict = json.loads(content)
        print(plan_dict)
        state["draft_plan"] = plan_dict
        print("✅ 行程草案生成成功")
    except Exception as e:
        print(f"⚠️ JSON解析失败: {e}")
        state["draft_plan"] = {"error": "Failed to parse plan", "raw": response.content}
        
    return state

def map_node(state: AgentState) -> AgentState:
    """地图节点 - 使用高德MCP验证路线"""
    print("--- MAP AGENT ---")
    plan = state["draft_plan"]
    
    if "days" not in plan:
        print("⚠️ 行程数据不完整，跳过地图验证")
        state["validated_plan"] = plan
        return state
    
    # 使用新的路线规划工具
    route_tool = RoutePlanTool()
    validated_days = []
    mcp_available = True
    
    for day_idx, day in enumerate(plan["days"]):
        schedule = day.get("schedule", [])
        new_schedule = []
        
        print(f"📍 处理第 {day_idx + 1} 天行程...")
        
        for i in range(len(schedule) - 1):
            curr = schedule[i]
            next_spot = schedule[i + 1]
            
            curr_poi = curr.get("poi", curr.get("name", curr.get("location", "")))
            next_poi = next_spot.get("poi", next_spot.get("name", next_spot.get("location", "")))
            
            if curr_poi and next_poi and mcp_available:
                try:
                    route_info = route_tool._run(
                        origin=curr_poi,
                        destination=next_poi,
                        mode="driving"
                    )
                    route_data = json.loads(route_info)
                    
                    if "error" not in route_data:
                        distance = route_data.get("distance", "未知")
                        duration = route_data.get("duration", "未知")
                        curr["transport_suggestion"] = f"到下一站: {distance}, 约 {duration}"
                        print(f"  ✅ {curr_poi} → {next_poi}: {distance}, {duration}")
                    else:
                        curr["transport_suggestion"] = "路线信息获取失败"
                        print(f"  ⚠️ {curr_poi} → {next_poi}: {route_data.get('error', '未知错误')}")
                        
                except json.JSONDecodeError:
                    curr["transport_suggestion"] = "路线解析失败"
                except Exception as e:
                    print(f"  ❌ 路线规划异常: {type(e).__name__}: {e}")
                    curr["transport_suggestion"] = "路线信息暂不可用"
                    
                    # 如果是超时错误，后续不再尝试
                    if "Timeout" in type(e).__name__ or "超时" in str(e):
                        print("  ⚠️ 检测到超时，跳过后续路线查询")
                        mcp_available = False
            
            new_schedule.append(curr)
            
            # 如果 MCP 不可用，直接复制剩余行程
            if not mcp_available:
                new_schedule.extend(schedule[i+1:])
                break
        else:
            # 正常结束循环，添加最后一个景点
            if schedule:
                new_schedule.append(schedule[-1])
        
        day["schedule"] = new_schedule
        validated_days.append(day)
    
    plan["days"] = validated_days
    state["validated_plan"] = plan
    print("✅ 地图验证完成")
    return state

def weather_node(state: AgentState) -> AgentState:
    """天气节点 - 查询目的地天气（可选）"""
    print("--- WEATHER AGENT ---")
    user_profile = state["user_profile"]
    destination = user_profile.destination
    
    weather_tool = WeatherTool()
    
    try:
        result = weather_tool._run(city=destination)
        weather_data = json.loads(result)
        
        if "error" not in weather_data:
            state["weather_info"] = weather_data
            print(f"✅ 获取 {destination} 天气成功")
            
            # 将天气建议添加到规划规则
            if state.get("planning_rules") and weather_data.get("travel_tips"):
                tips = state["planning_rules"].transport_tips or []
                tips.extend(weather_data["travel_tips"])
                state["planning_rules"].transport_tips = tips
        else:
            print(f"⚠️ 天气查询失败: {weather_data.get('error')}")
            
    except Exception as e:
        print(f"❌ 天气查询异常: {e}")
    
    return state


def refine_node(state: AgentState) -> AgentState:
    """精炼节点 - 润色最终行程"""
    print("--- REFINE AGENT ---")
    
    # ✅ 调试：打印 state 的所有 key
    print(f"📋 State keys: {list(state.keys())}")
    
    # ✅ 获取 session_id
    session_id = state.get("session_id") or get_session_id()
    print(f"📌 state.get('session_id'): '{state.get('session_id')}'")
    print(f"📌 get_session_id(): '{get_session_id()}'")
    print(f"📌 Final session_id: '{session_id}'")
    
    # 更新进度
    if session_id:
        redis_service.update_plan_status(
            session_id,
            status="processing",
            progress=80,
            message="正在润色行程..."
        )

    plan = state.get("validated_plan") or state.get("draft_plan")
    user_profile = state.get("user_profile")
    
    destination = user_profile.destination if user_profile else "目的地"
    days_count = user_profile.days if user_profile else 3
    
    if not plan:
        print("⚠️ 没有可用的行程数据")
        state["final_result"] = create_empty_result(destination, days_count)
        _save_to_cache(state)
        return state
    
    # 添加天气信息
    weather_context = ""
    if state.get("weather_info"):
        weather_info = state["weather_info"]
        weather_context = f"\n\n当前天气信息：\n{json.dumps(weather_info, ensure_ascii=False)}"
    
    content = json.dumps(plan, ensure_ascii=False)
    
      # 更新进度
    if session_id:
        redis_service.update_plan_status(
            session_id,
            status="processing",
            progress=85,
            message="正在生成最终计划..."
        )


    response = llm.invoke([
        SystemMessage(content=POLISHING_PROMPT),
        HumanMessage(content=f"{content}{weather_context}")
    ])
    
    try:
        res_content = response.content.strip()
        
        # 提取 JSON
        if "```json" in res_content:
            res_content = res_content.split("```json")[1].split("```")[0]
        elif "```" in res_content:
            res_content = res_content.split("```")[1].split("```")[0]
        
        res_content = res_content.strip()
        res_content = fix_json_string(res_content)
        
        final_json = json.loads(res_content)
        
        # 标准化数据
        normalized = normalize_plan_data(final_json, destination)
        state["final_result"] = TravelPlanResult(**normalized)
        
        # ✅ 存储到缓存
        _save_to_cache(state)
        
        print("✅ 行程润色完成")
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析失败: {e}")
        state["final_result"] = create_fallback_result(state, plan, destination, days_count)
        _save_to_cache(state)
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        state["final_result"] = create_fallback_result(state, plan, destination, days_count)
        _save_to_cache(state)
        
    return state

def fix_json_string(json_str: str) -> str:
    """修复 JSON 字符串中的常见问题"""
    
    # 1. 修复字符串内部的换行符（在引号内的换行转为空格）
    # 匹配 "..." 内的内容，替换其中的换行
    def fix_string_newlines(match):
        content = match.group(0)
        # 替换字符串内的实际换行为空格
        fixed = content.replace('\n', ' ').replace('\r', ' ')
        # 压缩多余空格
        fixed = re.sub(r'\s+', ' ', fixed)
        return fixed
    
    # 匹配 JSON 字符串（考虑转义引号）
    json_str = re.sub(r'"(?:[^"\\]|\\.)*"', fix_string_newlines, json_str)
    
    # 2. 移除控制字符
    json_str = re.sub(r'[\x00-\x1f\x7f]', ' ', json_str)
    
    # 3. 修复常见的 Unicode 问题
    json_str = json_str.replace('\u2028', ' ').replace('\u2029', ' ')
    
    return json_str


def normalize_plan_data(data: dict, destination: str) -> dict:
    """标准化数据，确保符合 TravelPlanResult schema"""
    
    result = {
        "overview": "",
        "destination": destination,  # ✅ 确保包含 destination
        "highlights": [],
        "days": [],
        "tips": {}
    }
    
    # 1. 修复 overview
    overview = data.get("overview", "")
    if isinstance(overview, dict):
        result["overview"] = overview.get("summary", f"{destination}精彩之旅")
    elif isinstance(overview, str):
        result["overview"] = overview
    else:
        result["overview"] = f"{destination}精彩之旅"
    
    # 2. 修复 highlights
    highlights = data.get("highlights", [])
    if isinstance(highlights, list):
        result["highlights"] = [str(h) for h in highlights if h]
    else:
        result["highlights"] = []
    
    # 3. 修复 days
    days = data.get("days", [])
    fixed_days = []
    
    for day in days:
        fixed_day = {
            "day": day.get("day", len(fixed_days) + 1),
            "date": day.get("date", f"Day {len(fixed_days) + 1}"),
            "theme": day.get("theme", ""),
            "weather_tip": day.get("weather_tip", ""),
            "schedule": []
        }
        
        schedule = day.get("schedule", [])
        for item in schedule:
            fixed_item = normalize_schedule_item(item)
            if fixed_item:
                fixed_day["schedule"].append(fixed_item)
        
        fixed_days.append(fixed_day)
    
    result["days"] = fixed_days
    
    # 4. 修复 tips
    tips = data.get("tips", {})
    if isinstance(tips, dict):
        result["tips"] = {
            "transport": _to_string(tips.get("transport", "")),
            "food": _to_string(tips.get("food", "")),
            "accommodation": _to_string(tips.get("accommodation", "")),
            "budget": _to_string(tips.get("budget", "")),
            "avoid": _to_list(tips.get("avoid", [])),
            "replaceable": _to_list(tips.get("replaceable", [])),
        }
    else:
        result["tips"] = {
            "transport": "",
            "food": "",
            "avoid": [],
            "replaceable": []
        }
    
    return result


def normalize_schedule_item(item: dict) -> Optional[dict]:
    """标准化单个行程项"""
    if not isinstance(item, dict):
        return None
    
    # ✅ 关键：tips 必须是字符串
    tips = item.get("tips", "")
    if isinstance(tips, list):
        tips = "；".join(str(t) for t in tips)  # 列表转字符串
    elif not isinstance(tips, str):
        tips = str(tips) if tips else ""
    
    return {
        "time": item.get("time", "待定"),
        "poi": _get_poi(item),
        "activity": item.get("activity", item.get("description", "")),
        "duration": item.get("duration", "1小时"),
        "tips": tips,  # ✅ 确保是字符串
        "route_info": item.get("route_info", item.get("transport", ""))
    }


def _get_poi(item: dict) -> str:
    """从 item 中提取 POI 名称"""
    poi = (
        item.get("poi") or 
        item.get("location") or 
        item.get("name") or 
        item.get("place") or
        ""
    )
    
    # 如果还是空的，尝试从 activity 中提取
    if not poi:
        activity = item.get("activity", "")
        for keyword in ["游览", "前往", "到达", "参观"]:
            if keyword in activity:
                parts = activity.split(keyword)
                if len(parts) > 1:
                    poi = parts[1].split("，")[0].split("（")[0].strip()[:20]
                    break
    
    return poi if poi else "待定地点"


def _to_string(value: Any) -> str:
    """将任意值转为字符串"""
    if isinstance(value, list):
        return "；".join(str(v) for v in value)
    elif isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    elif value is None:
        return ""
    else:
        return str(value)


def _to_list(value: Any) -> List[str]:
    """将任意值转为字符串列表"""
    if isinstance(value, list):
        return [str(v) for v in value]
    elif isinstance(value, str):
        return [value] if value else []
    else:
        return []


def _save_to_cache(state: AgentState) -> bool:
    """
    将最终结果保存到 Redis
    
    Args:
        state: Agent 状态
        
    Returns:
        是否保存成功
    """
    # ✅ 从 state 获取 session_id，如果没有则从上下文获取
    session_id = state.get("session_id") or get_session_id()
    
    if not session_id:
        print("⚠️ 无法保存：session_id 为空")
        return False
    
    final_result = state.get("final_result")
    if not final_result:
        print("⚠️ 无法保存：final_result 为空")
        return False
    
    # 转换结果为字典
    if hasattr(final_result, 'model_dump'):
        result_dict = final_result.model_dump()
    elif hasattr(final_result, 'dict'):
        result_dict = final_result.dict()
    else:
        result_dict = final_result
    
    # 获取用户画像
    user_profile = state.get("user_profile")
    user_profile_dict = None
    if user_profile:
        if hasattr(user_profile, 'model_dump'):
            user_profile_dict = user_profile.model_dump()
        elif hasattr(user_profile, 'dict'):
            user_profile_dict = user_profile.dict()
        else:
            user_profile_dict = user_profile
    
    # 构建完整的存储数据
    plan_data = {
        "plan": result_dict,
        "user_profile": user_profile_dict,
        "destination": user_profile.destination if user_profile else "未知",
        "days": user_profile.days if user_profile else 0,
        "meta": {
            "search_count": state.get("_search_count", 0),
            "has_weather": state.get("weather_info") is not None,
            "has_map_validation": state.get("validated_plan") is not None,
        },
        "generated_at": datetime.now().isoformat()
    }
    
    # ✅ 保存到 Redis
    success = redis_service.save_plan(session_id, plan_data)
    
    if success:
        # 更新状态为完成
        redis_service.update_plan_status(
            session_id,
            status="completed",
            progress=100,
            message="旅行计划生成完成"
        )
        print(f"✅ 计划已保存到 Redis，session_id: {session_id}")
    
    return success


def create_empty_result(destination: str, days: int) -> TravelPlanResult:
    """创建空结果"""
    return TravelPlanResult(
        destination=destination,
        title=f"{destination}{days}日游",
        summary="暂无行程信息",
        highlights=[],
        daily_plans=[],
        tips=[],
        estimated_budget=""
    )


def create_fallback_result(state: AgentState, plan, destination: str, days_count: int) -> TravelPlanResult:
    """创建兜底的旅行结果"""
    from datetime import datetime
    
    # 获取用户信息
    user_profile = state.get("user_profile")
    planning_rules = state.get("planning_rules")
    
    # 构建每日行程
    daily_plans = []
    if plan and hasattr(plan, 'daily_plans') and plan.daily_plans:
        daily_plans = plan.daily_plans
    else:
        # 创建默认每日行程
        for i in range(days_count):
            daily_plans.append(DailyPlan(
                day=i + 1,
                date=f"第{i + 1}天",
                theme=f"Day {i + 1} 行程",
                activities=[],
                meals={},
                tips=[]
            ))
    
    # ✅ 根据你的 TravelTips 模型构建
    tips = TravelTips(
        transport="",
        food="",
        accommodation="",
        budget="",
        avoid=[],
        replaceable=[]
    )
    
    # 从 planning_rules 填充 tips
    if planning_rules:
        # 交通建议
        if planning_rules.transport_tips:
            tips.transport = "；".join(planning_rules.transport_tips[:3])
        
        # 美食建议
        if planning_rules.food_accommodation:
            fa = planning_rules.food_accommodation
            food_items = []
            if hasattr(fa, 'food_areas') and fa.food_areas:
                food_items.extend(fa.food_areas[:2])
            if hasattr(fa, 'recommendations') and fa.recommendations:
                food_items.extend(fa.recommendations[:2])
            tips.food = "；".join(food_items) if food_items else ""
            
            # 住宿建议
            if hasattr(fa, 'stay_areas') and fa.stay_areas:
                tips.accommodation = "；".join(fa.stay_areas[:2])
        
        # 避坑建议
        if hasattr(planning_rules, 'avoid') and planning_rules.avoid:
            tips.avoid = planning_rules.avoid[:5]
        elif hasattr(planning_rules, 'avoid_list') and planning_rules.avoid_list:
            # 从 avoid_list 提取
            avoid_items = []
            for item in planning_rules.avoid_list[:5]:
                if isinstance(item, str):
                    avoid_items.append(item)
                elif isinstance(item, dict):
                    avoid_items.append(item.get("item", str(item)))
                elif hasattr(item, 'item'):
                    avoid_items.append(item.item)
            tips.avoid = avoid_items
        
        # 实用建议作为可替换项
        if planning_rules.practical_tips:
            tips.replaceable = planning_rules.practical_tips[:3]
    
    # 构建结果
    return TravelPlanResult(
        destination=destination,
        duration=f"{days_count}天",
        travel_dates=user_profile.travel_dates if user_profile else "",
        daily_plans=daily_plans,
        tips=tips,  # ✅ 传入 TravelTips 对象
        summary=f"{destination}{days_count}天行程规划",
        budget_estimate=None,
        weather_summary=None,
        created_at=datetime.now().isoformat()
    )

# ============ 辅助函数 ============

def get_geocode(address: str, city: str = "") -> dict:
    """获取地址的经纬度坐标"""
    geo_tool = GeoCodeTool()
    try:
        result = geo_tool._run(address=address, city=city)
        return json.loads(result)
    except Exception as e:
        return {"error": str(e)}


def get_route_info(origin: str, destination: str, mode: str = "driving") -> dict:
    """获取两点间的路线信息"""
    route_tool = RoutePlanTool()
    try:
        result = route_tool._run(origin=origin, destination=destination, mode=mode)
        return json.loads(result)
    except Exception as e:
        return {"error": str(e)}