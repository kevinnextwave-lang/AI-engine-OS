"""Competitive AI Visibility responses (Milestone 5C). Payloads carry the full
breakdown; these schemas pin the fields consumers rely on and allow the rest."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.visibility import DateRange, PeriodView, Sufficiency, Trend


class CompetitiveDataQuality(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_size: int
    prompt_count: int
    provider_count: int
    providers: list[str]
    date_range: DateRange
    confidence: Sufficiency
    competitors_configured: int
    minimum_sample: int
    ranking_minimum_sample: int


class EntityCounts(BaseModel):
    mentions: int
    recommendations: int
    positioned_mentions: int
    cited_responses: int
    citations: int


class EntityMetricsView(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(description='"brand" or the configured competitor name')
    is_brand: bool
    score: float | None = Field(
        description="Competitive Visibility Score 0–100; null below minimum sample"
    )
    mention_share: float | None
    recommendation_share: float | None
    average_position: float | None
    citation_share: float | None
    sentiment_score: float | None
    sentiment: dict[str, int]
    prompt_coverage: int
    counts: EntityCounts
    components: dict[str, float | None]
    sufficiency: Sufficiency


class EntityWithChange(EntityMetricsView):
    previous_score: float | None
    change: float | None
    trend: Trend


class AdvantageView(BaseModel):
    competitor: str
    competitor_score: float | None
    brand_score: float | None
    advantage: float | None = Field(description="competitor score − brand score")
    material: bool
    reason: str | None
    components: dict[str, float | None]
    where_they_win: list[str]


class RankingView(BaseModel):
    available: bool
    reason: str | None
    order: list[str]
    brand_rank: int | None


class MethodFields(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str
    weights: dict[str, float]
    note: str


class CompetitiveOverview(MethodFields):
    window: str
    generated_at: str
    period: PeriodView
    previous_period: PeriodView
    entities: list[EntityWithChange]
    advantages: list[AdvantageView]
    ranking: RankingView
    data_quality: CompetitiveDataQuality
    previous_data_quality: CompetitiveDataQuality
    material_advantage_threshold: float


class TrendEntity(BaseModel):
    name: str
    is_brand: bool
    current_score: float | None
    previous_score: float | None
    current_mention_share: float | None
    previous_mention_share: float | None
    change: float | None
    trend: Trend


class TrendWindow(BaseModel):
    current_sample_size: int
    previous_sample_size: int
    sufficiency: Sufficiency
    entities: list[TrendEntity]
    advantages: list[AdvantageView]


class SeriesPoint(BaseModel):
    start: str
    end: str
    score: float | None
    mention_share: float | None
    recommendation_share: float | None
    citation_share: float | None
    sample_size: int
    sufficiency: Sufficiency


class CompetitiveTrends(MethodFields):
    generated_at: str
    windows: dict[str, TrendWindow]
    series: dict[str, list[SeriesPoint]]
    bucket_days: int
    minimum_sample: int
    data_quality: CompetitiveDataQuality


class PromptEntityLatest(BaseModel):
    mentioned: bool
    recommended: bool
    position: int | None
    sentiment: str
    citation_count: int
    recommendation_strength: str


class PromptEntityView(BaseModel):
    name: str
    is_brand: bool
    mentioned: bool
    recommended: bool
    position: float | None = Field(description="average list position over the prompt's responses")
    sentiment: str
    citation_count: int
    recommendation_strength: str
    mentioned_in: int
    recommended_in: int
    responses: int
    latest: PromptEntityLatest


class PromptLeader(BaseModel):
    name: str | None
    reason: str | None


class PromptComparison(BaseModel):
    prompt_id: str
    text: str
    category: str
    funnel_stage: str
    responses: int
    providers: list[str]
    last_completed_at: str
    sufficiency: Sufficiency
    entities: list[PromptEntityView]
    leader: PromptLeader
    brand_outperformed_by: list[str]


class CompetitivePrompts(MethodFields):
    window: str
    period: PeriodView
    prompts: list[PromptComparison]
    data_quality: CompetitiveDataQuality
    note: str


class CompetitiveBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    entities: list[EntityMetricsView]
    advantages: list[AdvantageView]
    ranking: RankingView
    data_quality: CompetitiveDataQuality


class ProviderBlock(CompetitiveBlock):
    provider: str
    models: list[str]


class EngineSpread(BaseModel):
    provider: str
    brand_score: float | None
    top_competitor: str | None
    top_competitor_advantage: float | None
    sample_size: int


class CompetitiveEngines(MethodFields):
    window: str
    period: PeriodView
    overall: CompetitiveBlock
    providers: list[ProviderBlock]
    engine_spread: list[EngineSpread]
    ranking_minimum_sample: int
