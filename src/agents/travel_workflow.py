# src/agents/travel_workflow.py
import re
import json
from typing import List, Dict, Any,Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from src.agents.state import AgentState
from src.utils.token_budget import TokenBudget, token_counter
from src.utils.value_evaluator import InformationValueEvaluator
from src.models.schemas import SearchResult, SearchNote, TravelPlanResult
from src.tools.tools import XiaohongshuSearchTool
from src.models.llm import LLMFactory
from src.services.travel_cache import travel_cache
from src.services.multi_plan_store import multi_plan_store
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field




# 导入你的 LLM 工厂
from src.models.llm import LLMFactory, get_llm

# ==================== 搜索关键词结构化输出 ====================

class CoreSearchQueries(BaseModel):
    """第1轮核心搜索关键词"""
    route: List[str] = Field(
        description="路线规划相关搜索词，1-2个，如'XX 3天2晚行程安排'"
    )
    food: List[str] = Field(
        description="美食相关搜索词，1-2个，如'XX 必吃美食推荐'"
    )
    accommodation: List[str] = Field(
        description="住宿相关搜索词，1-2个，如'XX 住哪里方便'"
    )
    attraction: List[str] = Field(
        description="景点攻略相关搜索词，1-2个，如'XX 必去景点攻略'"
    )
    preference: List[str] = Field(
        default=[],
        description="根据用户偏好生成的额外搜索词，0-2个"
    )


class SupplementSearchQueries(BaseModel):
    """补充搜索关键词"""
    queries: List[str] = Field(
        description="补充搜索关键词列表，2-4个"
    )
    reasoning: str = Field(
        description="为什么选择这些关键词的简短说明"
    )


# ==================== 修复后的 Prompt 模板 ====================

CORE_SEARCH_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个旅游搜索专家，需要为用户生成小红书搜索关键词。

## 用户信息
- 目的地：{destination}
- 天数：{days}天
- 偏好：{preferences}
- 出行人数/类型：{travel_type}

## 任务
生成搜索关键词，**必须覆盖以下4个核心领域**：

1. **路线规划** (route)：如何安排每天行程
   - 示例：「成都3天2晚行程安排」「西安4日游路线」

2. **美食推荐** (food)：当地必吃美食
   - 示例：「成都必吃美食攻略」「本地人推荐的成都小吃」

3. **住宿推荐** (accommodation)：住在哪里方便
   - 示例：「成都住哪里方便」「春熙路附近酒店推荐」

4. **景点攻略** (attraction)：必去景点和玩法
   - 示例：「成都必去景点」「成都旅游攻略」

## 要求
- 关键词要**具体、接地气**，适合小红书搜索风格
- 每个领域生成 **1-2个** 关键词
- 关键词必须包含**目的地名称**
- 如果用户有特殊偏好，在 preference 中生成相关关键词

## 输出格式
请以 JSON 格式返回结果。"""),
    ("human", "请生成搜索关键词，确保覆盖路线、美食、住宿、景点这4个核心领域。请返回JSON格式。")
])


SUPPLEMENT_SEARCH_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一个旅游搜索专家，需要为用户生成**补充搜索关键词**。

## 用户信息
- 目的地：{destination}
- 天数：{days}天
- 偏好：{preferences}

## 已搜索过的关键词
{searched_queries}

## 当前缺失/不足的信息
{missing_info}

## 任务
针对缺失的信息，生成更**具体、精准**的补充搜索关键词。

## 信息类型说明
- places: 景点信息不足 → 搜「XX 小众景点」「XX 景点详细攻略」
- food: 美食信息不足 → 搜「XX 美食街」「XX 本地人推荐餐厅」
- accommodation: 住宿信息不足 → 搜「XX 酒店民宿推荐」「XX 住宿攻略」
- transportation: 交通信息不足 → 搜「XX 交通攻略」「XX 怎么去」
- route: 路线信息不足 → 搜「XX 行程规划」「XX 几日游安排」
- avoid: 避坑信息不足 → 搜「XX 避坑指南」「XX 旅游注意事项」
- tips: 实用信息不足 → 搜「XX 旅游必备」「XX 花费预算」

## 要求
- **不要重复**已搜索的关键词
- 关键词要比之前更**具体、更有针对性**
- 生成 **2-4个** 关键词
- 关键词必须包含目的地名称

## 输出格式
请以 JSON 格式返回结果。"""),
    ("human", "请生成补充搜索关键词，返回JSON格式。")
])


# ==================== LLM 关键词生成器 ====================

class LLMSearchQueryGenerator:
    """
    LLM驱动的搜索关键词生成器
    
    使用 LLMFactory 获取模型实例，支持多提供商
    """
    
    def __init__(self, model_type: str = "light"):
        """
        初始化生成器
        
        Args:
            model_type: 模型类型 "light" | "smart" | "default"
        """
        self.model_type = model_type
        self._llm = None
        self._core_chain = None
        self._supplement_chain = None
    
    @property
    def llm(self):
        """懒加载 LLM 实例"""
        if self._llm is None:
            self._llm = LLMFactory.get(self.model_type)
            print(f"🔍 搜索关键词生成器使用 [{self.model_type}] 模型")
        return self._llm
    
    @property
    def core_chain(self):
        """懒加载核心搜索 Chain"""
        if self._core_chain is None:
            # 使用 method="json_mode" 确保兼容性
            self._core_chain = CORE_SEARCH_PROMPT | self.llm.with_structured_output(
                CoreSearchQueries,
                method="json_mode"  # 明确指定 JSON 模式
            )
        return self._core_chain
    
    @property
    def supplement_chain(self):
        """懒加载补充搜索 Chain"""
        if self._supplement_chain is None:
            self._supplement_chain = SUPPLEMENT_SEARCH_PROMPT | self.llm.with_structured_output(
                SupplementSearchQueries,
                method="json_mode"
            )
        return self._supplement_chain
    
    def generate_core_queries(
        self,
        destination: str,
        days: int,
        preferences: List[str] = None,
        travel_type: str = None
    ) -> List[str]:
        """
        生成第1轮核心搜索关键词
        确保覆盖：路线、美食、住宿、景点
        """
        preferences = preferences or []
        travel_type = travel_type or "自由行"
        
        try:
            result: CoreSearchQueries = self.core_chain.invoke({
                "destination": destination,
                "days": days,
                "preferences": "、".join(preferences) if preferences else "无特殊偏好",
                "travel_type": travel_type,
            })
            
            # 合并所有类别的关键词
            all_queries = []
            all_queries.extend(result.route[:2])
            all_queries.extend(result.food[:2])
            all_queries.extend(result.accommodation[:2])
            all_queries.extend(result.attraction[:2])
            all_queries.extend(result.preference[:2])
            
            # 去重
            seen = set()
            unique_queries = []
            for q in all_queries:
                if q and q not in seen:
                    unique_queries.append(q)
                    seen.add(q)
            
            print(f"   ✅ LLM生成 {len(unique_queries)} 个核心关键词")
            return unique_queries
            
        except Exception as e:
            print(f"⚠️ LLM生成关键词失败: {e}")
            return self._fallback_core_queries(destination, days)
    
    def generate_supplement_queries(
        self,
        destination: str,
        days: int,
        preferences: List[str] = None,
        searched_queries: List[str] = None,
        missing_info: List[str] = None
    ) -> List[str]:
        """生成补充搜索关键词"""
        preferences = preferences or []
        searched_queries = searched_queries or []
        missing_info = missing_info or ["avoid", "tips"]
        
        try:
            result: SupplementSearchQueries = self.supplement_chain.invoke({
                "destination": destination,
                "days": days,
                "preferences": "、".join(preferences) if preferences else "无特殊偏好",
                "searched_queries": "\n".join(f"- {q}" for q in searched_queries) or "无",
                "missing_info": "、".join(missing_info),
            })
            
            print(f"   💡 LLM思路: {result.reasoning}")
            
            searched_set = set(searched_queries)
            unique_queries = [q for q in result.queries if q not in searched_set]
            
            return unique_queries[:4]
            
        except Exception as e:
            print(f"⚠️ LLM生成补充关键词失败: {e}")
            return self._fallback_supplement_queries(destination, missing_info)
    
    def _fallback_core_queries(self, destination: str, days: int) -> List[str]:
        """降级方案"""
        print("   ⚠️ 使用降级模板")
        return [
            f"{destination} {days}天旅游攻略",
            f"{destination} 美食推荐",
            f"{destination} 住宿攻略",
            f"{destination} 必去景点",
        ]
    
    def _fallback_supplement_queries(self, destination: str, missing_info: List[str]) -> List[str]:
        """降级方案"""
        templates = {
            "places": f"{destination} 景点推荐",
            "food": f"{destination} 本地美食",
            "accommodation": f"{destination} 酒店推荐",
            "transportation": f"{destination} 交通攻略",
            "route": f"{destination} 行程安排",
            "avoid": f"{destination} 避坑指南",
            "tips": f"{destination} 旅游注意事项",
        }
        return [templates.get(info, f"{destination} 旅游攻略") for info in missing_info[:3]]


