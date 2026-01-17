# src/utils/incremental_summary.py
"""
增量摘要：避免重复处理已总结的内容
"""
from typing import Dict, List, Any
import hashlib
import json


class IncrementalSummarizer:
    """增量摘要器 - 只处理新增内容"""
    
    def __init__(self):
        self._processed_hashes: set = set()
        self._accumulated_info: Dict[str, List] = {
            "routes": [],
            "must_visit": [],
            "avoid": [],
            "tips": []
        }
    
    def get_new_notes(self, notes: List[Dict]) -> List[Dict]:
        """获取未处理过的笔记"""
        new_notes = []
        for note in notes:
            content_hash = self._hash_content(note.get("content", ""))
            if content_hash not in self._processed_hashes:
                new_notes.append(note)
                self._processed_hashes.add(content_hash)
        return new_notes
    
    def merge_info(self, new_info: Dict) -> Dict:
        """合并新信息到累积结果"""
        for key in self._accumulated_info:
            if key in new_info and new_info[key]:
                # 去重合并
                existing = set(str(x) for x in self._accumulated_info[key])
                for item in new_info[key]:
                    if str(item) not in existing:
                        self._accumulated_info[key].append(item)
                        existing.add(str(item))
        
        return self._accumulated_info.copy()
    
    def _hash_content(self, content: str) -> str:
        """计算内容哈希"""
        return hashlib.md5(content.encode()).hexdigest()[:8]


# 在 summary_node 中使用
def incremental_summary_node(state: AgentState) -> AgentState:
    """增量摘要节点"""
    
    summarizer: IncrementalSummarizer = state.get("_summarizer")
    if not summarizer:
        summarizer = IncrementalSummarizer()
        state["_summarizer"] = summarizer
    
    search_results = state.get("search_results")
    if not search_results or not search_results.notes:
        return state
    
    # 获取新笔记
    notes_dicts = [{"content": n.content, "title": n.title} for n in search_results.notes]
    new_notes = summarizer.get_new_notes(notes_dicts)
    
    if not new_notes:
        print("📊 无新笔记需要总结")
        return state
    
    print(f"📊 增量总结: {len(new_notes)} 条新笔记")
    
    # 只总结新笔记...（后续逻辑同原 summary_node）
    # ...
    
    return state