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
  StockEnrichResponse,
  StockEnrichStatusResponse,
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
  score_min?: number;
  score_max?: number;
  change_pct_min?: number;
  change_pct_max?: number;
  q?: string;
  sort_by?: "score" | "change_pct" | "price";
  page?: number;
  page_size?: number;
}

interface StockEnrichQuery {
  force?: boolean;
  market?: MarketType;
  limit?: number;
  sleep_ms?: number;
}

export async function listStocks(query: StockListQuery = {}): Promise<StockListResponse> {
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

  return request<StockListResponse>({
    path: `/stocks${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
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

export async function getSectorRotation(market?: MarketType, topN = 8): Promise<SectorRotationResponse> {
  const params = new URLSearchParams();
  if (market) {
    params.set("market", market);
  }
  params.set("top_n", String(topN));

  return request<SectorRotationResponse>({
    path: `/stocks/sectors/rotation${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
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
