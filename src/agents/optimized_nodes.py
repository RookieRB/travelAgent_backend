# src/agents/optimized_nodes.py
import json
from typing import List, Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from enum import Enum
from src.agents.state import AgentState, print_state_status
from src.utils.token_budget import TokenBudget, token_counter
from src.utils.value_evaluator import InformationValueEvaluator
from src.models.schemas import SearchResult, SearchNote, PlanningRules
from src.tools.tools import XiaohongshuSearchTool
from src.models.llm import LLMFactory
from src.services.travel_cache import travel_cache


class SearchCategory(Enum):
    """搜索类别"""
    ROUTE = "route"           # 路线攻略
    ATTRACTION = "attraction" # 景点推荐
    FOOD = "food"             # 美食攻略
    TRANSPORT = "transport"   # 交通攻略
    ACCOMMODATION = "accommodation"  # 住宿推荐
    AVOID = "avoid"           # 避坑指南
    PHOTO = "photo"           # 拍照打卡
    SPECIAL = "special"       # 特殊偏好


# 搜索模板
SEARCH_TEMPLATES: Dict[SearchCategory, List[str]] = {
    SearchCategory.ROUTE: [
        "{dest} {days}天攻略",
        "{dest} 旅游路线推荐",
        "{dest} 行程安排",
    ],
    SearchCategory.ATTRACTION: [
        "{dest} 景点推荐",
        "{dest} 热门景点攻略",
    ],
    SearchCategory.FOOD: [
        "{dest} 美食攻略",
        "{dest} 必吃美食推荐",
        "{dest} 本地人推荐美食",
        "{dest} 美食街",
    ],
    SearchCategory.TRANSPORT: [
        "{dest} 交通攻略",
        "{dest} 怎么去",
        "{dest} 地铁公交",
    ],
    SearchCategory.ACCOMMODATION: [
        "{dest} 住宿推荐",
        "{dest} 住哪里方便",
        "{dest} 酒店民宿",
    ],
    SearchCategory.AVOID: [
        "{dest} 避坑",
        "{dest} 旅游注意事项",
        "{dest} 不要踩雷",
    ],
    SearchCategory.PHOTO: [
        "{dest} 拍照打卡",
        "{dest} 出片",
        "{dest} 网红景点",
    ],
}

# 偏好到搜索类别的映射
PREFERENCE_CATEGORY_MAP: Dict[str, List[SearchCategory]] = {
    "美食": [SearchCategory.FOOD],
    "吃货": [SearchCategory.FOOD],
    "拍照": [SearchCategory.PHOTO],
    "摄影": [SearchCategory.PHOTO],
    "网红": [SearchCategory.PHOTO],
    "打卡": [SearchCategory.PHOTO],
    "历史": [SearchCategory.ATTRACTION],
    "文化": [SearchCategory.ATTRACTION],
    "自然": [SearchCategory.ATTRACTION],
    "休闲": [SearchCategory.ACCOMMODATION],
    "度假": [SearchCategory.ACCOMMODATION],
}



