import json
import os
import httpx
from typing import Any, Dict, List, Optional, Type
from datetime import datetime, timedelta

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from .http import McpStreamableHttpClient

from src.utils.context import get_session_id
from src.services.redis_service import redis_service


TYPECODE_MAP = {
    # 风景名胜 110000
    "110000": "风景名胜",
    "110100": "公园广场",
    "110101": "公园",
    "110102": "广场",
    "110103": "街道",
    "110104": "城市绿地",
    "110105": "社区公园",
    "110200": "风景名胜",
    "110201": "世界遗产",
    "110202": "国家级景点",
    "110203": "省级景点",
    "110204": "市级景点",
    "110205": "县级景点",
    "110206": "文物古迹",
    "110207": "红色景点",
    "110208": "湿地公园",
    "110209": "森林公园",
    "110210": "地质公园",
    
    # 餐饮服务 050000
    "050000": "餐饮服务",
    "050100": "中餐厅",
    "050101": "综合中餐厅",
    "050102": "四川菜",
    "050103": "广东菜",
    "050104": "山东菜",
    "050105": "江苏菜",
    "050106": "浙江菜",
    "050107": "湖南菜",
    "050108": "福建菜",
    "050109": "东北菜",
    "050110": "云南菜",
    "050111": "贵州菜",
    "050112": "新疆菜",
    "050113": "火锅店",
    "050114": "海鲜酒楼",
    "050115": "素菜馆",
    "050200": "外国餐厅",
    "050201": "日本料理",
    "050202": "韩国料理",
    "050203": "西餐厅",
    "050204": "泰国菜",
    "050205": "越南菜",
    "050206": "印度菜",
    "050300": "快餐厅",
    "050301": "肯德基",
    "050302": "麦当劳",
    "050303": "必胜客",
    "050304": "中式快餐",
    "050305": "面馆",
    "050306": "饺子馆",
    "050307": "麻辣烫",
    "050400": "休闲餐饮",
    "050401": "咖啡厅",
    "050402": "茶馆",
    "050403": "甜品店",
    "050404": "冷饮店",
    "050405": "酒吧",
    "050500": "糕点店",
    "050501": "面包房",
    "050502": "蛋糕店",
    
    # 购物服务 060000
    "060000": "购物服务",
    "060100": "商场",
    "060101": "购物中心",
    "060102": "百货商场",
    "060200": "超市",
    "060201": "大型超市",
    "060202": "便利店",
    "060300": "专卖店",
    "060301": "服装鞋帽",
    "060302": "家电数码",
    "060400": "市场",
    "060401": "农贸市场",
    "060402": "批发市场",
    "060500": "特产店",
    
    # 生活服务 070000
    "070000": "生活服务",
    "070100": "通讯服务",
    "070200": "邮政",
    "070300": "物流速递",
    "070400": "图文快印",
    "070500": "洗衣店",
    "070600": "美容美发",
    "070700": "摄影冲印",
    "070800": "家政服务",
    "070900": "维修服务",
    
    # 体育休闲 080000
    "080000": "体育休闲",
    "080100": "运动场馆",
    "080101": "体育馆",
    "080102": "游泳馆",
    "080103": "健身房",
    "080104": "球场",
    "080105": "高尔夫球场",
    "080106": "滑雪场",
    "080200": "休闲娱乐",
    "080201": "电影院",
    "080202": "KTV",
    "080203": "游乐园",
    "080204": "度假村",
    "080205": "洗浴中心",
    "080206": "足疗按摩",
    
    # 医疗保健 090000
    "090000": "医疗保健",
    "090100": "综合医院",
    "090101": "三甲医院",
    "090102": "专科医院",
    "090200": "诊所",
    "090300": "药店",
    "090400": "疗养院",
    "090500": "急救中心",
    "090600": "疾控中心",
    
    # 住宿服务 100000
    "100000": "住宿服务",
    "100100": "星级酒店",
    "100101": "五星级酒店",
    "100102": "四星级酒店",
    "100103": "三星级酒店",
    "100200": "快捷酒店",
    "100201": "如家",
    "100202": "7天",
    "100203": "汉庭",
    "100300": "宾馆",
    "100400": "旅馆",
    "100500": "招待所",
    "100600": "民宿",
    "100700": "青年旅社",
    
    # 交通设施 150000
    "150000": "交通设施",
    "150100": "火车站",
    "150101": "高铁站",
    "150102": "普通火车站",
    "150200": "长途汽车站",
    "150300": "机场",
    "150301": "国际机场",
    "150302": "国内机场",
    "150400": "港口码头",
    "150401": "客运码头",
    "150402": "货运码头",
    "150500": "地铁站",
    "150501": "地铁入口",
    "150600": "公交站",
    "150700": "停车场",
    "150701": "地上停车场",
    "150702": "地下停车场",
    "150703": "路边停车位",
    "150800": "加油站",
    "150900": "充电站",
    "151000": "服务区",
    "151100": "收费站",
    
    # 汽车服务 010000
    "010000": "汽车服务",
    "010100": "加油站",
    "010200": "充电站",
    "010300": "汽车维修",
    "010400": "汽车美容",
    "010500": "汽车租赁",
    "010600": "汽车销售",
    
    # 金融服务 160000
    "160000": "金融服务",
    "160100": "银行",
    "160101": "中国银行",
    "160102": "工商银行",
    "160103": "建设银行",
    "160104": "农业银行",
    "160105": "交通银行",
    "160106": "招商银行",
    "160200": "ATM",
    "160300": "保险公司",
    "160400": "证券公司",
    
    # 科教文化 140000
    "140000": "科教文化",
    "140100": "学校",
    "140101": "大学",
    "140102": "中学",
    "140103": "小学",
    "140104": "幼儿园",
    "140105": "培训机构",
    "140200": "科研机构",
    "140300": "图书馆",
    "140400": "博物馆",
    "140500": "美术馆",
    "140600": "展览馆",
    "140700": "文化宫",
    "140800": "档案馆",
    
    # 政府机构 130000
    "130000": "政府机构",
    "130100": "政府机关",
    "130200": "公检法",
    "130201": "公安局",
    "130202": "派出所",
    "130203": "法院",
    "130204": "检察院",
    "130300": "交通管理",
    "130400": "工商税务",
    
    # 公共设施 190000
    "190000": "公共设施",
    "190100": "公共厕所",
    "190200": "报亭",
    "190300": "公用电话",
    "190400": "紧急避难场所",
}

# ============ 辅助函数 ============
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


# ============ 高德地图 MCP 客户端 ============

