import json
import os
from typing import Any, Dict, List, Optional, Type
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from tools.search import get_search_tool
from prompts import (
    ATTRACTION_ANALYSIS_PROMPT,
    FOOD_ANALYSIS_PROMPT,
    ROUTE_ANALYSIS_PROMPT,
    ACCOMMODATION_ANALYSIS_PROMPT,
    COMPREHENSIVE_ANALYSIS_PROMPT,
)


class BaseLLMAnalyzer:
    """LLM 分析器基类"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=0.3,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE"),
        )
        self.search_tool = get_search_tool()
    
    def search_and_format(self, keywords: List[str], limit_per_keyword: int = 3) -> str:
        """搜索并格式化结果"""
        all_notes = []
        
        for keyword in keywords:
            try:
                result = self.search_tool.run(keyword)
                data = json.loads(result) if isinstance(result, str) else result
                
                notes = data.get("notes", [])
                for note in notes[:limit_per_keyword]:
                    all_notes.append({
                        "keyword": keyword,
                        "title": note.get("title", ""),
                        "content": note.get("desc", ""),
                        "author": note.get("author", ""),
                        "likes": note.get("likes", 0),
                    })
            except Exception as e:
                print(f"搜索 '{keyword}' 失败: {e}")
        
        if not all_notes:
            return "未找到相关笔记"
        
        # 格式化为文本
        formatted = []
        for i, note in enumerate(all_notes, 1):
            formatted.append(f"""
            ---笔记 {i}---
            搜索词: {note['keyword']}
            标题: {note['title']}
            作者: {note['author']} | 点赞: {note['likes']}
            内容:
            {note['content']}
            """)
        
        return "\n".join(formatted)
    
    def analyze(self, prompt: str, notes_content: str) -> Dict[str, Any]:
        """使用 LLM 分析内容"""
        full_prompt = prompt + "\n\n" + notes_content
        
        try:
            response = self.llm.invoke([HumanMessage(content=full_prompt)])
            content = response.content
            
            # 提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()
            
            return json.loads(content)
        except json.JSONDecodeError:
            return {"error": "分析结果解析失败", "raw": content[:500]}
        except Exception as e:
            return {"error": str(e)}


# ============ 景点分析工具 ============

class AttractionAnalysisSchema(BaseModel):
    city: str = Field(description="要分析景点的城市")
    category: str = Field(default="all", description="景点类别过滤：all/自然风光/历史古迹/网红打卡/小众秘境")


class AttractionAnalysisTool(BaseTool):
    """从小红书搜索并分析城市景点"""
    name: str = "analyze_attractions"
    description: str = "搜索小红书获取城市景点信息，并进行智能分类分析。返回景点推荐、分类、评价等信息。"
    args_schema: Type[BaseModel] = AttractionAnalysisSchema
    
    _analyzer: BaseLLMAnalyzer = PrivateAttr()
    
    def __init__(self, **data):
        super().__init__(**data)
        self._analyzer = BaseLLMAnalyzer()
    
    def _run(self, city: str, category: str = "all") -> str:
        """分析城市景点"""
        # 构建搜索关键词
        keywords = [
            f"{city} 必去景点",
            f"{city} 景点推荐",
            f"{city} 小众景点",
        ]
        
        if category != "all":
            keywords.append(f"{city} {category}")
        
        # 搜索笔记
        notes_content = self._analyzer.search_and_format(keywords, limit_per_keyword=3)
        
        if notes_content == "未找到相关笔记":
            return json.dumps({
                "city": city,
                "error": "未找到相关景点信息",
                "suggestion": "请尝试其他城市或稍后重试"
            }, ensure_ascii=False)
        
        # LLM 分析
        result = self._analyzer.analyze(ATTRACTION_ANALYSIS_PROMPT, notes_content)
        result["city"] = city
        result["query_category"] = category
        result["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return json.dumps(result, ensure_ascii=False, indent=2)


# ============ 美食分析工具 ============

class FoodAnalysisSchema(BaseModel):
    city: str = Field(description="要分析美食的城市")
    food_type: str = Field(default="all", description="美食类型：all/小吃/正餐/甜品/夜宵")


class FoodAnalysisTool(BaseTool):
    """从小红书搜索并分析城市美食"""
    name: str = "analyze_food"
    description: str = "搜索小红书获取城市美食推荐，包括必吃美食、推荐餐厅、美食街区等信息。"
    args_schema: Type[BaseModel] = FoodAnalysisSchema
    
    _analyzer: BaseLLMAnalyzer = PrivateAttr()
    
    def __init__(self, **data):
        super().__init__(**data)
        self._analyzer = BaseLLMAnalyzer()
    
    def _run(self, city: str, food_type: str = "all") -> str:
        """分析城市美食"""
        keywords = [
            f"{city} 必吃美食",
            f"{city} 美食攻略",
            f"{city} 美食推荐",
        ]
        
        if food_type != "all":
            keywords.append(f"{city} {food_type}推荐")
        
        notes_content = self._analyzer.search_and_format(keywords, limit_per_keyword=3)
        
        if notes_content == "未找到相关笔记":
            return json.dumps({
                "city": city,
                "error": "未找到相关美食信息"
            }, ensure_ascii=False)
        
        result = self._analyzer.analyze(FOOD_ANALYSIS_PROMPT, notes_content)
        result["city"] = city
        result["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return json.dumps(result, ensure_ascii=False, indent=2)


# ============ 路线分析工具 ============

class RouteAnalysisSchema(BaseModel):
    city: str = Field(description="目的地城市")
    days: int = Field(default=3, description="计划游玩天数")
    crowd_type: str = Field(default="", description="出行人群：家庭/情侣/朋友/独自")


class RouteAnalysisTool(BaseTool):
    """从小红书搜索并分析热门游玩路线"""
    name: str = "analyze_routes"
    description: str = "搜索小红书获取城市热门游玩路线，包括每日行程安排、交通建议等。"
    args_schema: Type[BaseModel] = RouteAnalysisSchema
    
    _analyzer: BaseLLMAnalyzer = PrivateAttr()
    
    def __init__(self, **data):
        super().__init__(**data)
        self._analyzer = BaseLLMAnalyzer()
    
    def _run(self, city: str, days: int = 3, crowd_type: str = "") -> str:
        """分析游玩路线"""
        keywords = [
            f"{city} {days}天攻略",
            f"{city} 游玩路线",
            f"{city} 行程安排",
        ]
        
        if crowd_type:
            keywords.append(f"{city} {crowd_type}游")
        
        notes_content = self._analyzer.search_and_format(keywords, limit_per_keyword=3)
        
        if notes_content == "未找到相关笔记":
            return json.dumps({
                "city": city,
                "error": "未找到相关路线信息"
            }, ensure_ascii=False)
        
        result = self._analyzer.analyze(ROUTE_ANALYSIS_PROMPT, notes_content)
        result["city"] = city
        result["requested_days"] = days
        result["crowd_type"] = crowd_type
        result["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return json.dumps(result, ensure_ascii=False, indent=2)


# ============ 综合攻略分析工具 ============

class ComprehensiveAnalysisSchema(BaseModel):
    city: str = Field(description="目的地城市")
    days: int = Field(default=3, description="计划游玩天数")
    preferences: List[str] = Field(default_factory=list, description="偏好：美食/购物/自然/历史/网红打卡")


class ComprehensiveAnalysisTool(BaseTool):
    """综合分析城市旅游攻略"""
    name: str = "analyze_comprehensive"
    description: str = "综合搜索分析城市的景点、美食、路线、住宿等全方位旅游信息，生成完整的攻略摘要。"
    args_schema: Type[BaseModel] = ComprehensiveAnalysisSchema
    
    _analyzer: BaseLLMAnalyzer = PrivateAttr()
    
    def __init__(self, **data):
        super().__init__(**data)
        self._analyzer = BaseLLMAnalyzer()
    
    def _run(self, city: str, days: int = 3, preferences: List[str] = None) -> str:
        """综合分析"""
        keywords = [
            f"{city} 旅游攻略",
            f"{city} {days}天游",
            f"{city} 必去景点",
            f"{city} 必吃美食",
            f"{city} 避坑",
        ]
        
        if preferences:
            for pref in preferences[:2]:
                keywords.append(f"{city} {pref}")
        
        notes_content = self._analyzer.search_and_format(keywords, limit_per_keyword=2)
        
        if notes_content == "未找到相关笔记":
            return json.dumps({
                "city": city,
                "error": "未找到相关攻略信息"
            }, ensure_ascii=False)
        
        result = self._analyzer.analyze(COMPREHENSIVE_ANALYSIS_PROMPT, notes_content)
        result["city"] = city
        result["requested_days"] = days
        result["preferences"] = preferences or []
        result["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        return json.dumps(result, ensure_ascii=False, indent=2)