def _generate_smart_queries(
    user_profile, 
    search_count: int, 
    searched: List[str],
    missing_info: List[str] = None  # 新增：缺失的信息类型
) -> List[str]:
    """
    智能生成搜索关键词 - 按信息类型组织
    
    策略:
    - 第1轮: 路线攻略（获取整体框架）
    - 第2轮: 景点 + 美食（填充核心内容）
    - 第3轮: 交通/住宿/避坑（按需补充）
    - 后续轮: 根据缺失信息定向搜索
    """
    dest = user_profile.destination
    days = user_profile.days
    prefs = user_profile.preferences or []
    group_type = user_profile.group_type or ""
    
    queries = []
    missing_info = missing_info or []
    
    # ============ 按轮次确定搜索类别 ============
    if search_count == 1:
        # 第1轮: 路线攻略（最重要）
        categories = [SearchCategory.ROUTE]
        
    elif search_count == 2:
        # 第2轮: 景点 + 美食
        categories = [SearchCategory.ATTRACTION, SearchCategory.FOOD]
        
    elif search_count == 3:
        # 第3轮: 避坑 + 交通/住宿
        categories = [SearchCategory.AVOID, SearchCategory.TRANSPORT]
        
    else:
        # 后续轮: 根据缺失信息搜索
        categories = _get_categories_for_missing(missing_info)
        if not categories:
            # 没有明确缺失，搜索用户偏好相关
            categories = _get_categories_for_preferences(prefs)
    
    # ============ 生成查询语句 ============
    for category in categories:
        templates = SEARCH_TEMPLATES.get(category, [])
        if templates:
            # 每个类别取1-2个模板
            for template in templates[:2]:
                query = template.format(dest=dest, days=days)
                queries.append(query)
    
    # ============ 用户偏好补充（第1-2轮） ============
    if search_count <= 2:
        pref_queries = _generate_preference_queries(dest, prefs, search_count)
        queries.extend(pref_queries)
    
    # ============ 人群定制补充 ============
    if search_count == 1:
        group_query = _generate_group_query(dest, group_type)
        if group_query:
            queries.append(group_query)
    
    # ============ 去重和过滤 ============
    seen = set(searched)
    unique_queries = []
    for q in queries:
        q_clean = q.strip()
        if q_clean and q_clean not in seen:
            unique_queries.append(q_clean)
            seen.add(q_clean)
    
    # 限制每轮查询数量
    max_queries = 3 if search_count <= 2 else 2
    return unique_queries[:max_queries]


def _get_categories_for_missing(missing_info: List[str]) -> List[SearchCategory]:
    """根据缺失信息确定搜索类别"""
    category_map = {
        "places": SearchCategory.ATTRACTION,
        "food": SearchCategory.FOOD,
        "transportation": SearchCategory.TRANSPORT,
        "accommodation": SearchCategory.ACCOMMODATION,
        "avoid": SearchCategory.AVOID,
        "routes": SearchCategory.ROUTE,
    }
    
    categories = []
    for info in missing_info:
        if info in category_map:
            categories.append(category_map[info])
    
    return categories[:2]  # 最多2个类别


def _get_categories_for_preferences(prefs: List[str]) -> List[SearchCategory]:
    """根据用户偏好确定搜索类别"""
    categories = set()
    
    for pref in prefs:
        pref_lower = pref.lower()
        for key, cats in PREFERENCE_CATEGORY_MAP.items():
            if key in pref_lower:
                categories.update(cats)
    
    return list(categories)[:2]


def _generate_preference_queries(dest: str, prefs: List[str], search_count: int) -> List[str]:
    """根据用户偏好生成查询"""
    queries = []
    
    pref_keywords = {
        "特种兵": ["一日游", "暴走攻略"],
        "休闲": ["慢游", "悠闲度假"],
        "深度": ["深度游", "小众景点"],
        "亲子": ["亲子游", "带娃攻略"],
        "情侣": ["情侣约会", "浪漫打卡"],
        "拍照": ["拍照圣地", "出片机位"],
        "美食": ["必吃榜", "地道美食"],
        "历史": ["历史古迹", "博物馆"],
    }
    
    for pref in prefs:
        pref_lower = pref.lower()
        for key, keywords in pref_keywords.items():
            if key in pref_lower:
                # 根据搜索轮次选择不同关键词
                idx = min(search_count - 1, len(keywords) - 1)
                queries.append(f"{dest} {keywords[idx]}")
                break
    
    return queries[:2]


def _generate_group_query(dest: str, group_type: str) -> str:
    """根据人群类型生成查询"""
    group_queries = {
        "family": f"{dest} 亲子游攻略",
        "couple": f"{dest} 情侣旅行",
        "friends": f"{dest} 闺蜜游",
        "solo": f"{dest} 一个人旅行",
        "elderly": f"{dest} 老年人旅游",
    }
    return group_queries.get(group_type, "")

