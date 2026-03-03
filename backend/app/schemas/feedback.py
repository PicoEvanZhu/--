from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FeedbackType = Literal["bug", "feature", "data", "ux", "other"]
FeedbackScope = Literal["home", "dashboard", "stocks", "stock_detail", "report", "news", "other"]
FeedbackStatus = Literal["new", "triaged", "done"]


class FeedbackCreate(BaseModel):
    user_id: Optional[str] = None
    page: str = Field(min_length=1, max_length=120)
    type: FeedbackType
    scope: FeedbackScope
    content: str = Field(min_length=10, max_length=4000)
    contact: Optional[str] = Field(default=None, max_length=120)
    screenshot_url: Optional[str] = Field(default=None, max_length=500)
    meta_json: Optional[Dict] = None


class FeedbackListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[str]
    page: str
    type: str
    scope: str
    content: str
    contact: Optional[str]
    screenshot_url: Optional[str]
    meta_json: Optional[str]
    status: FeedbackStatus
    created_at: datetime


class FeedbackCreateResponse(BaseModel):
    feedback_id: int


class FeedbackStatusUpdate(BaseModel):
    status: FeedbackStatus
