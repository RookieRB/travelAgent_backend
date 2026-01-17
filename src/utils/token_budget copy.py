# src/utils/token_budget.py
from dataclasses import dataclass, field
from typing import Dict, Optional, List
import tiktoken
from functools import lru_cache


@dataclass
class TokenBudget:
    """Token 预算配置"""
    # 各阶段预算
    search_filter: int = 1000      # 搜索结果筛选
    summary: int = 3000            # 摘要阶段
    planning: int = 4000           # 规划阶段
    refine: int = 2000             # 润色阶段
    
    # 输入限制
    max_notes_per_search: int = 3  # 每次搜索最多保留笔记数
    max_note_length: int = 800     # 单条笔记最大字符
    max_context_length: int = 5000 # 上下文最大长度
    
    # 总预算
    total_budget: int = 40000
    
    # 当前消耗追踪
    consumed: Dict[str, int] = field(default_factory=dict)
    
    def consume(self, stage: str, tokens: int):
        """记录消耗"""
        self.consumed[stage] = self.consumed.get(stage, 0) + tokens
        
    def get_remaining(self, stage: str) -> int:
        """获取剩余预算"""
        budget_map = {
            "search_filter": self.search_filter,
            "summary": self.summary,
            "planning": self.planning,
            "refine": self.refine,
        }
        used = self.consumed.get(stage, 0)
        return budget_map.get(stage, 0) - used
    
    def get_total_consumed(self) -> int:
        """获取总消耗"""
        return sum(self.consumed.values())
    
    def is_over_budget(self) -> bool:
        """是否超出总预算"""
        return self.get_total_consumed() > self.total_budget
    def get_summary(self) -> Dict:
        """获取消耗摘要"""
        return {
            "consumed": self.consumed.copy(),
            "total": self.get_total_consumed(),
            "budget": self.total_budget,
            "remaining": self.total_budget - self.get_total_consumed(),
        }


class TokenCounter:
    """Token 计数器"""
    
    def __init__(self, model: str = "gpt-3.5-turbo"):
        self.model = model
        self._encoder = None
    
    @property
    def encoder(self):
        if self._encoder is None:
            try:
                self._encoder = tiktoken.encoding_for_model(self.model)
            except KeyError:
                # 对于不支持的模型，使用 cl100k_base
                self._encoder = tiktoken.get_encoding("cl100k_base")
        return self._encoder
    
    def count(self, text: str) -> int:
        """计算文本的 token 数"""
        if not text:
            return 0
        try:
            return len(self.encoder.encode(text))
        except Exception:
            # 兜底：按字符数估算（中文约1.5token/字，英文约0.25token/字）
            chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            other_chars = len(text) - chinese_chars
            return int(chinese_chars * 1.5 + other_chars * 0.3)
    
    def truncate_to_budget(self, text: str, max_tokens: int) -> str:
        """截断文本到指定 token 数"""
        if self.count(text) <= max_tokens:
            return text
        
        # 二分查找合适的截断点
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.count(text[:mid]) <= max_tokens:
                low = mid
            else:
                high = mid - 1
        
        return text[:low] + "..."


# 全局实例
token_counter = TokenCounter()