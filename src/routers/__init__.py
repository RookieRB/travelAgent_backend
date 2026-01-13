from sqlalchemy.orm import Session
from src.models.trip import Trip
from src.models.budget import BudgetItem



# 在文件顶部或 utils 中定义
def sync_trip_budget(db: Session, trip_id: str) -> tuple[float, float]:
    """
    同步更新行程的预算和支出汇总
    
    Returns:
        (total_budget, total_spent)
    """
    from sqlalchemy import func
    
    # 计算预算项汇总
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
        Trip.budget: total_budget,
        Trip.spent: total_spent
    })
    db.commit()
    
    return total_budget, total_spent