# ==================== 全局实例 ====================

_query_generator: Optional[LLMSearchQueryGenerator] = None

def get_query_generator(model_type: str = "light") -> LLMSearchQueryGenerator:
    global _query_generator
    if _query_generator is None or _query_generator.model_type != model_type:
        _query_generator = LLMSearchQueryGenerator(model_type=model_type)
    return _query_generator


def reset_query_generator():
    """重置生成器（用于测试或重新加载配置）"""
    global _query_generator
    _query_generator = None
    print("🔄 搜索关键词生成器已重置")


def search_node(state: AgentState) -> AgentState:
    """
    搜索节点
    
    第1轮: 使用 LLM 生成核心搜索关键词（路线、美食、住宿、景点）
    第2轮+: 根据缺失信息，使用 LLM 生成补充搜索关键词
    """
    search_count = state.get("_search_count", 0) + 1
    state["_search_count"] = search_count
    
    print(f"\n{'='*50}")
    print(f"🔍 SEARCH NODE (第 {search_count} 轮)")
    print(f"{'='*50}")
    
    user: UserProfile = state["user_profile"]
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    searched: List[str] = state.get("_searched_queries", [])
    missing: List[str] = state.get("_missing_info", [])
    
    # 获取 LLM 关键词生成器
    query_generator = get_query_generator(model_type="light")
    
    # 根据搜索轮次生成不同的关键词
    if search_count == 1:
        # 第1轮：核心搜索
        print("🎯 目标: 核心信息（路线 + 美食 + 住宿 + 景点）")
        
        # 推断出行类型
        travel_type = _infer_travel_type(user.preferences)
        
        queries = query_generator.generate_core_queries(
            destination=user.destination,
            days=user.days,
            preferences=user.preferences,
            travel_type=travel_type
        )
    else:
        # 第2轮+：补充搜索
        if missing:
            print(f"🎯 目标: 补充缺失信息 {missing}")
        else:
            print("🎯 目标: 补充搜索（避坑 + 实用信息）")
            missing = ["avoid", "tips"]  # 默认补充避坑和实用信息
        
        queries = query_generator.generate_supplement_queries(
            destination=user.destination,
            days=user.days,
            preferences=user.preferences,
            searched_queries=searched,
            missing_info=missing
        )
    
    if not queries:
        print("⚠️ 没有新的搜索关键词")
        return state
    
    print(f"\n📝 搜索关键词:")
    for q in queries:
        print(f"   • {q}")
    
    # 创建评估器
    evaluator = InformationValueEvaluator(
        destination=user.destination,
        days=user.days,
        preferences=user.preferences
    )
    
    search_tool = XiaohongshuSearchTool()
    all_notes = []
    
    print(f"\n🔎 执行搜索:")
    for keyword in queries:
        # 检查缓存
        cached = travel_cache.get_search_results(keyword)
        if cached:
            all_notes.extend(cached)
            print(f"   ✅ [缓存] {keyword}: {len(cached)} 条")
            continue
        
        # 实际搜索
        try:
            res = search_tool._run(keyword=keyword)
            data = json.loads(res)
            
            if "error" not in data:
                notes = data.get("notes", [])
                all_notes.extend(notes)
                travel_cache.set_search_results(keyword, notes)
                print(f"   ✅ [搜索] {keyword}: {len(notes)} 条")
            else:
                print(f"   ⚠️ [失败] {keyword}: {data.get('error', '未知错误')}")
        except Exception as e:
            print(f"   ❌ [异常] {keyword}: {e}")
    
    # 过滤和评估
    if all_notes:
        print(f"\n📊 笔记评估:")
        print(f"   原始数量: {len(all_notes)}")
        
        filtered = evaluator.filter_and_compress(
            all_notes,
            max_notes=budget.max_notes_per_search,
            max_chars_per_note=budget.max_note_length
        )
        
        print(f"   筛选后: {len(filtered)} 条")
        
        # 打印筛选结果
        for note in filtered[:3]:
            print(f"   • [{note.get('score', 0):.2f}] {note['title'][:40]}...")
        
        # 合并到现有笔记（去重）
        existing = []
        existing_titles = set()
        
        if state.get("search_results") and state["search_results"].notes:
            for n in state["search_results"].notes:
                existing.append(n)
                existing_titles.add(n.title)
        
        new_count = 0
        for note in filtered:
            if note["title"] not in existing_titles:
                existing.append(SearchNote(
                    title=note["title"],
                    content=note["content"],
                    likes=note.get("likes", 0),
                ))
                existing_titles.add(note["title"])
                new_count += 1
        
        print(f"   新增笔记: {new_count} 条")
        
        state["search_results"] = SearchResult(notes=existing)
    
    # 更新状态
    state["_searched_queries"] = searched + queries
    state["_missing_info"] = []  # 清空，等 check 节点重新评估
    
    print(f"\n📚 累计笔记: {len(state.get('search_results', SearchResult(notes=[])).notes)} 条")
    
    return state


