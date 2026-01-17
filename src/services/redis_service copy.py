# src/services/redis_service.py
import redis
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime


class RedisService:
    """Redis 服务 - 用于存储和获取旅行计划"""
    
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
    
    # ===================== 新增方法 =====================
    
    def is_connected(self) -> bool:
        """
        检查 Redis 是否连接正常
        
        Returns:
            bool: 连接正常返回 True，否则返回 False
        """
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
        """
        获取 Redis 统计信息
        
        Returns:
            包含统计信息的字典
        """
        if not self.is_connected():
            return {
                "connected": False,
                "error": "Redis 未连接"
            }
        
        try:
            # 获取 Redis 服务器信息
            info = self.client.info()
            
            # 获取当前数据库的 key 数量
            db_info = info.get(f"db{self.db}", {})
            
            # 统计旅行计划相关的 key
            plan_keys = self.client.keys("travel_plan:*")
            status_keys = self.client.keys("travel_status:*")
            
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
            return {
                "connected": False,
                "error": str(e)
            }
    
    def get_memory_usage(self, session_id: str) -> Optional[int]:
        """
        获取指定 key 的内存使用量
        
        Args:
            session_id: 会话ID
            
        Returns:
            内存使用字节数，失败返回 None
        """
        if not self.is_connected():
            return None
            
        try:
            key = self._get_plan_key(session_id)
            return self.client.memory_usage(key)
        except Exception:
            return None
    
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查（用于 API 健康检查接口）
        
        Returns:
            健康状态信息
        """
        is_healthy = self.is_connected()
        
        result = {
            "service": "redis",
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": datetime.now().isoformat()
        }
        
        if is_healthy:
            try:
                # 测试读写
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
    
    # ===================== 原有方法 =====================
    
    def _get_plan_key(self, session_id: str) -> str:
        """生成计划的 Redis key"""
        return f"travel_plan:{session_id}"
    
    def _get_status_key(self, session_id: str) -> str:
        """生成状态的 Redis key"""
        return f"travel_status:{session_id}"
    
    def save_plan(
        self, 
        session_id: str, 
        plan_data: Dict[str, Any], 
        expire_seconds: int = 86400 * 7
    ) -> bool:
        """保存旅行计划到 Redis"""
        if not self.is_connected():
            print("⚠️ Redis 未连接，无法保存计划")
            return False
            
        try:
            key = self._get_plan_key(session_id)
            
            data_to_save = {
                "session_id": session_id,
                "data": plan_data,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            
            self.client.setex(
                key, 
                expire_seconds, 
                json.dumps(data_to_save, ensure_ascii=False, default=str)
            )
            
            print(f"✅ Plan saved to Redis: {session_id}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to save plan: {e}")
            return False
    
    def get_plan(self, session_id: str) -> Optional[Dict[str, Any]]:
        """从 Redis 获取旅行计划"""
        if not self.is_connected():
            return None
            
        try:
            key = self._get_plan_key(session_id)
            data = self.client.get(key)
            
            if data:
                return json.loads(data)
            return None
            
        except Exception as e:
            print(f"❌ Failed to get plan: {e}")
            return None
    
    def update_plan_status(
        self, 
        session_id: str, 
        status: str,
        progress: int = 0,
        message: str = ""
    ) -> bool:
        """更新计划生成状态"""
        if not self.is_connected():
            return False
            
        try:
            key = self._get_status_key(session_id)
            status_data = {
                "session_id": session_id,
                "status": status,
                "progress": progress,
                "message": message,
                "updated_at": datetime.now().isoformat()
            }
            
            self.client.setex(
                key, 
                3600,
                json.dumps(status_data, ensure_ascii=False)
            )
            return True
            
        except Exception as e:
            print(f"❌ Failed to update status: {e}")
            return False
    
    def get_plan_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取计划生成状态"""
        if not self.is_connected():
            return None
            
        try:
            key = self._get_status_key(session_id)
            data = self.client.get(key)
            
            if data:
                return json.loads(data)
            return None
            
        except Exception as e:
            print(f"❌ Failed to get status: {e}")
            return None
    
    def delete_plan(self, session_id: str) -> bool:
        """删除计划"""
        if not self.is_connected():
            return False
            
        try:
            plan_key = self._get_plan_key(session_id)
            status_key = self._get_status_key(session_id)
            
            self.client.delete(plan_key, status_key)
            print(f"🗑️ Plan deleted: {session_id}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to delete plan: {e}")
            return False
    
    def list_plans(self, pattern: str = "travel_plan:*", limit: int = 100) -> list:
        """列出所有计划"""
        if not self.is_connected():
            return []
            
        try:
            keys = self.client.keys(pattern)[:limit]
            plans = []
            
            for key in keys:
                data = self.client.get(key)
                if data:
                    plan = json.loads(data)
                    plans.append({
                        "session_id": plan.get("session_id"),
                        "created_at": plan.get("created_at"),
                        "destination": plan.get("data", {}).get("destination", "Unknown")
                    })
            
            return plans
            
        except Exception as e:
            print(f"❌ Failed to list plans: {e}")
            return []


# 全局单例
redis_service = RedisService()