from src.tools.travel_plan_tool import TravelPlanTool

from src.agents.optimized_workflow import create_optimized_travel_graph
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# 创建工作流
graph = create_optimized_travel_graph()

# 创建工具
travel_tool = TravelPlanTool(travel_graph=graph)

# 设置 session_id
travel_tool.set_session_id("test-session-123")

# 执行
result = travel_tool._run(
    destination="南京",
    days=3,
    origin="上海",
    group_type="couple",
    preferences=["美食", "拍照", "历史"],
    budget="中等",
    max_searches=2,
    quality_level="normal"  # fast/normal/high
)

print(result)