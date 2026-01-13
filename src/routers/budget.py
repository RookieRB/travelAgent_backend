from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional,Tuple
from datetime import date
from src.services.mysql_service import get_db
from src.models.user import User
from src.models.trip import Trip
from src.models.budget import BudgetItem, Expense
from src.schemas.budget import (
    BudgetItemCreate, BudgetItemUpdate, BudgetItemResponse,
    BudgetSummary, ExpenseCreate, ExpenseUpdate, ExpenseResponse
)
from src.middleware.auth import get_current_user
from src.routers import sync_trip_budget




router = APIRouter(prefix="/travelapi/trips", tags=["预算管理"])



def sync_trip_budget(db: Session, trip_id: str, items: List[BudgetItem] = None) -> Tuple[float, float]:
    """
    同步更新行程的预算和支出汇总
    
    Args:
        db: 数据库会话
        trip_id: 行程ID
        items: 预算项列表（可选，如果已查询过则直接传入，避免重复查询）
    
    Returns:
        (total_budget, total_spent)
    """
    if items is not None:
        # 直接使用传入的 items 计算
        total_budget = sum(float(item.amount or 0) for item in items)
        total_spent = sum(float(item.spent or 0) for item in items)
    else:
        # 从数据库查询计算
        result = db.query(
            func.coalesce(func.sum(BudgetItem.amount), 0).label('total_budget'),
            func.coalesce(func.sum(BudgetItem.spent), 0).label('total_spent')
        ).filter(
            BudgetItem.trip_id == trip_id
        ).first()
        
        total_budget = float(result.total_budget) if result else 0
        total_spent = float(result.total_spent) if result else 0
    
    # 更新 Trip 表
    db.query(Trip).filter(Trip.id == trip_id).update({
        "budget": total_budget,
        "spent": total_spent
    })
    db.commit()
    
    return total_budget, total_spent


def generate_budget_insights(
    items: List[BudgetItem], 
    total_budget: float, 
    total_spent: float
) -> Tuple[List[str], List[str]]:
    """
    生成预算分析洞察和警告
    
    Returns:
        (insights, warnings)
    """
    insights = []
    warnings = []
    
    if not items or total_budget == 0:
        return insights, warnings
    
    # 过滤有效的预算项（有预算或有支出的）
    active_items = [item for item in items if float(item.amount or 0) > 0 or float(item.spent or 0) > 0]
    
    if not active_items:
        return insights, warnings
    
    # 1. 支出最高类别分析
    if total_spent > 0:
        max_spent_item = max(active_items, key=lambda x: float(x.spent or 0))
        if float(max_spent_item.spent or 0) > 0:
            pct = round(float(max_spent_item.spent) / total_spent * 100)
            insights.append(f"您的「{max_spent_item.category}」支出占总支出的 {pct}%")
    
    # 2. 预算最高类别分析
    max_budget_item = max(active_items, key=lambda x: float(x.amount or 0))
    if float(max_budget_item.amount or 0) > 0:
        budget_pct = round(float(max_budget_item.amount) / total_budget * 100)
        if budget_pct >= 40:
            insights.append(f"「{max_budget_item.category}」占总预算的 {budget_pct}%，是主要支出项")
    
    # 3. 逐项分析
    over_budget_count = 0
    near_limit_count = 0
    under_utilized_items = []
    
    for item in active_items:
        amount = float(item.amount or 0)
        spent = float(item.spent or 0)
        
        if amount > 0:
            usage = spent / amount
            
            # 超支检查
            if spent > amount:
                over_budget_count += 1
                over = spent - amount
                warnings.append(f"「{item.category}」已超支 ¥{over:.0f}，建议适当控制")
            
            # 接近预算上限
            elif 0.8 <= usage < 1.0:
                near_limit_count += 1
                insights.append(f"「{item.category}」已使用 {usage*100:.0f}%，请注意控制")
            
            # 预算使用率低（低于20%且预算较大）
            elif usage < 0.2 and amount >= total_budget * 0.1:
                under_utilized_items.append(item.category)
    
    # 4. 整体分析
    overall_usage = total_spent / total_budget if total_budget > 0 else 0
    
    if overall_usage > 1:
        warnings.insert(0, f"总预算已超支 ¥{total_spent - total_budget:.0f}，请控制后续支出")
    elif overall_usage >= 0.9:
        warnings.insert(0, f"总预算已使用 {overall_usage*100:.0f}%，剩余空间有限")
    elif overall_usage >= 0.7:
        insights.insert(0, f"总预算已使用 {overall_usage*100:.0f}%，整体进度正常")
    elif overall_usage < 0.3 and total_spent > 0:
        insights.insert(0, f"总预算使用 {overall_usage*100:.0f}%，资金充裕")
    
    # 5. 多项超支警告
    if over_budget_count >= 2:
        warnings.append(f"已有 {over_budget_count} 个类别超支，建议重新调整预算分配")
    
    # 6. 低使用率提示
    if len(under_utilized_items) >= 2:
        insights.append(f"「{'、'.join(under_utilized_items[:3])}」预算使用率较低，可考虑调整")
    
    return insights, warnings