class AmapMcpClient(McpStreamableHttpClient):
    """
    高德地图 MCP 客户端（官方版）
    
    使用高德开放平台的 MCP 服务
    URL 格式: https://mcp.amap.com/mcp?key=YOUR_KEY
    """
    
    def __init__(self):
        # 获取高德 API Key
        amap_key = os.getenv("AMAP_KEY")
        if not amap_key:
            raise ValueError("AMAP_KEY 环境变量未设置！请在 .env 中配置您的高德 API Key")
        
        # 构建完整的 URL（key 作为 query 参数）
        base_url = os.getenv("AMAP_MCP_URL", "https://mcp.amap.com/mcp")
        
        # 确保 URL 包含 key 参数
        if "?" in base_url:
            full_url = f"{base_url}&key={amap_key}"
        else:
            full_url = f"{base_url}?key={amap_key}"
        
        # 获取超时配置
        timeout = float(os.getenv("AMAP_MCP_TIMEOUT", "30"))
        
        super().__init__(endpoint=full_url, timeout_s=timeout)
        
        # 高德官方 MCP 不需要 Bearer Token，但可能需要其他 headers
        # 如果需要可以在这里添加
        
        if _env_bool("MCP_DEBUG"):
            # 隐藏 key 的日志
            safe_url = base_url + "?key=***"
            print(f"[AMAP MCP] Endpoint: {safe_url}")


_amap_mcp_client: Optional[AmapMcpClient] = None


def get_amap_mcp_client() -> AmapMcpClient:
    """获取高德地图 MCP 客户端单例"""
    global _amap_mcp_client
    if _amap_mcp_client is None:
        _amap_mcp_client = AmapMcpClient()
    return _amap_mcp_client


def reset_amap_mcp_client():
    """重置高德 MCP 客户端（用于重新初始化）"""
    global _amap_mcp_client
    if _amap_mcp_client is not None:
        _amap_mcp_client.close()
        _amap_mcp_client = None


# ============ 小红书搜索工具 ============

class XiaohongshuSearchSchema(BaseModel):
    keyword: str = Field(description="搜索关键词")


