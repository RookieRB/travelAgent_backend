# src/api/routes/plans.py

from fastapi import APIRouter, HTTPException
from src.services.multi_plan_store import multi_plan_store

router = APIRouter(prefix="/travelapi/plan", tags=["Travel Plans"])


@router.get("/{session_id}")
async def list_plans(session_id: str):
    """获取某个 session 的所有 plans"""
    plans = multi_plan_store.list_plans(session_id)
    return {"session_id": session_id, "plans": plans, "count": len(plans)}


@router.get("/{session_id}/active")
async def get_active_plan(session_id: str):
    """获取当前激活的 plan"""
    plan = multi_plan_store.get_active_plan(session_id)
    if not plan:
        raise HTTPException(404, "No active plan found")
    return plan.to_dict()


@router.get("/{session_id}/{plan_id}")
async def get_plan(session_id: str, plan_id: str):
    """获取指定 plan 详情"""
    plan = multi_plan_store.get_plan(session_id, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    # success = multi_plan_store.set_active_plan(session_id, plan_id)
    # if not success:
    #     raise HTTPException(500, "Set active plan failed")
    return plan.to_dict()


@router.put("/{session_id}/active/{plan_id}")
async def set_active_plan(session_id: str, plan_id: str):
    """切换激活的 plan"""
    success = multi_plan_store.set_active_plan(session_id, plan_id)
    if not success:
        raise HTTPException(404, "Plan not found")
    return {"message": "已切换", "active_plan_id": plan_id}


@router.delete("/{session_id}/{plan_id}")
async def delete_plan(session_id: str, plan_id: str):
    """删除 plan"""
    success = multi_plan_store.delete_plan(session_id, plan_id)
    if not success:
        raise HTTPException(404, "Plan not found")
    return {"message": "已删除"}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除整个 session 的所有 plans"""
    success = multi_plan_store.delete_session(session_id)
    if not success:
        raise HTTPException(500, "Delete failed")
    return {"message": "已删除所有计划"}