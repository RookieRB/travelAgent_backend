# src/tools/travel_plan_tool.py
import json
from typing import Type, List, Any
from pydantic import BaseModel, Field, PrivateAttr
from langchain.tools import BaseTool

from src.utils.context import get_session_id
from src.services.redis_service import redis_service
from src.agents.state import create_initial_state, print_state_status
from src.utils.token_budget import TokenBudget


class TravelPlanSchema(BaseModel):
    """旅行计划输入参数"""
    destination: str = Field(description="目的地城市")
    days: int = Field(description="旅行天数")
    origin: str = Field(default="", description="出发城市")
    date_range: str = Field(default="", description="出行日期范围")
    group_type: str = Field(default="", description="出行人群类型：family/couple/friends/solo")
    preferences: List[str] = Field(default_factory=list, description="偏好：美食/购物/自然/历史/网红打卡/特种兵/亲子/拍照等")
    budget: str = Field(default="", description="预算范围：经济/中等/高端")
    max_searches: int = Field(default=2, description="最大搜索次数")
    skip_map: bool = Field(default=True, description="是否跳过地图路线验证")
    include_weather: bool = Field(default=True, description="是否查询天气信息")
    quality_level: str = Field(default="normal", description="质量级别：fast/normal/high")


class TravelPlanTool(BaseTool):
    """生成完整的旅行计划 - 优化版"""
    
    name: str = "generate_travel_plan"
    description: str = """根据用户需求生成完整的旅行计划。
    工作流程：
    1. 智能搜索小红书攻略（基于用户偏好动态生成关键词）
    2. 价值评估和信息过滤
    3. 总结提取规划规则
    4. 查询天气（可选）
    5. 生成详细行程
    6. 润色输出

    必需参数：destination（目的地）、days（天数）
    """
    args_schema: Type[BaseModel] = TravelPlanSchema
    
    _graph: Any = PrivateAttr(default=None)
    _current_session_id: str = PrivateAttr(default="")
    
    def __init__(self, travel_graph: Any = None, **data):
        super().__init__(**data)
        self._graph = travel_graph
        self._current_session_id = ""

    def set_session_id(self, session_id: str):
        """外部设置 session_id"""
        self._current_session_id = session_id
    
    def _run(
        self,
        destination: str,
        days: int,
        origin: str = "",
        date_range: str = "",
        group_type: str = "",
        preferences: List[str] = None,
        budget: str = "",
        max_searches: int = 2,
        skip_map: bool = True,
        include_weather: bool = True,
        quality_level: str = "normal",
    ) -> str:
        from src.models.schemas import UserProfile
        
        # 获取 session_id
        final_session_id = self._current_session_id or get_session_id()
        
        self._print_start_info(
            destination, days, origin, group_type, 
            preferences, budget, max_searches, skip_map, 
            include_weather, quality_level
        )
        
        # 更新状态
        if final_session_id:
            redis_service.update_plan_status(
                final_session_id, 
                status="processing", 
                progress=5,
                message="初始化旅行规划..."
            )
        
        # 构建用户画像
        user_profile = UserProfile(
            origin=origin or "未指定",
            destination=destination,
            days=days,
            date_range=date_range or "灵活",
            group_type=group_type or "未指定",
            preferences=preferences or [],
            budget=budget or "中等",
        )
        
        # 根据质量级别配置 Token 预算
        token_budget = self._get_token_budget(quality_level)
        
        # 使用辅助函数创建初始状态
        initial_state = create_initial_state(
            user_profile=user_profile,
            session_id=final_session_id,
            max_searches=max_searches,
            skip_map=skip_map,
            skip_weather=not include_weather,
            token_budget=token_budget,
        )
        
        try:
            if self._graph is None:
                return self._handle_error("旅行规划工作流未初始化", destination, days, final_session_id)
            
            # 执行工作流
            print("🔄 开始执行工作流...")
            print_state_status(initial_state, "初始化")
            
            final_state = self._graph.invoke(initial_state)
            
            print_state_status(final_state, "完成")
            
            # 处理结果
            return self._process_result(final_state, destination, days, user_profile)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._handle_error(str(e), destination, days, final_session_id)
    
    def _get_token_budget(self, quality_level: str) -> TokenBudget:
        """根据质量级别获取 Token 预算"""
        configs = {
            "fast": TokenBudget(
                summary=2500,
                planning=3500,
                refine=1500,
                total_budget=12000,
                max_notes_per_search=3,
                max_note_length=600,
            ),
            "normal": TokenBudget(
                summary=4000,
                planning=5000,
                refine=3000,
                total_budget=20000,
                max_notes_per_search=5,
                max_note_length=1000,
            ),
            "high": TokenBudget(
                summary=6000,
                planning=8000,
                refine=4000,
                total_budget=30000,
                max_notes_per_search=8,
                max_note_length=1500,
            ),
        }
        return configs.get(quality_level, configs["normal"])
    
    def _print_start_info(self, destination, days, origin, group_type, 
                          preferences, budget, max_searches, skip_map, 
                          include_weather, quality_level):
        """打印启动信息"""
        print(f"\n{'='*60}")
        print(f"🚀 开始生成旅行计划 (优化版)")
        print(f"   📍 目的地: {destination}")
        print(f"   📅 天数: {days} 天")
        print(f"   🏠 出发地: {origin or '未指定'}")
        print(f"   👥 出行类型: {group_type or '未指定'}")
        print(f"   💝 偏好: {preferences or '无特殊偏好'}")
        print(f"   💰 预算: {budget or '中等'}")
        print(f"   🔍 最大搜索: {max_searches} 次")
        print(f"   ⚡ 质量级别: {quality_level}")
        print(f"   🗺️ 地图验证: {'跳过' if skip_map else '启用'}")
        print(f"   🌤️ 天气查询: {'启用' if include_weather else '跳过'}")
        print(f"{'='*60}\n")
    
    def _handle_error(self, error_msg: str, destination: str, days: int, session_id: str) -> str:
        """处理错误"""
        print(f"❌ 错误: {error_msg}")
        if session_id:
            redis_service.update_plan_status(session_id, status="failed", message=error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "destination": destination,
            "days": days,
            "suggestion": "请检查网络连接或稍后重试"
        }, ensure_ascii=False, indent=2)
    
    def _process_result(self, final_state: dict, destination: str, days: int, user_profile) -> str:
        """处理工作流返回结果"""
        result = final_state.get("final_result")
        session_id = final_state.get("session_id", "")
        budget = final_state.get("_token_budget")
        
        if result:
            print("\n✅ 旅行计划生成成功!")
            
            # 转换结果
            if hasattr(result, 'model_dump'):
                plan_dict = result.model_dump()
            elif hasattr(result, 'dict'):
                plan_dict = result.dict()
            else:
                plan_dict = result
            
            response = {
                "success": True,
                "session_id": session_id,
                "destination": destination,
                "days": days,
                "user_profile": {
                    "origin": user_profile.origin,
                    "destination": user_profile.destination,
                    "days": user_profile.days,
                    "group_type": user_profile.group_type,
                    "preferences": user_profile.preferences,
                    "budget": user_profile.budget,
                },
                "plan": plan_dict,
                "meta": {
                    "search_count": final_state.get("_search_count", 0),
                    "has_weather": final_state.get("weather_info") is not None,
                    "token_consumed": budget.get_total_consumed() if budget else 0,
                }
            }
            
            return json.dumps(response, ensure_ascii=False, indent=2)
        
        # 尝试返回部分结果
        return self._get_partial_result(final_state, destination, days)
    
    def _get_partial_result(self, final_state: dict, destination: str, days: int) -> str:
        """获取部分结果"""
        draft_plan = final_state.get("draft_plan")
        planning_rules = final_state.get("planning_rules")
        
        if draft_plan:
            return json.dumps({
                "success": False,
                "partial": True,
                "destination": destination,
                "days": days,
                "draft_plan": draft_plan,
                "message": "返回草案数据"
            }, ensure_ascii=False, indent=2)
        
        if planning_rules:
            rules_dict = planning_rules.model_dump() if hasattr(planning_rules, 'model_dump') else str(planning_rules)
            return json.dumps({
                "success": False,
                "partial": True,
                "destination": destination,
                "days": days,
                "planning_rules": rules_dict,
                "message": "仅完成信息收集"
            }, ensure_ascii=False, indent=2)
        
        return json.dumps({
            "success": False,
            "error": "无有效结果",
            "destination": destination,
            "days": days,
        }, ensure_ascii=False, indent=2)