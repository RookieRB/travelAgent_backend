from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from enum import Enum


class TripStatus(str, Enum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TripCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    destination: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date
    budget: float = Field(default=0, ge=0)
    participants: int = Field(default=1, ge=1)
    image: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class TripUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    destination: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = Field(None, ge=0)
    participants: Optional[int] = Field(None, ge=1)
    status: Optional[TripStatus] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    image: Optional[str] = None
    highlights: Optional[List[str]] = None
    notes: Optional[str] = None


class TripResponse(BaseModel):
    id: str
    user_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    budget: float
    spent: float
    participants: int
    status: str
    rating: Optional[int]
    image: Optional[str]
    highlights: List[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class TripStats(BaseModel):
    total_trips: int = 0
    completed_trips: int = 0
    upcoming_trips: int = 0
    total_spent: float = 0
    cities_visited: int = 0
    total_days: int = 0