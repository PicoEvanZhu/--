export type MarketType = "A股" | "港股" | "创业板" | "科创板" | "美股";
export type RecommendationType = "buy" | "watch" | "hold_cautious" | "avoid";
export type RiskLevel = "low" | "medium" | "high";
export type TradeReviewAction = "buy" | "sell" | "add" | "reduce" | "observe";
export type FollowUpStatus = "open" | "in_progress" | "closed";

export interface StockItem {
  symbol: string;
  name: string;
  market: MarketType;
  board: string;
  exchange: string;
  industry: string;
  sector: string;
  tags: string[];
  price: number;
  change_pct: number;
  analyzed: boolean;
  score: number;
  recommendation: RecommendationType;
  updated_at?: string | null;
}

export interface FinancialReport {
  year: string;
  revenue: number;
  net_profit: number;
  gross_margin: number;
  net_margin: number;
  roe: number;
  debt_ratio: number;
  operating_cashflow: number;
  eps: number;
  dividend_yield: number;
  report_url: string;
}

export interface ValuationHistoryPoint {
  year: string;
  pe: number;
  pb: number;
  market_cap: number;
}

export interface DividendRecord {
  year: string;
  cash_dividend_per_share: number;
  payout_ratio: number;
  ex_dividend_date: string;
}

export interface ShareholderRecord {
  name: string;
  holder_type: string;
  holding_ratio: number;
  change_yoy: number;
}

export interface PeerCompany {
  symbol: string;
  name: string;
  market: string;
  pe: number;
  revenue_growth: number;
  roe: number;
  market_cap: number;
  comparison_view: string;
}

export interface StockDetail {
  symbol: string;
  name: string;
  market: MarketType;
  board: string;
  exchange: string;
  sector: string;
  price: number;
  change_pct: number;
  analyzed: boolean;
  pe: number;
  pb: number;
  roe: number;
  debt_ratio: number;
  revenue_growth: number;
  profit_growth: number;
  momentum: number;
  volatility: number;
  news_sentiment: number;
  currency: string;
  market_cap: number;
  free_float_cap: number;
  turnover_rate: number;
  amplitude: number;
  avg_volume_5d: number;
  avg_volume_20d: number;
  support_price: number;
  resistance_price: number;
  company_full_name: string;
  english_name: string;
  listing_date: string;
  company_website: string;
  investor_relations_url: string;
  exchange_profile_url: string;
  quote_url: string;
  headquarters: string;
  legal_representative: string;
  employees: number;
  main_business: string;
  products_services: string[];
  company_intro: string;
  business_tags: string[];
  recent_events: string[];
  core_logic: string[];
  key_risks: string[];
  catalyst_events: string[];
  financial_reports: FinancialReport[];
  valuation_history: ValuationHistoryPoint[];
  dividend_history: DividendRecord[];
  shareholder_structure: ShareholderRecord[];
  peer_companies: PeerCompany[];
  news_highlights: string[];
  last_report_date: string;
}

export interface TradePlan {
  entry_range: string;
  stop_loss: string;
  take_profit: string;
  position_advice: string;
}

export interface StockFactorScores {
  fundamental: number;
  valuation: number;
  momentum: number;
  sentiment: number;
  risk_control: number;
}

export interface StockAnalysis {
  symbol: string;
  score: number;
  risk_level: RiskLevel;
  recommendation: RecommendationType;
  summary: string;
  confidence: number;
  factor_scores: StockFactorScores;
  strengths: string[];
  risks: string[];
  action_items: string[];
  monitoring_points: string[];
  scenario_analysis: string[];
  trade_plan: TradePlan;
}

export interface StockSnapshot {
  symbol: string;
  detail: StockDetail;
  analysis: StockAnalysis;
}

export interface StockTradeReviewItem {
  id: number;
  symbol: string;
  owner_user_id?: number | null;
  owner_username?: string | null;
  trade_date: string;
  action: TradeReviewAction;
  price?: number | null;
  quantity?: number | null;
  thesis: string;
  execution_notes?: string | null;
  outcome_review?: string | null;
  lessons_learned?: string | null;
  follow_up_items: string[];
  follow_up_status: FollowUpStatus;
  next_review_date?: string | null;
  confidence_score?: number | null;
  discipline_score?: number | null;
  created_at: string;
  updated_at: string;
  floating_pnl?: number | null;
  floating_pnl_pct?: number | null;
  is_follow_up_due: boolean;
}

export interface StockTradeReviewSummary {
  total_reviews: number;
  open_follow_ups: number;
  in_progress_follow_ups: number;
  closed_follow_ups: number;
  due_follow_ups: number;
  avg_confidence_score: number;
  avg_discipline_score: number;
  net_floating_pnl: number;
  net_floating_pnl_pct: number;
}

export interface StockTradeReviewResponse {
  symbol: string;
  current_price?: number | null;
  items: StockTradeReviewItem[];
  summary: StockTradeReviewSummary;
}

export interface StockTradeReviewCreateRequest {
  trade_date: string;
  action: TradeReviewAction;
  price?: number;
  quantity?: number;
  thesis: string;
  execution_notes?: string;
  outcome_review?: string;
  lessons_learned?: string;
  follow_up_items?: string[];
  follow_up_status?: FollowUpStatus;
  next_review_date?: string;
  confidence_score?: number;
  discipline_score?: number;
}

export interface StockTradeReviewUpdateRequest {
  trade_date?: string;
  action?: TradeReviewAction;
  price?: number;
  quantity?: number;
  thesis?: string;
  execution_notes?: string;
  outcome_review?: string;
  lessons_learned?: string;
  follow_up_items?: string[];
  follow_up_status?: FollowUpStatus;
  next_review_date?: string;
  confidence_score?: number;
  discipline_score?: number;
}

export interface DashboardSummary {
  total_stocks: number;
  analyzed_count: number;
  risk_alert_count: number;
  average_score: number;
  best_opportunities: StockItem[];
  high_risk_stocks: StockItem[];
  latest_updates: string[];
}

export interface StockListStats {
  average_score: number;
  median_score: number;
  positive_change_count: number;
  negative_change_count: number;
  by_market: Record<string, number>;
  by_board: Record<string, number>;
  by_recommendation: Record<string, number>;
  top_industries: Record<string, number>;
  top_tags: Record<string, number>;
}

export interface StockListResponse {
  items: StockItem[];
  total: number;
  page: number;
  page_size: number;
  industries: string[];
  tags: string[];
  boards: string[];
  exchanges: string[];
  recommendations: RecommendationType[];
  stats: StockListStats;
  last_synced_at?: string | null;
}

export interface StockSyncResponse {
  success: boolean;
  total_count: number;
  a_share_count: number;
  hk_count: number;
  us_count: number;
  duration_ms: number;
  last_synced_at?: string | null;
  message?: string | null;
}

export interface StockEnrichResponse {
  success: boolean;
  total: number;
  processed: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  duration_ms: number;
  message?: string | null;
}

export interface StockEnrichStatusResponse {
  total_universe: number;
  enriched_count: number;
  success_count: number;
  failed_count: number;
  coverage_rate: number;
  latest_enriched_at?: string | null;
}

export interface ReportListItem {
  report_id: string;
  symbol: string;
  name: string;
  market: MarketType;
  score: number;
  recommendation: RecommendationType;
  risk_level: RiskLevel;
  report_version: string;
  report_date: string;
  headline: string;
}

export interface ReportDetail extends ReportListItem {
  summary: string;
  key_points: string[];
  risk_alerts: string[];
  action_plan: string[];
  trade_plan: TradePlan;
}