def _infer_travel_type(preferences: List[str]) -> str:
    """根据用户偏好推断出行类型"""
    if not preferences:
        return "自由行"
    
    prefs_lower = [p.lower() for p in preferences]
    prefs_text = " ".join(prefs_lower)
    
    if any(keyword in prefs_text for keyword in ["亲子", "带娃", "儿童", "孩子", "宝宝"]):
        return "亲子游"
    elif any(keyword in prefs_text for keyword in ["情侣", "约会", "蜜月", "浪漫", "两个人"]):
        return "情侣游"
    elif any(keyword in prefs_text for keyword in ["闺蜜", "朋友", "好友"]):
        return "闺蜜/朋友游"
    elif any(keyword in prefs_text for keyword in ["一个人", "独自", "solo"]):
        return "独自旅行"
    elif any(keyword in prefs_text for keyword in ["家庭", "全家", "父母", "老人"]):
        return "家庭游"
    else:
        return "自由行"





# # ==================== 搜索模板配置 ====================

# # 核心搜索模板（第1轮必搜）
# CORE_SEARCH_TEMPLATES = [
#     "{dest} {days}天旅游攻略",
#     "{dest} 旅游路线推荐",
#     "{dest} 美食攻略",
#     "{dest} 住宿推荐",
# ]

# # 补充搜索模板（按类别）
# SUPPLEMENT_TEMPLATES = {
#     "places": [
#         "{dest} 必去景点",
#         "{dest} 景点推荐攻略",
#     ],
#     "food": [
#         "{dest} 必吃美食推荐",
#         "{dest} 本地人推荐美食",
#         "{dest} 美食街",
#     ],
#     "transportation": [
#         "{dest} 交通攻略",
#         "{dest} 怎么去 地铁公交",
#     ],
#     "accommodation": [
#         "{dest} 住哪里方便",
#         "{dest} 酒店民宿推荐",
#     ],
#     "avoid": [
#         "{dest} 避坑指南",
#         "{dest} 旅游注意事项",
#     ],
# }

# # 偏好关键词映射
# PREFERENCE_KEYWORDS = {
#     "特种兵": ["暴走攻略", "一日游"],
#     "休闲": ["慢游", "悠闲度假"],
#     "亲子": ["亲子游", "带娃攻略"],
#     "情侣": ["情侣约会", "浪漫打卡"],
#     "拍照": ["拍照圣地", "出片机位"],
#     "美食": ["必吃榜", "地道美食"],
#     "历史": ["历史古迹", "博物馆"],
#     "深度": ["深度游", "小众景点"],
# }


# #==================== 搜索关键词生成 ====================
# def _generate_search_queries(
#     user_profile,
#     search_count: int,
#     searched: List[str],
#     missing_info: List[str] = None
# ) -> List[str]:
#     """
#     生成搜索关键词
    
#     策略:
#     - 第1轮: 核心搜索（路线 + 美食 + 住宿）
#     - 第2轮+: 根据缺失信息补充
#     """
#     dest = user_profile.destination
#     days = user_profile.days
#     prefs = user_profile.preferences or []
#     missing_info = missing_info or []
    
#     queries = []
    
#     if search_count == 1:
#         # ========== 第1轮: 核心搜索 ==========
#         for template in CORE_SEARCH_TEMPLATES:
#             query = template.format(dest=dest, days=days)
#             queries.append(query)
        
#         # 添加偏好相关搜索
#         for pref in prefs[:2]:  # 最多2个偏好
#             pref_lower = pref.lower()
#             for key, keywords in PREFERENCE_KEYWORDS.items():
#                 if key in pref_lower:
#                     queries.append(f"{dest} {keywords[0]}")
#                     break
    
#     else:
#         # ========== 第2轮+: 补充搜索 ==========
#         if missing_info:
#             for info_type in missing_info:
#                 templates = SUPPLEMENT_TEMPLATES.get(info_type, [])
#                 for template in templates[:2]:  # 每个类别最多2个
#                     query = template.format(dest=dest, days=days)
#                     queries.append(query)
#         else:
#             # 没有明确缺失，补充避坑信息
#             for template in SUPPLEMENT_TEMPLATES.get("avoid", []):
#                 query = template.format(dest=dest, days=days)
#                 queries.append(query)
    
#     # ========== 去重过滤 ==========
#     seen = set(searched)
#     unique = []
#     for q in queries:
#         q = q.strip()
#         if q and q not in seen:
#             unique.append(q)
#             seen.add(q)
    
#     # 第1轮多搜一些，后续轮次少搜
#     max_queries = 4 if search_count == 1 else 3
#     return unique[:max_queries]



# ==================== 搜索节点 ====================

# def search_node(state: AgentState) -> AgentState:
#     """
#     搜索节点
    
#     第1轮: 搜索核心信息（路线、美食、住宿）
#     第2轮+: 根据缺失信息补充搜索
#     """
#     search_count = state.get("_search_count", 0) + 1
#     state["_search_count"] = search_count
    
#     print(f"\n{'='*50}")
#     print(f"🔍 SEARCH NODE (第 {search_count} 轮)")
#     print(f"{'='*50}")
    
#     user = state["user_profile"]
#     budget: TokenBudget = state.get("_token_budget") or TokenBudget()
#     searched = state.get("_searched_queries", [])
#     missing = state.get("_missing_info", [])
    
#     # 打印搜索目标
#     if search_count == 1:
#         print("🎯 目标: 核心信息（路线 + 美食 + 住宿）")
#     elif missing:
#         print(f"🎯 目标: 补充缺失信息 {missing}")
#     else:
#         print("🎯 目标: 补充搜索")
    
#     # 生成搜索关键词
#     queries = _generate_search_queries(user, search_count, searched, missing)
    
#     if not queries:
#         print("⚠️ 没有新的搜索关键词")
#         return state
    
#     print(f"\n📝 搜索关键词:")
#     for q in queries:
#         print(f"   • {q}")
    
#     # 创建评估器
#     evaluator = InformationValueEvaluator(
#         destination=user.destination,
#         days=user.days,
#         preferences=user.preferences
#     )
    
#     search_tool = XiaohongshuSearchTool()
#     all_notes = []
    
#     print(f"\n🔎 执行搜索:")
#     for keyword in queries:
#         # 检查缓存
#         cached = travel_cache.get_search_results(keyword)
#         if cached:
#             all_notes.extend(cached)
#             print(f"   ✅ [缓存] {keyword}: {len(cached)} 条")
#             continue
        