# ==================== 预算接口 ====================

@router.get("/{trip_id}/budget", response_model=BudgetSummary, summary="获取预算汇总")
async def get_budget(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取行程的预算汇总
    
    包含：
    - 预算项列表
    - 总预算/已支出/剩余金额
    - AI 智能洞察和预警
    """
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 获取预算项列表
    items = db.query(BudgetItem).filter(
        BudgetItem.trip_id == trip_id
    ).order_by(BudgetItem.sort_order).all()
    
    # 同步并获取汇总（传入 items 避免重复查询）
    total_budget, total_spent = sync_trip_budget(db, trip_id, items)
    
    # 计算剩余和百分比
    remaining = total_budget - total_spent
    spent_percentage = round((total_spent / total_budget * 100) if total_budget > 0 else 0, 1)
    
    # 生成 AI 洞察
    insights, warnings = generate_budget_insights(items, total_budget, total_spent)
    
    return BudgetSummary(
        total_budget=total_budget,
        total_spent=total_spent,
        remaining=remaining,
        spent_percentage=spent_percentage,
        items=items,
        insights=insights,
        warnings=warnings
    )

@router.post("/{trip_id}/budget", response_model=BudgetItemResponse, summary="添加预算项")
async def create_budget_item(
    trip_id: str,
    data: BudgetItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """添加新的预算分类"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 获取最大排序号
    max_order = db.query(func.max(BudgetItem.sort_order)).filter(
        BudgetItem.trip_id == trip_id
    ).scalar() or 0
    
    item = BudgetItem(
        trip_id=trip_id,
        category=data.category,
        category_type=data.category_type.value,
        amount=data.amount,
        color=data.color,
        icon=data.icon,
        sort_order=max_order + 1
    )
    
    db.add(item)
    db.commit()
    db.refresh(item)
    
    return item


@router.put("/budget/{item_id}", response_model=BudgetItemResponse, summary="更新预算项")
async def update_budget_item(
    item_id: str,
    data: BudgetItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新预算项"""
    item = db.query(BudgetItem).join(Trip).filter(
        BudgetItem.id == item_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="预算项不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    
    return item


@router.delete("/budget/{item_id}", summary="删除预算项")
async def delete_budget_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除预算分类"""
    item = db.query(BudgetItem).join(Trip).filter(
        BudgetItem.id == item_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="预算项不存在")
    
    db.delete(item)
    db.commit()
    
    return {"message": "删除成功"}


# ==================== 支出接口 ====================

@router.post("/{trip_id}/expenses", response_model=ExpenseResponse, summary="添加支出")
async def add_expense(
    trip_id: str,
    data: ExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """记录一笔支出"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    item = db.query(BudgetItem).filter(
        BudgetItem.id == data.budget_item_id,
        BudgetItem.trip_id == trip_id
    ).first()
    
    if not item:
        raise HTTPException(status_code=400, detail="预算项不存在")
    
    # 更新预算项已支出金额
    item.spent = float(item.spent) + data.amount
    
    # 创建支出记录
    expense = Expense(
        trip_id=trip_id,
        budget_item_id=data.budget_item_id,
        amount=data.amount,
        note=data.note,
        expense_date=data.expense_date or date.today()
    )
    
    db.add(expense)
    db.commit()
    db.refresh(expense)
    
    return expense


@router.get("/{trip_id}/expenses", response_model=List[ExpenseResponse], summary="获取行程所有支出记录")
async def get_expenses(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取行程的所有支出记录"""
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    expenses = db.query(Expense).filter(
        Expense.trip_id == trip_id
    ).order_by(Expense.expense_date.desc()).all()
    
    return expenses


@router.get(
    "/{trip_id}/budget/{budget_item_id}/expenses", 
    response_model=List[ExpenseResponse], 
    summary="获取某预算项的所有支出记录"
)
async def get_budget_item_expenses(
    trip_id: str,
    budget_item_id: str,
    start_date: Optional[date] = Query(None, description="开始日期筛选"),
    end_date: Optional[date] = Query(None, description="结束日期筛选"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取某个预算项下的所有支出记录
    
    - **trip_id**: 行程ID
    - **budget_item_id**: 预算项ID
    - **start_date**: 开始日期（可选，筛选用）
    - **end_date**: 结束日期（可选，筛选用）
    """
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 验证预算项归属
    budget_item = db.query(BudgetItem).filter(
        BudgetItem.id == budget_item_id,
        BudgetItem.trip_id == trip_id
    ).first()
    
    if not budget_item:
        raise HTTPException(status_code=404, detail="预算项不存在")
    
    # 构建查询
    query = db.query(Expense).filter(
        Expense.trip_id == trip_id,
        Expense.budget_item_id == budget_item_id
    )
    
    # 日期筛选
    if start_date:
        query = query.filter(Expense.expense_date >= start_date)
    if end_date:
        query = query.filter(Expense.expense_date <= end_date)
    
    # 按日期倒序
    expenses = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    
    return expenses


@router.get(
    "/{trip_id}/expenses/{expense_id}", 
    response_model=ExpenseResponse, 
    summary="获取支出详情"
)
async def get_expense_detail(
    trip_id: str,
    expense_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取单条支出记录详情"""
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.trip_id == trip_id
    ).first()
    
    if not expense:
        raise HTTPException(status_code=404, detail="支出记录不存在")
    
    return expense


@router.put(
    "/{trip_id}/expenses/{expense_id}", 
    response_model=ExpenseResponse, 
    summary="更新支出记录"
)
async def update_expense(
    trip_id: str,
    expense_id: str,
    data: ExpenseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新支出记录
    
    - **expense_id**: 支出记录ID
    - **amount**: 新金额（可选）
    - **note**: 新备注（可选）
    - **expense_date**: 新日期（可选）
    - **budget_item_id**: 更改所属预算项（可选）
    """
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 获取支出记录
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.trip_id == trip_id
    ).first()
    
    if not expense:
        raise HTTPException(status_code=404, detail="支出记录不存在")
    
    # 获取更新数据
    update_data = data.model_dump(exclude_unset=True)
    
    # 如果修改了金额，需要更新预算项的已支出金额
    if "amount" in update_data:
        old_amount = float(expense.amount)
        new_amount = float(update_data["amount"])
        amount_diff = new_amount - old_amount
        
        # 更新原预算项的已支出金额
        old_budget_item = db.query(BudgetItem).filter(
            BudgetItem.id == expense.budget_item_id
        ).first()
        if old_budget_item:
            old_budget_item.spent = float(old_budget_item.spent) + amount_diff
    
    # 如果更改了所属预算项
    if "budget_item_id" in update_data and update_data["budget_item_id"] != expense.budget_item_id:
        new_budget_item_id = update_data["budget_item_id"]
        
        # 验证新预算项存在且属于同一行程
        new_budget_item = db.query(BudgetItem).filter(
            BudgetItem.id == new_budget_item_id,
            BudgetItem.trip_id == trip_id
        ).first()
        
        if not new_budget_item:
            raise HTTPException(status_code=400, detail="目标预算项不存在")
        
        expense_amount = float(update_data.get("amount", expense.amount))
        
        # 从原预算项减去金额
        old_budget_item = db.query(BudgetItem).filter(
            BudgetItem.id == expense.budget_item_id
        ).first()
        if old_budget_item:
            old_budget_item.spent = max(0, float(old_budget_item.spent) - float(expense.amount))
        
        # 给新预算项加上金额
        new_budget_item.spent = float(new_budget_item.spent) + expense_amount
    
    # 更新支出记录
    for key, value in update_data.items():
        setattr(expense, key, value)
    
    db.commit()
    db.refresh(expense)
    
    return expense


@router.delete("/{trip_id}/expenses/{expense_id}", summary="删除支出记录")
async def delete_expense(
    trip_id: str,
    expense_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除支出记录
    
    删除后会自动更新对应预算项的已支出金额
    """
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 获取支出记录
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.trip_id == trip_id
    ).first()
    
    if not expense:
        raise HTTPException(status_code=404, detail="支出记录不存在")
    
    # 更新预算项的已支出金额（减去被删除的金额）
    budget_item = db.query(BudgetItem).filter(
        BudgetItem.id == expense.budget_item_id
    ).first()
    
    if budget_item:
        budget_item.spent = max(0, float(budget_item.spent) - float(expense.amount))
    
    # 删除支出记录
    db.delete(expense)
    db.commit()
    
    return {"message": "删除成功", "deleted_amount": float(expense.amount)}


@router.delete("/{trip_id}/budget/{budget_item_id}/expenses", summary="批量删除预算项下所有支出")
async def delete_all_budget_item_expenses(
    trip_id: str,
    budget_item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除某预算项下的所有支出记录
    
    删除后会自动将预算项的已支出金额重置为0
    """
    # 验证行程归属
    trip = db.query(Trip).filter(
        Trip.id == trip_id,
        Trip.user_id == current_user.id
    ).first()
    
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    
    # 验证预算项归属
    budget_item = db.query(BudgetItem).filter(
        BudgetItem.id == budget_item_id,
        BudgetItem.trip_id == trip_id
    ).first()
    
    if not budget_item:
        raise HTTPException(status_code=404, detail="预算项不存在")
    
    # 获取要删除的支出数量和总金额
    expenses = db.query(Expense).filter(
        Expense.trip_id == trip_id,
        Expense.budget_item_id == budget_item_id
    ).all()
    
    deleted_count = len(expenses)
    deleted_amount = sum(float(e.amount) for e in expenses)
    
    # 删除所有支出记录
    db.query(Expense).filter(
        Expense.trip_id == trip_id,
        Expense.budget_item_id == budget_item_id
    ).delete()
    
    # 重置预算项的已支出金额
    budget_item.spent = 0
    
    db.commit()
    
    return {
        "message": "批量删除成功",
        "deleted_count": deleted_count,
        "deleted_amount": deleted_amount
    }