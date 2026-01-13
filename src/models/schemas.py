
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field

# --- User Input ---
class UserProfile(BaseModel):
    origin: str = Field(..., description="出发地")
    destination: str = Field(..., description="目的地")
    days: int = Field(..., description="出行天数")
    date_range: Optional[str] = Field(None, description="出行时间范围")
    group_type: str = Field(..., description="人群类型: solo, couple, family, friends")
    preferences: List[str] = Field(..., description="偏好: 美食, 拍照, 轻松, 深度, 特种兵")
    budget: str = Field(..., description="预算区间")

class TravelPlanRequest(BaseModel):
    destination: str
    days: int
    preferences: List[str]
    origin: str = "北京"  # Default
    date_range: str = "随时"
    group_type: str = "friends"
    budget: str = "中等"

# --- Intermediate Data ---
class SearchNote(BaseModel):
    title: str
    content: str
    url: Optional[str] = None
    likes: Optional[int] = 0

class SearchResult(BaseModel):
    notes: List[SearchNote]

class ScheduleItem(BaseModel):
    """日程项"""
    time: Optional[str] = ""
    place: Optional[str] = ""
    duration: Optional[str] = ""
    tips: Optional[str] = ""
    
    class Config:
        extra = "allow"


class DailyRoute(BaseModel):
    """每日路线"""
    day: Union[int, str] = 1
    theme: Optional[str] = ""
    schedule: List[ScheduleItem] = Field(default_factory=list)
    
    class Config:
        extra = "allow"


class MustVisitItem(BaseModel):
    """必去景点"""
    name: str = ""
    reason: Optional[str] = ""
    best_time: Optional[str] = ""
    duration: Optional[str] = ""
    
    class Config:
        extra = "allow"


class AvoidItem(BaseModel):
    """避坑项"""
    item: str = ""
    reason: Optional[str] = ""
    
    class Config:
        extra = "allow"


class FoodAccommodation(BaseModel):
    """餐饮住宿"""
    food_areas: List[str] = Field(default_factory=list)
    stay_areas: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    
    class Config:
        extra = "allow"


class CrowdSpecific(BaseModel):
    """人群特定建议"""
    family: List[str] = Field(default_factory=list)
    couple: List[str] = Field(default_factory=list)
    friends: List[str] = Field(default_factory=list)
    solo: List[str] = Field(default_factory=list)
    
    class Config:
        extra = "allow"


class PlanningRules(BaseModel):
    """规划规则 - 完全匹配 XIAOHONGSHU_SUMMARY_PROMPT 输出"""
    
    destination: Optional[str] = ""
    recommended_days: Optional[Union[str, int]] = ""  # ✅ 兼容 str 和 int
    
    # 每日路线
    daily_routes: List[DailyRoute] = Field(default_factory=list)
    
    # 兼容旧字段名
    common_routes: List[Any] = Field(default_factory=list)
    
    # 必去景点 - 支持字符串或对象
    must_visit: List[Union[str, Dict[str, Any], MustVisitItem]] = Field(default_factory=list)
    
    # 避坑指南 - 支持字符串或对象
    avoid_list: List[Union[str, Dict[str, Any], AvoidItem]] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    
    # 交通建议
    transport_tips: List[str] = Field(default_factory=list)
    
    # 餐饮住宿
    food_accommodation: Optional[FoodAccommodation] = None
    
    # 实用贴士
    practical_tips: List[str] = Field(default_factory=list)
    
    # 人群特定建议
    crowd_specific: Optional[CrowdSpecific] = None
    
    # 来源摘要
    sources_summary: Optional[str] = ""
    
    class Config:
        extra = "allow"
    
    def get_recommended_days_str(self) -> str:
        """获取推荐天数（字符串格式）"""
        if isinstance(self.recommended_days, int):
            return f"{self.recommended_days}天"
        return str(self.recommended_days) if self.recommended_days else ""
    
    def get_must_visit_names(self) -> List[str]:
        """获取必去景点名称列表"""
        names = []
        for item in self.must_visit:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.append(item.get("name", ""))
            elif hasattr(item, "name"):
                names.append(item.name)
        return [n for n in names if n]
    
    def get_avoid_list(self) -> List[str]:
        """获取避坑列表"""
        items = []
        for item in self.avoid_list:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict):
                items.append(item.get("item", ""))
            elif hasattr(item, "item"):
                items.append(item.item)
        items.extend(self.avoid)
        return [i for i in items if i]
# --- Final Output ---
class ItineraryItem(BaseModel):
    time: str
    poi: str
    duration: str
    transport: Optional[str] = None
    notes: Optional[str] = None

class DailySchedule(BaseModel):
    day: int
    schedule: List[ItineraryItem]

class TravelPlanResult(BaseModel):
    overview: str
    days: List[DailySchedule]
    map_routes: Optional[List[Any]] = None
    tips: Dict[str, List[str]]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    action: str
    reply: str
    missing_fields: List[str] = []
    plan: Optional[TravelPlanResult] = None
    messages: List[ChatMessage] = []


class ScheduleItem(BaseModel):
    """行程项 - 每个活动/景点"""
    time: str = ""
    poi: str = ""  # 景点名称，必填
    activity: Optional[str] = ""
    duration: str = ""  # 时长，必填
    tips: Optional[str] = ""
    route_info: Optional[str] = ""
    
    class Config:
        extra = "allow"


class DayPlan(BaseModel):
    """每日行程"""
    day: Union[int, str] = 1
    date: Optional[str] = ""
    theme: Optional[str] = ""
    weather_tip: Optional[str] = ""
    schedule: List[ScheduleItem] = Field(default_factory=list)
    
    class Config:
        extra = "allow"


class TravelTips(BaseModel):
    """旅行建议"""
    transport: Optional[str] = ""
    food: Optional[str] = ""
    accommodation: Optional[str] = ""
    budget: Optional[str] = ""
    avoid: List[str] = Field(default_factory=list)
    replaceable: List[str] = Field(default_factory=list)
    
    class Config:
        extra = "allow"


class TravelPlanResult(BaseModel):
    """最终行程结果"""
    overview: str = "精彩行程"
    highlights: List[str] = Field(default_factory=list)
    days: List[DayPlan] = Field(default_factory=list)
    tips: TravelTips = Field(default_factory=TravelTips)
    
    class Config:
        extra = "allow"