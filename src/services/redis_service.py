# src/services/redis_service.py
import redis
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime


class RedisService:
    """Redis 服务 - 基础连接和通用操作"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.db = int(os.getenv("REDIS_DB", 0))
        self.password = os.getenv("REDIS_PASSWORD", None)
        
        self._connected = False
        
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            self._test_connection()
        except Exception as e:
            print(f"❌ Redis 初始化失败: {e}")
            self.client = None
            
        self._initialized = True
    
    def _test_connection(self):
        """测试 Redis 连接"""
        try:
            self.client.ping()
            self._connected = True
            print(f"✅ Redis connected: {self.host}:{self.port}")
        except redis.ConnectionError as e:
            self._connected = False
            print(f"⚠️ Redis connection failed: {e}")
    
    def is_connected(self) -> bool:
        """检查 Redis 是否连接正常"""
        if not self.client:
            return False
            
        try:
            self.client.ping()
            self._connected = True
            return True
        except (redis.ConnectionError, redis.TimeoutError, Exception):
            self._connected = False
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取 Redis 统计信息"""
        if not self.is_connected():
            return {"connected": False, "error": "Redis 未连接"}
        
        try:
            info = self.client.info()
            db_info = info.get(f"db{self.db}", {})
            
            # 统计各类 key
            plan_keys = self.client.keys("travel_plans:*")
            status_keys = self.client.keys("travel_plans_status:*")
            
            return {
                "connected": True,
                "host": self.host,
                "port": self.port,
                "db": self.db,
                "redis_version": info.get("redis_version", "unknown"),
                "uptime_days": info.get("uptime_in_days", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "total_keys": db_info.get("keys", 0) if isinstance(db_info, dict) else 0,
                "travel_plans_count": len(plan_keys),
                "travel_status_count": len(status_keys),
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        is_healthy = self.is_connected()
        
        result = {
            "service": "redis",
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": datetime.now().isoformat()
        }
        
        if is_healthy:
            try:
                test_key = "_health_check_test"
                self.client.setex(test_key, 10, "ok")
                value = self.client.get(test_key)
                self.client.delete(test_key)
                
                result["read_write"] = "ok" if value == "ok" else "failed"
                result["latency_ms"] = self._measure_latency()
            except Exception as e:
                result["status"] = "degraded"
                result["error"] = str(e)
        else:
            result["error"] = "Connection failed"
            
        return result
    
    def _measure_latency(self) -> float:
        """测量 Redis 延迟（毫秒）"""
        import time
        try:
            start = time.perf_counter()
            self.client.ping()
            end = time.perf_counter()
            return round((end - start) * 1000, 2)
        except Exception:
            return -1


# 全局单例
redis_service = RedisService()