# ============ 搜索节点 ============

def optimized_search_node(state: AgentState) -> AgentState:
    """
    优化的搜索节点
    - 按信息类型搜索
    - 支持根据缺失信息补充搜索
    """
    search_count = state.get("_search_count", 0) + 1
    state["_search_count"] = search_count
    
    print(f"\n--- 🔍 SEARCH NODE (第 {search_count} 轮) ---")
    
    user_profile = state["user_profile"]
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    searched_queries = state.get("_search_queries", [])
    missing_info = state.get("_missing_info", [])  # 从 check 节点传入
    
    # 初始化价值评估器
    evaluator = InformationValueEvaluator(
        destination=user_profile.destination,
        days=user_profile.days,
        preferences=user_profile.preferences
    )
    
    # 生成搜索关键词
    queries = _generate_smart_queries(
        user_profile, 
        search_count, 
        searched_queries,
        missing_info
    )
    
    if not queries:
        print("⚠️ 没有新的搜索关键词")
        return state
    
    # 打印搜索计划
    print(f"📝 本轮搜索:")
    for q in queries:
        print(f"   - {q}")
    
    search_tool = XiaohongshuSearchTool()
    all_notes = []
    
    for keyword in queries:
        # 检查缓存
        cached_notes = travel_cache.get_search_results(keyword)
        if cached_notes:
            all_notes.extend(cached_notes)
            print(f"  ✅ [缓存] {keyword}: {len(cached_notes)} 条")
            continue
        
        # 实际搜索
        try:
            res = search_tool._run(keyword=keyword)
            data = json.loads(res)
            
            if "error" not in data:
                notes = data.get("notes", [])
                all_notes.extend(notes)
                print(f"  ✅ [搜索] {keyword}: {len(notes)} 条")
                travel_cache.set_search_results(keyword, notes)
            else:
                print(f"  ⚠️ [失败] {keyword}: {data.get('error')}")
                
        except Exception as e:
            print(f"  ❌ [异常] {keyword}: {e}")
    
    # 价值评估和过滤
    if all_notes:
        filtered_notes = evaluator.filter_and_compress(
            all_notes,
            max_notes=budget.max_notes_per_search,
            max_chars_per_note=budget.max_note_length
        )
        
        print(f"\n📊 过滤: {len(all_notes)} → {len(filtered_notes)} 条")
        
        # 合并到现有笔记
        existing_notes = []
        if state.get("search_results") and state["search_results"].notes:
            existing_notes = list(state["search_results"].notes)
        
        # 去重合并
        existing_titles = {n.title for n in existing_notes}
        for note in filtered_notes:
            if note["title"] not in existing_titles:
                existing_notes.append(SearchNote(
                    title=note["title"],
                    content=note["content"],
                    likes=note.get("likes", 0),
                ))
                existing_titles.add(note["title"])
        
        state["search_results"] = SearchResult(notes=existing_notes)
    
    # 更新状态
    state["_search_queries"] = searched_queries + queries
    state["_missing_info"] = []  # 清空，等下一次 check 重新评估
    
    print(f"📚 累计笔记: {len(state.get('search_results', SearchResult(notes=[])).notes)} 条")
    
    return state


# ============ 优化的摘要节点 ============

SMART_SUMMARY_PROMPT = """你是一位旅行规划专家。请从以下小红书笔记中提取旅行规划的关键信息。

  【目的地】{destination}
  【天数】{days}天
  【用户偏好】{preferences}

  【笔记内容】
  {context}

  请提取并输出 JSON 格式的规划信息：

  ```json
  {{
    "destination": "{destination}",
    "recommended_days": "{days}天",
    "daily_routes": [
      {{
        "day": 1,
        "theme": "主题描述",
        "places": ["景点1", "景点2", "景点3"]
      }}
    ],
    "must_visit": [
      {{"name": "景点名", "reason": "推荐理由", "duration": "建议时长"}}
    ],
    "avoid": ["避坑事项1", "避坑事项2"],
    "transport_tips": ["交通建议1", "交通建议2"],
    "food_recommendations": ["美食推荐1", "美食推荐2"],
    "practical_tips": ["实用贴士1", "实用贴士2"]
  }}
  要求：
  只提取笔记中明确提到的信息
  保留具体的景点名称、时间、价格等细节
  避坑信息优先保留
  如果信息不足，对应字段可以为空数组"""


