# src/utils/value_evaluator.py

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set
import re
from collections import Counter
from enum import Enum


class InfoCategory(Enum):
    """信息类别"""
    ROUTE = "route"                 # 路线行程
    ATTRACTION = "attraction"       # 景点信息
    FOOD = "food"                   # 美食推荐
    TRANSPORT = "transport"         # 交通信息
    ACCOMMODATION = "accommodation" # 住宿信息
    AVOID = "avoid"                 # 避坑指南
    UNKNOWN = "unknown"             # 未知


@dataclass
class NoteScore:
    """笔记评分结果"""
    note_index: int
    title: str
    relevance_score: float
    information_density: float
    uniqueness_score: float
    final_score: float
    key_info: List[str]
    categories: List[str] = field(default_factory=list)  # 笔记包含的信息类别


class InformationValueEvaluator:
    """
    信息价值评估器 - 适配按类别搜索策略
    
    功能：
    1. 评估笔记价值
    2. 检测信息类别
    3. 按类别筛选笔记
    4. 智能压缩内容
    """
    
    # ============ 分类别关键词 ============
    CATEGORY_KEYWORDS = {
        InfoCategory.ROUTE: {
            "high": ["路线", "行程", "攻略", "day1", "day2", "day3", "第一天", "第二天", "第三天", "安排"],
            "medium": ["规划", "计划", "游玩", "顺序"],
            "weight": 3
        },
        InfoCategory.ATTRACTION: {
            "high": ["景点", "必去", "必玩", "打卡", "推荐", "游览", "参观"],
            "medium": ["门票", "开放时间", "预约", "排队", "闭馆"],
            "weight": 3
        },
        InfoCategory.FOOD: {
            "high": ["美食", "必吃", "好吃", "餐厅", "小吃", "特色", "推荐吃"],
            "medium": ["饭店", "人均", "口味", "招牌", "排队"],
            "weight": 2
        },
        InfoCategory.TRANSPORT: {
            "high": ["交通", "地铁", "公交", "高铁", "机场", "怎么去"],
            "medium": ["打车", "步行", "骑行", "换乘", "站点"],
            "weight": 2
        },
        InfoCategory.ACCOMMODATION: {
            "high": ["住宿", "酒店", "民宿", "住哪", "推荐住"],
            "medium": ["入住", "房间", "位置", "价格", "预订"],
            "weight": 2
        },
        InfoCategory.AVOID: {
            "high": ["避坑", "避雷", "踩坑", "不要", "别去", "注意", "坑"],
            "medium": ["小心", "警惕", "差评", "失望", "后悔"],
            "weight": 3
        },
    }
    
    # ============ 通用高价值关键词 ============
    HIGH_VALUE_KEYWORDS = {
        # 时间相关
        "第一天": 3, "第二天": 3, "第三天": 3,
        "day1": 3, "day2": 3, "day3": 3,
        "上午": 1, "下午": 1, "晚上": 1,
        
        # 推荐相关
        "必去": 3, "必玩": 3, "必吃": 3,
        "推荐": 2, "强烈推荐": 3,
        "本地人": 2, "老字号": 2,
        
        # 实用信息
        "门票": 2, "开放时间": 2, "预约": 2,
        "免费": 2, "排队": 2, "闭馆": 2,
        "交通": 2, "地铁": 2, "公交": 2,
        "价格": 2, "人均": 2, "费用": 2,
        
        # 路线相关
        "路线": 3, "行程": 3, "攻略": 2,
        "顺路": 2, "步行": 1,
        
        # 避坑相关
        "避坑": 3, "避雷": 3, "踩坑": 3,
        "不要": 2, "别去": 2, "注意": 2,
    }
    
    # ============ 低价值标记 ============
    LOW_VALUE_MARKERS = [
        "广告", "推广", "合作", "优惠券", "限时",
        "私信", "评论区", "链接", "点击购买",
        "加微信", "加我", "找我", "代购",
    ]
    
    def __init__(
        self, 
        destination: str, 
        days: int, 
        preferences: List[str] = None,
        target_categories: List[str] = None  # 目标信息类别
    ):
        self.destination = destination
        self.days = days
        self.preferences = preferences or []
        self.target_categories = target_categories or []
        self._seen_info: Set[str] = set()
        self._seen_places: Set[str] = set()
    
    # ============ 安全转换方法 ============
    
    @staticmethod
    def _safe_int(value: Any) -> int:
        """安全转换为整数"""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return 0
            try:
                multiplier = 1
                if value.endswith(('k', 'K')):
                    multiplier = 1000
                    value = value[:-1]
                elif value.endswith(('w', 'W', '万')):
                    multiplier = 10000
                    value = value[:-1]
                value = value.replace(',', '').replace('，', '')
                return int(float(value) * multiplier)
            except (ValueError, TypeError):
                return 0
        return 0
    
    @staticmethod
    def _safe_str(value: Any) -> str:
        """安全转换为字符串"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
    
    # ============ 信息类别检测 ============
    
    def detect_categories(self, text: str) -> List[InfoCategory]:
        """检测文本包含的信息类别"""
        text_lower = text.lower()
        detected = []
        
        for category, config in self.CATEGORY_KEYWORDS.items():
            high_count = sum(1 for kw in config["high"] if kw in text_lower)
            medium_count = sum(1 for kw in config["medium"] if kw in text_lower)
            
            # 高权重关键词匹配2个以上，或中权重匹配3个以上
            if high_count >= 2 or (high_count >= 1 and medium_count >= 2):
                detected.append(category)
        
        return detected if detected else [InfoCategory.UNKNOWN]
    
    def get_category_score(self, text: str, category: InfoCategory) -> float:
        """计算特定类别的匹配分数"""
        if category not in self.CATEGORY_KEYWORDS:
            return 0
        
        text_lower = text.lower()
        config = self.CATEGORY_KEYWORDS[category]
        
        high_count = sum(1 for kw in config["high"] if kw in text_lower)
        medium_count = sum(1 for kw in config["medium"] if kw in text_lower)
        
        score = high_count * 0.15 + medium_count * 0.08
        return min(1.0, score)
    
    # ============ 核心评估方法 ============
    
    def evaluate_notes(self, notes: List[Dict]) -> List[NoteScore]:
        """评估笔记列表"""
        scores = []
        
        for idx, note in enumerate(notes):
            title = self._safe_str(note.get("title", ""))
            content = self._safe_str(note.get("content", note.get("desc", "")))
            likes = note.get("likes", 0)
            
            score = self._evaluate_single_note(idx, title, content, likes)
            scores.append(score)
        
        # 按最终分数排序
        scores.sort(key=lambda x: x.final_score, reverse=True)
        return scores
    
    def _evaluate_single_note(
        self, 
        idx: int, 
        title: str, 
        content: str, 
        likes: Any
    ) -> NoteScore:
        """评估单条笔记"""
        text = f"{title} {content}".lower()
        
        # 检测信息类别
        categories = self.detect_categories(text)
        category_names = [c.value for c in categories]
        
        # 计算各项分数
        relevance = self._calc_relevance(text, categories)
        density, key_info = self._calc_information_density(text)
        uniqueness = self._calc_uniqueness(key_info)
        
        # 社交分数
        likes_int = self._safe_int(likes)
        social_bonus = min(0.15, likes_int / 10000) if likes_int > 0 else 0
        
        # 低价值惩罚
        penalty = self._calc_penalty(text)
        
        # 类别匹配奖励（如果有目标类别）
        category_bonus = 0
        if self.target_categories:
            matched = [c for c in category_names if c in self.target_categories]
            category_bonus = len(matched) * 0.1
        
        # 最终分数
        final_score = (
            relevance * 0.25 + 
            density * 0.35 + 
            uniqueness * 0.20 +
            social_bonus +
            category_bonus
        ) * (1 - penalty)
        
        return NoteScore(
            note_index=idx,
            title=title[:50],
            relevance_score=relevance,
            information_density=density,
            uniqueness_score=uniqueness,
            final_score=final_score,
            key_info=key_info[:5],
            categories=category_names
        )
    
    def _calc_relevance(self, text: str, categories: List[InfoCategory]) -> float:
        """计算相关性分数"""
        score = 0
        
        # 目的地匹配
        if self.destination.lower() in text:
            score += 0.3
        
        # 天数匹配
        day_patterns = [
            f"{self.days}天", f"{self.days}日", 
            f"{self.days}d", f"{self.days}day"
        ]
        if any(p in text for p in day_patterns):
            score += 0.15
        
        # 偏好匹配
        pref_matches = sum(1 for p in self.preferences if p.lower() in text)
        score += min(0.15, pref_matches * 0.05)
        
        # 高价值关键词
        keyword_score = sum(
            weight for kw, weight in self.HIGH_VALUE_KEYWORDS.items() 
            if kw in text
        )
        score += min(0.25, keyword_score / 25)
        
        # 类别权重加成
        for category in categories:
            if category in self.CATEGORY_KEYWORDS:
                weight = self.CATEGORY_KEYWORDS[category]["weight"]
                score += weight * 0.03
        
        return min(1.0, score)
    
    def _calc_information_density(self, text: str) -> Tuple[float, List[str]]:
        """计算信息密度并提取关键信息"""
        key_info = []
        
        # 时间信息
        time_pattern = r'(\d{1,2}[：:]\d{2}|\d{1,2}点|上午|下午|早上|晚上)'
        times = re.findall(time_pattern, text)
        if times:
            key_info.append(f"时间: {', '.join(set(times[:3]))}")
        
        # 价格信息
        price_pattern = r'(\d+元|￥\d+|\d+块|人均\d+)'
        prices = re.findall(price_pattern, text)
        if prices:
            key_info.append(f"价格: {', '.join(set(prices[:3]))}")
        
        # 开放时间
        open_time_pattern = r'(开放时间[：:]\s*[\d:：\-~～至到]+|[\d:：]+\s*[-~～至到]\s*[\d:：]+)'
        open_times = re.findall(open_time_pattern, text)
        if open_times:
            key_info.append(f"开放: {open_times[0]}")
        
        # 门票信息
        ticket_pattern = r'(门票[：:]\s*\d+|票价[：:]\s*\d+|免费|免门票)'
        tickets = re.findall(ticket_pattern, text)
        if tickets:
            key_info.append(f"门票: {', '.join(set(tickets[:2]))}")
        
        # 交通信息
        transport_pattern = r'(地铁\d+号线|公交\d+路|步行\d+分钟|打车\d+[分元]|高铁站|机场)'
        transport = re.findall(transport_pattern, text)
        if transport:
            key_info.append(f"交通: {', '.join(set(transport[:3]))}")
        
        # 景点名称（引号内）
        place_pattern = r'[「【《"\']([\u4e00-\u9fa5]{2,10})[」】》"\']'
        places = re.findall(place_pattern, text)
        new_places = [p for p in places if p not in self._seen_places]
        if new_places:
            key_info.append(f"景点: {', '.join(new_places[:5])}")
            self._seen_places.update(new_places)
        
        # 餐厅/店名
        restaurant_pattern = r'([\u4e00-\u9fa5]{2,8}(?:店|馆|楼|坊|记|居|斋))'
        restaurants = re.findall(restaurant_pattern, text)
        if restaurants:
            key_info.append(f"餐厅: {', '.join(set(restaurants[:3]))}")
        
        # 避坑信息
        avoid_pattern = r'(不要.{2,15}|别.{2,10}|避免.{2,15}|注意.{2,15})'
        avoids = re.findall(avoid_pattern, text)
        if avoids:
            key_info.append(f"避坑: {avoids[0][:20]}")
        
        # 计算密度分数
        text_len = max(len(text), 1)
        density = min(1.0, len(key_info) / max(text_len / 150, 1))
        
        return density, key_info
    
    def _calc_uniqueness(self, key_info: List[str]) -> float:
        """计算独特性"""
        if not key_info:
            return 0.5
        
        new_info = [info for info in key_info if info not in self._seen_info]
        uniqueness = len(new_info) / len(key_info) if key_info else 0.5
        self._seen_info.update(key_info)
        
        return uniqueness
    
    def _calc_penalty(self, text: str) -> float:
        """计算低价值惩罚"""
        penalty_count = sum(1 for marker in self.LOW_VALUE_MARKERS if marker in text)
        
        # 内容过短惩罚
        if len(text) < 100:
            penalty_count += 1
        
        return min(0.5, penalty_count * 0.1)
    
    # ============ 筛选和压缩 ============
    
    def filter_and_compress(
        self, 
        notes: List[Dict], 
        max_notes: int = 5,
        max_chars_per_note: int = 1000,
        required_categories: List[str] = None
    ) -> List[Dict]:
        """
        筛选并压缩笔记
        
        Args:
            notes: 原始笔记列表
            max_notes: 最多保留笔记数
            max_chars_per_note: 单条笔记最大字符
            required_categories: 必须包含的信息类别
            
        Returns:
            筛选压缩后的笔记列表
        """
        if not notes:
            return []
        
        # 评估所有笔记
        scores = self.evaluate_notes(notes)
        
        selected = []
        category_covered = set()
        
        for score in scores:
            # 分数过低跳过
            if score.final_score < 0.15:
                continue
            
            # 已经选够了
            if len(selected) >= max_notes:
                break
            
            original = notes[score.note_index]
            content = self._safe_str(original.get("content", original.get("desc", "")))
            
            # 智能压缩
            compressed = self._compress_content(content, max_chars_per_note)
            
            selected.append({
                "title": self._safe_str(original.get("title", "")),
                "content": compressed,
                "score": round(score.final_score, 3),
                "key_info": score.key_info,
                "categories": score.categories,
                "likes": self._safe_int(original.get("likes", 0))
            })
            
            category_covered.update(score.categories)
        
        # 检查是否覆盖必需类别
        if required_categories:
            missing = set(required_categories) - category_covered
            if missing:
                # 尝试从剩余笔记中补充
                for score in scores[len(selected):]:
                    if not missing:
                        break
                    if any(c in missing for c in score.categories):
                        original = notes[score.note_index]
                        content = self._safe_str(original.get("content", original.get("desc", "")))
                        compressed = self._compress_content(content, max_chars_per_note)
                        
                        selected.append({
                            "title": self._safe_str(original.get("title", "")),
                            "content": compressed,
                            "score": round(score.final_score, 3),
                            "key_info": score.key_info,
                            "categories": score.categories,
                            "likes": self._safe_int(original.get("likes", 0))
                        })
                        
                        missing -= set(score.categories)
        
        return selected
    
    def filter_by_category(
        self,
        notes: List[Dict],
        category: str,
        max_notes: int = 3
    ) -> List[Dict]:
        """按特定类别筛选笔记"""
        # 设置目标类别
        self.target_categories = [category]
        
        return self.filter_and_compress(
            notes,
            max_notes=max_notes,
            required_categories=[category]
        )
    
    def _compress_content(self, content: str, max_chars: int) -> str:
        """智能压缩内容，保留高价值段落"""
        if not content or len(content) <= max_chars:
            return content
        
        # 按换行分段
        paragraphs = content.split('\n')
        
        # 评分每个段落
        scored_paras = []
        for para in paragraphs:
            para = para.strip()
            if not para or len(para) < 5:
                continue
            
            # 计算段落价值
            score = 0
            para_lower = para.lower()
            
            # 关键词得分
            for kw, weight in self.HIGH_VALUE_KEYWORDS.items():
                if kw in para_lower:
                    score += weight
            
            # 包含具体信息加分
            if re.search(r'\d+[元块]', para):
                score += 2
            if re.search(r'\d+[：:]\d+', para):
                score += 2
            if re.search(r'地铁|公交|步行', para):
                score += 1
            
            scored_paras.append((para, score, len(para)))
        
        # 按得分排序，优先保留高价值段落
        scored_paras.sort(key=lambda x: (x[1], -x[2]), reverse=True)
        
        # 拼接结果
        result = []
        current_len = 0
        
        for para, score, length in scored_paras:
            if current_len + length > max_chars:
                # 尝试截断当前段落
                remaining = max_chars - current_len
                if remaining > 50:
                    result.append(para[:remaining] + "...")
                break
            result.append(para)
            current_len += length + 1
        
        return '\n'.join(result) if result else content[:max_chars]
    
    # ============ 统计方法 ============
    
    def get_coverage_report(self, notes: List[Dict]) -> Dict[str, Any]:
        """获取信息覆盖报告"""
        scores = self.evaluate_notes(notes)
        
        category_count = Counter()
        for score in scores:
            for cat in score.categories:
                category_count[cat] += 1
        
        return {
            "total_notes": len(notes),
            "category_distribution": dict(category_count),
            "top_notes": [
                {
                    "title": s.title,
                    "score": round(s.final_score, 3),
                    "categories": s.categories
                }
                for s in scores[:5]
            ],
            "coverage": {
                "route": category_count.get("route", 0) > 0,
                "attraction": category_count.get("attraction", 0) > 0,
                "food": category_count.get("food", 0) > 0,
                "transport": category_count.get("transport", 0) > 0,
                "accommodation": category_count.get("accommodation", 0) > 0,
                "avoid": category_count.get("avoid", 0) > 0,
            }
        }


# ============ 便捷函数 ============

def evaluate_search_results(
    notes: List[Dict],
    destination: str,
    days: int,
    preferences: List[str] = None,
    max_notes: int = 5,
    target_categories: List[str] = None
) -> List[Dict]:
    """
    评估并筛选搜索结果（便捷函数）
    
    Args:
        notes: 搜索结果笔记列表
        destination: 目的地
        days: 天数
        preferences: 用户偏好
        max_notes: 最多保留数量
        target_categories: 目标信息类别
        
    Returns:
        筛选后的笔记列表
    """
    evaluator = InformationValueEvaluator(
        destination=destination,
        days=days,
        preferences=preferences,
        target_categories=target_categories
    )
    
    return evaluator.filter_and_compress(
        notes,
        max_notes=max_notes,
        required_categories=target_categories
    )