# src/services/travel_cache.py
"""
旅行规划专用缓存 - 缓存可复用的中间数据，而非 LLM 响应
"""
import json
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime
from src.services.redis_service import redis_service


# src/services/travel_cache.py

class TravelCache:
    """旅行数据缓存"""
    
    # ============ 搜索结果缓存 ============
    
    @staticmethod
    def get_search_results(keyword: str) -> Optional[List[Dict]]:
        """
        获取缓存的搜索结果
        
        Returns:
            - List[Dict]: 有缓存数据
            - []: 缓存的空结果（之前搜索过但没结果）
            - None: 无缓存
        """
        key = f"search:{hashlib.md5(keyword.encode()).hexdigest()[:12]}"
        try:
            data = redis_service.client.get(key)
            if data:
                result = json.loads(data)
                print(f"🎯 搜索缓存命中: {keyword} ({len(result)} 条)")
                return result
            # data 为 None 表示无缓存
            return None
        except Exception as e:
            print(f"⚠️ 缓存读取失败: {e}")
            return None
    
    @staticmethod
    def set_search_results(keyword: str, results: List[Dict], ttl: int = 604800):
        """
        缓存搜索结果（包括空结果）
        
        Args:
            keyword: 搜索关键词
            results: 搜索结果（可以是空列表）
            ttl: 过期时间（秒）
        """
        key = f"search:{hashlib.md5(keyword.encode()).hexdigest()[:12]}"
        try:
            redis_service.client.setex(key, ttl, json.dumps(results, ensure_ascii=False))
            print(f"💾 搜索结果已缓存: {keyword} ({len(results)} 条)")
        except Exception as e:
            print(f"⚠️ 缓存写入失败: {e}")
# 全局实例
travel_cache = TravelCache()