def optimized_summary_node(state: AgentState) -> AgentState:
    """
    优化的摘要节点
    - 使用轻量模型
    - 增量摘要
    - 合理的 token 控制
    """
    print("\n--- 📝 SUMMARY NODE ---")

    search_results = state.get("search_results")
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    user = state["user_profile"]

    if not search_results or not search_results.notes:
        print("⚠️ 无搜索结果")
        state["planning_rules"] = _create_minimal_rules(state)
        return state

    # 构建上下文
    context_parts = []
    total_chars = 0
    max_context_chars = budget.max_context_length

    for i, note in enumerate(search_results.notes):
        note_text = f"【笔记{i+1}】{note.title}\n{note.content}"
        
        
        print(f"note_text:{note_text}")
        if total_chars + len(note_text) > max_context_chars:
            print(f"  ⚠️ 达到上下文限制，使用 {i} 条笔记")
            break
        
        context_parts.append(note_text)
        total_chars += len(note_text)

    context = "\n\n---\n\n".join(context_parts)


    print(f"总字符数: {total_chars}")
    print(f"处理后的context内容:{context}")

    # 构建 prompt
    prompt = SMART_SUMMARY_PROMPT.format(
        destination=user.destination,
        days=user.days,
        preferences="、".join(user.preferences) if user.preferences else "无特殊偏好",
        context=context
    )

  

    # 🔥 使用轻量模型
    llm = LLMFactory.get_light_model()

    input_tokens = token_counter.count(prompt)
    print(f"📊 摘要输入: {input_tokens} tokens ({len(context_parts)} 条笔记)")

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        output_tokens = token_counter.count(response.content)
        budget.consume("summary", input_tokens + output_tokens)
        
        # 解析结果
        content = _extract_json(response.content)
        data = json.loads(content)
        print(f"解析后的 JSON 数据: {data}")
        # 标准化为 PlanningRules
        rules = _normalize_to_rules(data, state)
        print(f"标准化后的规划规则: {rules}")

        state["planning_rules"] = rules
        
        print(f"✅ 摘要完成 (消耗 {input_tokens + output_tokens} tokens)")
        print(f"   路线: {len(rules.daily_routes)} 天")
        print(f"   必去: {len(rules.must_visit)} 个")
        print(f"   避坑: {len(rules.avoid)} 条")
        
    except Exception as e:
        print(f"❌ 摘要解析失败: {e}")
        state["planning_rules"] = _create_minimal_rules(state)
        state["_warnings"] = state.get("_warnings", []) + [f"摘要解析失败: {e}"]

    state["_token_budget"] = budget
    return state