#         # 实际搜索
#         try:
#             res = search_tool._run(keyword=keyword)
#             data = json.loads(res)
            
#             if "error" not in data:
#                 notes = data.get("notes", [])
#                 all_notes.extend(notes)
#                 travel_cache.set_search_results(keyword, notes)
#                 print(f"   ✅ [搜索] {keyword}: {len(notes)} 条")
#             else:
#                 print(f"   ⚠️ [失败] {keyword}: {data.get('error', '未知错误')}")
#         except Exception as e:
#             print(f"   ❌ [异常] {keyword}: {e}")
    
#     # 过滤和评估
#     if all_notes:
#         print(f"\n📊 笔记评估:")
#         print(f"   原始数量: {len(all_notes)}")
        
#         filtered = evaluator.filter_and_compress(
#             all_notes,
#             max_notes=budget.max_notes_per_search,
#             max_chars_per_note=budget.max_note_length
#         )
        
#         print(f"   筛选后: {len(filtered)} 条")
        
#         # 打印筛选结果
#         for note in filtered[:3]:
#             print(f"   • [{note.get('score', 0):.2f}] {note['title'][:40]}...")
        
#         # 合并到现有笔记（去重）
#         existing = []
#         existing_titles = set()
        
#         if state.get("search_results") and state["search_results"].notes:
#             for n in state["search_results"].notes:
#                 existing.append(n)
#                 existing_titles.add(n.title)
        
#         new_count = 0
#         for note in filtered:
#             if note["title"] not in existing_titles:
#                 existing.append(SearchNote(
#                     title=note["title"],
#                     content=note["content"],
#                     likes=note.get("likes", 0),
#                 ))
#                 existing_titles.add(note["title"])
#                 new_count += 1
        
#         print(f"   新增笔记: {new_count} 条")
        
#         state["search_results"] = SearchResult(notes=existing)
    
#     # 更新状态
#     state["_searched_queries"] = searched + queries
#     state["_missing_info"] = []  # 清空，等 check 节点重新评估
    
#     print(f"\n📚 累计笔记: {len(state.get('search_results', SearchResult(notes=[])).notes)} 条")
    
#     return state

# ==================== 提取节点 ====================

# ==================== 提取提示词 ====================

EXTRACT_PROMPT = """你是信息提取专家。请从以下小红书笔记中提取旅行相关信息。

    【目的地】{destination}
    【笔记内容】
    {context}

    请输出 JSON，**只填写笔记中明确提到的信息，没有的字段省略**：

    ```json
    {{
      "routes": [
        {{
          "source": "笔记来源标识（如：笔记1）",
          "days": 3,
          "description": "路线简述（如：经典3日游）",
          "daily_plan": [
            {{
              "day": 1,
              "theme": "主题（如有）",
              "places": ["景点1", "景点2", "景点3"]
            }},
            {{
              "day": 2,
              "theme": "主题（如有）",
              "places": ["景点4", "景点5"]
            }}
          ]
        }}
      ],
      
      "places": [
        {{
          "name": "景点名",
          "open_time": "开放时间（如有）",
          "closed_day": "闭馆日（如：周一闭馆）",
          "ticket": "门票价格（如有）",
          "duration": "建议游玩时长（如有）",
          "tips": "游玩提示（如有）",
          "need_booking": "是否需要预约（如有）"
        }}
      ],
      
      "transportation": {{
        "arrival": "到达交通（如：南京南站，地铁1号线便捷）",
        "local": ["市内交通建议1", "建议2"]
      }},
      "accommodation": {{
        "recommended_areas": [
          {{
            "area": "区域名称（如：新街口）",
            "reasons": ["原因1", "原因2", "原因3"],
            "nearby": ["周边设施/景点"],
            "transport": "交通便利性描述",
            "price_range": "价格区间（如有）"
          }}
        ],
        "tips": ["住宿相关建议"],
      }},
      "food": {{
        "specialties": [
          {{"name": "美食名", "description": "描述（如有）"}}
        ],
        "restaurants": [
          {{"name": "店名", "type": "类型（早餐/午餐等）", "specialty": "招牌菜"}}
        ],
        "streets": [
          {{"name": "美食街名", "location": "位置", "features": "特色"}}
        ]
      }},
      
      "avoid": [
        {{"item": "避坑事项", "reason": "原因（如有）"}}
      ],
      
      "tips": ["实用贴士1", "贴士2"]
    }}
    提取原则：
    ✅ 路线信息最重要：完整保留笔记中的 DAY1/DAY2/DAY3 等路线规划
    ✅ 住宿信息要详细：保留推荐原因、周边配套、交通便利性等
    ✅ 保留具体信息：价格、时间、地址
    ✅ 景点详情单独提取，方便后续补充到路线中
    ✅ 没提到的字段直接省略
    ❌ 不要编造信息
    ❌ 不要修改原始路线顺序"""

