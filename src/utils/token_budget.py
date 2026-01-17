# src/utils/token_budget.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import tiktoken


@dataclass
class TokenBudget:
    """
    Token 预算配置（适配新工作流）
    
    工作流: search → extract → plan
    """
    
    # ============ 各阶段预算 ============
    extract: int = 3000             # 提取阶段
    plan: int = 5000                # 规划阶段
    
    # ============ 搜索控制 ============
    max_notes_per_search: int = 5   # 每次搜索最多保留笔记数
    max_note_length: int = 2000     # 单条笔记最大字符
    max_context_length: int = 6000  # 上下文最大长度
    
    # ============ 总预算 ============
    total_budget: int = 30000
    
    # ============ 消耗追踪 ============
    consumed: Dict[str, int] = field(default_factory=dict)
    
    def consume(self, stage: str, tokens: int):
        """记录消耗"""
        self.consumed[stage] = self.consumed.get(stage, 0) + tokens
    
    def get_stage_budget(self, stage: str) -> int:
        """获取阶段预算"""
        budget_map = {
            "extract": self.extract,
            "plan": self.plan,
        }
        return budget_map.get(stage, 0)
    
    def get_remaining(self, stage: str) -> int:
        """获取阶段剩余预算"""
        budget = self.get_stage_budget(stage)
        used = self.consumed.get(stage, 0)
        return max(0, budget - used)
    
    def get_total_consumed(self) -> int:
        """获取总消耗"""
        return sum(self.consumed.values())
    
    def get_total_remaining(self) -> int:
        """获取总剩余预算"""
        return max(0, self.total_budget - self.get_total_consumed())
    
    def is_over_budget(self) -> bool:
        """是否超出总预算"""
        return self.get_total_consumed() > self.total_budget
    
    def can_afford(self, tokens: int) -> bool:
        """是否能负担指定 token 数"""
        return self.get_total_remaining() >= tokens
    
    def get_summary(self) -> Dict:
        """获取消耗摘要"""
        return {
            "consumed": self.consumed.copy(),
            "total_consumed": self.get_total_consumed(),
            "total_budget": self.total_budget,
            "remaining": self.get_total_remaining(),
            "is_over": self.is_over_budget(),
        }
    
    def print_summary(self):
        """打印消耗摘要"""
        summary = self.get_summary()
        print(f"\n{'─' * 40}")
        print(f"📊 Token 消耗统计:")
        for stage, tokens in summary["consumed"].items():
            budget = self.get_stage_budget(stage)
            if budget > 0:
                pct = tokens / budget * 100
                print(f"   {stage}: {tokens} / {budget} ({pct:.1f}%)")
            else:
                print(f"   {stage}: {tokens}")
        print(f"   {'─' * 20}")
        print(f"   总计: {summary['total_consumed']} / {summary['total_budget']}")
        print(f"   剩余: {summary['remaining']}")
        if summary['is_over']:
            print(f"   ⚠️ 已超出预算!")
        print(f"{'─' * 40}")


class TokenCounter:
    """Token 计数器"""
    
    def __init__(self, model: str = "gpt-4"):
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
            # 兜底：按字符数估算
            return self._estimate_tokens(text)
    
    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数（兜底方案）"""
        # 中文约 1.5 token/字，英文约 0.25 token/字
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars * 0.3)
    
    def count_messages(self, messages: List[Dict]) -> int:
        """计算消息列表的 token 数"""
        total = 0
        for msg in messages:
            # 每条消息有固定开销
            total += 4  # role + content 的开销
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count(content)
        total += 2  # 对话结束标记
        return total
    
    def truncate_to_budget(self, text: str, max_tokens: int) -> str:
        """截断文本到指定 token 数"""
        current_tokens = self.count(text)
        if current_tokens <= max_tokens:
            return text
        
        # 二分查找合适的截断点
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.count(text[:mid]) <= max_tokens:
                low = mid
            else:
                high = mid - 1
        
        # 尝试在句子边界截断
        truncated = text[:low]
        for sep in ["。", "！", "？", ".", "!", "?", "\n"]:
            last_sep = truncated.rfind(sep)
            if last_sep > low * 0.7:  # 至少保留70%
                truncated = truncated[:last_sep + 1]
                break
        
        return truncated + "..."
    
    def truncate_notes(
        self, 
        notes: List[str], 
        max_total_tokens: int,
        max_per_note: int = 500
    ) -> List[str]:
        """
        截断笔记列表
        
        Args:
            notes: 笔记内容列表
            max_total_tokens: 总 token 限制
            max_per_note: 单条笔记 token 限制
            
        Returns:
            截断后的笔记列表
        """
        result = []
        total_tokens = 0
        
        for note in notes:
            # 先截断单条
            truncated = self.truncate_to_budget(note, max_per_note)
            note_tokens = self.count(truncated)
            
            # 检查总量
            if total_tokens + note_tokens > max_total_tokens:
                break
            
            result.append(truncated)
            total_tokens += note_tokens
        
        return result


# ============ 全局实例 ============
token_counter = TokenCounter()


# ============ 便捷函数 ============

def create_budget(
    total: int = 15000,
    extract: int = 3000,
    plan: int = 5000,
    max_notes: int = 5,
    max_note_len: int = 1000,
) -> TokenBudget:
    """
    创建 Token 预算
    
    Args:
        total: 总预算
        extract: 提取阶段预算
        plan: 规划阶段预算
        max_notes: 每次搜索最多笔记数
        max_note_len: 单条笔记最大长度
        
    Returns:
        TokenBudget 实例
    """
    return TokenBudget(
        extract=extract,
        plan=plan,
        max_notes_per_search=max_notes,
        max_note_length=max_note_len,
        total_budget=total,
    )


def estimate_cost(tokens: int, model: str = "gpt-4") -> float:
    """
    估算 API 调用成本（美元）
    
    Args:
        tokens: token 数量
        model: 模型名称
        
    Returns:
        估算成本（美元）
    """
    # 价格表（每1K tokens）
    prices = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "deepseek": {"input": 0.001, "output": 0.002},
    }
    
    price = prices.get(model, prices["gpt-4o-mini"])
    # 假设输入输出各占一半
    avg_price = (price["input"] + price["output"]) / 2
    
    return tokens / 1000 * avg_price