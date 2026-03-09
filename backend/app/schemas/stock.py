from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


MarketType = Literal["A股", "港股", "创业板", "科创板", "美股"]
RecommendationType = Literal["buy", "watch", "hold_cautious", "avoid"]
RiskLevel = Literal["low", "medium", "high"]
TradeReviewAction = Literal["buy", "sell", "add", "reduce", "observe"]
FollowUpStatus = Literal["open", "in_progress", "closed"]


class StockItem(BaseModel):
    symbol: str
    name: str
    market: MarketType
    board: str
    exchange: str
    industry: str
    sector: str
    concepts: List[str]
    tags: List[str]
    price: float
    change_pct: float
    analyzed: bool
    score: int
    recommendation: RecommendationType
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    net_profit: Optional[float] = None
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    revenue_growth_qoq: Optional[float] = None
    profit_growth: Optional[float] = None
    profit_growth_qoq: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    debt_ratio: Optional[float] = None
    is_st: bool = False
    has_dividend: bool = False
    dividend_years: int = 0
    latest_dividend_year: Optional[str] = None
    dividend_yield: Optional[float] = None
    ex_dividend_date: Optional[str] = None
    is_high_dividend: bool = False
    is_ex_dividend_soon: bool = False
    updated_at: Optional[str] = None


class FinancialReport(BaseModel):
    year: str
    revenue: float
    net_profit: float
    gross_margin: float
    net_margin: float
    roe: float
    debt_ratio: float
    operating_cashflow: float
    eps: float
    dividend_yield: float
    report_url: str


class ValuationHistoryPoint(BaseModel):
    year: str
    pe: float
    pb: float
    market_cap: float


class DividendRecord(BaseModel):
    year: str
    cash_dividend_per_share: float
    payout_ratio: float
    ex_dividend_date: str


class ShareholderRecord(BaseModel):
    name: str
    holder_type: str
    holding_ratio: float
    change_yoy: float


class PeerCompany(BaseModel):
    symbol: str
    name: str
    market: str
    pe: float
    revenue_growth: float
    roe: float
    market_cap: float
    comparison_view: str


class StockDataQuality(BaseModel):
    source: str
    price_source: str
    fundamentals_source: str
    coverage_score: float
    reliability_score: int
    is_enriched: bool
    updated_at: Optional[str] = None
    freshness_days: Optional[int] = None
    warnings: List[str]


class StockDetail(BaseModel):
    symbol: str
    name: str
    market: MarketType
    board: str
    exchange: str
    sector: str
    price: float
    change_pct: float
    analyzed: bool
    pe: float
    pb: float
    roe: float
    debt_ratio: float
    revenue_growth: float
    profit_growth: float
    momentum: float
    volatility: float
    news_sentiment: float
    currency: str
    market_cap: float
    free_float_cap: float
    turnover_rate: float
    amplitude: float
    avg_volume_5d: float
    avg_volume_20d: float
    support_price: float
    resistance_price: float
    company_full_name: str
    english_name: str
    listing_date: str
    company_website: str
    investor_relations_url: str
    exchange_profile_url: str
    quote_url: str
    headquarters: str
    legal_representative: str
    employees: int
    main_business: str
    products_services: List[str]
    industry_positioning: str
    business_scope: List[str]
    market_coverage: List[str]
    company_intro: str
    business_tags: List[str]
    company_highlights: List[str]
    recent_events: List[str]
    core_logic: List[str]
    key_risks: List[str]
    catalyst_events: List[str]
    financial_reports: List[FinancialReport]
    valuation_history: List[ValuationHistoryPoint]
    dividend_history: List[DividendRecord]
    shareholder_structure: List[ShareholderRecord]
    peer_companies: List[PeerCompany]
    news_highlights: List[str]
    last_report_date: str
    data_quality: StockDataQuality


class TradePlan(BaseModel):
    entry_range: str
    stop_loss: str
    take_profit: str
    position_advice: str