def extract_node(state: AgentState) -> AgentState:
    """提取节点 - 只提取信息，不生成路线"""
    print(f"\n{'='*50}")
    print(f"📋 EXTRACT NODE")
    print(f"{'='*50}")

    search_results = state.get("search_results")
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()
    user = state["user_profile"]

    if not search_results or not search_results.notes:
        print("⚠️ 无搜索结果")
        state["extracted_info"] = {}
        return state

    # 构建上下文
    context_parts = []
    for i, note in enumerate(search_results.notes):
        text = f"【笔记{i+1}】{note.title}\n{note.content}"
        context_parts.append(text)

    context = "\n\n---\n\n".join(context_parts)

    prompt = EXTRACT_PROMPT.format(
        destination=user.destination,
        context=context
    )

    llm = LLMFactory.get_light_model()
    input_tokens = token_counter.count(prompt)

    print(f"📊 输入: {input_tokens} tokens ({len(context_parts)} 条笔记)")
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        output_tokens = token_counter.count(response.content)
        budget.consume("extract", input_tokens + output_tokens)
        
        # ✅ 使用安全解析
        extracted = _safe_parse_json(response.content, default={})
        
        if not extracted:
            print("⚠️ JSON 解析返回空结果")
        else:
            print(f"📝 提取成功: {len(extracted.get('places', []))} 个景点")

        # 合并到现有提取信息
        existing = state.get("extracted_info") or {}
        merged = _merge_extracted_info(existing, extracted)
        
        state["extracted_info"] = merged
        
        print(f"✅ 提取完成 ({input_tokens + output_tokens} tokens)")
        _print_extracted_summary(merged)
        
    except Exception as e:
        print(f"❌ 提取失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 保留现有信息或设为空
        if not state.get("extracted_info"):
            state["extracted_info"] = {}

    state["_token_budget"] = budget
    return state

def _merge_extracted_info(existing: dict, new: dict) -> dict:
    """
    合并提取信息（去重）
    """
    # ✅ 添加空值保护
    if existing is None:
        existing = {}
    if new is None:
        new = {}
    merged = existing.copy()
    
    # ==================== 合并路线 ====================
    existing_routes = merged.get("routes", [])
    new_routes = new.get("routes", [])
    
    existing_keys = {
        (r.get("source", ""), r.get("days", 0)) 
        for r in existing_routes
    }
    
    for route in new_routes:
        key = (route.get("source", ""), route.get("days", 0))
        if key not in existing_keys:
            existing_routes.append(route)
            existing_keys.add(key)
    
    merged["routes"] = existing_routes
    
    # ==================== 合并景点 ====================
    existing_places = {p.get("name"): p for p in merged.get("places", [])}
    for place in new.get("places", []):
        name = place.get("name")
        if name:
            if name in existing_places:
                for k, v in place.items():
                    if v and not existing_places[name].get(k):
                        existing_places[name][k] = v
            else:
                existing_places[name] = place
    merged["places"] = list(existing_places.values())
    
    # ==================== 合并交通 ====================
    if new.get("transportation"):
        if merged.get("transportation"):
            if new["transportation"].get("arrival"):
                existing_arrival = merged["transportation"].get("arrival", "")
                new_arrival = new["transportation"].get("arrival", "")
                if len(new_arrival) > len(existing_arrival):
                    merged["transportation"]["arrival"] = new_arrival
            
            if new["transportation"].get("local"):
                existing_local = set(merged["transportation"].get("local", []))
                new_local = new["transportation"].get("local", [])
                if isinstance(new_local, list):
                    existing_local.update(new_local)
                elif isinstance(new_local, str):
                    existing_local.add(new_local)
                merged["transportation"]["local"] = list(existing_local)
        else:
            merged["transportation"] = new["transportation"]
    
    # ==================== 合并住宿 ====================
    if new.get("accommodation"):
        if not merged.get("accommodation"):
            merged["accommodation"] = {
                "recommended_areas": [],
                "tips": []
            }
        
        existing_acc = merged["accommodation"]
        new_acc = new["accommodation"]
        
        # --- 合并推荐区域 ---
        existing_areas = existing_acc.get("recommended_areas", [])
        new_areas = new_acc.get("recommended_areas", [])
        
        existing_area_map = {a.get("area"): a for a in existing_areas if a.get("area")}
        
        for area in new_areas:
            area_name = area.get("area")
            if not area_name:
                continue
                
            if area_name in existing_area_map:
                existing_area = existing_area_map[area_name]
                
                # 合并原因
                existing_reasons = set(existing_area.get("reasons", []))
                new_reasons = area.get("reasons", [])
                if isinstance(new_reasons, list):
                    existing_reasons.update(new_reasons)
                existing_area["reasons"] = list(existing_reasons)
                
                # 合并周边
                existing_nearby = set(existing_area.get("nearby", []))
                new_nearby = area.get("nearby", [])
                if isinstance(new_nearby, list):
                    existing_nearby.update(new_nearby)
                existing_area["nearby"] = list(existing_nearby)
                
                # 补充其他字段
                for key in ["transport", "price_range"]:
                    if area.get(key) and not existing_area.get(key):
                        existing_area[key] = area[key]
            else:
                existing_areas.append(area)
                existing_area_map[area_name] = area
        
        existing_acc["recommended_areas"] = existing_areas
        
        # --- 合并住宿 tips ---
        existing_tips = set(existing_acc.get("tips", []))
        new_tips = new_acc.get("tips", [])
        if isinstance(new_tips, list):
            existing_tips.update(new_tips)
        existing_acc["tips"] = list(existing_tips)
        
        merged["accommodation"] = existing_acc
    
    # ==================== 合并美食 ====================
    if new.get("food"):
        if not merged.get("food"):
            merged["food"] = {
                "specialties": [],
                "restaurants": [],
                "streets": []
            }
        
        existing_food = merged["food"]
        new_food = new["food"]
        
        # 合并特色美食
        existing_specialties = existing_food.get("specialties", [])
        new_specialties = new_food.get("specialties", [])
        existing_names = set()
        for s in existing_specialties:
            if isinstance(s, dict):
                existing_names.add(s.get("name", ""))
            elif isinstance(s, str):
                existing_names.add(s)
        
        for item in new_specialties:
            name = item.get("name", "") if isinstance(item, dict) else str(item)
            if name and name not in existing_names:
                existing_specialties.append(item)
                existing_names.add(name)
        existing_food["specialties"] = existing_specialties
        
        # 合并餐厅
        existing_restaurants = existing_food.get("restaurants", [])
        new_restaurants = new_food.get("restaurants", [])
        existing_names = {r.get("name") for r in existing_restaurants if isinstance(r, dict) and r.get("name")}
        
        for item in new_restaurants:
            if isinstance(item, dict) and item.get("name") and item.get("name") not in existing_names:
                existing_restaurants.append(item)
                existing_names.add(item.get("name"))
        existing_food["restaurants"] = existing_restaurants
        
        # 合并美食街
        existing_streets = existing_food.get("streets", [])
        new_streets = new_food.get("streets", [])
        existing_names = set()
        for s in existing_streets:
            if isinstance(s, dict):
                existing_names.add(s.get("name", ""))
            elif isinstance(s, str):
                existing_names.add(s)
        
        for item in new_streets:
            name = item.get("name", "") if isinstance(item, dict) else str(item)
            if name and name not in existing_names:
                existing_streets.append(item)
                existing_names.add(name)
        existing_food["streets"] = existing_streets
        
        merged["food"] = existing_food
    
    # ==================== 合并避坑 ====================
    existing_avoid = merged.get("avoid", [])
    new_avoid = new.get("avoid", [])
    existing_items = set()
    for a in existing_avoid:
        if isinstance(a, dict):
            existing_items.add(a.get("item", ""))
        elif isinstance(a, str):
            existing_items.add(a)
    
    for item in new_avoid:
        item_text = item.get("item", "") if isinstance(item, dict) else str(item)
        if item_text and item_text not in existing_items:
            existing_avoid.append(item)
            existing_items.add(item_text)
    merged["avoid"] = existing_avoid
    
    # ==================== 合并贴士 ====================
    existing_tips = set(merged.get("tips", []))
    new_tips = new.get("tips", [])
    if isinstance(new_tips, list):
        existing_tips.update(new_tips)
    merged["tips"] = list(existing_tips)
    
    return merged

def _print_extracted_summary(extracted: dict):
    """打印提取摘要"""
    routes = extracted.get("routes", [])
    places = extracted.get("places", [])
    food = extracted.get("food", {})
    accommodation = extracted.get("accommodation", {})
    
    print(f"\n📊 提取结果:")
    
    # 路线
    print(f"   🗺️ 路线: {len(routes)} 条")
    for i, route in enumerate(routes[:3]):
        days = route.get("days", "?")
        desc = route.get("description", "")[:25]
        daily_plan = route.get("daily_plan", [])
        print(f"      {i+1}. {days}天 - {desc} ({len(daily_plan)}天计划)")
    
    # 景点
    print(f"   📍 景点: {len(places)} 个")
    detailed = [p for p in places if p.get("ticket") or p.get("open_time")]
    if detailed:
        print(f"      (其中 {len(detailed)} 个有详细信息)")
    
    # 美食
    if isinstance(food, dict):
        specialties_count = len(food.get("specialties", []))
        restaurants_count = len(food.get("restaurants", []))
        streets_count = len(food.get("streets", []))
        print(f"   🍜 美食: {specialties_count}种特色 + {restaurants_count}家餐厅 + {streets_count}条美食街")
    else:
        print(f"   🍜 美食: 无")
    
    # 住宿
    if isinstance(accommodation, dict):
        areas = accommodation.get("recommended_areas", [])
        tips = accommodation.get("tips", [])
        
        print(f"   🏨 住宿: {len(areas)}个区域, {len(tips)}条建议")
        
        for area in areas[:2]:
            area_name = area.get("area", "未知")
            reasons = area.get("reasons", [])[:3]
            print(f"      • {area_name}: {', '.join(reasons)}")
    else:
        print(f"   🏨 住宿: 无")
    
    # 交通
    transportation = extracted.get("transportation", {})
    if transportation:
        arrival = transportation.get("arrival", "")[:30] if transportation.get("arrival") else ""
        local_count = len(transportation.get("local", []))
        print(f"   🚗 交通: 到达-{arrival}..., 市内{local_count}条建议")
    else:
        print(f"   🚗 交通: 无")
    
    # 避坑和贴士
    print(f"   ⚠️ 避坑: {len(extracted.get('avoid', []))} 条")
    print(f"   💡 贴士: {len(extracted.get('tips', []))} 条")



def check_info_quality(state: AgentState) -> str:
    """检查信息质量，决定是否继续搜索"""
    print(f"\n{'─'*50}")
    print(f"🔎 CHECK INFO QUALITY")
    print(f"{'─'*50}")
    
    search_count = state.get("_search_count", 0)
    max_searches = state.get("_max_searches", 3)
    
    if search_count >= max_searches:
        print(f"⚠️ 已达最大搜索次数 ({max_searches})")
        return "enough"
    
    extracted = state.get("extracted_info", {})
    missing = []
    
    # 1. 路线信息
    routes = extracted.get("routes", [])
    valid_routes = [r for r in routes if r.get("daily_plan")]
    if len(valid_routes) < 1:
        missing.append("places")
        print(f"   🗺️ 路线: {len(routes)}条 (有效:{len(valid_routes)}) ❌")
    else:
        print(f"   🗺️ 路线: {len(routes)}条 (有效:{len(valid_routes)}) ✅")
    
    # 2. 景点信息
    places = extracted.get("places", [])
    if len(places) < 3 and len(valid_routes) < 1:
        if "places" not in missing:
            missing.append("places")
        print(f"   📍 景点: {len(places)}个 ❌")
    else:
        print(f"   📍 景点: {len(places)}个 ✅")
    
    # 3. 美食信息
    food = extracted.get("food", {})
    if isinstance(food, dict):
        food_count = (
            len(food.get("specialties", [])) + 
            len(food.get("restaurants", [])) +
            len(food.get("streets", []))
        )
    else:
        food_count = 0
    
    if food_count < 2:
        missing.append("food")
        print(f"   🍜 美食: {food_count}项 ❌")
    else:
        print(f"   🍜 美食: {food_count}项 ✅")
    
    # 4. 住宿信息
    accommodation = extracted.get("accommodation", {})
    if isinstance(accommodation, dict):
        areas = accommodation.get("recommended_areas", [])
        valid_areas = [a for a in areas if a.get("area")]
        
        if len(valid_areas) < 1:
            missing.append("accommodation")
            print(f"   🏨 住宿: 无有效区域 ❌")
        else:
            area_names = [a.get("area", "") for a in valid_areas[:2]]
            print(f"   🏨 住宿: {', '.join(area_names)} ✅")
    else:
        missing.append("accommodation")
        print(f"   🏨 住宿: 无 ❌")
    
    # 5. 交通信息
    if search_count >= 2:
        transportation = extracted.get("transportation")
        if not transportation or not transportation.get("arrival"):
            missing.append("transportation")
            print(f"   🚗 交通: 无 ⚠️")
        else:
            print(f"   🚗 交通: 有 ✅")
    
    # 6. 避坑信息
    avoid = extracted.get("avoid", [])
    print(f"   ⚠️ 避坑: {len(avoid)}条")
    
    if missing:
        state["_missing_info"] = missing
        print(f"\n→ 继续搜索，缺失: {missing}")
        return "need_more"
    
    print(f"\n→ 信息充足，开始规划 ✅")
    return "enough"


# ==================== 规划节点 ====================

PLAN_PROMPT = """你是专业旅行规划师。请根据以下信息生成{days}天{destination}旅行计划。

    【用户信息】
    - 出发地: {origin}
    - 天数: {days}天
    - 人群: {group_type}
    - 偏好: {preferences}

    【已收集的攻略信息】
    {extracted_info}

    【生成要求】
    1. **参考已有路线**：上面的 `routes` 字段包含网友推荐的路线，请参考这些路线规划行程
    2. **使用景点详情**：`places` 字段有景点的开放时间、门票、闭馆日等信息，要体现在行程中
    3. **融入美食推荐**：
      - 将 `food.restaurants` 中的餐厅安排到合适的用餐时间
      - 将 `food.specialties` 中的特色美食体现在推荐中
      - 将 `food.streets` 中的美食街作为用餐地点推荐
    4. **使用住宿信息**：`accommodation.recommended_areas` 包含推荐区域和原因
    5. **使用交通信息**：`transportation` 包含到达和市内交通建议
    6. **注意避坑信息**：`avoid` 中的事项要在行程提示中体现
    7. 每天安排 4-6 个活动，时间合理
    8. 注意景点闭馆日（如周一闭馆），合理安排

    直接输出 JSON：
    ```json
    {{
      "overview": "行程概述（50字内）",
      "highlights": ["亮点1", "亮点2", "亮点3"],
      "reference_routes": ["参考的路线来源，如：笔记1的3日游路线"],
      "days": [
        {{
          "day": 1,
          "date": "Day 1",
          "theme": "当日主题",
          "schedule": [
            {{
              "time": "09:00-11:00",
              "poi": "景点名称（纯名词，必填）",
              "activity": "活动描述",
              "duration": "2小时",
              "ticket": "门票信息（从 places 中获取，如：免费/32元）",
              "tips": "游玩提示（如：需提前预约、周一闭馆等）"
            }}
          ],
          "meals": {{
            "breakfast": {{
              "recommend": "推荐餐厅或美食",
              "location": "位置",
              "reason": "推荐原因"
            }},
            "lunch": {{
              "recommend": "推荐",
              "location": "位置",
              "reason": "推荐原因"
            }},
            "dinner": {{
              "recommend": "推荐",
              "location": "位置",
              "reason": "推荐原因"
            }}
          }}
        }}
      ],
      "tips": {{
        "transportation": {{
          "arrival": "到达交通建议",
          "local": ["市内交通建议1", "建议2"]
        }},
        "accommodation": {{
          "area": "推荐住宿区域",
          "reasons": ["原因1", "原因2"],
          "nearby": ["周边设施"]
        }},
        "food": {{
          "specialties": [
            {{
              "name": "特色美食名",
              "description": "美食描述",
              "reason": "为什么推荐（如：南京必吃、本地人推荐等）"
            }}
          ],
          "streets": [
            {{
              "name": "美食街名",
              "location": "位置",
              "features": "特色",
              "reason": "为什么推荐"
            }}
          ],
          "restaurants": [
            {{
              "name": "餐厅名",
              "specialty": "招牌菜",
              "reason": "为什么推荐（如：老字号、本地人常去等）"
            }}
          ]
        }},
        "avoid": [
          {{
            "item": "注意事项",
            "reason": "原因"
          }}
        ],
        "practical": ["其他实用贴士"]
      }}
    }}
    ⚠️ POI 字段规则（严格遵守）：
    必须是纯名词：仅填写地图可定位的具体地点名称
    返回的poi必须要是这个城市的而不是别的城市
    严禁包含动词：删除"前往"、"游览"、"参观"、"夜游"、"打卡"等词汇
    示例：❌ "游览中山陵" → ✅ "中山陵"
    示例：❌ "秦淮河夜游" → ✅ "秦淮河"
    不要出现多地点：❌ "老门东 → 夫子庙" → ✅ 分成两个 schedule 项
    specialties信息和restaurants信息保留并加以润色。
    """


def plan_node(state: AgentState) -> AgentState:
    """规划节点 - 生成完整行程"""
    print(f"\n{'='*50}")
    print(f"🗓️ PLAN NODE")
    print(f"{'='*50}")

    user = state["user_profile"]
    extracted = state.get("extracted_info") or {}
    budget: TokenBudget = state.get("_token_budget") or TokenBudget()




    prompt = PLAN_PROMPT.format(
        days=user.days,
        destination=user.destination,
        origin=user.origin or "未知",
        group_type=user.group_type or "普通游客",
        preferences="、".join(user.preferences) if user.preferences else "无特殊偏好",
        extracted_info=json.dumps(extracted, ensure_ascii=False, indent=2)
    )

    llm = LLMFactory.get_smart_model()
    input_tokens = token_counter.count(prompt)

    print(f"📊 输入: {input_tokens} tokens")

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        output_tokens = token_counter.count(response.content)
        budget.consume("plan", input_tokens + output_tokens)
        
        # ✅ 使用安全解析
        plan = _safe_parse_json(response.content, default={})
        
        if not plan or not plan.get("days"):
            print("⚠️ 规划结果不完整，使用兜底方案")
            plan = _create_fallback_plan(user, extracted)
        
        # 转换为最终结果
        state["final_result"] = TravelPlanResult(
            destination=user.destination,
            overview=plan.get("overview", ""),
            highlights=plan.get("highlights", []),
            reference_routes=plan.get("reference_routes", []),
            days=plan.get("days", []),
            tips=plan.get("tips", {})
        )
        
        print(f"✅ 规划完成 ({input_tokens + output_tokens} tokens)")
        print(f"   生成 {len(plan.get('days', []))} 天行程")
        
    except Exception as e:
        print(f"❌ 规划失败: {e}")
        import traceback
        traceback.print_exc()
        state["final_result"] = _create_fallback_result(user)

    saved_plan_id = _save_result(state)
    if saved_plan_id:
        state["current_plan_id"] = saved_plan_id

    state["_token_budget"] = budget
    return state


def _create_fallback_plan(user, extracted: dict) -> dict:
    """创建基于已提取信息的兜底计划"""
    routes = extracted.get("routes", [])
    places = extracted.get("places", [])
    
    days = []
    
    # 尝试使用已有路线
    if routes:
        best_route = None
        for route in routes:
            route_days = route.get("days", 0)
            if route_days == user.days:
                best_route = route
                break
        
        if not best_route:
            best_route = routes[0]
        
        daily_plan = best_route.get("daily_plan", [])
        for dp in daily_plan[:user.days]:
            days.append({
                "day": dp.get("day", len(days) + 1),
                "date": f"Day {dp.get('day', len(days) + 1)}",
                "theme": dp.get("theme", "游览"),
                "schedule": [
                    {"time": "09:00", "poi": place, "activity": "游览", "duration": "2小时"}
                    for place in dp.get("places", [])[:5]
                ]
            })
    
    # 如果没有路线，使用景点列表
    elif places:
        places_per_day = max(1, len(places) // user.days)
        for day_num in range(user.days):
            start_idx = day_num * places_per_day
            end_idx = start_idx + places_per_day
            day_places = places[start_idx:end_idx]
            
            days.append({
                "day": day_num + 1,
                "date": f"Day {day_num + 1}",
                "theme": "游览",
                "schedule": [
                    {"time": "09:00", "poi": p.get("name", ""), "activity": "游览", "duration": "2小时"}
                    for p in day_places
                ]
            })
    
    return {
        "overview": f"{user.destination}{user.days}天之旅",
        "highlights": [],
        "days": days,
        "tips": {}
    }

def _print_planning_input(extracted: dict):
    """打印规划输入信息"""
    print(f"\n📋 规划输入:")
    
    # 路线参考
    routes = extracted.get("routes", [])
    print(f"   🗺️ 可参考路线: {len(routes)} 条")
    for r in routes[:2]:
        days = r.get("days", "?")
        desc = r.get("description", "")[:20]
        print(f"      • {days}天 - {desc}")
    
    # 景点
    places = extracted.get("places", [])
    print(f"   📍 景点信息: {len(places)} 个")
    
    # 美食
    food = extracted.get("food", {})
    if food:
        print(f"   🍜 美食: {len(food.get('specialties', []))}特色 + {len(food.get('restaurants', []))}餐厅 + {len(food.get('streets', []))}美食街")
    
    # 住宿
    accommodation = extracted.get("accommodation", {})
    if accommodation:
        areas = accommodation.get("recommended_areas", [])
        print(f"   🏨 住宿区域: {len(areas)} 个")
    
    # 交通
    transportation = extracted.get("transportation", {})
    if transportation:
        print(f"   🚗 交通: 有")


def _print_plan_summary(plan: dict):
    """打印规划结果摘要"""
    print(f"\n📋 规划结果:")
    print(f"   📝 概述: {plan.get('overview', '')[:50]}...")
    print(f"   ⭐ 亮点: {plan.get('highlights', [])}")
    print(f"   🗺️ 参考: {plan.get('reference_routes', [])}")
    
    days = plan.get("days", [])
    print(f"   📅 行程: {len(days)} 天")
    
    for day in days:
        day_num = day.get("day", "?")
        theme = day.get("theme", "")
        schedule = day.get("schedule", [])
        print(f"      Day {day_num}: {theme} ({len(schedule)}个活动)")

# ==================== 辅助函数 ====================

def _extract_json(content: str) -> str:
    """从 LLM 响应中提取 JSON 字符串"""
    if not content:
        return "{}"
    
    content = content.strip()
    
    # 方法1：正则匹配 markdown 代码块
    pattern = r'```(?:json)?\s*([\s\S]*?)```'
    match = re.search(pattern, content)
    if match:
        return match.group(1).strip()
    
    # 方法2：找 JSON 对象边界
    start = content.find('{')
    end = content.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        return content[start:end + 1]
    
    return content

def _fix_json_string(json_str: str) -> str:
    """
    修复常见的 JSON 格式错误
    """
    if not json_str:
        return "{}"
    
    # 1. 移除注释（某些 LLM 会添加注释）
    # 移除 // 注释
    json_str = re.sub(r'//.*?(?=\n|$)', '', json_str)
    # 移除 /* */ 注释
    json_str = re.sub(r'/\*[\s\S]*?\*/', '', json_str)
    
    # 2. 移除尾部逗号（常见错误）
    # 移除 },] 或 },} 前的逗号
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    
    # 3. 修复单引号（应该是双引号）
    # 这个比较危险，只在解析失败时尝试
    
    # 4. 移除控制字符
    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
    
    # 5. 确保字符串中的换行符被转义
    # 这个在 JSON 值中很常见
    
    return json_str


def _safe_parse_json(content: str, default: dict = None) -> dict:
    """
    安全解析 JSON，带多重容错机制
    
    Args:
        content: 原始内容
        default: 解析失败时返回的默认值
        
    Returns:
        解析后的字典
    """
    if default is None:
        default = {}
    
    if not content:
        return default
    
    # 尝试1：提取 JSON 后直接解析
    try:
        json_str = _extract_json(content)
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # 尝试2：修复后解析
    try:
        json_str = _extract_json(content)
        fixed = _fix_json_string(json_str)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # 尝试3：使用更宽松的解析（处理单引号）
    try:
        json_str = _extract_json(content)
        # 替换单引号为双引号（危险操作，仅作为最后手段）
        fixed = json_str.replace("'", '"')
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # 尝试4：逐行修复
    try:
        json_str = _extract_json(content)
        fixed = _fix_json_line_by_line(json_str)
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析最终失败: {e}")
        # 打印问题位置附近的内容
        _debug_json_error(json_str, e)
    
    return default


def _fix_json_line_by_line(json_str: str) -> str:
    """逐行修复 JSON"""
    lines = json_str.split('\n')
    fixed_lines = []
    
    for i, line in enumerate(lines):
        # 移除行尾逗号后的空格和逗号（在 ] 或 } 之前）
        line = re.sub(r',\s*$', '', line.rstrip())
        
        # 如果下一行是 ] 或 }，确保当前行没有逗号
        if i < len(lines) - 1:
            next_line = lines[i + 1].strip()
            if next_line.startswith(']') or next_line.startswith('}'):
                line = line.rstrip().rstrip(',')
        
        fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)


def _debug_json_error(json_str: str, error: json.JSONDecodeError):
    """调试 JSON 解析错误"""
    pos = error.pos
    start = max(0, pos - 100)
    end = min(len(json_str), pos + 100)
    
    context = json_str[start:end]
    pointer_pos = pos - start
    
    print(f"\n{'='*50}")
    print(f"JSON 解析错误位置 (字符 {pos}):")
    print(f"{'='*50}")
    print(context)
    print(' ' * pointer_pos + '^')
    print(f"{'='*50}\n")


def _create_fallback_result(user) -> TravelPlanResult:
    """创建兜底结果"""
    return TravelPlanResult(
    destination=user.destination,
    overview=f"{user.destination}{user.days}天之旅",
    highlights=[],
    days=[
    {"day": i + 1, "theme": f"第{i+1}天", "schedule": []}
    for i in range(user.days)
    ],
    tips={}
    )



def _save_result(state: AgentState) -> Optional[str]:
    """保存结果，创建新 plan"""
    from datetime import datetime
    from src.utils.token_budget import TokenBudget
    from src.services.multi_plan_store import multi_plan_store
    
    session_id = state.get("session_id", "")
    if not session_id:
        print("⚠️ 没有 session_id，无法保存")
        return None

    result = state.get("final_result")
    if not result:
        print("⚠️ 没有 final_result，无法保存")
        return None

    result_dict = result.model_dump() if hasattr(result, 'model_dump') else result
    
    budget = state.get("_token_budget") or TokenBudget()
    route_data = {
        "plan": result_dict,
        "meta": {
            "search_count": state.get("_search_count", 0),
            "token_consumed": budget.get_total_consumed() if hasattr(budget, 'get_total_consumed') else 0,
        },
        "generated_at": datetime.now().isoformat()
    }
    
    # 生成名称
    user = state.get("user_profile")
    plan_name = None
    if user:
        destination = getattr(user, 'destination', '') or result_dict.get('destination', '')
        days = getattr(user, 'days', 0) or len(result_dict.get('days', []))
        if destination:
            plan_name = f"{destination}{days}日游" if days else f"{destination}之旅"
    
    # 直接创建新 plan
    plan_id = multi_plan_store.create_plan(
        session_id=session_id,
        route_data=route_data,
        name=plan_name
    )
    
    if plan_id:
        print(f"💾 已保存: {session_id[:8]}.../{plan_id}")
    
    return plan_id



def _print_token_summary(budget: TokenBudget):
    """打印 Token 统计"""
    print(f"\n{'─'*40}")
    print(f"📊 Token 消耗统计:")
    for stage, tokens in budget.consumed.items():
      print(f" {stage}: {tokens}")
      print(f" ────────")
    print(f" 总计: {budget.get_total_consumed()}")
    print(f"{'─'*40}")

def create_travel_graph():
    """
    创建旅行规划工作流
    流程: search → extract → [check] → plan → END
                  ↑          ↓
                  ←── need_more
    """
    workflow = StateGraph(AgentState)

    # 注册节点
    workflow.add_node("search", search_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("plan", plan_node)

    # 设置入口
    workflow.set_entry_point("search")

    # search → extract
    workflow.add_edge("search", "extract")

    # extract → 检查 → plan 或 search
    workflow.add_conditional_edges(
        "extract",
        check_info_quality,
        {
            "need_more": "search",
            "enough": "plan"
        }
    )

    # plan → END
    workflow.add_edge("plan", END)

    return workflow.compile()