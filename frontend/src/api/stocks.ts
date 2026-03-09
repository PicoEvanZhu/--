import { request } from "./client";
import type {
  DashboardSummary,
  MarketType,
  RecommendationType,
  ReportDetail,
  ReportListItem,
  SectorRotationResponse,
  StockAnalysis,
  StockDetail,
  StockSnapshot,
  StockQARequest,
  StockQAResponse,
  StockEnrichResponse,
  StockEnrichStatusResponse,
  StockKLineResponse,
  StockListResponse,
  StockTradeReviewCreateRequest,
  StockTradeReviewItem,
  StockTradeReviewResponse,
  StockSyncResponse,
  StockTradeReviewUpdateRequest,
} from "../types/stock";

interface StockListQuery {
  analyzed?: boolean;
  market?: MarketType;
  board?: string;
  exchange?: string;
  industry?: string;
  concept?: string;
  tag?: string;
  recommendation?: RecommendationType;
  dividend_only?: boolean;
  dividend_years_min?: number;
  dividend_yield_min?: number;
  ex_dividend_soon?: boolean;
  market_cap_min?: number;
  market_cap_max?: number;
  price_min?: number;
  price_max?: number;
  pe_max?: number;
  net_profit_min?: number;
  revenue_min?: number;
  revenue_growth_min?: number;
  revenue_growth_qoq_min?: number;
  profit_growth_min?: number;
  profit_growth_qoq_min?: number;
  gross_margin_min?: number;
  net_margin_min?: number;
  roe_min?: number;
  debt_ratio_max?: number;
  exclude_st?: boolean;
  score_min?: number;
  score_max?: number;
  change_pct_min?: number;
  change_pct_max?: number;
  prev_limit_up?: boolean;
  prev_limit_down?: boolean;
  q?: string;
  sort_by?: "score" | "change_pct" | "price" | "dividend_years" | "dividend_yield";
  page?: number;
  page_size?: number;
  include_meta?: boolean;
}

interface RequestOptions {
  signal?: AbortSignal;
}

interface StockEnrichQuery {
  force?: boolean;
  market?: MarketType;
  limit?: number;
  sleep_ms?: number;
}