class StockFactorScores(BaseModel):
    fundamental: int
    valuation: int
    momentum: int
    sentiment: int
    risk_control: int


class StockAnalysis(BaseModel):
    symbol: str
    score: int
    risk_level: RiskLevel
    recommendation: RecommendationType
    summary: str
    confidence: int
    methodology: str
    evidence_points: List[str]
    suitability_note: str
    disclaimer: str
    factor_scores: StockFactorScores
    strengths: List[str]
    risks: List[str]
    action_items: List[str]
    monitoring_points: List[str]
    scenario_analysis: List[str]
    trade_plan: TradePlan


class StockSnapshot(BaseModel):
    symbol: str
    detail: StockDetail
    analysis: StockAnalysis


class StockQAMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class StockQARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: List[StockQAMessage] = Field(default_factory=list, max_length=12)


class StockQAResponse(BaseModel):
    symbol: str
    question: str
    answer: str
    confidence: int = Field(ge=1, le=99)
    bullets: List[str]
    references: List[str]
    follow_up_questions: List[str]
    disclaimer: str
    generated_at: str
    search_used: bool = False
    search_query: Optional[str] = None
    search_result_count: int = 0


class StockTradeReviewBase(BaseModel):
    trade_date: str
    action: TradeReviewAction
    price: Optional[float] = None
    quantity: Optional[float] = None
    thesis: str
    execution_notes: Optional[str] = None
    outcome_review: Optional[str] = None
    lessons_learned: Optional[str] = None
    follow_up_items: List[str] = Field(default_factory=list)
    follow_up_status: FollowUpStatus = "open"
    next_review_date: Optional[str] = None
    confidence_score: Optional[int] = Field(default=None, ge=0, le=100)
    discipline_score: Optional[int] = Field(default=None, ge=0, le=100)


class StockTradeReviewCreate(StockTradeReviewBase):
    pass


class StockTradeReviewUpdate(BaseModel):
    trade_date: Optional[str] = None
    action: Optional[TradeReviewAction] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    thesis: Optional[str] = None
    execution_notes: Optional[str] = None
    outcome_review: Optional[str] = None
    lessons_learned: Optional[str] = None
    follow_up_items: Optional[List[str]] = None
    follow_up_status: Optional[FollowUpStatus] = None
    next_review_date: Optional[str] = None
    confidence_score: Optional[int] = Field(default=None, ge=0, le=100)
    discipline_score: Optional[int] = Field(default=None, ge=0, le=100)


class StockTradeReviewItem(StockTradeReviewBase):
    id: int
    symbol: str
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    created_at: str
    updated_at: str
    floating_pnl: Optional[float] = None
    floating_pnl_pct: Optional[float] = None
    is_follow_up_due: bool = False


class StockTradeReviewSummary(BaseModel):
    total_reviews: int
    open_follow_ups: int
    in_progress_follow_ups: int
    closed_follow_ups: int
    due_follow_ups: int
    avg_confidence_score: float
    avg_discipline_score: float
    net_floating_pnl: float
    net_floating_pnl_pct: float