class XiaohongshuSearchTool(BaseTool):
    """小红书搜索工具 - 通过MCP获取笔记列表和详情"""
    name: str = "xiaohongshu_search"
    description: str = "通过MCP服务搜索小红书笔记，获取笔记详细内容"
    args_schema: Type[BaseModel] = XiaohongshuSearchSchema

    _mcp: McpStreamableHttpClient = PrivateAttr()
    _debug: bool = PrivateAttr()
    _detail_limit: int = PrivateAttr()

    def __init__(self, **data: Any):
        super().__init__(**data)

        self._debug = _env_bool("XHS_DEBUG", False)
        self._detail_limit = int(os.getenv("XHS_DETAIL_LIMIT", "2"))
        
        endpoint = os.getenv("XHS_MCP_URL", "http://localhost:18060/mcp")
        timeout_s = float(os.getenv("XHS_MCP_TIMEOUT_S", "60"))
        
        self._mcp = McpStreamableHttpClient(endpoint=endpoint, timeout_s=timeout_s)
        
        if self._debug:
            print(f"[XHS] Endpoint: {endpoint}, Detail limit: {self._detail_limit}")

    def _dprint(self, msg: str, payload: Any = None) -> None:
        if not self._debug:
            return
        if payload is None:
            print(f"[XHS] {msg}")
        else:
            try:
                s = json.dumps(payload, ensure_ascii=False)
                if len(s) > 500:
                    s = s[:500] + "..."
            except Exception:
                s = str(payload)[:500]
            print(f"[XHS] {msg}: {s}")

    def _run(self, keyword: str) -> str:
        """执行搜索并获取笔记详情"""
        try:
            self._dprint("搜索关键词", keyword)

            search_result = self._mcp.call_tool("search_feeds", {"keyword": keyword, "filters": {"sort_by": "最多点赞"}})
            self._dprint("搜索结果类型", type(search_result).__name__)

            feeds = self._extract_feeds(search_result)
            self._dprint(f"找到 {len(feeds)} 条笔记")
            
            notes_with_details = []
            for idx, feed in enumerate(feeds[:self._detail_limit]):
                feed_id = feed.get("id")
                xsec_token = feed.get("xsecToken")
                display_title = feed.get("noteCard", {}).get("displayTitle", "")
                
                if not feed_id or not xsec_token:
                    self._dprint(f"跳过第{idx+1}条: 缺少id或xsecToken")
                    continue

                self._dprint(f"获取第{idx+1}条详情", {"feed_id": feed_id, "title": display_title})

                try:
                    detail_result = self._mcp.call_tool("get_feed_detail", {
                        "feed_id": feed_id,
                        "xsec_token": xsec_token
                    })
                    
                    note_info = self._extract_note_detail(detail_result)
                    note_info["rank"] = idx + 1
                    note_info["feed_id"] = feed_id
                    
                    if not note_info.get("title") and display_title:
                        note_info["title"] = display_title
                    
                    notes_with_details.append(note_info)
                    self._dprint(f"第{idx+1}条详情获取成功", {"title": note_info.get("title", "")[:30]})

                except Exception as e:
                    self._dprint(f"第{idx+1}条详情获取失败", str(e))
                    notes_with_details.append({
                        "rank": idx + 1,
                        "feed_id": feed_id,
                        "title": display_title,
                        "desc": "",
                        "error": str(e)
                    })

            result = {
                "keyword": keyword,
                "total_found": len(feeds),
                "detail_fetched": len(notes_with_details),
                "notes": notes_with_details
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            self._dprint("搜索异常", str(e))
            import traceback
            traceback.print_exc()
            return json.dumps({
                "error": str(e),
                "keyword": keyword
            }, ensure_ascii=False)

    def _extract_feeds(self, search_result: Any) -> List[Dict[str, Any]]:
        feeds = []
        if isinstance(search_result, dict):
            raw_feeds = search_result.get("feeds", [])
            for feed in raw_feeds:
                if not isinstance(feed, dict):
                    continue
                model_type = feed.get("modelType", "")
                if model_type != "note":
                    continue
                if feed.get("id") and feed.get("xsecToken"):
                    feeds.append(feed)
        return feeds

    def _extract_note_detail(self, detail_result: Any) -> Dict[str, Any]:
        note_info = {
            "title": "",
            "desc": "",
            "author": "",
            "likes": 0,
            "comments_count": 0
        }
        
        if not isinstance(detail_result, dict):
            return note_info
            
        data = detail_result.get("data", {})
        note = data.get("note", {})
        
        if not note:
            note = detail_result.get("note", {})
        
        if isinstance(note, dict):
            note_info["title"] = note.get("title", "")
            note_info["desc"] = note.get("desc", "")
            
            user = note.get("user", {})
            if isinstance(user, dict):
                note_info["author"] = user.get("nickname", "") or user.get("name", "")
            
            interact_info = note.get("interactInfo", {})
            if isinstance(interact_info, dict):
                note_info["likes"] = interact_info.get("likedCount", 0) or interact_info.get("liked_count", 0)
                note_info["comments_count"] = interact_info.get("commentCount", 0) or interact_info.get("comment_count", 0)
        
        return note_info


# ============ 天气查询工具 ============

class WeatherQuerySchema(BaseModel):
    city: str = Field(description="要查询天气的城市名称，如：北京、上海、杭州")


class WeatherTool(BaseTool):
    """查询城市天气预报（使用高德地图MCP）"""
    name: str = "query_weather"
    description: str = "查询指定城市的天气预报，包括温度、天气状况、风向等信息。规划旅行时应先查询目的地天气。"
    args_schema: Type[BaseModel] = WeatherQuerySchema

    def _run(self, city: str) -> str:
        """调用高德地图 MCP 查询天气"""
        try:
            client = get_amap_mcp_client()
            
            result = client.call_tool("maps_weather", {"city": city})
            
            if _env_bool("MCP_DEBUG"):
                print(f"[Weather] 原始返回: {result}")
            
            if result:
                weather_data = self._parse_weather_result(result, city)
                return json.dumps(weather_data, ensure_ascii=False, indent=2)
            else:
                return json.dumps({
                    "error": "天气查询无结果",
                    "city": city
                }, ensure_ascii=False)
                
        except Exception as e:
            return json.dumps({
                "error": f"天气查询失败: {str(e)}",
                "city": city
            }, ensure_ascii=False)

    def _parse_weather_result(self, result: Any, city: str) -> Dict:
        """解析高德天气返回结果"""
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return {
                    "city": city,
                    "raw_result": result,
                    "query_time": datetime.now().strftime("%Y-%m-%d %H:%M")
                }
        
        if isinstance(result, dict):
            # 优先使用返回的城市名
            city_name = result.get("city", city)
            
            formatted_result = {
                "city": city_name,
                "query_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            
            # 解析实时天气（如果有）
            lives = result.get("lives", [])
            if lives:
                live = lives[0] if isinstance(lives, list) else lives
                formatted_result["current"] = {
                    "weather": live.get("weather", ""),
                    "temperature": f"{live.get('temperature', '')}°C",
                    "humidity": f"{live.get('humidity', '')}%",
                    "wind_direction": live.get("winddirection", ""),
                    "wind_power": live.get("windpower", ""),
                }
            
            # 解析天气预报
            forecasts = result.get("forecasts", [])
            
            if forecasts:
                formatted_result["forecasts"] = []
                
                # 自动判断数据结构
                first_item = forecasts[0] if forecasts else {}
                
                if "casts" in first_item:
                    # 嵌套结构：forecasts[0].casts
                    casts = first_item.get("casts", [])
                elif "date" in first_item and "dayweather" in first_item:
                    # 扁平结构：forecasts 直接是天气数组
                    casts = forecasts
                else:
                    casts = forecasts
                
                # 星期映射
                week_map = {
                    "1": "一", "2": "二", "3": "三", 
                    "4": "四", "5": "五", "6": "六", 
                    "7": "日", "0": "日"
                }
                
                for cast in casts:
                    week_num = str(cast.get("week", ""))
                    week_str = f"周{week_map.get(week_num, week_num)}"
                    
                    formatted_result["forecasts"].append({
                        "date": cast.get("date", ""),
                        "week": week_str,
                        "day_weather": cast.get("dayweather", ""),
                        "night_weather": cast.get("nightweather", ""),
                        "temp_max": f"{cast.get('daytemp', '')}°C",
                        "temp_min": f"{cast.get('nighttemp', '')}°C",
                        "day_wind": f"{cast.get('daywind', '')}风 {cast.get('daypower', '')}级",
                        "night_wind": f"{cast.get('nightwind', '')}风 {cast.get('nightpower', '')}级",
                    })
                
                # 生成旅行建议
                formatted_result["travel_tips"] = self._generate_travel_tips(formatted_result["forecasts"])
            
            return formatted_result
        
        return {
            "city": city,
            "raw_result": str(result),
            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    def _generate_travel_tips(self, forecasts: List[Dict]) -> List[str]:
        """根据天气生成旅行建议"""
        tips = []
        
        if not forecasts:
            return tips
        
        # 检查是否有雨
        has_rain = any(
            "雨" in f.get("day_weather", "") or "雨" in f.get("night_weather", "") 
            for f in forecasts
        )
        
        # 收集最高温度
        max_temps = []
        min_temps = []
        for f in forecasts:
            # 提取最高温度
            temp_max_str = f.get("temp_max", "").replace("°C", "").strip()
            if temp_max_str and temp_max_str.lstrip('-').isdigit():
                max_temps.append(int(temp_max_str))
            
            # 提取最低温度
            temp_min_str = f.get("temp_min", "").replace("°C", "").strip()
            if temp_min_str and temp_min_str.lstrip('-').isdigit():
                min_temps.append(int(temp_min_str))
        
        # 生成建议
        if has_rain:
            tips.append("☔ 预计有雨，请携带雨具")
        
        if max_temps:
            avg_max = sum(max_temps) / len(max_temps)
            avg_min = sum(min_temps) / len(min_temps) if min_temps else avg_max - 10
            
            if avg_max > 35:
                tips.append("🌡️ 气温很高，注意防暑降温")
                tips.append("🧴 紫外线强烈，务必做好防晒")
                tips.append("💧 多喝水，避免中午户外活动")
            elif avg_max > 28:
                tips.append("🌡️ 天气较热，注意防暑")
                tips.append("🧴 建议涂抹防晒霜")
            elif avg_max < 10:
                tips.append("🧥 气温较低，请注意保暖")
                if avg_min < 0:
                    tips.append("❄️ 夜间可能有霜冻，注意防寒")
            elif avg_max < 20:
                tips.append("🧥 早晚温差大，建议带件外套")
            else:
                tips.append("👕 气温适宜，穿着轻便舒适即可")
        
        # 检查天气状况
        weather_types = [f.get("day_weather", "") for f in forecasts]
        if any("雪" in w for w in weather_types):
            tips.append("❄️ 预计有雪，注意防滑")
        if any("大风" in w or "台风" in w for w in weather_types):
            tips.append("💨 有大风天气，户外活动请注意安全")
        if all("晴" in w or "多云" in w for w in weather_types):
            tips.append("☀️ 天气晴好，适合户外游玩")
        
        return tips

# ============ 周边搜索工具 ============

class NearbySearchSchema(BaseModel):
    location: str = Field(description="中心点位置，可以是地名或经纬度（如：120.153576,30.287459）")
    keywords: str = Field(default="", description="搜索关键词，如：餐厅、酒店、停车场等")
    radius: int = Field(default=1000, description="搜索半径，单位米，默认1000米")
    city: str = Field(default="", description="城市名称（使用地名时建议填写）")
    limit: int = Field(default=20, description="返回结果数量限制，默认20条")


class NearbySearchTool(BaseTool):
    """搜索周边设施（使用高德地图MCP）"""
    name: str = "search_nearby"
    description: str = "搜索指定位置周边的设施，如餐厅、酒店、停车场、地铁站等。适合在确定景点后搜索周边配套。"
    args_schema: Type[BaseModel] = NearbySearchSchema

    def _get_type_name(self, typecode: str) -> str:
        """根据类型码获取类型名称，支持多个类型码（用|分隔）"""
        if not typecode:
            return "其他"
        
        # 处理多个类型码的情况，如 '050100|080304'
        codes = typecode.split("|")
        type_names = []
        
        for code in codes:
            code = code.strip()
            if not code:
                continue
            
            # 精确匹配
            if code in TYPECODE_MAP:
                type_names.append(TYPECODE_MAP[code])
                continue
            
            # 匹配前4位
            if len(code) >= 4:
                prefix4 = code[:4] + "00"
                if prefix4 in TYPECODE_MAP:
                    type_names.append(TYPECODE_MAP[prefix4])
                    continue
            
            # 匹配前2位
            if len(code) >= 2:
                prefix2 = code[:2] + "0000"
                if prefix2 in TYPECODE_MAP:
                    type_names.append(TYPECODE_MAP[prefix2])
                    continue
            
            # 根据首位猜测
            first_digit = code[0] if code else ""
            category_map = {
                "0": "汽车服务", "1": "风景名胜", "2": "商务住宅",
                "3": "政府机构", "4": "科教文化", "5": "餐饮服务",
                "6": "购物服务", "7": "生活服务", "8": "体育休闲",
                "9": "医疗保健",
            }
            type_names.append(category_map.get(first_digit, "其他"))
        
        # 去重并返回
        seen = set()
        unique_names = []
        for name in type_names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name)
        
        return "/".join(unique_names) if unique_names else "其他"

    def _is_coordinate(self, text: str) -> bool:
        """检查是否是坐标格式"""
        if not text or "," not in text:
            return False
        try:
            parts = text.split(",")
            lng, lat = float(parts[0]), float(parts[1])
            return 73 < lng < 136 and 3 < lat < 54
        except:
            return False

    def _get_coordinate(self, client: Any, location: str, city: str = "") -> Optional[str]:
        """获取坐标"""
        if self._is_coordinate(location):
            return location
        
        # 地理编码
        try:
            params = {"address": location}
            if city:
                params["city"] = city
            result = client.call_tool("maps_geo", params)
            if isinstance(result, dict):
                if result.get("location"):
                    return result["location"]
                geocodes = result.get("geocodes", [])
                if geocodes and geocodes[0].get("location"):
                    return geocodes[0]["location"]
        except:
            pass
        
        # POI 搜索
        try:
            params = {"keywords": location}
            if city:
                params["city"] = city
            result = client.call_tool("maps_text_search", params)
            if isinstance(result, dict):
                pois = result.get("pois", [])
                if pois and pois[0].get("location"):
                    return pois[0]["location"]
        except:
            pass
        
        return None

    def _run(self, location: str, keywords: str = "", radius: int = 1000, 
             city: str = "", limit: int = 20) -> str:
        try:
            client = get_amap_mcp_client()
            
            # 转换坐标
            coord = location
            if not self._is_coordinate(location):
                coord = self._get_coordinate(client, location, city)
                if not coord:
                    return json.dumps({
                        "error": f"无法解析位置: {location}",
                        "tip": "请使用经纬度坐标（如：120.153576,30.287459）或更具体的地址",
                        "location": location,
                        "keywords": keywords
                    }, ensure_ascii=False, indent=2)
            
            if _env_bool("MCP_DEBUG"):
                print(f"[Nearby] location={location} -> coord={coord}")
                print(f"[Nearby] keywords={keywords}, radius={radius}")
            
            result = client.call_tool("maps_around_search", {
                "location": coord,
                "keywords": keywords,
                "radius": str(radius)
            })
            
            if _env_bool("MCP_DEBUG"):
                poi_count = len(result.get("pois", [])) if isinstance(result, dict) else 0
                print(f"[Nearby] 返回 {poi_count} 条结果")
            
            if result:
                return self._format_nearby_result(result, location, coord, keywords, radius, limit)
            else:
                return json.dumps({
                    "error": "周边搜索无结果",
                    "location": location,
                    "keywords": keywords
                }, ensure_ascii=False)
                
        except Exception as e:
            return json.dumps({
                "error": f"周边搜索失败: {str(e)}",
                "location": location,
                "keywords": keywords
            }, ensure_ascii=False)

    def _format_nearby_result(self, result: Any, location: str, coord: str, 
                           keywords: str, radius: int, limit: int = 20) -> str:
      """格式化周边搜索结果"""
      if isinstance(result, str):
          try:
              result = json.loads(result)
          except json.JSONDecodeError:
              return json.dumps({
                  "location": location,
                  "keywords": keywords,
                  "raw_result": result
              }, ensure_ascii=False, indent=2)
      
      pois = []
      if isinstance(result, dict):
          pois = result.get("pois", [])
      elif isinstance(result, list):
          pois = result
      
      formatted_pois = []
      for poi in pois[:limit]:
          if not isinstance(poi, dict):
              continue
          
          typecode = poi.get("typecode", "")
          type_name = self._get_type_name(typecode)
          
          formatted_poi = {
              "id": poi.get("id", ""),
              "name": poi.get("name", "").strip(),
              "address": poi.get("address", ""),
              "type": type_name,
              "typecode": typecode,
          }
          
          if poi.get("photo"):
              formatted_poi["photo"] = poi["photo"]
          
          if poi.get("location"):
              formatted_poi["location"] = poi["location"]
          
          distance = poi.get("distance")
          if distance:
              try:
                  dist_m = int(distance)
                  if dist_m < 1000:
                      formatted_poi["distance"] = f"{dist_m}米"
                  else:
                      formatted_poi["distance"] = f"{dist_m / 1000:.1f}公里"
                  formatted_poi["distance_m"] = dist_m
              except:
                  formatted_poi["distance"] = distance
          
          if poi.get("tel"):
              formatted_poi["tel"] = poi["tel"]
          
          formatted_pois.append(formatted_poi)
      
      # 构建返回结果
      response = {
          "location": location,
          "keywords": keywords,
          "radius": f"{radius}米",
          "count": len(formatted_pois),
          "total": len(pois),
          "pois": formatted_pois
      }
      
      # 只有当用户输入的是地名（非坐标）时，才显示转换后的坐标
      if location != coord:
          response["coordinate"] = coord
      
      return json.dumps(response, ensure_ascii=False, indent=2)

# ============ 路线规划工具 ============

class RouteQuerySchema(BaseModel):
    origin: str = Field(description="起点，可以是地名（如：杭州东站）或经纬度（如：120.213841,30.290956）")
    destination: str = Field(description="终点，可以是地名或经纬度")
    mode: str = Field(default="driving", description="出行方式：driving(驾车)/walking(步行)/transit(公交)/bicycling(骑行)")
    city: str = Field(default="杭州", description="城市名称，用于地名解析和公交规划")


class RoutePlanTool(BaseTool):
    """规划出行路线（使用高德地图MCP）"""
    name: str = "plan_route"
    description: str = "规划从起点到终点的出行路线，支持驾车、步行、公交、骑行等方式。"
    args_schema: Type[BaseModel] = RouteQuerySchema

    def _run(self, origin: str, destination: str, mode: str = "driving", city: str = "杭州") -> str:
        try:
            client = get_amap_mcp_client()
            
            # Step 1: 将地名转换为经纬度（传入城市用于精确匹配）
            origin_coord = self._ensure_coordinate(client, origin, city)
            
            # ⚠️ 添加延时避免 QPS 限制
            import time
            time.sleep(0.5)
            
            dest_coord = self._ensure_coordinate(client, destination, city)
            
            if _env_bool("MCP_DEBUG"):
                print(f"[Route] 起点: {origin} -> {origin_coord}")
                print(f"[Route] 终点: {destination} -> {dest_coord}")
            
            if not origin_coord:
                return json.dumps({
                    "error": f"无法解析起点地址: {origin}",
                    "origin": origin,
                    "destination": destination,
                    "mode": mode
                }, ensure_ascii=False)
            
            if not dest_coord:
                return json.dumps({
                    "error": f"无法解析终点地址: {destination}",
                    "origin": origin,
                    "destination": destination,
                    "mode": mode
                }, ensure_ascii=False)
            
            # ⚠️ 再次延时
            time.sleep(0.5)
            
            # Step 2: 规划路线
            if mode == "transit":
                result = self._plan_transit(client, origin_coord, dest_coord, city)
            else:
                result = self._plan_other(client, origin_coord, dest_coord, mode)
            if result:
                return self._format_route_result(result, origin, destination, mode)
            else:
                return json.dumps({
                    "error": "路线规划无结果",
                    "origin": origin,
                    "destination": destination,
                    "mode": mode
                }, ensure_ascii=False)
                
        except Exception as e:
            import traceback
            if _env_bool("MCP_DEBUG"):
                traceback.print_exc()
            return json.dumps({
                "error": f"路线规划失败: {str(e)}",
                "origin": origin,
                "destination": destination,
                "mode": mode
            }, ensure_ascii=False)

    def _ensure_coordinate(self, client: Any, location: str, city: str = "") -> Optional[str]:
        """确保位置是经纬度格式，如果是地名则转换"""
        if self._is_coordinate(location):
            return location
        
        try:
            # ✅ 关键修复：把城市名加到地址前面，确保定位准确
            search_address = location
            if city and city not in location:
                search_address = f"{city}{location}"
            
            params = {"address": search_address}
            
            result = client.call_tool("maps_geo", params)
            
            if _env_bool("MCP_DEBUG"):
                print(f"[GeoCode] {search_address} -> {result}")
            
            return self._extract_location_from_geocode(result, city)
            
        except Exception as e:
            if _env_bool("MCP_DEBUG"):
                print(f"[GeoCode] 转换失败: {e}")
            return None

    def _extract_location_from_geocode(self, result: Any, prefer_city: str = "") -> Optional[str]:
        """从地理编码结果中提取坐标，优先匹配指定城市"""
        
        if result is None:
            return None
        
        # 如果是错误字符串
        if isinstance(result, str):
            if "失败" in result or "EXCEEDED" in result or "error" in result.lower():
                if _env_bool("MCP_DEBUG"):
                    print(f"[GeoCode] API 错误: {result}")
                return None
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                if self._is_coordinate(result):
                    return result
                return None
        
        if isinstance(result, dict):
            results = result.get("results", [])
            if results and isinstance(results, list):
                # ✅ 优先选择匹配城市的结果
                if prefer_city and len(results) > 1:
                    for item in results:
                        if isinstance(item, dict):
                            item_city = item.get("city", "")
                            item_province = item.get("province", "")
                            # 检查城市或省份是否匹配
                            if (prefer_city in item_city or 
                                prefer_city in item_province or
                                item_city.replace("市", "") in prefer_city):
                                loc = item.get("location", "")
                                if isinstance(loc, str) and self._is_coordinate(loc):
                                    if _env_bool("MCP_DEBUG"):
                                        print(f"[GeoCode] 匹配城市 {item_city}: {loc}")
                                    return loc
                
                # 取第一个结果
                first = results[0]
                if isinstance(first, dict) and "location" in first:
                    loc = first["location"]
                    if isinstance(loc, str) and self._is_coordinate(loc):
                        return loc
            
            # 备用格式
            if "location" in result:
                loc = result["location"]
                if isinstance(loc, str) and self._is_coordinate(loc):
                    return loc
        
        return None

    def _is_coordinate(self, location: str) -> bool:
        """检查是否是经纬度坐标格式"""
        if not location:
            return False
        parts = location.split(",")
        if len(parts) != 2:
            return False
        try:
            lng = float(parts[0].strip())
            lat = float(parts[1].strip())
            return 73 < lng < 136 and 3 < lat < 54
        except ValueError:
            return False

    def _plan_transit(self, client: Any, origin: str, destination: str, city: str) -> Any:
        """公交路线规划"""
        params = {
            "origin": origin,
            "destination": destination,
            "city": city,
            "cityd": city,
        }
        return client.call_tool("maps_direction_transit_integrated", params)

    def _plan_other(self, client: Any, origin: str, destination: str, mode: str) -> Any:
        """驾车/步行/骑行路线规划"""
        tool_mapping = {
            "driving": "maps_direction_driving",
            "walking": "maps_direction_walking", 
            "bicycling": "maps_direction_bicycling",
        }
        tool_name = tool_mapping.get(mode, "maps_direction_driving")
        params = {"origin": origin, "destination": destination}
        return client.call_tool(tool_name, params)

    def _format_route_result(self, result: Any, origin: str, destination: str, mode: str) -> str:
      """格式化路线规划结果，保留完整信息"""
      if isinstance(result, str):
          if "失败" in result or "INVALID" in result or "error" in result.lower():
              return json.dumps({
                  "origin": origin,
                  "destination": destination,
                  "mode": mode,
                  "error": result
              }, ensure_ascii=False, indent=2)
          
          try:
              result = json.loads(result)
          except json.JSONDecodeError:
              return json.dumps({
                  "origin": origin,
                  "destination": destination,
                  "mode": mode,
                  "raw_result": result
              }, ensure_ascii=False, indent=2)
      
      formatted = {
          "origin": origin,
          "destination": destination,
          "mode": mode,
      }
      
      if isinstance(result, dict):
          # 检查错误
          if "error" in result:
              formatted["error"] = result.get("error")
              return json.dumps(formatted, ensure_ascii=False, indent=2)
          
          if result.get("status") == "0":
              formatted["error"] = result.get("info", "API调用失败")
              return json.dumps(formatted, ensure_ascii=False, indent=2)
          
          # 保存原始坐标
          if "origin" in result:
              formatted["origin_coord"] = result["origin"]
          if "destination" in result:
              formatted["destination_coord"] = result["destination"]
          
          # 驾车/骑行/步行路线
          paths = result.get("paths", [])
          if paths:
              path = paths[0]
              formatted.update(self._parse_path(path))
              
              # ✅ 保存详细步骤（用于后续展示导航）
              steps = path.get("steps", [])
              if steps:
                  formatted["steps"] = self._parse_steps(steps)
                  formatted["steps_count"] = len(steps)
          
          # 公交路线
          transits = result.get("transits", [])
          if transits:
              transit = transits[0]
              formatted.update(self._parse_transit(transit))
      
      return json.dumps(formatted, ensure_ascii=False, indent=2)


    def _parse_path(self, path: dict) -> dict:
        """解析驾车/步行/骑行路径"""
        result = {}
        
        distance = path.get("distance", 0)
        duration = path.get("duration", 0)
        
        if isinstance(distance, str):
            distance = int(distance) if distance.isdigit() else 0
        if isinstance(duration, str):
            duration = int(duration) if duration.isdigit() else 0
        
        # 保存原始数值（方便后续计算）
        result["distance_meters"] = distance
        result["duration_seconds"] = duration
        
        # 格式化显示
        result["distance"] = f"{distance / 1000:.1f} 公里"
        result["duration"] = f"{duration // 60} 分钟"
        
        if path.get("strategy"):
            result["strategy"] = path["strategy"]
        
        if path.get("tolls"):
            tolls = path["tolls"]
            if isinstance(tolls, str):
                tolls = float(tolls) if tolls else 0
            result["tolls"] = f"{tolls} 元"
            result["tolls_amount"] = tolls
        
        if path.get("toll_distance"):
            toll_dist = path["toll_distance"]
            if isinstance(toll_dist, str):
                toll_dist = int(toll_dist) if toll_dist.isdigit() else 0
            result["toll_distance"] = f"{toll_dist / 1000:.1f} 公里"
        
        # 保存路径坐标（用于地图绘制）
        if path.get("path"):
            result["polyline"] = path["path"]
        
        return result


    def _parse_steps(self, steps: list) -> list:
        """解析路线步骤"""
        parsed_steps = []
        
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            
            parsed_step = {
                "index": i + 1,
                "instruction": step.get("instruction", ""),
                "road": step.get("road", ""),
                "orientation": step.get("orientation", ""),
            }
            
            # 距离
            distance = step.get("distance", 0)
            if isinstance(distance, str):
                distance = int(distance) if distance.isdigit() else 0
            parsed_step["distance"] = distance
            parsed_step["distance_text"] = f"{distance}米" if distance < 1000 else f"{distance/1000:.1f}公里"
            
            # 时间
            duration = step.get("duration", 0)
            if isinstance(duration, str):
                duration = int(duration) if duration.isdigit() else 0
            parsed_step["duration"] = duration
            parsed_step["duration_text"] = f"{duration}秒" if duration < 60 else f"{duration//60}分钟"
            
            parsed_steps.append(parsed_step)
        
        return parsed_steps


    def _parse_transit(self, transit: dict) -> dict:
        """解析公交换乘方案"""
        result = {}
        
        distance = transit.get("distance", 0)
        duration = transit.get("duration", 0)
        
        if isinstance(distance, str):
            distance = int(distance) if distance.isdigit() else 0
        if isinstance(duration, str):
            duration = int(duration) if duration.isdigit() else 0
        
        # 保存原始数值
        result["distance_meters"] = distance
        result["duration_seconds"] = duration
        
        # 格式化显示
        result["distance"] = f"{distance / 1000:.1f} 公里"
        result["duration"] = f"{duration // 60} 分钟"
        
        # 费用
        if transit.get("cost"):
            cost = transit["cost"]
            if isinstance(cost, str):
                cost = float(cost) if cost else 0
            result["cost"] = f"{cost} 元"
            result["cost_amount"] = cost
        
        # 步行距离
        walking = transit.get("walking_distance", 0)
        if isinstance(walking, str):
            walking = int(walking) if walking.isdigit() else 0
        result["walking_distance"] = f"{walking} 米"
        result["walking_distance_meters"] = walking
        
        # 换乘次数
        if transit.get("segments"):
            segments = transit["segments"]
            result["segments"] = self._parse_transit_segments(segments)
            # 计算换乘次数（公交/地铁段数 - 1）
            bus_count = sum(1 for s in segments if s.get("bus") or s.get("railway"))
            result["transfer_count"] = max(0, bus_count - 1)
        
        return result


    def _parse_transit_segments(self, segments: list) -> list:
        """解析公交换乘段"""
        parsed_segments = []
        
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            
            parsed_seg = {}
            
            # 步行段
            walking = seg.get("walking", {})
            if walking:
                distance = walking.get("distance", 0)
                if isinstance(distance, str):
                    distance = int(distance) if distance.isdigit() else 0
                if distance > 0:
                    parsed_seg = {
                        "type": "walking",
                        "distance": distance,
                        "distance_text": f"步行{distance}米",
                    }
                    parsed_segments.append(parsed_seg)
            
            # 公交段
            bus = seg.get("bus", {})
            if bus and bus.get("buslines"):
                buslines = bus["buslines"]
                if isinstance(buslines, list) and buslines:
                    busline = buslines[0]
                    parsed_seg = {
                        "type": "bus",
                        "name": busline.get("name", ""),
                        "departure_stop": busline.get("departure_stop", {}).get("name", ""),
                        "arrival_stop": busline.get("arrival_stop", {}).get("name", ""),
                        "via_num": busline.get("via_num", 0),
                        "duration": busline.get("duration", 0),
                    }
                    parsed_segments.append(parsed_seg)
            
            # 地铁/轨道交通段
            railway = seg.get("railway", {})
            if railway:
                parsed_seg = {
                    "type": "railway",
                    "name": railway.get("name", ""),
                    "departure_stop": railway.get("departure_stop", {}).get("name", ""),
                    "arrival_stop": railway.get("arrival_stop", {}).get("name", ""),
                    "via_num": railway.get("via_stops", []),
                }
                parsed_segments.append(parsed_seg)
        
        return parsed_segments

# ============ 地理编码工具 ============

class GeoCodeSchema(BaseModel):
    address: str = Field(description="要查询的地址，如：北京市朝阳区阜通东大街6号")
    city: str = Field(default="", description="城市名称，可选，用于提高准确性")


class GeoCodeTool(BaseTool):
    """地理编码：地址转坐标（使用高德地图MCP）"""
    name: str = "geo_code"
    description: str = "将地址转换为经纬度坐标，可用于后续的路线规划或周边搜索。"
    args_schema: Type[BaseModel] = GeoCodeSchema

    def _run(self, address: str, city: str = "") -> str:
        try:
            client = get_amap_mcp_client()
            
            arguments = {"address": address}
            if city:
                arguments["city"] = city
            
            result = client.call_tool("maps_geo", arguments)
            
            print("maps_geo",result)
            if result:
                return self._format_geocode_result(result, address)
            else:
                return json.dumps({
                    "error": "地理编码无结果",
                    "address": address
                }, ensure_ascii=False)
                
        except Exception as e:
            return json.dumps({
                "error": f"地理编码失败: {str(e)}",
                "address": address
            }, ensure_ascii=False)

    def _format_geocode_result(self, result: Any, address: str) -> str:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return json.dumps({
                    "address": address,
                    "raw_result": result
                }, ensure_ascii=False, indent=2)
        
        if isinstance(result, dict):
            geocodes = result.get("geocodes", [])
            if geocodes:
                geo = geocodes[0]
                return json.dumps({
                    "address": address,
                    "formatted_address": geo.get("formatted_address", ""),
                    "location": geo.get("location", ""),
                    "province": geo.get("province", ""),
                    "city": geo.get("city", ""),
                    "district": geo.get("district", "")
                }, ensure_ascii=False, indent=2)
        
        return json.dumps({
            "address": address,
            "raw_result": str(result)
        }, ensure_ascii=False, indent=2)


# ============ POI搜索工具 ============

class KeywordSearchSchema(BaseModel):
    keywords: str = Field(description="搜索关键词，如：西湖、杭州东站、灵隐寺、肯德基等")
    city: str = Field(description="城市名称，如：杭州、上海、北京")
    limit: int = Field(default=20, description="返回结果数量限制，默认20条")


class KeywordSearchTool(BaseTool):
    """关键词搜索POI（使用高德地图MCP）"""
    name: str = "search_poi"
    description: str = "在指定城市搜索POI（兴趣点），如景点、餐厅、酒店、车站等地点。返回名称、地址、类型、图片等信息。"
    args_schema: Type[BaseModel] = KeywordSearchSchema

    def _get_type_name(self, typecode: str) -> str:
        """根据类型码获取类型名称"""
        if not typecode:
            return "其他"
        
        typecode = str(typecode).strip()
        
        # 1. 精确匹配
        if typecode in TYPECODE_MAP:
            return TYPECODE_MAP[typecode]
        
        # 2. 匹配前4位（子类）
        if len(typecode) >= 4:
            prefix4 = typecode[:4] + "00"
            if prefix4 in TYPECODE_MAP:
                return TYPECODE_MAP[prefix4]
        
        # 3. 匹配前2位（大类）
        if len(typecode) >= 2:
            prefix2 = typecode[:2] + "0000"
            if prefix2 in TYPECODE_MAP:
                return TYPECODE_MAP[prefix2]
        
        # 4. 根据首位数字猜测大类
        first_digit = typecode[0] if typecode else ""
        category_map = {
            "0": "汽车服务",
            "1": "风景名胜",
            "2": "商务住宅",
            "3": "政府机构",
            "4": "科教文化",
            "5": "餐饮服务",
            "6": "购物服务",
            "7": "生活服务",
            "8": "体育休闲",
            "9": "医疗保健",
        }
        return category_map.get(first_digit, "其他")

    def _run(self, keywords: str, city: str, limit: int = 20) -> str:
        try:
            client = get_amap_mcp_client()
            
            result = client.call_tool("maps_text_search", {
                "keywords": keywords,
                "city": city
            })
            
            if _env_bool("MCP_DEBUG"):
                print(f"[POI Search] keywords={keywords}, city={city}")
                poi_count = len(result.get("pois", [])) if isinstance(result, dict) else 0
                print(f"[POI Search] 原始返回 {poi_count} 条结果")
            
            if result:
                return self._format_search_result(result, keywords, city, limit)
            else:
                return json.dumps({
                    "error": "搜索无结果",
                    "keywords": keywords,
                    "city": city
                }, ensure_ascii=False)
                
        except Exception as e:
            return json.dumps({
                "error": f"搜索失败: {str(e)}",
                "keywords": keywords,
                "city": city
            }, ensure_ascii=False)

    def _format_search_result(self, result: Any, keywords: str, city: str, limit: int = 20) -> str:
        """格式化搜索结果"""
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return json.dumps({
                    "keywords": keywords,
                    "city": city,
                    "raw_result": result
                }, ensure_ascii=False, indent=2)
        
        pois = []
        if isinstance(result, dict):
            pois = result.get("pois", [])
        elif isinstance(result, list):
            pois = result
        
        # 处理搜索建议（可选）
        suggestion = None
        if isinstance(result, dict) and result.get("suggestion"):
            sug = result["suggestion"]
            if sug.get("keywords"):
                suggestion = {"keywords": sug["keywords"]}
        
        # 格式化 POI 列表
        formatted_pois = []
        for poi in pois[:limit]:  # 使用 limit 参数控制数量
            if not isinstance(poi, dict):
                continue
            
            # 获取类型名称
            typecode = poi.get("typecode", "")
            type_name = self._get_type_name(typecode)
            
            # 构建格式化的 POI 信息
            formatted_poi = {
                "id": poi.get("id", ""),
                "name": poi.get("name", "").strip(),
                "address": poi.get("address", ""),
                "type": type_name,
                "typecode": typecode,
            }
            
            # 添加图片（如果有）
            photo = poi.get("photo")
            if photo:
                formatted_poi["photo"] = photo
            
            # 添加经纬度（如果有）
            location = poi.get("location")
            if location:
                formatted_poi["location"] = location
            
            # 添加电话（如果有）
            tel = poi.get("tel")
            if tel:
                formatted_poi["tel"] = tel
            
            # 添加评分（如果有）
            rating = poi.get("biz_ext", {}).get("rating") if isinstance(poi.get("biz_ext"), dict) else None
            if rating:
                formatted_poi["rating"] = rating
            
            formatted_pois.append(formatted_poi)
        
        # 构建返回结果
        response = {
            "keywords": keywords,
            "city": city,
            "count": len(formatted_pois),
            "total": len(pois),
            "pois": formatted_pois
        }
        
        # 添加搜索建议
        if suggestion:
            response["suggestion"] = suggestion
        
        return json.dumps(response, ensure_ascii=False, indent=2)

# ============ 旅行计划生成工具 ============

class TravelPlanSchema(BaseModel):
    destination: str = Field(description="目的地城市")
    days: int = Field(description="旅行天数")
    origin: str = Field(default="", description="出发城市")
    date_range: str = Field(default="", description="出行日期范围")
    group_type: str = Field(default="", description="出行人群类型：家庭/情侣/朋友/独自")
    preferences: List[str] = Field(default_factory=list, description="偏好：美食/购物/自然/历史/网红打卡等")
    budget: str = Field(default="", description="预算范围：经济/中等/高端")
    max_searches: int = Field(default=2, description="最大搜索次数，控制搜索循环次数")
    skip_map: bool = Field(default=False, description="是否跳过地图路线验证")
    include_weather: bool = Field(default=True, description="是否查询天气信息")

class TravelPlanTool(BaseTool):
    """生成完整的旅行计划"""
    name: str = "generate_travel_plan"
    description: str = """根据用户需求生成完整的旅行计划。
    工作流程：
    1. 搜索小红书获取目的地攻略（可循环多次直到信息充足）
    2. 总结提取规划规则
    3. 查询目的地天气（可选）
    4. 生成详细行程
    5. 验证交通路线（可选）
    6. 润色输出最终计划

    必需参数：destination（目的地）、days（天数）
    """
    args_schema: Type[BaseModel] = TravelPlanSchema
    
    _graph: Any = PrivateAttr(default=None)
    _current_session_id: str = PrivateAttr(default="")  # ✅ 存储当前 session_id
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
    ) -> str:
        from src.models.schemas import UserProfile, PlanningRules
        
        # ✅ 获取 session_id（优先级：实例变量 > 上下文变量）
        final_session_id = self._current_session_id or get_session_id()

        print(f"\n{'='*60}")
        print(f"🚀 开始生成旅行计划")
        print(f"   📍 目的地: {destination}")
        print(f"   📅 天数: {days} 天")
        print(f"   🏠 出发地: {origin or '未指定'}")
        print(f"   👥 出行类型: {group_type or '未指定'}")
        print(f"   💝 偏好: {preferences or '无特殊偏好'}")
        print(f"   💰 预算: {budget or '中等'}")
        print(f"   🔍 最大搜索次数: {max_searches}")
        print(f"   🗺️ 地图验证: {'跳过' if skip_map else '启用'}")
        print(f"   🌤️ 天气查询: {'启用' if include_weather else '跳过'}")
        print(f"{'='*60}\n")
        
        # 校验 session_id
        if not final_session_id:
            print("⚠️ Warning: session_id 为空，结果将无法缓存")

        if final_session_id:
          redis_service.update_plan_status(
              final_session_id, 
              status="processing", 
              progress=10,
              message="开始生成旅行计划..."
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

        # 构建初始状态
        initial_state = {
            "user_profile": user_profile,
            # 搜索相关
            "session_id": final_session_id,  # ✅ 添加这行
            "search_results": None,
            "_search_count": 0,
            "_max_searches": max_searches,
            "_search_queries": [],
            # 规划相关
            "planning_rules": None,
            "draft_plan": None,
            "validated_plan": None,
            # 可选功能控制
            "skip_map_validation": True,
            "weather_info": None if include_weather else {"skipped": True},
            # 输出
            "final_result": None,
        }

        try:
            # 检查工作流是否初始化
            if self._graph is None:

              error_msg = "旅行规划工作流未初始化"
              if final_session_id:
                  redis_service.update_plan_status(
                      final_session_id, 
                      status="failed", 
                      message=error_msg
                  )
              return self._error_response(
                  "旅行规划工作流未初始化，请确保正确传入 travel_graph",
                  destination, days
              )
            
            # 执行工作流
            print("🔄 开始执行工作流...")
            print(f"   初始状态 session_id: {initial_state.get('session_id')}")  # ← 验证
            final_state = self._graph.invoke(initial_state)
            
            # 提取结果
            return self._process_result(final_state, destination, days, user_profile)
                
        except Exception as e:
            import traceback
            print(f"\n❌ 工作流执行异常:")
            traceback.print_exc()

            if final_session_id:
              redis_service.update_plan_status(
                  final_session_id, 
                  status="failed", 
                  message=str(e)
              )

            return self._error_response(str(e), destination, days)

    def _process_result(
        self, 
        final_state: dict, 
        destination: str, 
        days: int,
        user_profile: Any
    ) -> str:
        """处理工作流返回结果"""
        
        result = final_state.get("final_result")
        session_id = final_state.get("session_id", "")
        
        if result:
            print("\n✅ 旅行计划生成成功!")
            
            # 转换为字典
            if hasattr(result, 'model_dump'):
                plan_dict = result.model_dump()
            elif hasattr(result, 'dict'):
                plan_dict = result.dict()
            else:
                plan_dict = result
            
            # 添加元信息
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
                # 包含中间数据（可选，用于调试）
                "meta": {
                    "search_count": final_state.get("_search_count", 0),
                    "has_weather": final_state.get("weather_info") is not None,
                    "has_map_validation": final_state.get("validated_plan") is not None,
                }
            }
            
            return json.dumps(response, ensure_ascii=False, indent=2)
        
        else:
            # 尝试从其他字段获取部分结果
            draft_plan = final_state.get("draft_plan")
            validated_plan = final_state.get("validated_plan")
            planning_rules = final_state.get("planning_rules")
            
            if validated_plan or draft_plan:
                print("\n⚠️ 未生成最终结果，但有草案数据")
                return json.dumps({
                    "success": False,
                    "partial": True,
                    "destination": destination,
                    "days": days,
                    "draft_plan": validated_plan or draft_plan,
                    "planning_rules": planning_rules.model_dump() if planning_rules and hasattr(planning_rules, 'model_dump') else None,
                    "message": "规划未完全完成，返回草案数据"
                }, ensure_ascii=False, indent=2)
            
            elif planning_rules:
                print("\n⚠️ 仅完成搜索总结阶段")
                return json.dumps({
                    "success": False,
                    "partial": True,
                    "destination": destination,
                    "days": days,
                    "planning_rules": planning_rules.model_dump() if hasattr(planning_rules, 'model_dump') else str(planning_rules),
                    "message": "仅完成信息收集，未生成行程"
                }, ensure_ascii=False, indent=2)
            
            else:
                return self._error_response(
                    "工作流执行完成但无有效结果",
                    destination, days
                )

    def _error_response(self, error_msg: str, destination: str, days: int) -> str:
        """生成错误响应"""
        return json.dumps({
            "success": False,
            "error": error_msg,
            "destination": destination,
            "days": days,
            "suggestion": "请检查网络连接或稍后重试"
        }, ensure_ascii=False, indent=2)


# ============ 简化版工具（不依赖工作流） ============

class QuickTravelPlanTool(BaseTool):
    """快速生成旅行计划（直接使用 LLM，不走完整工作流）"""
    name: str = "quick_travel_plan"
    description: str = "快速生成简单的旅行计划建议，适合简单咨询。如需详细规划请使用 generate_travel_plan。"
    args_schema: Type[BaseModel] = TravelPlanSchema

    def _run(
        self,
        destination: str,
        days: int,
        origin: str = "",
        date_range: str = "",
        group_type: str = "",
        preferences: List[str] = None,
        budget: str = "",
        **kwargs  # 忽略其他参数
    ) -> str:
        from langchain_openai import ChatOpenAI
        import os
        
        llm = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "qwen-plus"),
            temperature=0.7,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE"),
        )
        
        prompt = f"""请为以下旅行需求生成一个简洁的行程建议：
        目的地：{destination}
        天数：{days} 天
        出发地：{origin or '未指定'}
        出行类型：{group_type or '未指定'}
        偏好：{', '.join(preferences) if preferences else '无特殊偏好'}
        预算：{budget or '中等'}
        日期：{date_range or '灵活'}

        请生成一个简洁的行程概览，包括：
        1. 每天的主要安排（2-3个景点/活动）
        2. 简单的交通建议
        3. 1-2条实用小贴士

        用轻松友好的语气，适当使用 emoji。
        """
        
        try:
            response = llm.invoke(prompt)
            return json.dumps({
                "success": True,
                "type": "quick_plan",
                "destination": destination,
                "days": days,
                "suggestion": response.content
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "destination": destination,
                "days": days
            }, ensure_ascii=False)

# ============ 工具工厂函数 ============
def get_all_tools(travel_graph: Any = None) -> List[BaseTool]:
    """获取所有可用工具"""
    
    tools = [
        # 搜索工具
        # XiaohongshuSearchTool(),
        
        # # 地图工具
        # NearbySearchTool(),
        # RoutePlanTool(),
        # GeoCodeTool(),
        
        # # 天气工具
        WeatherTool(),
        
        # 规划工具
        TravelPlanTool(travel_graph=travel_graph),
        # QuickTravelPlanTool(),  # 快速规划备选
    ]
    
    return tools


def get_amap_tools() -> List[BaseTool]:
    """仅获取高德地图相关工具"""
    return [
        WeatherTool(),
        NearbySearchTool(),
        KeywordSearchTool(),
        RoutePlanTool(),
        GeoCodeTool(),
    ]