export async function listStocks(query: StockListQuery = {}, options: RequestOptions = {}): Promise<StockListResponse> {
  const params = new URLSearchParams();

  if (query.analyzed !== undefined) {
    params.set("analyzed", String(query.analyzed));
  }
  if (query.market) {
    params.set("market", query.market);
  }
  if (query.board) {
    params.set("board", query.board);
  }
  if (query.exchange) {
    params.set("exchange", query.exchange);
  }
  if (query.industry) {
    params.set("industry", query.industry);
  }
  if (query.concept) {
    params.set("concept", query.concept);
  }
  if (query.tag) {
    params.set("tag", query.tag);
  }
  if (query.recommendation) {
    params.set("recommendation", query.recommendation);
  }
  if (query.dividend_only) {
    params.set("dividend_only", "true");
  }
  if (query.dividend_years_min !== undefined) {
    params.set("dividend_years_min", String(query.dividend_years_min));
  }
  if (query.dividend_yield_min !== undefined) {
    params.set("dividend_yield_min", String(query.dividend_yield_min));
  }
  if (query.ex_dividend_soon) {
    params.set("ex_dividend_soon", "true");
  }
  if (query.market_cap_min !== undefined) {
    params.set("market_cap_min", String(query.market_cap_min));
  }
  if (query.market_cap_max !== undefined) {
    params.set("market_cap_max", String(query.market_cap_max));
  }
  if (query.price_min !== undefined) {
    params.set("price_min", String(query.price_min));
  }
  if (query.price_max !== undefined) {
    params.set("price_max", String(query.price_max));
  }
  if (query.pe_max !== undefined) {
    params.set("pe_max", String(query.pe_max));
  }
  if (query.net_profit_min !== undefined) {
    params.set("net_profit_min", String(query.net_profit_min));
  }
  if (query.revenue_min !== undefined) {
    params.set("revenue_min", String(query.revenue_min));
  }
  if (query.revenue_growth_min !== undefined) {
    params.set("revenue_growth_min", String(query.revenue_growth_min));
  }
  if (query.revenue_growth_qoq_min !== undefined) {
    params.set("revenue_growth_qoq_min", String(query.revenue_growth_qoq_min));
  }
  if (query.profit_growth_min !== undefined) {
    params.set("profit_growth_min", String(query.profit_growth_min));
  }
  if (query.profit_growth_qoq_min !== undefined) {
    params.set("profit_growth_qoq_min", String(query.profit_growth_qoq_min));
  }
  if (query.gross_margin_min !== undefined) {
    params.set("gross_margin_min", String(query.gross_margin_min));
  }
  if (query.net_margin_min !== undefined) {
    params.set("net_margin_min", String(query.net_margin_min));
  }
  if (query.roe_min !== undefined) {
    params.set("roe_min", String(query.roe_min));
  }
  if (query.debt_ratio_max !== undefined) {
    params.set("debt_ratio_max", String(query.debt_ratio_max));
  }
  if (query.exclude_st) {
    params.set("exclude_st", "true");
  }
  if (query.score_min !== undefined) {
    params.set("score_min", String(query.score_min));
  }
  if (query.score_max !== undefined) {
    params.set("score_max", String(query.score_max));
  }
  if (query.change_pct_min !== undefined) {
    params.set("change_pct_min", String(query.change_pct_min));
  }
  if (query.change_pct_max !== undefined) {
    params.set("change_pct_max", String(query.change_pct_max));
  }
  if (query.prev_limit_up) {
    params.set("prev_limit_up", "true");
  }
  if (query.prev_limit_down) {
    params.set("prev_limit_down", "true");
  }
  if (query.q) {
    params.set("q", query.q);
  }
  if (query.sort_by) {
    params.set("sort_by", query.sort_by);
  }
  if (query.page) {
    params.set("page", String(query.page));
  }
  if (query.page_size) {
    params.set("page_size", String(query.page_size));
  }
  if (query.include_meta === false) {
    params.set("include_meta", "false");
  }

  return request<StockListResponse>({
    path: `/stocks${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
    signal: options.signal,
  });
}

export async function syncStockUniverse(force = false): Promise<StockSyncResponse> {
  const params = new URLSearchParams();
  if (force) {
    params.set("force", "true");
  }

  return request<StockSyncResponse>({
    path: `/stocks/sync${params.toString() ? `?${params.toString()}` : ""}`,
    method: "POST",
  });
}

export async function enrichStockUniverse(query: StockEnrichQuery = {}): Promise<StockEnrichResponse> {
  const params = new URLSearchParams();

  if (query.force) {
    params.set("force", "true");
  }
  if (query.market) {
    params.set("market", query.market);
  }
  if (query.limit !== undefined) {
    params.set("limit", String(query.limit));
  }
  if (query.sleep_ms !== undefined) {
    params.set("sleep_ms", String(query.sleep_ms));
  }

  return request<StockEnrichResponse>({
    path: `/stocks/enrich${params.toString() ? `?${params.toString()}` : ""}`,
    method: "POST",
  });
}

export async function getStockEnrichStatus(): Promise<StockEnrichStatusResponse> {
  return request<StockEnrichStatusResponse>({
    path: "/stocks/enrich/status",
    method: "GET",
  });
}

export async function getStockDetail(symbol: string): Promise<StockDetail> {
  return request<StockDetail>({
    path: `/stocks/${encodeURIComponent(symbol)}`,
    method: "GET",
  });
}

export async function getStockAnalysis(symbol: string): Promise<StockAnalysis> {
  return request<StockAnalysis>({
    path: `/stocks/${encodeURIComponent(symbol)}/analysis`,
    method: "GET",
  });
}

export async function getStockSnapshot(symbol: string): Promise<StockSnapshot> {
  return request<StockSnapshot>({
    path: `/stocks/${encodeURIComponent(symbol)}/snapshot`,
    method: "GET",
  });
}

export async function askStockQuestion(symbol: string, payload: StockQARequest, options: RequestOptions = {}): Promise<StockQAResponse> {
  return request<StockQAResponse>({
    path: `/stocks/${encodeURIComponent(symbol)}/qa`,
    method: "POST",
    body: JSON.stringify(payload),
    signal: options.signal,
  });
}

export async function getStockKLine(
  symbol: string,
  period: "1mo" | "3mo" | "6mo" | "1y" | "5y" = "6mo",
  interval: "1d" | "1h" = "1d"
): Promise<StockKLineResponse> {
  const params = new URLSearchParams();
  params.set("period", period);
  params.set("interval", interval);

  return request<StockKLineResponse>({
    path: `/stocks/${encodeURIComponent(symbol)}/kline?${params.toString()}`,
    method: "GET",
  });
}

export async function getStockTradeReviews(symbol: string): Promise<StockTradeReviewResponse> {
  return request<StockTradeReviewResponse>({
    path: `/stocks/${encodeURIComponent(symbol)}/reviews`,
    method: "GET",
  });
}

export async function createStockTradeReview(
  symbol: string,
  payload: StockTradeReviewCreateRequest
): Promise<StockTradeReviewItem> {
  return request<StockTradeReviewItem>({
    path: `/stocks/${encodeURIComponent(symbol)}/reviews`,
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateStockTradeReview(
  symbol: string,
  reviewId: number,
  payload: StockTradeReviewUpdateRequest
): Promise<StockTradeReviewItem> {
  return request<StockTradeReviewItem>({
    path: `/stocks/${encodeURIComponent(symbol)}/reviews/${reviewId}`,
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>({
    path: "/dashboard/summary",
    method: "GET",
  });
}

export async function getSectorRotation(market?: MarketType, topN = 8, options: RequestOptions = {}): Promise<SectorRotationResponse> {
  const params = new URLSearchParams();
  if (market) {
    params.set("market", market);
  }
  params.set("top_n", String(topN));

  return request<SectorRotationResponse>({
    path: `/stocks/sectors/rotation${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
    signal: options.signal,
  });
}

export async function listReports(q?: string): Promise<ReportListItem[]> {
  const params = new URLSearchParams();

  if (q?.trim()) {
    params.set("q", q.trim());
  }

  return request<ReportListItem[]>({
    path: `/reports${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
  });
}

export async function getReportDetail(symbol: string): Promise<ReportDetail> {
  return request<ReportDetail>({
    path: `/reports/${encodeURIComponent(symbol)}`,
    method: "GET",
  });
}