class StockTradeReviewResponse(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    items: List[StockTradeReviewItem]
    summary: StockTradeReviewSummary


class DashboardSummary(BaseModel):
    total_stocks: int
    analyzed_count: int
    risk_alert_count: int
    average_score: float
    best_opportunities: List[StockItem]
    high_risk_stocks: List[StockItem]
    latest_updates: List[str]


class StockListStats(BaseModel):
    average_score: float
    median_score: float
    positive_change_count: int
    negative_change_count: int
    by_market: Dict[str, int]
    by_board: Dict[str, int]
    by_recommendation: Dict[str, int]
    top_industries: Dict[str, int]
    top_concepts: Dict[str, int]
    top_tags: Dict[str, int]


class StockDividendSummary(BaseModel):
    total: int
    continuous_3y_count: int
    high_yield_count: int
    upcoming_ex_dividend_count: int
    latest_year: Optional[str] = None
    by_market: Dict[str, int]
    by_board: Dict[str, int]


class StockListResponse(BaseModel):
    items: List[StockItem]
    total: int
    page: int
    page_size: int
    industries: Optional[List[str]] = None
    concepts: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    boards: Optional[List[str]] = None
    exchanges: Optional[List[str]] = None
    recommendations: Optional[List[RecommendationType]] = None
    stats: Optional[StockListStats] = None
    dividend_summary: Optional[StockDividendSummary] = None
    last_synced_at: Optional[str] = None


class SectorConceptItem(BaseModel):
    name: str
    stock_count: int
    avg_change_pct: float
    relative_change_pct: float
    avg_score: float
    buy_watch_ratio: float
    breadth_ratio: float
    leader_avg_score: float
    heat_score: float
    confidence: int
    is_broad_theme: bool = False
    leading_symbols: List[str]
    rotation_stage: str
    warnings: List[str]


class SectorRotationResponse(BaseModel):
    generated_at: str
    market_scope: str
    benchmark_change_pct: float
    methodology: List[str]
    sample_policy: str
    total_sectors: int
    current_hot_sectors: List[SectorConceptItem]
    next_potential_sector: Optional[SectorConceptItem] = None
    rotation_path: List[str]
    reasoning: List[str]
    risk_warnings: List[str]


class KLinePoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class StockKLineResponse(BaseModel):
    symbol: str
    period: str
    interval: str
    source: str
    points: List[KLinePoint]
    latest_price: Optional[float] = None
    change_pct: Optional[float] = None
    is_fallback: bool = False
    warning: Optional[str] = None


class StockSyncResponse(BaseModel):
    success: bool
    total_count: int
    a_share_count: int
    hk_count: int
    us_count: int = 0
    duration_ms: int
    last_synced_at: Optional[str] = None
    message: Optional[str] = None


class StockEnrichResponse(BaseModel):
    success: bool
    total: int
    processed: int
    success_count: int
    failed_count: int
    skipped_count: int
    duration_ms: int
    message: Optional[str] = None


class StockEnrichStatusResponse(BaseModel):
    total_universe: int
    enriched_count: int
    success_count: int
    failed_count: int
    coverage_rate: float
    latest_enriched_at: Optional[str] = None


class ReportListItem(BaseModel):
    report_id: str
    symbol: str
    name: str
    market: MarketType
    score: int
    recommendation: RecommendationType
    risk_level: RiskLevel
    report_version: str
    report_date: str
    headline: str


class ReportDetail(ReportListItem):
    summary: str
    key_points: List[str]
    risk_alerts: List[str]
    action_plan: List[str]
    trade_plan: TradePlan


class StockQuery(BaseModel):
    analyzed: Optional[bool] = None
    market: Optional[MarketType] = None
    board: Optional[str] = None
    exchange: Optional[str] = None
    industry: Optional[str] = None
    concept: Optional[str] = None
    tag: Optional[str] = None
    recommendation: Optional[RecommendationType] = None
    market_cap_min: Optional[float] = None
    market_cap_max: Optional[float] = None
    pe_max: Optional[float] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    net_profit_min: Optional[float] = None
    revenue_min: Optional[float] = None
    revenue_growth_min: Optional[float] = None
    revenue_growth_qoq_min: Optional[float] = None
    profit_growth_min: Optional[float] = None
    profit_growth_qoq_min: Optional[float] = None
    gross_margin_min: Optional[float] = None
    net_margin_min: Optional[float] = None
    exclude_st: Optional[bool] = None
    roe_min: Optional[float] = None
    debt_ratio_max: Optional[float] = None
    score_min: Optional[int] = None
    score_max: Optional[int] = None
    change_pct_min: Optional[float] = None
    change_pct_max: Optional[float] = None
    q: Optional[str] = None
    sort_by: Optional[Literal["score", "change_pct", "price"]] = "score"