SMART_PLANNING_PROMPT = """你是一位专业的旅行规划师。请根据以下信息生成详细的{days}天{destination}旅行计划。

  【用户画像】

  出发地: {origin}
  人群类型: {group_type}
  偏好: {preferences}
  预算: {budget}
  【规划参考】
  {rules}

  【要求】

  1.每天安排 4-6 个活动，包含具体时间
  2.考虑景点之间的距离和交通
  3.合理安排用餐时间
  4.结合用户偏好和人群特点
  5.包含实用小贴士
  6.直接输出 JSON 格式：
  {{
    "overview": "行程概述（50字内）",
    "highlights": ["亮点1", "亮点2", "亮点3"],
    "days": [
      {{
        "day": 1,
        "date": "第一天",
        "theme": "主题",
        "schedule": [
          {{
            "time": "09:00",
            "poi": "景点名称",
            "activity": "活动描述",
            "duration": "2小时",
            "tips": "小贴士"
          }}
        ]
      }}
    ],
    "tips": {{
      "transport": "交通建议",
      "food": "美食推荐",
      "accommodation": "住宿建议",
      "budget": "预算参考",
      "avoid": ["注意事项1", "注意事项2"]
    }}
  }}
⚠️ 核心字段填写要求（POI 字段至关重要）
poi 字段（严格清洗规则）：
必须是纯名词：仅填写地图可定位的具体地点名称。
严禁包含动词/介词：绝对删除“前往”、“抵达”、“游览”、“参观”、“夜游”、“打卡”、“启程”、“返回”等词汇。
修正示例：
❌ "前往牛首山文化旅游区" -> ✅ "牛首山文化旅游区"
❌ "秦淮河夜游" -> ✅ "秦淮河"
❌ "启程返回杭州" -> ✅ "南京南站" (推荐填具体车站) 或 "杭州" (推荐填具体车站)
不要出现多地点的情况: "老门东 → 夫子庙 → 秦淮河夜游" 
overview 字段：必须是字符串。
duration 字段：必须填写具体时长（如"2小时"）。
activity 字段：将原本poi中的动作描述（如“夜游”、“乘船”、“返回”）移动到这里。
任务
请根据以上规则润色提供的行程数据，直接返回 JSON，不要添加额外解释。
请润色以下行程数据：
```"""
# ============ 优化的规划节点 ============
def optimized_planning_node(state: AgentState) -> AgentState:
    """
    优化的规划节点
    - 使用智能模型
    - 单次调用
    - 包含完整信息
    """
    print("\n--- 🗓️ PLANNING NODE ---")
    
    user = state["user_profile"]
    rules = state.get("planning_rules")
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    
    # 压缩规则
    rules_str = _compress_rules_for_planning(rules) if rules else "{}"
    
    prompt = SMART_PLANNING_PROMPT.format(
        days=user.days,
        destination=user.destination,
        origin=user.origin,
        group_type=user.group_type or "普通游客",
        preferences="、".join(user.preferences) if user.preferences else "无特殊偏好",
        budget=user.budget or "中等",
        rules=rules_str
    )
    
    # 🔥 使用智能模型
    llm = LLMFactory.get_smart_model()
    
    input_tokens = token_counter.count(prompt)
    print(f"📊 规划输入: {input_tokens} tokens")
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        output_tokens = token_counter.count(response.content)
        budget.consume("planning", input_tokens + output_tokens)
        
        content = _extract_json(response.content)
        plan = json.loads(content)
        state["draft_plan"] = plan
        
        print(f"✅ 规划完成 (消耗 {input_tokens + output_tokens} tokens)")
        print(f"   生成 {len(plan.get('days', []))} 天行程")
        
    except Exception as e:
        print(f"❌ 规划解析失败: {e}")
        state["draft_plan"] = _create_fallback_plan(user)
        state["_warnings"] = state.get("_warnings", []) + [f"规划解析失败: {e}"]
    
    state["_token_budget"] = budget
    return state


def _compress_rules_for_planning(rules: PlanningRules) -> str:
    """压缩规则用于规划"""
    compressed = {
        "routes": [],
        "must_visit": [],
        "avoid": [],
        "tips": []
    }
    
    # 路线信息
    if rules.daily_routes:
        for route in rules.daily_routes[:3]:
            if hasattr(route, 'day') and hasattr(route, 'places'):
                compressed["routes"].append({
                    "day": route.day,
                    "places": route.places[:5] if route.places else []
                })
    
    # 必去景点
    if rules.must_visit:
        for v in rules.must_visit[:8]:
            name = v.name if hasattr(v, 'name') else str(v)
            compressed["must_visit"].append(name)
    
    # 避坑
    if rules.avoid:
        compressed["avoid"] = rules.avoid[:5]
    
    # 交通建议
    if rules.transport_tips:
        compressed["tips"] = rules.transport_tips[:3]
    
    return json.dumps(compressed, ensure_ascii=False)


