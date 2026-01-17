# src/services/multi_plan_store.py

from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
import uuid
import json

from src.services.redis_service import redis_service


@dataclass
class TravelPlan:
    """单个旅行计划"""
    plan_id: str
    name: str
    created_at: str
    updated_at: str
    route_data: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TravelPlan":
        return cls(**data)


class MultiPlanStore:
    """
    简化版多 Plan 存储
    
    Redis 结构（单 Hash）:
    
    travel_plans:{session_id}
      ├── _active    -> "plan_abc"
      ├── _order     -> ["plan_abc", "plan_def"]
      ├── plan_abc   -> {plan数据}
      └── plan_def   -> {plan数据}
    """
    
    KEY_PREFIX = "travel_plans:"
    EXPIRE_SECONDS = 86400 * 7
    
    FIELD_ACTIVE = "_active"
    FIELD_ORDER = "_order"
    
    def __init__(self):
        self.redis = redis_service
    
    def _key(self, session_id: str) -> str:
        return f"{self.KEY_PREFIX}{session_id}"
    
    # ==================== CRUD ====================
    
    def create_plan(
        self, 
        session_id: str, 
        route_data: Dict = None,
        name: str = None
    ) -> Optional[str]:
        """创建新 plan，返回 plan_id"""
        if not self.redis.is_connected():
            return None
        
        try:
            key = self._key(session_id)
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            
            # 获取顺序
            order_json = self.redis.client.hget(key, self.FIELD_ORDER)
            order = json.loads(order_json) if order_json else []
            
            if not name:
                name = f"行程方案 {len(order) + 1}"
            
            plan = TravelPlan(
                plan_id=plan_id,
                name=name,
                created_at=now,
                updated_at=now,
                route_data=route_data or {}
            )
            
            order.append(plan_id)
            
            pipe = self.redis.client.pipeline()
            pipe.hset(key, plan_id, json.dumps(plan.to_dict(), ensure_ascii=False))
            pipe.hset(key, self.FIELD_ORDER, json.dumps(order))
            pipe.hset(key, self.FIELD_ACTIVE, plan_id)
            pipe.expire(key, self.EXPIRE_SECONDS)
            pipe.execute()
            
            print(f"✅ Plan created: {session_id[:8]}.../{plan_id}")
            return plan_id
            
        except Exception as e:
            print(f"❌ Create plan failed: {e}")
            return None
    
    def get_plan(self, session_id: str, plan_id: str) -> Optional[TravelPlan]:
        """获取指定 plan"""
        if not self.redis.is_connected():
            return None
        try:
            data = self.redis.client.hget(self._key(session_id), plan_id)
            return TravelPlan.from_dict(json.loads(data)) if data else None
        except Exception:
            return None
    
    def get_active_plan(self, session_id: str) -> Optional[TravelPlan]:
        """获取当前激活的 plan"""
        plan_id = self.get_active_plan_id(session_id)
        return self.get_plan(session_id, plan_id) if plan_id else None
    
    def get_active_plan_id(self, session_id: str) -> Optional[str]:
        """获取当前激活的 plan_id"""
        if not self.redis.is_connected():
            return None
        try:
            return self.redis.client.hget(self._key(session_id), self.FIELD_ACTIVE)
        except Exception:
            return None
    
    def set_active_plan(self, session_id: str, plan_id: str) -> bool:
        """设置激活的 plan"""
        if not self.redis.is_connected():
            return False
        try:
            key = self._key(session_id)
            if not self.redis.client.hexists(key, plan_id):
                return False
            self.redis.client.hset(key, self.FIELD_ACTIVE, plan_id)
            return True
        except Exception:
            return False
    
    def list_plans(self, session_id: str) -> List[Dict]:
        """列出所有 plans 摘要"""
        if not self.redis.is_connected():
            return []
        
        try:
            key = self._key(session_id)
            order_json = self.redis.client.hget(key, self.FIELD_ORDER)
            active_id = self.redis.client.hget(key, self.FIELD_ACTIVE)
            
            if not order_json:
                return []
            
            order = json.loads(order_json)
            plans_data = self.redis.client.hmget(key, order)
            
            return [
                {
                    "plan_id": (p := json.loads(data))["plan_id"],
                    "name": p["name"],
                    "created_at": p["created_at"],
                    "is_active": pid == active_id
                }
                for pid, data in zip(order, plans_data) if data
            ]
        except Exception:
            return []
    
    def update_plan(
        self, 
        session_id: str, 
        plan_id: str, 
        route_data: Dict = None,
        name: str = None
    ) -> bool:
        """更新 plan"""
        if not self.redis.is_connected():
            return False
        
        try:
            plan = self.get_plan(session_id, plan_id)
            if not plan:
                return False
            
            if route_data is not None:
                plan.route_data = route_data
            if name is not None:
                plan.name = name
            plan.updated_at = datetime.now().isoformat()
            
            self.redis.client.hset(
                self._key(session_id), 
                plan_id, 
                json.dumps(plan.to_dict(), ensure_ascii=False)
            )
            return True
        except Exception:
            return False
    
    def delete_plan(self, session_id: str, plan_id: str) -> bool:
        """删除 plan"""
        if not self.redis.is_connected():
            return False
        
        try:
            key = self._key(session_id)
            if not self.redis.client.hexists(key, plan_id):
                return False
            
            order_json = self.redis.client.hget(key, self.FIELD_ORDER)
            order = json.loads(order_json) if order_json else []
            if plan_id in order:
                order.remove(plan_id)
            
            pipe = self.redis.client.pipeline()
            pipe.hdel(key, plan_id)
            pipe.hset(key, self.FIELD_ORDER, json.dumps(order))
            
            if self.redis.client.hget(key, self.FIELD_ACTIVE) == plan_id:
                pipe.hset(key, self.FIELD_ACTIVE, order[0] if order else "")
            
            pipe.execute()
            return True
        except Exception:
            return False
    
    # ==================== 辅助 ====================
    
    def plan_exists(self, session_id: str, plan_id: str) -> bool:
        if not self.redis.is_connected():
            return False
        try:
            return self.redis.client.hexists(self._key(session_id), plan_id)
        except Exception:
            return False
    
    def get_plan_count(self, session_id: str) -> int:
        try:
            order_json = self.redis.client.hget(self._key(session_id), self.FIELD_ORDER)
            return len(json.loads(order_json)) if order_json else 0
        except Exception:
            return 0
    
    def delete_session(self, session_id: str) -> bool:
        if not self.redis.is_connected():
            return False
        try:
            self.redis.client.delete(self._key(session_id))
            return True
        except Exception:
            return False


# 全局实例
multi_plan_store = MultiPlanStore()