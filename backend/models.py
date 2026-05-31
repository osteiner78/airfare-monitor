import re

from pydantic import BaseModel, field_validator


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(v: str | None) -> str | None:
    if v is None:
        return v
    if not _DATE_RE.match(v):
        raise ValueError("Date must be YYYY-MM-DD")
    return v


class TrackerCreate(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: str | None = None
    currency: str = "EUR"
    interval_minutes: int = 180
    top_n: int = 10

    @field_validator("depart_date", "return_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        return _validate_date(v)


class TrackerUpdate(BaseModel):
    active: bool | None = None
    interval_minutes: int | None = None


class TrackerResponse(BaseModel):
    id: int
    origin: str
    destination: str
    depart_date: str
    return_date: str | None
    currency: str
    interval_minutes: int
    top_n: int
    active: bool
    created_at: str


class NotificationCreate(BaseModel):
    tracker_id: int
    rule_type: str
    threshold: float


class NotificationResponse(BaseModel):
    id: int
    tracker_id: int
    rule_type: str
    threshold: float
    created_at: str