# ============ 优化的润色节点 ============

SMART_REFINE_PROMPT = """请优化以下旅行计划，使其更加完善和实用：

  {plan}

  优化要求：
  1. 确保时间安排合理
  2. 补充交通衔接建议
  3. 添加实用小贴士
  4. 保持 JSON 格式不变

  直接输出优化后的完整 JSON。"""


def optimized_refine_node(state: AgentState) -> AgentState:
    """
    优化的润色节点
    - 智能判断是否需要润色
    - 轻量级优化
    """
    print("\n--- ✨ REFINE NODE ---")
    
    plan = state.get("validated_plan") or state.get("draft_plan")
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    session_id = state.get("session_id", "")
    
    if not plan:
        print("⚠️ 无行程数据")
        state["final_result"] = _create_empty_result(state)
        return state
    
    # 检查预算
    remaining = budget.get_remaining("refine")
    if remaining < 1000:
        print(f"⚠️ 预算不足 ({remaining} tokens)，跳过润色")
        state["final_result"] = _plan_to_result(plan, state)
        _save_final_result(state)
        return state
    
    # 压缩 plan
    compressed_plan = json.dumps(plan, ensure_ascii=False)
    
    # 如果 plan 已经很完整，跳过润色
    if _is_plan_complete(plan):
        print("✅ 行程已完整，跳过润色")
        state["final_result"] = _plan_to_result(plan, state)
        _save_final_result(state)
        return state
    
    prompt = SMART_REFINE_PROMPT.format(plan=compressed_plan)
    
    # 🔥 使用轻量模型润色
    llm = LLMFactory.get_light_model()
    
    input_tokens = token_counter.count(prompt)
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        output_tokens = token_counter.count(response.content)
        budget.consume("refine", input_tokens + output_tokens)
        
        content = _extract_json(response.content)
        final_data = json.loads(content)
        state["final_result"] = _normalize_final_result(final_data, state)
        
        print(f"✅ 润色完成 (消耗 {input_tokens + output_tokens} tokens)")
        
    except Exception as e:
        print(f"⚠️ 润色失败，使用原始计划: {e}")
        state["final_result"] = _plan_to_result(plan, state)
    
    # 保存结果
    _save_final_result(state)
    
    # 打印消耗统计
    _print_token_summary(budget)
    
    state["_token_budget"] = budget
    return state


def _is_plan_complete(plan: dict) -> bool:
    """检查计划是否完整"""
    if "days" not in plan:
        return False
    
    days = plan["days"]
    if not days:
        return False
    
    # 检查是否每天都有行程
    for day in days:
        schedule = day.get("schedule", [])
        if len(schedule) < 3:
            return False
        
        # 检查是否有关键信息
        for item in schedule:
            if not item.get("poi") or not item.get("time"):
                return False
    
    return True


def _save_final_result(state: AgentState):
    """保存最终结果到 Redis"""
    from datetime import datetime
    
    session_id = state.get("session_id", "")
    if not session_id:
        return
    
    result = state.get("final_result")
    if not result:
        return
    
    # 转换结果
    if hasattr(result, 'model_dump'):
        result_dict = result.model_dump()
    elif hasattr(result, 'dict'):
        result_dict = result.dict()
    else:
        result_dict = result
    
    user = state.get("user_profile")
    budget = state.get("_token_budget")
    
    plan_data = {
        "plan": result_dict,
        "user_profile": user.model_dump() if hasattr(user, 'model_dump') else None,
        "meta": {
            "search_count": state.get("_search_count", 0),
            "token_consumed": budget.get_total_consumed() if budget else 0,
        },
        "generated_at": datetime.now().isoformat()
    }
    
    from src.services.redis_service import redis_service
    redis_service.save_plan(session_id, plan_data)
    redis_service.update_plan_status(session_id, status="completed", progress=100, message="完成")
    
    print(f"💾 结果已保存: {session_id[:8]}...")


