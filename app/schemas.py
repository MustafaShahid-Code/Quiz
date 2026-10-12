"""Pydantic request models."""
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
FONT_FAMILY = re.compile(r"^[A-Za-z0-9 ,'\"_\-]{1,200}$")
Lang = Literal["en", "ar"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str
    role: Literal["admin", "editor", "viewer"] = "editor"


class UserUpdateIn(BaseModel):
    role: Optional[Literal["admin", "editor", "viewer"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class OptionIn(BaseModel):
    id: Optional[int] = None
    label_en: str = Field(default="", max_length=200)
    label_ar: str = Field(default="", max_length=200)
    is_correct: bool = False


class QuestionIn(BaseModel):
    text_en: str = Field(default="", max_length=500)
    text_ar: str = Field(default="", max_length=500)
    explanation_en: str = Field(default="", max_length=1000)
    explanation_ar: str = Field(default="", max_length=1000)
    category_id: Optional[int] = None
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    image_asset_id: Optional[int] = None
    character_id: Optional[int] = None
    reveal_asset_id: Optional[int] = None
    scheme_id: Optional[int] = None
    enabled: bool = True
    sort_order: int = 0
    options: list[OptionIn] = Field(default_factory=lambda: [OptionIn() for _ in range(4)], max_length=8)

    @field_validator("options")
    @classmethod
    def at_most_one_correct(cls, v):
        if sum(1 for o in v if o.is_correct) > 1:
            raise ValueError("a single-answer question can have only one correct option")
        return v


class StatusIn(BaseModel):
    status: Literal["draft", "published", "unpublished"]


class CategoryIn(BaseModel):
    slug: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_-]+$")
    name_en: str = Field(min_length=1, max_length=100)
    name_ar: str = Field(default="", max_length=100)


class CharacterIn(BaseModel):
    name_en: str = Field(default="", max_length=120)
    name_ar: str = Field(default="", max_length=120)
    description_en: str = Field(default="", max_length=1000)
    description_ar: str = Field(default="", max_length=1000)
    category: str = Field(default="player", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)
    asset_id: Optional[int] = None
    reveal_asset_id: Optional[int] = None


class SchemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    scheme_type: Literal["touch_zones", "pose_mapping"] = "touch_zones"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SlideIn(BaseModel):
    title_en: str = Field(default="", max_length=120)
    title_ar: str = Field(default="", max_length=120)
    body_en: str = Field(default="", max_length=400)
    body_ar: str = Field(default="", max_length=400)
    asset_id: Optional[int] = None
    bg_color: str = "#000000"
    fit: Literal["contain", "cover"] = "contain"
    duration_ms: int = Field(default=6000, ge=1500, le=60000)
    sort_order: int = 0
    enabled: bool = True
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None

    @field_validator("bg_color")
    @classmethod
    def color(cls, v):
        if not HEX.match(v):
            raise ValueError("invalid colour")
        return v


class ThemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tokens: dict[str, Any] = Field(default_factory=dict)  # validated by app.themes.sanitize_tokens


class SettingsIn(BaseModel):
    """Partial update: only provided keys are changed. Validated in routers.settings."""
    values: dict[str, Any]


class SessionStartIn(BaseModel):
    lang: Lang = "en"


class AnswerIn(BaseModel):
    question_id: int
    option_id: int
    input_source: Literal["mouse", "touch", "keyboard", "lidar", "simulated", "pose"] = "mouse"
    response_ms: Optional[int] = Field(default=None, ge=0, le=3_600_000)


class SensorConfigIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    sensor_model: Optional[Literal["S2", "S3", "other"]] = None
    source_type: Optional[Literal["none", "simulator", "serial", "subprocess", "replay"]] = None
    params: Optional[dict[str, Any]] = None
    thresholds: Optional[dict[str, Any]] = None


class CalibrationPoint(BaseModel):
    target: tuple[float, float]
    raw: tuple[float, float]


class CalibrationIn(BaseModel):
    points: list[CalibrationPoint] = Field(min_length=4, max_length=12)


class ValidationTrial(BaseModel):
    target: tuple[float, float]
    hit: Optional[tuple[float, float]] = None
    latency_ms: Optional[float] = None


class ValidationIn(BaseModel):
    trials: list[ValidationTrial] = Field(min_length=3, max_length=60)


class SimTouchIn(BaseModel):
    u: float = Field(ge=0, le=1)
    v: float = Field(ge=0, le=1)


class PoseEventIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    confidence: float = Field(default=1.0, ge=0, le=1)
