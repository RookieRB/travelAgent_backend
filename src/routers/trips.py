from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date
from src.services.mysql_service import get_db
from src.models.user import User
from src.models.trip import Trip
from src.models.budget import BudgetItem
from src.schemas.trip import TripCreate, TripUpdate, TripResponse, TripStats, TripStatus
from src.middleware.auth import get_current_user

router = APIRouter(prefix="/api/trips", tags=["行程管理"])


# ==================== 行程 CRUD ====================

@router.post("", response_model=TripResponse, summary="创建行程")
async def create_trip(
    data: TripCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新的旅行行程"""
    # 默认封面图
    default_images = [
        "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&q=80&w=800",
        "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&q=80&w=800",
    ]
    
    trip = Trip(
        user_id=current_user.id,
        title=data.title,
        destination=data.destination,
        start_date=data.start_date,
        end_date=data.end_date,
        budget=data.budget,
        participants=data.participants,
        image=data.image or default_images[hash(data.title) % len(default_images)],
        highlights=data.highlights or []
    )
    
    db.add(trip)
    db.commit()
    db.refresh(trip)
    
    # 创建默认预算分类
    _create_default_budget_items(db, trip.id)
    
    return trip


def _create_default_budget_items(db: Session, trip_id: str):
    """创建默认预算分类"""
    defaults = [
        {"category": "交通出行", "category_type": "transport", "color": "#3B82F6", "icon": "Car"},
        {"category": "酒店住宿", "category_type": "accommodation", "color": "#10B981", "icon": "Home"},
        {"category": "餐饮美食", "category_type": "food", "color": "#F59E0B", "icon": "Coffee"},
        {"category": "景点门票", "category_type": "tickets", "color": "#EC4899", "icon": "Ticket"},
        {"category": "购物纪念", "category_type": "shopping", "color": "#8B5CF6", "icon": "ShoppingBag"},
    ]
    
    for i, item in enumerate(defaults):
        budget_item = BudgetItem(
            trip_id=trip_id,
            category=item["category"],
            category_type=item["category_type"],
            color=item["color"],
            icon=item["icon"],
            sort_order=i
        )
        db.add(budget_item)
    
    db.commit()


@router.get("", response_model=List[TripResponse], summary="获取行程列表")
async def get_trips(
    status: Optional[str] = Query(None, description="按状态筛选"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户的所有行程"""
    query = db.query(Trip).filter(Trip.user_id == current_user.id)
    
    if status:
        query = query.filter(Trip.status == status)
    
    trips = query.order_by(Trip.created_at.desc()).all()
    
    # 计算每个行程的已支出金额
    for trip in trips:
        total_spent = db.query(func.sum(BudgetItem.spent)).filter(
            BudgetItem.trip_id == trip.id
        ).scalar() or 0
        trip.spent = float(total_spent)
    
    return trips


@router.get("/stats", response_model=TripStats, summary="获取行程统计")
async def get_trip_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的行程统计数据"""
    trips = db.query(Trip).filter(Trip.user_id == current_user.id).all()
    
    total_days = 0
    for trip in trips:
        if trip.start_date and trip.end_date:
            total_days += (trip.end_date - trip.start_date).days + 1
    
    # 计算总支出
    total_spent = db.query(func.sum(BudgetItem.spent)).join(Trip).filter(
        Trip.user_id == current_user.id
    ).scalar() or 0
    
    return TripStats(
        total_trips=len(trips),
        completed_trips=len([t for t in trips if t.status == "completed"]),
        upcoming_trips=len([t for t in trips if t.status == "upcoming"]),
        total_spent=float(total_spent),
        cities_visited=len(set(t.destination for t in trips)),
        total_days=total_days
    )


@router.get("/{trip_id}", response_model=TripResponse, summary="获取行程详情")
async def get_trip(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取行程详情"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 计算已支出
    total_spent = db.query(func.sum(BudgetItem.spent)).filter(
        BudgetItem.trip_id == trip.id
    ).scalar() or 0
    trip.spent = float(total_spent)
    
    return trip


@router.put("/{trip_id}", response_model=TripResponse, summary="更新行程")
async def update_trip(
    trip_id: str,
    data: TripUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新行程信息"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(trip, key, value)
    
    db.commit()
    db.refresh(trip)
    
    return trip


@router.delete("/{trip_id}", summary="删除行程")
async def delete_trip(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除行程及其关联数据"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    db.delete(trip)
    db.commit()
    
    return {"message": "删除成功"}


@router.post("/{trip_id}/complete", response_model=TripResponse, summary="完成行程")
async def complete_trip(
    trip_id: str,
    rating: int = Query(..., ge=1, le=5, description="评分1-5星"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """标记行程为已完成"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    trip.status = "completed"
    trip.rating = rating
    
    db.commit()
    db.refresh(trip)
    
    return trip