def _print_token_summary(budget: TokenBudget):
    """打印 Token 消耗统计"""
    print(f"\n{'='*40}")
    print(f"📊 Token 消耗统计:")
    for stage, tokens in budget.consumed.items():
        print(f"   {stage}: {tokens} tokens")
    print(f"   ────────────────")
    print(f"   总计: {budget.get_total_consumed()} / {budget.total_budget} tokens")
    print(f"{'='*40}\n")


# ============ 辅助函数 ============

def _extract_json(content: str) -> str:
    """从响应中提取 JSON"""
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
    return content.strip()


def _create_minimal_rules(state: AgentState) -> PlanningRules:
    """创建最小规则"""
    user = state.get("user_profile")
    return PlanningRules(
        destination=user.destination if user else "",
        recommended_days=f"{user.days}天" if user else "3天",
        daily_routes=[],
        common_routes=[],
        must_visit=[],
        avoid=[],
        transport_tips=["建议使用公共交通"],
        practical_tips=["提前规划行程"],
    )


def _normalize_to_rules(data: dict, state: AgentState) -> PlanningRules:
    """标准化数据为 PlanningRules"""
    user = state.get("user_profile")
    
    # 处理 daily_routes
    daily_routes = []
    for route in data.get("daily_routes", []):
        if isinstance(route, dict):
            daily_routes.append(route)
    
    # 处理 must_visit
    must_visit = []
    for item in data.get("must_visit", []):
        if isinstance(item, str):
            must_visit.append({"name": item, "reason": "", "duration": ""})
        elif isinstance(item, dict):
            must_visit.append(item)
    
    return PlanningRules(
        destination=data.get("destination", user.destination if user else ""),
        recommended_days=data.get("recommended_days", f"{user.days}天" if user else "3天"),
        daily_routes=daily_routes,
        common_routes=[],
        must_visit=must_visit,
        avoid=data.get("avoid", []),
        transport_tips=data.get("transport_tips", []),
        practical_tips=data.get("practical_tips", data.get("food_recommendations", [])),
    )


def _create_fallback_plan(user) -> dict:
    """创建兜底计划"""
    return {
        "overview": f"{user.destination}{user.days}天精彩之旅",
        "highlights": [],
        "days": [
            {
                "day": i + 1,
                "date": f"第{i+1}天",
                "theme": f"Day {i+1}",
                "schedule": []
            }
            for i in range(user.days)
        ],
        "tips": {}
    }


def _plan_to_result(plan: dict, state: AgentState):
    """将 plan 转换为 TravelPlanResult"""
    from src.models.schemas import TravelPlanResult
    user = state.get("user_profile")
    
    return TravelPlanResult(
        destination=user.destination if user else "",
        overview=plan.get("overview", f"{user.destination if user else ''}精彩之旅"),
        highlights=plan.get("highlights", []),
        days=plan.get("days", []),
        tips=plan.get("tips", {})
    )


def _create_empty_result(state: AgentState):
    """创建空结果"""
    from src.models.schemas import TravelPlanResult
    user = state.get("user_profile")
    
    return TravelPlanResult(
        destination=user.destination if user else "",
        overview="行程生成中...",
        highlights=[],
        days=[],
        tips={}
    )


def _normalize_final_result(data: dict, state: AgentState):
    """标准化最终结果"""
    from src.models.schemas import TravelPlanResult
    user = state.get("user_profile")
    
    # 处理 tips
    tips = data.get("tips", {})
    if isinstance(tips, dict):
        # 确保 avoid 是列表
        if "avoid" in tips and isinstance(tips["avoid"], str):
            tips["avoid"] = [tips["avoid"]]
    
    return TravelPlanResult(
        destination=user.destination if user else "",
        overview=data.get("overview", ""),
        highlights=data.get("highlights", []),
        days=data.get("days", []),
        tips=tips
    )