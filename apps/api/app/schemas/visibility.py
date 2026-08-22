"""AI Visibility Score responses.

The payloads carry the full methodology breakdown; the schemas below pin the
fields every consumer must be able to rely on and allow the rest through.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Window = Literal["7d", "30d", "90d"]
Sufficiency = Literal["insufficient", "low", "moderate", "high"]
Trend = Literal["up", "down", "flat", "unavailable"]


class DateRange(BaseModel):
    start: str | None
    end: str | None


class DataQuality(BaseModel):
    sample_size: int
    sufficiency: Sufficiency
    providers: int
    provider_keys: list[str]
    models: int
    prompts: int
    date_range: DateRange
    parser_versions: list[str]
    minimum_sample: int


class ComponentView(BaseModel):
    key: str
    value: float | None = Field(description="0–100, or null when unavailable")
    weight: float
    sample: int
    note: str


class ScoreView(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    score: float | None = Field(description="AI Visibility Score 0–100; null below minimum sample")
    mention_rate: float | None
    recommendation_rate: float | None
    average_position: float | None
    citation_rate: float | None
    sentiment: dict[str, int]
    components: list[ComponentView]
    data_quality: DataQuality


class PeriodView(BaseModel):
    start: str
    end: str


class ScorePeriodView(ScoreView):
    period: PeriodView


class VisibilityOverview(BaseModel):
    method: str
    window: Window
    generated_at: str
    current: ScorePeriodView
    previous: ScorePeriodView
    change: float | None
    trend: Trend
    reason: str | None
    competitors_configured: int


class WindowTrend(BaseModel):
    current_score: float | None
    previous_score: float | None
    current_sample_size: int
    previous_sample_size: int
    sufficiency: Sufficiency
    change: float | None
    trend: Trend
    reason: str | None


class SeriesPoint(BaseModel):
    start: str
    end: str
    score: float | None
    mention_rate: float | None
    recommendation_rate: float | None
    citation_rate: float | None
    sample_size: int
    sufficiency: Sufficiency


class VisibilityTrends(BaseModel):
    method: str
    generated_at: str
    windows: dict[Window, WindowTrend]
    series: list[SeriesPoint]
    minimum_sample: int


class ProviderScore(ScoreView):
    provider: str


class ModelScore(ScoreView):
    provider: str
    model: str


class VisibilityByEngine(BaseModel):
    method: str
    window: Window
    period: PeriodView
    overall: ScoreView
    providers: list[ProviderScore]
    models: list[ModelScore]


class PromptScore(BaseModel):
    prompt_id: str
    text: str
    category: str
    funnel_stage: str
    sample_size: int
    sufficiency: Sufficiency
    score: float | None
    mentions: int
    mention_rate: float | None
    recommendation_rate: float | None
    average_position: float | None
    citation_rate: float | None
    sentiment: dict[str, int]
    providers: int


class CategoryScore(ScoreView):
    category: str


class FunnelStageScore(ScoreView):
    funnel_stage: str


class VisibilityByPrompt(BaseModel):
    method: str
    window: Window
    period: PeriodView
    prompts: list[PromptScore]
    categories: list[CategoryScore]
    funnel_stages: list[FunnelStageScore]


class CompetitorRow(BaseModel):
    name: str
    is_brand: bool
    mentions: int
    mention_rate: float | None
    recommendation_rate: float | None
    average_position: float | None
    positioned_mentions: int
    sentiment_score: float | None
    sentiment: dict[str, int]
    share_of_voice: float | None


class VisibilityCompetitors(BaseModel):
    method: str
    window: Window
    period: PeriodView
    competitors_configured: int
    competitive_score: float | None
    data_quality: DataQuality
    rows: list[CompetitorRow]
    note: str
