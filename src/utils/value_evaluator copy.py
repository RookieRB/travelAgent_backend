# src/utils/value_evaluator.py
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Any
import re
from collections import Counter


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


class InformationValueEvaluator:
    """信息价值评估器 - 无需LLM的快速评估"""
    
    HIGH_VALUE_KEYWORDS = {
        "路线": 3, "行程": 3, "攻略": 2, "安排": 2,
        "第一天": 3, "第二天": 3, "第三天": 3, "day1": 3, "day2": 3,
        "必去": 3, "必玩": 3, "推荐": 2, "打卡": 2, "网红": 1,
        "门票": 2, "开放时间": 2, "交通": 2, "地铁": 2, "公交": 2,
        "价格": 2, "费用": 2, "预约": 2, "排队": 2,
        "避坑": 3, "避雷": 3, "踩坑": 3, "不要": 2, "别去": 2,
        "美食": 2, "好吃": 2, "住宿": 2, "酒店": 2,
    }
    
    LOW_VALUE_MARKERS = [
        "广告", "推广", "合作", "优惠券", "限时",
        "私信", "评论区", "链接", "点击购买"
    ]
    
    def __init__(self, destination: str, days: int, preferences: List[str] = None):
        self.destination = destination
        self.days = days
        self.preferences = preferences or []
        self._seen_info = set()
    
    @staticmethod
    def _safe_int(value: Any) -> int:
        """安全地将值转换为整数"""
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
        """安全地将值转换为字符串"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
        
    def evaluate_notes(self, notes: List[Dict]) -> List[NoteScore]:
        """评估笔记列表，返回评分结果"""
        scores = []
        
        for idx, note in enumerate(notes):
            # ✅ 安全获取字段
            title = self._safe_str(note.get("title", ""))
            content = self._safe_str(note.get("content", note.get("desc", "")))
            likes = note.get("likes", 0)  # 保持原始类型，在评分时转换
            
            score = self._evaluate_single_note(idx, title, content, likes)
            scores.append(score)
        
        scores.sort(key=lambda x: x.final_score, reverse=True)
        return scores
    
    def _evaluate_single_note(
        self, 
        idx: int, 
        title: str, 
        content: str, 
        likes: Any  # ✅ 接受任意类型
    ) -> NoteScore:
        """评估单条笔记"""
        text = f"{title} {content}".lower()
        
        relevance = self._calc_relevance(text)
        density, key_info = self._calc_information_density(text)
        uniqueness = self._calc_uniqueness(key_info)
        
        # ✅ 安全转换 likes
        likes_int = self._safe_int(likes)
        social_bonus = min(0.2, likes_int / 5000) if likes_int > 0 else 0
        
        penalty = self._calc_penalty(text)
        
        final_score = (
            relevance * 0.3 + 
            density * 0.35 + 
            uniqueness * 0.25 + 
            social_bonus
        ) * (1 - penalty)
        
        return NoteScore(
            note_index=idx,
            title=title[:50],
            relevance_score=relevance,
            information_density=density,
            uniqueness_score=uniqueness,
            final_score=final_score,
            key_info=key_info[:5]
        )
    
    def _calc_relevance(self, text: str) -> float:
        """计算相关性分数"""
        score = 0
        
        if self.destination.lower() in text:
            score += 0.4
        
        day_patterns = [
            f"{self.days}天", f"{self.days}日", 
            f"{self.days}d", f"{self.days}day"
        ]
        if any(p in text for p in day_patterns):
            score += 0.2
        
        pref_matches = sum(1 for p in self.preferences if p.lower() in text)
        score += min(0.2, pref_matches * 0.05)
        
        keyword_score = sum(
            weight for kw, weight in self.HIGH_VALUE_KEYWORDS.items() 
            if kw in text
        )
        score += min(0.2, keyword_score / 20)
        
        return min(1.0, score)
    
    def _calc_information_density(self, text: str) -> Tuple[float, List[str]]:
        """计算信息密度"""
        key_info = []
        
        time_pattern = r'(\d{1,2}[：:]\d{2}|\d{1,2}点|上午|下午|早上|晚上)'
        times = re.findall(time_pattern, text)
        if times:
            key_info.append(f"时间安排: {', '.join(times[:3])}")
        
        price_pattern = r'(\d+元|￥\d+|\d+块)'
        prices = re.findall(price_pattern, text)
        if prices:
            key_info.append(f"价格: {', '.join(prices[:3])}")
        
        place_pattern = r'[「【《"\'](.*?)[」】》"\']'
        places = re.findall(place_pattern, text)
        if places:
            key_info.extend([f"景点: {p}" for p in places[:5]])
        
        transport_pattern = r'(地铁\d+号线|公交\d+路|步行\d+分钟|打车\d+分钟)'
        transport = re.findall(transport_pattern, text)
        if transport:
            key_info.append(f"交通: {', '.join(transport[:3])}")
        
        text_len = max(len(text), 1)
        density = len(key_info) / max(text_len / 200, 1)
        return min(1.0, density), key_info
    
    def _calc_uniqueness(self, key_info: List[str]) -> float:
        """计算独特性"""
        if not key_info:
            return 0.5
        
        new_info = [info for info in key_info if info not in self._seen_info]
        uniqueness = len(new_info) / len(key_info)
        self._seen_info.update(key_info)
        return uniqueness
    
    def _calc_penalty(self, text: str) -> float:
        """计算低价值惩罚"""
        penalty_count = sum(1 for marker in self.LOW_VALUE_MARKERS if marker in text)
        return min(0.5, penalty_count * 0.1)
    
    def filter_and_compress(
        self, 
        notes: List[Dict], 
        max_notes: int = 5,
        max_chars_per_note: int = 800
    ) -> List[Dict]:
        """筛选并压缩笔记"""
        if not notes:
            return []
        
        scores = self.evaluate_notes(notes)
        
        selected = []
        for score in scores[:max_notes]:
            if score.final_score < 0.2:
                continue
            
            original = notes[score.note_index]
            content = self._safe_str(original.get("content", original.get("desc", "")))
            
            compressed = self._compress_content(content, max_chars_per_note)
            
            selected.append({
                "title": self._safe_str(original.get("title", "")),
                "content": compressed,
                "score": score.final_score,
                "key_info": score.key_info,
                "likes": self._safe_int(original.get("likes", 0))  # ✅ 转换为 int
            })
        
        return selected
    
    def _compress_content(self, content: str, max_chars: int) -> str:
        """智能压缩内容"""
        if not content or len(content) <= max_chars:
            return content
        
        paragraphs = content.split('\n')
        
        scored_paras = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            score = sum(
                1 for kw in self.HIGH_VALUE_KEYWORDS 
                if kw in para.lower()
            )
            scored_paras.append((para, score))
        
        scored_paras.sort(key=lambda x: x[1], reverse=True)
        
        result = []
        current_len = 0
        for para, _ in scored_paras:
            if current_len + len(para) > max_chars:
                break
            result.append(para)
            current_len += len(para) + 1
        
        return '\n'.join(result) if result else content[:max_chars]