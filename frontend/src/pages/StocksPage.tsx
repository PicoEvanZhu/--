import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { AppstoreOutlined, CalendarOutlined, FundOutlined } from "@ant-design/icons";
import { Link, useLocation, useNavigate, useNavigationType, useSearchParams } from "react-router-dom";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Pagination,
  Progress,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";

import { createMyWatchlistItem } from "../api/account";
import { getSectorRotation, listStocks, syncStockUniverse } from "../api/stocks";
import type { MarketType, RecommendationType, SectorRotationResponse, StockDividendSummary, StockItem, StockListStats } from "../types/stock";
import { isAuthenticated, isGuestMode } from "../utils/auth";
import { addStockToCart, getStockCartEventName, getStockCartItems } from "../utils/stockCart";

const { Text } = Typography;

type SortBy = "score" | "change_pct" | "price" | "dividend_years" | "dividend_yield";
type AnalyzedQuery = "all" | "true" | "false";

const marketOptions: { label: string; value: MarketType }[] = [
  { label: "A股", value: "A股" },
  { label: "港股", value: "港股" },
  { label: "创业板", value: "创业板" },
  { label: "科创板", value: "科创板" },
  { label: "美股", value: "美股" },
];

const sortOptions: { label: string; value: SortBy }[] = [
  { label: "按评分", value: "score" },
  { label: "按涨跌幅", value: "change_pct" },
  { label: "按价格", value: "price" },
  { label: "按分红年数", value: "dividend_years" },
  { label: "按股息率", value: "dividend_yield" },
];

const emptyStats: StockListStats = {
  average_score: 0,
  median_score: 0,
  positive_change_count: 0,
  negative_change_count: 0,
  by_market: {},
  by_board: {},
  by_recommendation: {},
  top_industries: {},
  top_concepts: {},
  top_tags: {},
};

const emptyDividendSummary: StockDividendSummary = {
  total: 0,
  continuous_3y_count: 0,
  high_yield_count: 0,
  upcoming_ex_dividend_count: 0,
  latest_year: null,
  by_market: {},
  by_board: {},
};

interface StocksPageListCache {
  items: StockItem[];
  total: number;
}

interface StocksPageMetaCache {
  lastSyncedAt: string | null;
  industryOptions: string[];
  conceptOptions: string[];
  tagOptions: string[];
  boardOptions: string[];
  exchangeOptions: string[];
  recommendationOptions: RecommendationType[];
  stats: StockListStats;
  dividendSummary: StockDividendSummary;
  sectorRotation: SectorRotationResponse | null;
  rotationLoaded: boolean;
}

interface StocksPagePanelCache {
  dividendCalendarStocks: StockItem[];
  highYieldStocks: StockItem[];
  dividendPanelsError: string | null;
}

const QUICK_FILTER_PRESETS_KEY = "stock_assistant_filter_presets_v1";
const QUICK_FILTER_PRESET_LIMIT = 30;
const FILTER_DEBOUNCE_MS = 450;
const DEFAULT_PAGE_SIZE = 20;
const STOCKS_PAGE_LIST_CACHE_LIMIT = 12;
const STOCKS_PAGE_META_CACHE_LIMIT = 12;
const STOCKS_PAGE_PANEL_CACHE_LIMIT = 8;

interface QuickFilterCriteria {
  analyzed: AnalyzedQuery;
  market?: MarketType;
  board?: string;
  exchange?: string;
  industry?: string;
  concept?: string;
  tag?: string;
  recommendation?: RecommendationType;
  dividendOnly: boolean;
  dividendYearsMin?: number;
  dividendYieldMin?: number;
  exDividendSoon: boolean;
  marketCapMin?: number;
  marketCapMax?: number;
  priceMin?: number;
  priceMax?: number;
  peMax?: number;
  netProfitMin?: number;
  revenueMin?: number;
  revenueGrowthMin?: number;
  revenueGrowthQoqMin?: number;
  profitGrowthMin?: number;
  profitGrowthQoqMin?: number;
  grossMarginMin?: number;
  netMarginMin?: number;
  roeMin?: number;
  debtRatioMax?: number;
  excludeSt: boolean;
  scoreMin?: number;
  scoreMax?: number;
  changePctMin?: number;
  changePctMax?: number;
  prevLimitUp: boolean;
  prevLimitDown: boolean;
  sortBy: SortBy;
  keyword: string;
}

interface QuickFilterPreset {
  id: string;
  name: string;
  criteria: QuickFilterCriteria;
  updated_at: string;
}

const stocksPageListCache = new Map<string, StocksPageListCache>();
const stocksPageMetaCache = new Map<string, StocksPageMetaCache>();
const stocksPagePanelCache = new Map<string, StocksPagePanelCache>();

function getLruCacheValue<T>(cache: Map<string, T>, key: string): T | undefined {
  const cached = cache.get(key);
  if (cached === undefined) {
    return undefined;
  }
  cache.delete(key);
  cache.set(key, cached);
  return cached;
}

function setLruCacheValue<T>(cache: Map<string, T>, key: string, value: T, limit: number): void {
  if (cache.has(key)) {
    cache.delete(key);
  }
  cache.set(key, value);
  while (cache.size > limit) {
    const oldestKey = cache.keys().next().value as string | undefined;
    if (!oldestKey) {
      break;
    }
    cache.delete(oldestKey);
  }
}

function clearStocksPageCaches(): void {
  stocksPageListCache.clear();
  stocksPageMetaCache.clear();
  stocksPagePanelCache.clear();
}

function buildDividendPanelsCacheKey(market?: MarketType, lastSyncedAt?: string | null): string {
  return `dividend-panels:${market ?? "all"}:${lastSyncedAt ?? "unknown"}`;
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === "AbortError";
  }
  return error instanceof Error && error.name === "AbortError";
}

function toAnalyzedFlag(value: AnalyzedQuery): boolean | undefined {
  if (value === "all") {
    return undefined;
  }
  return value === "true";
}

function recommendationLabel(recommendation: RecommendationType): string {
  if (recommendation === "buy") {
    return "关注买入";
  }
  if (recommendation === "watch") {
    return "继续观察";
  }
  if (recommendation === "hold_cautious") {
    return "谨慎持有";
  }
  return "暂时回避";
}

function recommendationColor(recommendation: RecommendationType): string {
  if (recommendation === "buy") {
    return "green";
  }
  if (recommendation === "watch") {
    return "blue";
  }
  if (recommendation === "hold_cautious") {
    return "gold";
  }
  return "red";
}

function parsePositiveInt(value: string | null, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return Math.floor(parsed);
}

function parseOptionalNumber(value: string | null): number | undefined {
  if (!value) {
    return undefined;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return undefined;
  }
  return parsed;
}

function formatMetric(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function loadQuickFilterPresets(): QuickFilterPreset[] {
  const raw = localStorage.getItem(QUICK_FILTER_PRESETS_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as QuickFilterPreset[];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item) => Boolean(item?.id) && Boolean(item?.name) && Boolean(item?.criteria));
  } catch {
    return [];
  }
}

function persistQuickFilterPresets(presets: QuickFilterPreset[]): void {
  localStorage.setItem(QUICK_FILTER_PRESETS_KEY, JSON.stringify(presets));
}

function createQuickFilterPresetId(): string {
  return `qf_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function buildStocksQueryKey(input: {
  analyzed: AnalyzedQuery;
  market?: MarketType;
  board?: string;
  exchange?: string;
  industry?: string;
  concept?: string;
  tag?: string;
  recommendation?: RecommendationType;
  dividendOnly: boolean;
  dividendYearsMin?: number;
  dividendYieldMin?: number;
  exDividendSoon: boolean;
  marketCapMin?: number;
  marketCapMax?: number;
  priceMin?: number;
  priceMax?: number;
  peMax?: number;
  netProfitMin?: number;
  revenueMin?: number;
  revenueGrowthMin?: number;
  revenueGrowthQoqMin?: number;
  profitGrowthMin?: number;
  profitGrowthQoqMin?: number;
  grossMarginMin?: number;
  netMarginMin?: number;
  roeMin?: number;
  debtRatioMax?: number;
  excludeSt: boolean;
  scoreMin?: number;
  scoreMax?: number;
  changePctMin?: number;
  changePctMax?: number;
  prevLimitUp: boolean;
  prevLimitDown: boolean;
  sortBy: SortBy;
  keyword: string;
  page: number;
  pageSize: number;
}): string {
  return JSON.stringify({
    analyzed: input.analyzed,
    market: input.market ?? null,
    board: input.board ?? null,
    exchange: input.exchange ?? null,
    industry: input.industry ?? null,
    concept: input.concept ?? null,
    tag: input.tag ?? null,
    recommendation: input.recommendation ?? null,
    dividend_only: input.dividendOnly,
    dividend_years_min: input.dividendYearsMin ?? null,
    dividend_yield_min: input.dividendYieldMin ?? null,
    ex_dividend_soon: input.exDividendSoon,
    market_cap_min: input.marketCapMin ?? null,
    market_cap_max: input.marketCapMax ?? null,
    price_min: input.priceMin ?? null,
    price_max: input.priceMax ?? null,
    pe_max: input.peMax ?? null,
    net_profit_min: input.netProfitMin ?? null,
    revenue_min: input.revenueMin ?? null,
    revenue_growth_min: input.revenueGrowthMin ?? null,
    revenue_growth_qoq_min: input.revenueGrowthQoqMin ?? null,
    profit_growth_min: input.profitGrowthMin ?? null,
    profit_growth_qoq_min: input.profitGrowthQoqMin ?? null,
    gross_margin_min: input.grossMarginMin ?? null,
    net_margin_min: input.netMarginMin ?? null,
    roe_min: input.roeMin ?? null,
    debt_ratio_max: input.debtRatioMax ?? null,
    exclude_st: input.excludeSt,
    score_min: input.scoreMin ?? null,
    score_max: input.scoreMax ?? null,
    change_pct_min: input.changePctMin ?? null,
    change_pct_max: input.changePctMax ?? null,
    prev_limit_up: input.prevLimitUp,
    prev_limit_down: input.prevLimitDown,
    sort_by: input.sortBy,
    keyword: input.keyword.trim(),
    page: input.page,
    page_size: input.pageSize,
  });
}

function buildStocksMetaKey(input: {
  analyzed: AnalyzedQuery;
  market?: MarketType;
  board?: string;
  exchange?: string;
  industry?: string;
  concept?: string;
  tag?: string;
  recommendation?: RecommendationType;
  dividendOnly: boolean;
  dividendYearsMin?: number;
  dividendYieldMin?: number;
  exDividendSoon: boolean;
  marketCapMin?: number;
  marketCapMax?: number;
  priceMin?: number;
  priceMax?: number;
  peMax?: number;
  netProfitMin?: number;
  revenueMin?: number;
  revenueGrowthMin?: number;
  revenueGrowthQoqMin?: number;
  profitGrowthMin?: number;
  profitGrowthQoqMin?: number;
  grossMarginMin?: number;
  netMarginMin?: number;
  roeMin?: number;
  debtRatioMax?: number;
  excludeSt: boolean;
  scoreMin?: number;
  scoreMax?: number;
  changePctMin?: number;
  changePctMax?: number;
  prevLimitUp: boolean;
  prevLimitDown: boolean;
  sortBy: SortBy;
  keyword: string;
}): string {
  return JSON.stringify({
    analyzed: input.analyzed,
    market: input.market ?? null,
    board: input.board ?? null,
    exchange: input.exchange ?? null,
    industry: input.industry ?? null,
    concept: input.concept ?? null,
    tag: input.tag ?? null,
    recommendation: input.recommendation ?? null,
    dividend_only: input.dividendOnly,
    dividend_years_min: input.dividendYearsMin ?? null,
    dividend_yield_min: input.dividendYieldMin ?? null,
    ex_dividend_soon: input.exDividendSoon,
    market_cap_min: input.marketCapMin ?? null,
    market_cap_max: input.marketCapMax ?? null,
    price_min: input.priceMin ?? null,
    price_max: input.priceMax ?? null,
    pe_max: input.peMax ?? null,
    net_profit_min: input.netProfitMin ?? null,
    revenue_min: input.revenueMin ?? null,
    revenue_growth_min: input.revenueGrowthMin ?? null,
    revenue_growth_qoq_min: input.revenueGrowthQoqMin ?? null,
    profit_growth_min: input.profitGrowthMin ?? null,
    profit_growth_qoq_min: input.profitGrowthQoqMin ?? null,
    gross_margin_min: input.grossMarginMin ?? null,
    net_margin_min: input.netMarginMin ?? null,
    roe_min: input.roeMin ?? null,
    debt_ratio_max: input.debtRatioMax ?? null,
    exclude_st: input.excludeSt,
    score_min: input.scoreMin ?? null,
    score_max: input.scoreMax ?? null,
    change_pct_min: input.changePctMin ?? null,
    change_pct_max: input.changePctMax ?? null,
    prev_limit_up: input.prevLimitUp,
    prev_limit_down: input.prevLimitDown,
    sort_by: input.sortBy,
    keyword: input.keyword.trim(),
  });
}

function formatErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }

  if (error && typeof error === "object") {
    const maybeError = error as { message?: unknown; detail?: unknown; error?: unknown };
    const candidate = maybeError.message ?? maybeError.detail ?? maybeError.error;

    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }

    if (Array.isArray(candidate)) {
      const joined = candidate
        .map((item) => {
          if (typeof item === "string") {
            return item;
          }
          if (item && typeof item === "object" && "msg" in item) {
            const msg = (item as { msg?: unknown }).msg;
            return typeof msg === "string" ? msg : "";
          }
          return "";
        })
        .filter(Boolean)
        .join("；");

      if (joined) {
        return joined;
      }
    }
  }

  return fallback;
}

function StocksPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const navigationType = useNavigationType();
  const [searchParams, setSearchParams] = useSearchParams();
  const { message } = AntdApp.useApp();
  const currentListPath = `${location.pathname}${location.search}`;
  const skipInitialListReloadRef = useRef(false);
  const skipInitialPanelsReloadRef = useRef(false);
  const listRequestIdRef = useRef(0);
  const listAbortRef = useRef<AbortController | null>(null);
  const sectorRotationAbortRef = useRef<AbortController | null>(null);
  const dividendPanelsAbortRef = useRef<AbortController | null>(null);

  const initialAnalyzed = (searchParams.get("analyzed") as AnalyzedQuery | null) ?? "all";
  const initialMarket = (searchParams.get("market") as MarketType | null) ?? undefined;
  const initialBoard = searchParams.get("board") ?? undefined;
  const initialExchange = searchParams.get("exchange") ?? undefined;
  const initialIndustry = searchParams.get("industry") ?? undefined;
  const initialConcept = searchParams.get("concept") ?? undefined;
  const initialTag = searchParams.get("tag") ?? undefined;
  const initialRecommendation = (searchParams.get("recommendation") as RecommendationType | null) ?? undefined;
  const initialDividendOnly = searchParams.get("dividend_only") === "true";
  const initialDividendYearsMin = parseOptionalNumber(searchParams.get("dividend_years_min"));
  const initialDividendYieldMin = parseOptionalNumber(searchParams.get("dividend_yield_min"));
  const initialExDividendSoon = searchParams.get("ex_dividend_soon") === "true";
  const initialMarketCapMin = parseOptionalNumber(searchParams.get("market_cap_min"));
  const initialMarketCapMax = parseOptionalNumber(searchParams.get("market_cap_max"));
  const initialPriceMin = parseOptionalNumber(searchParams.get("price_min"));
  const initialPriceMax = parseOptionalNumber(searchParams.get("price_max"));
  const initialPeMax = parseOptionalNumber(searchParams.get("pe_max"));
  const initialNetProfitMin = parseOptionalNumber(searchParams.get("net_profit_min"));
  const initialRevenueMin = parseOptionalNumber(searchParams.get("revenue_min"));
  const initialRevenueGrowthMin = parseOptionalNumber(searchParams.get("revenue_growth_min"));
  const initialRevenueGrowthQoqMin = parseOptionalNumber(searchParams.get("revenue_growth_qoq_min"));
  const initialProfitGrowthMin = parseOptionalNumber(searchParams.get("profit_growth_min"));
  const initialProfitGrowthQoqMin = parseOptionalNumber(searchParams.get("profit_growth_qoq_min"));
  const initialGrossMarginMin = parseOptionalNumber(searchParams.get("gross_margin_min"));
  const initialNetMarginMin = parseOptionalNumber(searchParams.get("net_margin_min"));
  const initialRoeMin = parseOptionalNumber(searchParams.get("roe_min"));
  const initialDebtRatioMax = parseOptionalNumber(searchParams.get("debt_ratio_max"));
  const initialExcludeSt = searchParams.get("exclude_st") === "true";
  const initialScoreMin = parseOptionalNumber(searchParams.get("score_min"));
  const initialScoreMax = parseOptionalNumber(searchParams.get("score_max"));
  const initialChangePctMin = parseOptionalNumber(searchParams.get("change_pct_min"));
  const initialChangePctMax = parseOptionalNumber(searchParams.get("change_pct_max"));
  const initialPrevLimitUp = searchParams.get("prev_limit_up") === "true";
  const initialPrevLimitDown = searchParams.get("prev_limit_down") === "true";
  const initialSort = (searchParams.get("sort_by") as SortBy | null) ?? "score";
  const initialKeyword = searchParams.get("q") ?? "";
  const initialPage = parsePositiveInt(searchParams.get("page"), 1);
  const initialPageSize = Math.min(200, Math.max(10, parsePositiveInt(searchParams.get("page_size"), DEFAULT_PAGE_SIZE)));

  const [analyzed, setAnalyzed] = useState<AnalyzedQuery>(initialAnalyzed);
  const [market, setMarket] = useState<MarketType | undefined>(initialMarket);
  const [board, setBoard] = useState<string | undefined>(initialBoard);
  const [exchange, setExchange] = useState<string | undefined>(initialExchange);
  const [industry, setIndustry] = useState<string | undefined>(initialIndustry);
  const [concept, setConcept] = useState<string | undefined>(initialConcept);
  const [tag, setTag] = useState<string | undefined>(initialTag);
  const [recommendation, setRecommendation] = useState<RecommendationType | undefined>(initialRecommendation);
  const [dividendOnly, setDividendOnly] = useState(initialDividendOnly);
  const [dividendYearsMin, setDividendYearsMin] = useState<number | undefined>(initialDividendYearsMin);
  const [dividendYieldMin, setDividendYieldMin] = useState<number | undefined>(initialDividendYieldMin);
  const [exDividendSoon, setExDividendSoon] = useState(initialExDividendSoon);
  const [marketCapMin, setMarketCapMin] = useState<number | undefined>(initialMarketCapMin);
  const [marketCapMax, setMarketCapMax] = useState<number | undefined>(initialMarketCapMax);
  const [priceMin, setPriceMin] = useState<number | undefined>(initialPriceMin);
  const [priceMax, setPriceMax] = useState<number | undefined>(initialPriceMax);
  const [peMax, setPeMax] = useState<number | undefined>(initialPeMax);
  const [netProfitMin, setNetProfitMin] = useState<number | undefined>(initialNetProfitMin);
  const [revenueMin, setRevenueMin] = useState<number | undefined>(initialRevenueMin);
  const [revenueGrowthMin, setRevenueGrowthMin] = useState<number | undefined>(initialRevenueGrowthMin);
  const [revenueGrowthQoqMin, setRevenueGrowthQoqMin] = useState<number | undefined>(initialRevenueGrowthQoqMin);
  const [profitGrowthMin, setProfitGrowthMin] = useState<number | undefined>(initialProfitGrowthMin);
  const [profitGrowthQoqMin, setProfitGrowthQoqMin] = useState<number | undefined>(initialProfitGrowthQoqMin);
  const [grossMarginMin, setGrossMarginMin] = useState<number | undefined>(initialGrossMarginMin);
  const [netMarginMin, setNetMarginMin] = useState<number | undefined>(initialNetMarginMin);
  const [roeMin, setRoeMin] = useState<number | undefined>(initialRoeMin);
  const [debtRatioMax, setDebtRatioMax] = useState<number | undefined>(initialDebtRatioMax);
  const [excludeSt, setExcludeSt] = useState(initialExcludeSt);
  const [scoreMin, setScoreMin] = useState<number | undefined>(initialScoreMin);
  const [scoreMax, setScoreMax] = useState<number | undefined>(initialScoreMax);
  const [changePctMin, setChangePctMin] = useState<number | undefined>(initialChangePctMin);
  const [changePctMax, setChangePctMax] = useState<number | undefined>(initialChangePctMax);
  const [prevLimitUp, setPrevLimitUp] = useState(initialPrevLimitUp);
  const [prevLimitDown, setPrevLimitDown] = useState(initialPrevLimitDown);
  const [sortBy, setSortBy] = useState<SortBy>(initialSort);
  const [keywordInput, setKeywordInput] = useState(initialKeyword);
  const [keywordComposing, setKeywordComposing] = useState(false);
  const [keyword, setKeyword] = useState(initialKeyword);
  const [page, setPage] = useState(initialPage);
  const [pageSize, setPageSize] = useState(initialPageSize);

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stocks, setStocks] = useState<StockItem[]>([]);
  const [total, setTotal] = useState(0);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [industryOptions, setIndustryOptions] = useState<string[]>([]);
  const [conceptOptions, setConceptOptions] = useState<string[]>([]);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [boardOptions, setBoardOptions] = useState<string[]>([]);
  const [exchangeOptions, setExchangeOptions] = useState<string[]>([]);
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationType[]>([]);
  const [stats, setStats] = useState<StockListStats>(emptyStats);
  const [dividendSummary, setDividendSummary] = useState<StockDividendSummary>(emptyDividendSummary);
  const [dividendCalendarStocks, setDividendCalendarStocks] = useState<StockItem[]>([]);
  const [highYieldStocks, setHighYieldStocks] = useState<StockItem[]>([]);
  const [dividendPanelsLoading, setDividendPanelsLoading] = useState(false);
  const [dividendPanelsError, setDividendPanelsError] = useState<string | null>(null);
  const [dividendPanelsReloadKey, setDividendPanelsReloadKey] = useState(0);
  const [dividendCenterHidden, setDividendCenterHidden] = useState(true);
  const [dividendCalendarCollapsed, setDividendCalendarCollapsed] = useState(false);
  const [dividendCalendarHidden, setDividendCalendarHidden] = useState(true);
  const [highYieldCollapsed, setHighYieldCollapsed] = useState(false);
  const [highYieldHidden, setHighYieldHidden] = useState(true);
  const [sectorRotationHidden, setSectorRotationHidden] = useState(true);
  const [sectorRotation, setSectorRotation] = useState<SectorRotationResponse | null>(null);
  const [cartItems, setCartItems] = useState(getStockCartItems());
  const [addingSymbols, setAddingSymbols] = useState<Record<string, boolean>>({});
  const [quickFilterNameInput, setQuickFilterNameInput] = useState("");
  const [quickFilterPresets, setQuickFilterPresets] = useState<QuickFilterPreset[]>(() => loadQuickFilterPresets());
  const [activeQuickFilterPresetId, setActiveQuickFilterPresetId] = useState<string | undefined>(undefined);

  const applyMetaCacheToState = (metaCache: StocksPageMetaCache) => {
    setLastSyncedAt(metaCache.lastSyncedAt);
    setIndustryOptions(metaCache.industryOptions);
    setConceptOptions(metaCache.conceptOptions);
    setTagOptions(metaCache.tagOptions);
    setBoardOptions(metaCache.boardOptions);
    setExchangeOptions(metaCache.exchangeOptions);
    setRecommendationOptions(metaCache.recommendationOptions);
    setStats(metaCache.stats);
    setDividendSummary(metaCache.dividendSummary);
    setSectorRotation(metaCache.sectorRotation);
  };

  const currentQuickFilterCriteria = useMemo<QuickFilterCriteria>(
    () => ({
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword: keyword.trim(),
    }),
    [
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword,
    ]
  );

  const applyQueryToUrl = (next: {
    analyzed: AnalyzedQuery;
    market?: MarketType;
    board?: string;
    exchange?: string;
    industry?: string;
    concept?: string;
    tag?: string;
    recommendation?: RecommendationType;
    dividend_only: boolean;
    dividend_years_min?: number;
    dividend_yield_min?: number;
    ex_dividend_soon: boolean;
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
    exclude_st: boolean;
    score_min?: number;
    score_max?: number;
    change_pct_min?: number;
    change_pct_max?: number;
    prev_limit_up: boolean;
    prev_limit_down: boolean;
    sort_by: SortBy;
    q: string;
    page: number;
    page_size: number;
  }) => {
    const params = new URLSearchParams();

    if (next.analyzed !== "all") {
      params.set("analyzed", next.analyzed);
    }
    if (next.market) {
      params.set("market", next.market);
    }
    if (next.board?.trim()) {
      params.set("board", next.board.trim());
    }
    if (next.exchange?.trim()) {
      params.set("exchange", next.exchange.trim());
    }
    if (next.industry?.trim()) {
      params.set("industry", next.industry.trim());
    }
    if (next.concept?.trim()) {
      params.set("concept", next.concept.trim());
    }
    if (next.tag?.trim()) {
      params.set("tag", next.tag.trim());
    }
    if (next.recommendation) {
      params.set("recommendation", next.recommendation);
    }
    if (next.dividend_only) {
      params.set("dividend_only", "true");
    }
    if (next.dividend_years_min !== undefined) {
      params.set("dividend_years_min", String(next.dividend_years_min));
    }
    if (next.dividend_yield_min !== undefined) {
      params.set("dividend_yield_min", String(next.dividend_yield_min));
    }
    if (next.ex_dividend_soon) {
      params.set("ex_dividend_soon", "true");
    }
    if (next.market_cap_min !== undefined) {
      params.set("market_cap_min", String(next.market_cap_min));
    }
    if (next.market_cap_max !== undefined) {
      params.set("market_cap_max", String(next.market_cap_max));
    }
    if (next.price_min !== undefined) {
      params.set("price_min", String(next.price_min));
    }
    if (next.price_max !== undefined) {
      params.set("price_max", String(next.price_max));
    }
    if (next.pe_max !== undefined) {
      params.set("pe_max", String(next.pe_max));
    }
    if (next.net_profit_min !== undefined) {
      params.set("net_profit_min", String(next.net_profit_min));
    }
    if (next.revenue_min !== undefined) {
      params.set("revenue_min", String(next.revenue_min));
    }
    if (next.revenue_growth_min !== undefined) {
      params.set("revenue_growth_min", String(next.revenue_growth_min));
    }
    if (next.revenue_growth_qoq_min !== undefined) {
      params.set("revenue_growth_qoq_min", String(next.revenue_growth_qoq_min));
    }
    if (next.profit_growth_min !== undefined) {
      params.set("profit_growth_min", String(next.profit_growth_min));
    }
    if (next.profit_growth_qoq_min !== undefined) {
      params.set("profit_growth_qoq_min", String(next.profit_growth_qoq_min));
    }
    if (next.gross_margin_min !== undefined) {
      params.set("gross_margin_min", String(next.gross_margin_min));
    }
    if (next.net_margin_min !== undefined) {
      params.set("net_margin_min", String(next.net_margin_min));
    }
    if (next.roe_min !== undefined) {
      params.set("roe_min", String(next.roe_min));
    }
    if (next.debt_ratio_max !== undefined) {
      params.set("debt_ratio_max", String(next.debt_ratio_max));
    }
    if (next.exclude_st) {
      params.set("exclude_st", "true");
    }
    if (next.score_min !== undefined) {
      params.set("score_min", String(next.score_min));
    }
    if (next.score_max !== undefined) {
      params.set("score_max", String(next.score_max));
    }
    if (next.change_pct_min !== undefined) {
      params.set("change_pct_min", String(next.change_pct_min));
    }
    if (next.change_pct_max !== undefined) {
      params.set("change_pct_max", String(next.change_pct_max));
    }
    if (next.prev_limit_up) {
      params.set("prev_limit_up", "true");
    }
    if (next.prev_limit_down) {
      params.set("prev_limit_down", "true");
    }
    if (next.sort_by) {
      params.set("sort_by", next.sort_by);
    }
    if (next.q.trim()) {
      params.set("q", next.q.trim());
    }
    params.set("page", String(next.page));
    params.set("page_size", String(next.page_size));

    setSearchParams(params, { replace: true });
  };

  useEffect(() => {
    const nextAnalyzed = (searchParams.get("analyzed") as AnalyzedQuery | null) ?? "all";
    const nextMarket = (searchParams.get("market") as MarketType | null) ?? undefined;
    const nextBoard = searchParams.get("board") ?? undefined;
    const nextExchange = searchParams.get("exchange") ?? undefined;
    const nextIndustry = searchParams.get("industry") ?? undefined;
    const nextConcept = searchParams.get("concept") ?? undefined;
    const nextTag = searchParams.get("tag") ?? undefined;
    const nextRecommendation = (searchParams.get("recommendation") as RecommendationType | null) ?? undefined;
    const nextDividendOnly = searchParams.get("dividend_only") === "true";
    const nextDividendYearsMin = parseOptionalNumber(searchParams.get("dividend_years_min"));
    const nextDividendYieldMin = parseOptionalNumber(searchParams.get("dividend_yield_min"));
    const nextExDividendSoon = searchParams.get("ex_dividend_soon") === "true";
    const nextMarketCapMin = parseOptionalNumber(searchParams.get("market_cap_min"));
    const nextMarketCapMax = parseOptionalNumber(searchParams.get("market_cap_max"));
    const nextPriceMin = parseOptionalNumber(searchParams.get("price_min"));
    const nextPriceMax = parseOptionalNumber(searchParams.get("price_max"));
    const nextPeMax = parseOptionalNumber(searchParams.get("pe_max"));
    const nextNetProfitMin = parseOptionalNumber(searchParams.get("net_profit_min"));
    const nextRevenueMin = parseOptionalNumber(searchParams.get("revenue_min"));
    const nextRevenueGrowthMin = parseOptionalNumber(searchParams.get("revenue_growth_min"));
    const nextRevenueGrowthQoqMin = parseOptionalNumber(searchParams.get("revenue_growth_qoq_min"));
    const nextProfitGrowthMin = parseOptionalNumber(searchParams.get("profit_growth_min"));
    const nextProfitGrowthQoqMin = parseOptionalNumber(searchParams.get("profit_growth_qoq_min"));
    const nextGrossMarginMin = parseOptionalNumber(searchParams.get("gross_margin_min"));
    const nextNetMarginMin = parseOptionalNumber(searchParams.get("net_margin_min"));
    const nextRoeMin = parseOptionalNumber(searchParams.get("roe_min"));
    const nextDebtRatioMax = parseOptionalNumber(searchParams.get("debt_ratio_max"));
    const nextExcludeSt = searchParams.get("exclude_st") === "true";
    const nextScoreMin = parseOptionalNumber(searchParams.get("score_min"));
    const nextScoreMax = parseOptionalNumber(searchParams.get("score_max"));
    const nextChangePctMin = parseOptionalNumber(searchParams.get("change_pct_min"));
    const nextChangePctMax = parseOptionalNumber(searchParams.get("change_pct_max"));
    const nextPrevLimitUp = searchParams.get("prev_limit_up") === "true";
    const nextPrevLimitDown = searchParams.get("prev_limit_down") === "true";
    const nextSort = (searchParams.get("sort_by") as SortBy | null) ?? "score";
    const nextKeyword = searchParams.get("q") ?? "";
    const nextPage = parsePositiveInt(searchParams.get("page"), 1);
    const nextPageSize = Math.min(200, Math.max(10, parsePositiveInt(searchParams.get("page_size"), DEFAULT_PAGE_SIZE)));

    if (nextAnalyzed !== analyzed) {
      setAnalyzed(nextAnalyzed);
    }
    if (nextMarket !== market) {
      setMarket(nextMarket);
    }
    if (nextBoard !== board) {
      setBoard(nextBoard);
    }
    if (nextExchange !== exchange) {
      setExchange(nextExchange);
    }
    if (nextIndustry !== industry) {
      setIndustry(nextIndustry);
    }
    if (nextConcept !== concept) {
      setConcept(nextConcept);
    }
    if (nextTag !== tag) {
      setTag(nextTag);
    }
    if (nextRecommendation !== recommendation) {
      setRecommendation(nextRecommendation);
    }
    if (nextDividendOnly !== dividendOnly) {
      setDividendOnly(nextDividendOnly);
    }
    if (nextDividendYearsMin !== dividendYearsMin) {
      setDividendYearsMin(nextDividendYearsMin);
    }
    if (nextDividendYieldMin !== dividendYieldMin) {
      setDividendYieldMin(nextDividendYieldMin);
    }
    if (nextExDividendSoon !== exDividendSoon) {
      setExDividendSoon(nextExDividendSoon);
    }
    if (nextMarketCapMin !== marketCapMin) {
      setMarketCapMin(nextMarketCapMin);
    }
    if (nextMarketCapMax !== marketCapMax) {
      setMarketCapMax(nextMarketCapMax);
    }
    if (nextPriceMin !== priceMin) {
      setPriceMin(nextPriceMin);
    }
    if (nextPriceMax !== priceMax) {
      setPriceMax(nextPriceMax);
    }
    if (nextPeMax !== peMax) {
      setPeMax(nextPeMax);
    }
    if (nextNetProfitMin !== netProfitMin) {
      setNetProfitMin(nextNetProfitMin);
    }
    if (nextRevenueMin !== revenueMin) {
      setRevenueMin(nextRevenueMin);
    }
    if (nextRevenueGrowthMin !== revenueGrowthMin) {
      setRevenueGrowthMin(nextRevenueGrowthMin);
    }
    if (nextRevenueGrowthQoqMin !== revenueGrowthQoqMin) {
      setRevenueGrowthQoqMin(nextRevenueGrowthQoqMin);
    }
    if (nextProfitGrowthMin !== profitGrowthMin) {
      setProfitGrowthMin(nextProfitGrowthMin);
    }
    if (nextProfitGrowthQoqMin !== profitGrowthQoqMin) {
      setProfitGrowthQoqMin(nextProfitGrowthQoqMin);
    }
    if (nextGrossMarginMin !== grossMarginMin) {
      setGrossMarginMin(nextGrossMarginMin);
    }
    if (nextNetMarginMin !== netMarginMin) {
      setNetMarginMin(nextNetMarginMin);
    }
    if (nextRoeMin !== roeMin) {
      setRoeMin(nextRoeMin);
    }
    if (nextDebtRatioMax !== debtRatioMax) {
      setDebtRatioMax(nextDebtRatioMax);
    }
    if (nextExcludeSt !== excludeSt) {
      setExcludeSt(nextExcludeSt);
    }
    if (nextScoreMin !== scoreMin) {
      setScoreMin(nextScoreMin);
    }
    if (nextScoreMax !== scoreMax) {
      setScoreMax(nextScoreMax);
    }
    if (nextChangePctMin !== changePctMin) {
      setChangePctMin(nextChangePctMin);
    }
    if (nextChangePctMax !== changePctMax) {
      setChangePctMax(nextChangePctMax);
    }
    if (nextPrevLimitUp !== prevLimitUp) {
      setPrevLimitUp(nextPrevLimitUp);
    }
    if (nextPrevLimitDown !== prevLimitDown) {
      setPrevLimitDown(nextPrevLimitDown);
    }
    if (nextSort !== sortBy) {
      setSortBy(nextSort);
    }
    if (nextKeyword !== keywordInput) {
      setKeywordInput(nextKeyword);
    }
    if (nextKeyword !== keyword) {
      setKeyword(nextKeyword);
    }
    if (nextPage !== page) {
      setPage(nextPage);
    }
    if (nextPageSize !== pageSize) {
      setPageSize(nextPageSize);
    }
  }, [searchParams]);

  useEffect(() => {
    if (navigationType !== "POP") {
      return;
    }

    const queryKey = buildStocksQueryKey({
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword,
      page,
      pageSize,
    });
    const metaKey = buildStocksMetaKey({
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword,
    });

    const cachedList = getLruCacheValue(stocksPageListCache, queryKey);
    if (!cachedList) {
      return;
    }

    setStocks(cachedList.items);
    setTotal(cachedList.total);
    const cachedMeta = getLruCacheValue(stocksPageMetaCache, metaKey);
    if (!cachedMeta) {
      return;
    }

    applyMetaCacheToState(cachedMeta);
    setLoading(false);
    setError(null);
    skipInitialListReloadRef.current = true;

    const cachedPanels = getLruCacheValue(stocksPagePanelCache, buildDividendPanelsCacheKey(market, cachedMeta.lastSyncedAt));
    if (cachedPanels) {
      setDividendCalendarStocks(cachedPanels.dividendCalendarStocks);
      setHighYieldStocks(cachedPanels.highYieldStocks);
      setDividendPanelsError(cachedPanels.dividendPanelsError);
      setDividendPanelsLoading(false);
      skipInitialPanelsReloadRef.current = true;
    }
  }, [navigationType]);

  const loadStocks = async (options: { force?: boolean } = {}) => {
    const requestId = ++listRequestIdRef.current;
    const force = options.force === true;
    const queryKey = buildStocksQueryKey({
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword,
      page,
      pageSize,
    });
    const metaKey = buildStocksMetaKey({
      analyzed,
      market,
      board,
      exchange,
      industry,
      concept,
      tag,
      recommendation,
      dividendOnly,
      dividendYearsMin,
      dividendYieldMin,
      exDividendSoon,
      marketCapMin,
      marketCapMax,
      priceMin,
      priceMax,
      peMax,
      netProfitMin,
      revenueMin,
      revenueGrowthMin,
      revenueGrowthQoqMin,
      profitGrowthMin,
      profitGrowthQoqMin,
      grossMarginMin,
      netMarginMin,
      roeMin,
      debtRatioMax,
      excludeSt,
      scoreMin,
      scoreMax,
      changePctMin,
      changePctMax,
      prevLimitUp,
      prevLimitDown,
      sortBy,
      keyword,
    });

    const cachedMeta = force ? undefined : getLruCacheValue(stocksPageMetaCache, metaKey);
    if (!force) {
      const cachedList = getLruCacheValue(stocksPageListCache, queryKey);
      if (cachedList && cachedMeta) {
        setStocks(cachedList.items);
        setTotal(cachedList.total);
        applyMetaCacheToState(cachedMeta);
        setLoading(false);
        setError(null);
        return;
      }
    }

    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    setLoading(true);
    setError(null);

    try {
      const includeMeta = force || !cachedMeta;
      const response = await listStocks({
        analyzed: toAnalyzedFlag(analyzed),
        market,
        board: board || undefined,
        exchange: exchange || undefined,
        industry: industry || undefined,
        concept: concept || undefined,
        tag: tag || undefined,
        recommendation,
        dividend_only: dividendOnly,
        dividend_years_min: dividendYearsMin,
        dividend_yield_min: dividendYieldMin,
        ex_dividend_soon: exDividendSoon,
        market_cap_min: marketCapMin,
        market_cap_max: marketCapMax,
        price_min: priceMin,
        price_max: priceMax,
        pe_max: peMax,
        net_profit_min: netProfitMin,
        revenue_min: revenueMin,
        revenue_growth_min: revenueGrowthMin,
        revenue_growth_qoq_min: revenueGrowthQoqMin,
        profit_growth_min: profitGrowthMin,
        profit_growth_qoq_min: profitGrowthQoqMin,
        gross_margin_min: grossMarginMin,
        net_margin_min: netMarginMin,
        roe_min: roeMin,
        debt_ratio_max: debtRatioMax,
        exclude_st: excludeSt,
        score_min: scoreMin,
        score_max: scoreMax,
        change_pct_min: changePctMin,
        change_pct_max: changePctMax,
        prev_limit_up: prevLimitUp,
        prev_limit_down: prevLimitDown,
        q: keyword.trim() || undefined,
        sort_by: sortBy,
        page,
        page_size: pageSize,
        include_meta: includeMeta,
      }, { signal: controller.signal });
      if (controller.signal.aborted || requestId !== listRequestIdRef.current) {
        return;
      }

      const nextListCache: StocksPageListCache = {
        items: response.items,
        total: response.total,
      };
      setStocks(nextListCache.items);
      setTotal(nextListCache.total);
      setLruCacheValue(stocksPageListCache, queryKey, nextListCache, STOCKS_PAGE_LIST_CACHE_LIMIT);

      let nextMetaCache = cachedMeta;
      if (includeMeta) {
        nextMetaCache = {
          lastSyncedAt: response.last_synced_at ?? null,
          industryOptions: response.industries ?? [],
          conceptOptions: response.concepts ?? [],
          tagOptions: response.tags ?? [],
          boardOptions: response.boards ?? [],
          exchangeOptions: response.exchanges ?? [],
          recommendationOptions: response.recommendations ?? [],
          stats: response.stats ?? emptyStats,
          dividendSummary: response.dividend_summary ?? emptyDividendSummary,
          sectorRotation: cachedMeta?.sectorRotation ?? null,
          rotationLoaded: cachedMeta?.rotationLoaded ?? false,
        };
        setLruCacheValue(stocksPageMetaCache, metaKey, nextMetaCache, STOCKS_PAGE_META_CACHE_LIMIT);
      }

      if (nextMetaCache) {
        applyMetaCacheToState(nextMetaCache);
      }
      setLoading(false);

      if (nextMetaCache?.rotationLoaded && !force) {
        return;
      }

      sectorRotationAbortRef.current?.abort();
      const rotationController = new AbortController();
      sectorRotationAbortRef.current = rotationController;

      void getSectorRotation(market, 8, { signal: rotationController.signal })
        .then((rotationResponse) => {
          if (rotationController.signal.aborted || requestId !== listRequestIdRef.current) {
            return;
          }
          setSectorRotation(rotationResponse);
          const latestMetaCache = getLruCacheValue(stocksPageMetaCache, metaKey);
          if (!latestMetaCache) {
            return;
          }
          setLruCacheValue(
            stocksPageMetaCache,
            metaKey,
            {
              ...latestMetaCache,
              sectorRotation: rotationResponse,
              rotationLoaded: true,
            },
            STOCKS_PAGE_META_CACHE_LIMIT,
          );
        })
        .catch((rotationError) => {
          if (isAbortError(rotationError) || rotationController.signal.aborted || requestId !== listRequestIdRef.current) {
            return;
          }
          setSectorRotation(null);
          const latestMetaCache = getLruCacheValue(stocksPageMetaCache, metaKey);
          if (!latestMetaCache) {
            return;
          }
          setLruCacheValue(
            stocksPageMetaCache,
            metaKey,
            {
              ...latestMetaCache,
              sectorRotation: null,
              rotationLoaded: true,
            },
            STOCKS_PAGE_META_CACHE_LIMIT,
          );
        });
    } catch (err) {
      if (isAbortError(err) || controller.signal.aborted || requestId !== listRequestIdRef.current) {
        return;
      }
      const messageText = formatErrorMessage(err, "加载失败");
      setError(messageText);
      setStocks([]);
      setTotal(0);
      setStats(emptyStats);
      setDividendSummary(emptyDividendSummary);
      setConceptOptions([]);
      setSectorRotation(null);
      setLoading(false);
    }
  };


  useEffect(() => {
    if (skipInitialListReloadRef.current) {
      skipInitialListReloadRef.current = false;
      return;
    }

    const timerId = window.setTimeout(() => {
      applyQueryToUrl({
        analyzed,
        market,
        board,
        exchange,
        industry,
        concept,
        tag,
        recommendation,
        dividend_only: dividendOnly,
        dividend_years_min: dividendYearsMin,
        dividend_yield_min: dividendYieldMin,
        ex_dividend_soon: exDividendSoon,
        market_cap_min: marketCapMin,
        market_cap_max: marketCapMax,
        price_min: priceMin,
        price_max: priceMax,
        pe_max: peMax,
        net_profit_min: netProfitMin,
        revenue_min: revenueMin,
        revenue_growth_min: revenueGrowthMin,
        revenue_growth_qoq_min: revenueGrowthQoqMin,
        profit_growth_min: profitGrowthMin,
        profit_growth_qoq_min: profitGrowthQoqMin,
        gross_margin_min: grossMarginMin,
        net_margin_min: netMarginMin,
        roe_min: roeMin,
        debt_ratio_max: debtRatioMax,
        exclude_st: excludeSt,
        score_min: scoreMin,
        score_max: scoreMax,
        change_pct_min: changePctMin,
        change_pct_max: changePctMax,
        prev_limit_up: prevLimitUp,
        prev_limit_down: prevLimitDown,
        sort_by: sortBy,
        q: keyword,
        page,
        page_size: pageSize,
      });
      void loadStocks();
    }, FILTER_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timerId);
    };
  }, [
    analyzed,
    market,
    board,
    exchange,
    industry,
    concept,
    tag,
    recommendation,
    dividendOnly,
    dividendYearsMin,
    dividendYieldMin,
    exDividendSoon,
    marketCapMin,
    marketCapMax,
    priceMin,
    priceMax,
    peMax,
    netProfitMin,
    revenueMin,
    revenueGrowthMin,
    revenueGrowthQoqMin,
    profitGrowthMin,
    profitGrowthQoqMin,
    grossMarginMin,
    netMarginMin,
    roeMin,
    debtRatioMax,
    excludeSt,
    scoreMin,
    scoreMax,
    changePctMin,
    changePctMax,
    prevLimitUp,
    prevLimitDown,
    keyword,
    sortBy,
    page,
    pageSize,
  ]);

  useEffect(() => {
    let mounted = true;
    if (skipInitialPanelsReloadRef.current) {
      skipInitialPanelsReloadRef.current = false;
      return () => {
        mounted = false;
      };
    }

    const panelQueryKey = buildDividendPanelsCacheKey(market, lastSyncedAt);
    const cachedPanels = getLruCacheValue(stocksPagePanelCache, panelQueryKey);
    if (cachedPanels) {
      setDividendCalendarStocks(cachedPanels.dividendCalendarStocks);
      setHighYieldStocks(cachedPanels.highYieldStocks);
      setDividendPanelsError(cachedPanels.dividendPanelsError);
      setDividendPanelsLoading(false);
      return () => {
        mounted = false;
      };
    }

    const loadDividendPanels = async () => {
      dividendPanelsAbortRef.current?.abort();
      const controller = new AbortController();
      dividendPanelsAbortRef.current = controller;
      setDividendPanelsLoading(true);
      setDividendPanelsError(null);

      try {
        const [calendarResponse, highYieldResponse] = await Promise.all([
          listStocks({
            market,
            dividend_only: true,
            ex_dividend_soon: true,
            sort_by: "dividend_yield",
            page: 1,
            page_size: 10,
            include_meta: false,
          }, { signal: controller.signal }),
          listStocks({
            market,
            dividend_only: true,
            dividend_yield_min: 3,
            sort_by: "dividend_yield",
            page: 1,
            page_size: 10,
            include_meta: false,
          }, { signal: controller.signal }),
        ]);

        if (!mounted || controller.signal.aborted) {
          return;
        }

        const nextCalendar = calendarResponse.items ?? [];
        const nextHighYield = highYieldResponse.items ?? [];
        setDividendCalendarStocks(nextCalendar);
        setHighYieldStocks(nextHighYield);
        setLruCacheValue(
          stocksPagePanelCache,
          panelQueryKey,
          {
            dividendCalendarStocks: nextCalendar,
            highYieldStocks: nextHighYield,
            dividendPanelsError: null,
          },
          STOCKS_PAGE_PANEL_CACHE_LIMIT,
        );
      } catch (err) {
        if (!mounted || isAbortError(err) || controller.signal.aborted) {
          return;
        }

        const messageText = formatErrorMessage(err, "加载失败");
        setDividendPanelsError(messageText);
        setDividendCalendarStocks([]);
        setHighYieldStocks([]);
        setLruCacheValue(
          stocksPagePanelCache,
          panelQueryKey,
          {
            dividendCalendarStocks: [],
            highYieldStocks: [],
            dividendPanelsError: messageText,
          },
          STOCKS_PAGE_PANEL_CACHE_LIMIT,
        );
      } finally {
        if (mounted && !controller.signal.aborted) {
          setDividendPanelsLoading(false);
        }
      }
    };

    void loadDividendPanels();

    return () => {
      mounted = false;
      dividendPanelsAbortRef.current?.abort();
    };
  }, [
    market,
    lastSyncedAt,
    dividendPanelsReloadKey,
  ]);

  useEffect(() => () => {
    listAbortRef.current?.abort();
    sectorRotationAbortRef.current?.abort();
    dividendPanelsAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    const syncCart = () => {
      setCartItems(getStockCartItems());
    };

    const eventName = getStockCartEventName();
    window.addEventListener(eventName, syncCart);
    window.addEventListener("storage", syncCart);
    return () => {
      window.removeEventListener(eventName, syncCart);
      window.removeEventListener("storage", syncCart);
    };
  }, []);

  const overview = useMemo(() => {
    const currentPageCount = stocks.length;
    const buyOrWatch = stocks.filter((item) => item.recommendation === "buy" || item.recommendation === "watch").length;
    const dividendCount = stocks.filter((item) => item.has_dividend).length;

    return {
      total,
      currentPageCount,
      buyOrWatch,
      dividendCount,
      averageScore: stats.average_score,
      medianScore: stats.median_score,
      positiveRate: total > 0 ? Math.round((stats.positive_change_count / total) * 1000) / 10 : 0,
    };
  }, [stocks, total, stats]);

  const handleSync = async (force: boolean) => {
    setSyncing(true);
    try {
      const result = await syncStockUniverse(force);
      if (result.success) {
        message.success(
          `同步成功：共 ${result.total_count} 只（A股 ${result.a_share_count} / 港股 ${result.hk_count} / 美股 ${result.us_count ?? 0}）`
        );
      } else {
        message.warning(result.message || "同步未完全成功，已保留现有数据");
      }
      clearStocksPageCaches();
      if (page !== 1) {
        setPage(1);
      } else {
        await loadStocks({ force: true });
      }
      setDividendPanelsReloadKey((value) => value + 1);
    } catch (err) {
      const messageText = formatErrorMessage(err, "同步失败");
      message.error(`同步失败：${messageText}`);
    } finally {
      setSyncing(false);
    }
  };

  const handleManualRefresh = async () => {
    clearStocksPageCaches();
    await loadStocks({ force: true });
    setDividendPanelsReloadKey((value) => value + 1);
  };

  const applyKeywordSearch = () => {
    const normalized = keywordInput.trim();
    setKeywordInput(normalized);
    if (normalized !== keyword) {
      setKeyword(normalized);
    }
    setPage(1);
  };

  const handleKeywordPressEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (keywordComposing || event.nativeEvent.isComposing) {
      return;
    }
    applyKeywordSearch();
  };

  const addToCart = (stock: StockItem) => {
    const inserted = addStockToCart({
      symbol: stock.symbol,
      name: stock.name,
      market: stock.market,
      industry: stock.industry,
      price: stock.price,
      change_pct: stock.change_pct,
      score: stock.score,
      recommendation: stock.recommendation,
      updated_at: stock.updated_at ?? null,
    });
    if (inserted) {
      message.success(`已添加到购物车：${stock.name}`);
    } else {
      message.info(`${stock.name} 已在购物车中`);
    }
  };

  const addToMyStocks = async (stock: { symbol: string; name: string }) => {
    if (!isAuthenticated()) {
      if (isGuestMode()) {
        message.warning("游客模式下不能新增到“我的股票”，请先注册账号。");
      } else {
        message.warning("请先登录后再添加到“我的股票”。");
      }
      navigate("/auth");
      return;
    }

    setAddingSymbols((prev) => ({ ...prev, [stock.symbol]: true }));
    try {
      await createMyWatchlistItem({
        symbol: stock.symbol,
        group_name: "股票池",
      });
      message.success(`已添加到“我的股票”：${stock.name}`);
    } catch (err) {
      const messageText = formatErrorMessage(err, "添加失败");
      message.warning(`添加失败：${messageText}`);
    } finally {
      setAddingSymbols((prev) => ({ ...prev, [stock.symbol]: false }));
    }
  };

  const isInCart = (symbol: string) => cartItems.some((item) => item.symbol.trim().toUpperCase() === symbol.trim().toUpperCase());

  const clearAllFilters = () => {
    setKeywordInput("");
    setKeyword("");
    setAnalyzed("all");
    setMarket(undefined);
    setBoard(undefined);
    setExchange(undefined);
    setIndustry(undefined);
    setConcept(undefined);
    setTag(undefined);
    setRecommendation(undefined);
    setDividendOnly(false);
    setDividendYearsMin(undefined);
    setDividendYieldMin(undefined);
    setExDividendSoon(false);
    setMarketCapMin(undefined);
    setMarketCapMax(undefined);
    setPriceMin(undefined);
    setPriceMax(undefined);
    setPeMax(undefined);
    setNetProfitMin(undefined);
    setRevenueMin(undefined);
    setRevenueGrowthMin(undefined);
    setRevenueGrowthQoqMin(undefined);
    setProfitGrowthMin(undefined);
    setProfitGrowthQoqMin(undefined);
    setGrossMarginMin(undefined);
    setNetMarginMin(undefined);
    setRoeMin(undefined);
    setDebtRatioMax(undefined);
    setExcludeSt(false);
    setScoreMin(undefined);
    setScoreMax(undefined);
    setChangePctMin(undefined);
    setChangePctMax(undefined);
    setPrevLimitUp(false);
    setPrevLimitDown(false);
    setSortBy("score");
    setPage(1);
    setPageSize(50);
    setActiveQuickFilterPresetId(undefined);
  };

  const applyQuickFilterPreset = (preset: QuickFilterPreset) => {
    const criteria = preset.criteria;
    setAnalyzed(criteria.analyzed);
    setMarket(criteria.market);
    setBoard(criteria.board);
    setExchange(criteria.exchange);
    setIndustry(criteria.industry);
    setConcept(criteria.concept);
    setTag(criteria.tag);
    setRecommendation(criteria.recommendation);
    setDividendOnly(criteria.dividendOnly);
    setDividendYearsMin(criteria.dividendYearsMin);
    setDividendYieldMin(criteria.dividendYieldMin);
    setExDividendSoon(criteria.exDividendSoon);
    setMarketCapMin(criteria.marketCapMin);
    setMarketCapMax(criteria.marketCapMax);
    setPriceMin(criteria.priceMin);
    setPriceMax(criteria.priceMax);
    setPeMax(criteria.peMax);
    setNetProfitMin(criteria.netProfitMin);
    setRevenueMin(criteria.revenueMin);
    setRevenueGrowthMin(criteria.revenueGrowthMin);
    setRevenueGrowthQoqMin(criteria.revenueGrowthQoqMin);
    setProfitGrowthMin(criteria.profitGrowthMin);
    setProfitGrowthQoqMin(criteria.profitGrowthQoqMin);
    setGrossMarginMin(criteria.grossMarginMin);
    setNetMarginMin(criteria.netMarginMin);
    setRoeMin(criteria.roeMin);
    setDebtRatioMax(criteria.debtRatioMax);
    setExcludeSt(criteria.excludeSt);
    setScoreMin(criteria.scoreMin);
    setScoreMax(criteria.scoreMax);
    setChangePctMin(criteria.changePctMin);
    setChangePctMax(criteria.changePctMax);
    setPrevLimitUp(Boolean(criteria.prevLimitUp));
    setPrevLimitDown(Boolean(criteria.prevLimitDown));
    setSortBy(criteria.sortBy);
    setKeywordInput(criteria.keyword);
    setKeyword(criteria.keyword);
    setPage(1);
    setActiveQuickFilterPresetId(preset.id);
    message.success(`已应用快捷筛选：${preset.name}`);
  };

  const saveQuickFilterPreset = () => {
    const trimmed = quickFilterNameInput.trim();
    if (!trimmed) {
      message.warning("请先输入快捷筛选名称");
      return;
    }

    const now = new Date().toISOString();
    const existing = quickFilterPresets.find((item) => item.name.trim().toLowerCase() === trimmed.toLowerCase());
    let nextPresets: QuickFilterPreset[];
    let nextActiveId: string;

    if (existing) {
      nextPresets = quickFilterPresets.map((item) =>
        item.id === existing.id
          ? {
              ...item,
              name: trimmed,
              criteria: currentQuickFilterCriteria,
              updated_at: now,
            }
          : item
      );
      nextActiveId = existing.id;
      message.success(`已更新快捷筛选：${trimmed}`);
    } else {
      const created: QuickFilterPreset = {
        id: createQuickFilterPresetId(),
        name: trimmed,
        criteria: currentQuickFilterCriteria,
        updated_at: now,
      };
      nextPresets = [created, ...quickFilterPresets].slice(0, QUICK_FILTER_PRESET_LIMIT);
      nextActiveId = created.id;
      message.success(`已保存快捷筛选：${trimmed}`);
    }

    setQuickFilterPresets(nextPresets);
    persistQuickFilterPresets(nextPresets);
    setActiveQuickFilterPresetId(nextActiveId);
    setQuickFilterNameInput("");
  };

  const removeQuickFilterPreset = (presetId: string) => {
    const target = quickFilterPresets.find((item) => item.id === presetId);
    const nextPresets = quickFilterPresets.filter((item) => item.id !== presetId);
    setQuickFilterPresets(nextPresets);
    persistQuickFilterPresets(nextPresets);
    if (activeQuickFilterPresetId === presetId) {
      setActiveQuickFilterPresetId(undefined);
    }
    if (target) {
      message.success(`已删除快捷筛选：${target.name}`);
    }
  };

  const clearQuickFilterPresets = () => {
    setQuickFilterPresets([]);
    persistQuickFilterPresets([]);
    setActiveQuickFilterPresetId(undefined);
    message.success("已清空快捷筛选列表");
  };

  useEffect(() => {
    if (!activeQuickFilterPresetId) {
      return;
    }
    const activePreset = quickFilterPresets.find((item) => item.id === activeQuickFilterPresetId);
    if (!activePreset) {
      setActiveQuickFilterPresetId(undefined);
      return;
    }
    const activeText = JSON.stringify(activePreset.criteria);
    const currentText = JSON.stringify(currentQuickFilterCriteria);
    if (activeText !== currentText) {
      setActiveQuickFilterPresetId(undefined);
    }
  }, [activeQuickFilterPresetId, currentQuickFilterCriteria, quickFilterPresets]);

  const activeFilterTags = useMemo(() => {
    const tags: { key: string; label: string; onClose: () => void }[] = [];

    if (keyword.trim()) {
      tags.push({ key: "keyword", label: `关键词：${keyword.trim()}`, onClose: () => {
        setKeywordInput("");
        setKeyword("");
      } });
    }
    if (analyzed !== "all") {
      tags.push({ key: "analyzed", label: `分析状态：${analyzed === "true" ? "已分析" : "未分析"}`, onClose: () => setAnalyzed("all") });
    }
    if (market) {
      tags.push({ key: "market", label: `市场：${market}`, onClose: () => setMarket(undefined) });
    }
    if (board) {
      tags.push({ key: "board", label: `板块：${board}`, onClose: () => setBoard(undefined) });
    }
    if (exchange) {
      tags.push({ key: "exchange", label: `交易所：${exchange}`, onClose: () => setExchange(undefined) });
    }
    if (industry) {
      tags.push({ key: "industry", label: `行业：${industry}`, onClose: () => setIndustry(undefined) });
    }
    if (concept) {
      tags.push({ key: "concept", label: `概念：${concept}`, onClose: () => setConcept(undefined) });
    }
    if (tag) {
      tags.push({ key: "tag", label: `标签：${tag}`, onClose: () => setTag(undefined) });
    }
    if (recommendation) {
      tags.push({ key: "recommendation", label: `建议：${recommendationLabel(recommendation)}`, onClose: () => setRecommendation(undefined) });
    }
    if (dividendOnly) {
      tags.push({ key: "dividend_only", label: "仅分红股", onClose: () => setDividendOnly(false) });
    }
    if (dividendYearsMin !== undefined) {
      tags.push({ key: "dividend_years_min", label: `分红年数 ≥ ${dividendYearsMin}`, onClose: () => setDividendYearsMin(undefined) });
    }
    if (dividendYieldMin !== undefined) {
      tags.push({ key: "dividend_yield_min", label: `股息率 ≥ ${dividendYieldMin}%`, onClose: () => setDividendYieldMin(undefined) });
    }
    if (exDividendSoon) {
      tags.push({ key: "ex_dividend_soon", label: "即将除权", onClose: () => setExDividendSoon(false) });
    }
    if (marketCapMin !== undefined) {
      tags.push({ key: "market_cap_min", label: `市值 ≥ ${marketCapMin}亿`, onClose: () => setMarketCapMin(undefined) });
    }
    if (marketCapMax !== undefined) {
      tags.push({ key: "market_cap_max", label: `市值 ≤ ${marketCapMax}亿`, onClose: () => setMarketCapMax(undefined) });
    }
    if (priceMin !== undefined) {
      tags.push({ key: "price_min", label: `价格 ≥ ${priceMin}`, onClose: () => setPriceMin(undefined) });
    }
    if (priceMax !== undefined) {
      tags.push({ key: "price_max", label: `价格 ≤ ${priceMax}`, onClose: () => setPriceMax(undefined) });
    }
    if (peMax !== undefined) {
      tags.push({ key: "pe_max", label: `PE ≤ ${peMax}`, onClose: () => setPeMax(undefined) });
    }
    if (netProfitMin !== undefined) {
      tags.push({ key: "net_profit_min", label: `净利润 ≥ ${netProfitMin}亿`, onClose: () => setNetProfitMin(undefined) });
    }
    if (revenueMin !== undefined) {
      tags.push({ key: "revenue_min", label: `营收规模 ≥ ${revenueMin}亿`, onClose: () => setRevenueMin(undefined) });
    }
    if (revenueGrowthMin !== undefined) {
      tags.push({ key: "revenue_growth_min", label: `营收增长率 ≥ ${revenueGrowthMin}%`, onClose: () => setRevenueGrowthMin(undefined) });
    }
    if (revenueGrowthQoqMin !== undefined) {
      tags.push({ key: "revenue_growth_qoq_min", label: `营收环比 ≥ ${revenueGrowthQoqMin}%`, onClose: () => setRevenueGrowthQoqMin(undefined) });
    }
    if (profitGrowthMin !== undefined) {
      tags.push({ key: "profit_growth_min", label: `净利同比 ≥ ${profitGrowthMin}%`, onClose: () => setProfitGrowthMin(undefined) });
    }
    if (profitGrowthQoqMin !== undefined) {
      tags.push({ key: "profit_growth_qoq_min", label: `净利环比 ≥ ${profitGrowthQoqMin}%`, onClose: () => setProfitGrowthQoqMin(undefined) });
    }
    if (grossMarginMin !== undefined) {
      tags.push({ key: "gross_margin_min", label: `毛利率 ≥ ${grossMarginMin}%`, onClose: () => setGrossMarginMin(undefined) });
    }
    if (netMarginMin !== undefined) {
      tags.push({ key: "net_margin_min", label: `净利率 ≥ ${netMarginMin}%`, onClose: () => setNetMarginMin(undefined) });
    }
    if (roeMin !== undefined) {
      tags.push({ key: "roe_min", label: `盈利能力(ROE) ≥ ${roeMin}%`, onClose: () => setRoeMin(undefined) });
    }
    if (debtRatioMax !== undefined) {
      tags.push({ key: "debt_ratio_max", label: `资产负债率 ≤ ${debtRatioMax}%`, onClose: () => setDebtRatioMax(undefined) });
    }
    if (excludeSt) {
      tags.push({ key: "exclude_st", label: "剔除 ST", onClose: () => setExcludeSt(false) });
    }
    if (scoreMin !== undefined) {
      tags.push({ key: "score_min", label: `评分 ≥ ${scoreMin}`, onClose: () => setScoreMin(undefined) });
    }
    if (scoreMax !== undefined) {
      tags.push({ key: "score_max", label: `评分 ≤ ${scoreMax}`, onClose: () => setScoreMax(undefined) });
    }
    if (changePctMin !== undefined) {
      tags.push({ key: "change_pct_min", label: `涨跌幅 ≥ ${changePctMin}%`, onClose: () => setChangePctMin(undefined) });
    }
    if (changePctMax !== undefined) {
      tags.push({ key: "change_pct_max", label: `涨跌幅 ≤ ${changePctMax}%`, onClose: () => setChangePctMax(undefined) });
    }
    if (prevLimitUp) {
      tags.push({ key: "prev_limit_up", label: "上一日涨停", onClose: () => setPrevLimitUp(false) });
    }
    if (prevLimitDown) {
      tags.push({ key: "prev_limit_down", label: "上一日跌停", onClose: () => setPrevLimitDown(false) });
    }
    if (sortBy !== "score") {
      const sortLabel = sortOptions.find((item) => item.value === sortBy)?.label ?? sortBy;
      tags.push({ key: "sort", label: `排序：${sortLabel}`, onClose: () => setSortBy("score") });
    }

    return tags;
  }, [
    keyword,
    analyzed,
    market,
    board,
    exchange,
    industry,
    concept,
    tag,
    recommendation,
    dividendOnly,
    dividendYearsMin,
    dividendYieldMin,
    exDividendSoon,
    marketCapMin,
    marketCapMax,
    priceMin,
    priceMax,
    peMax,
    netProfitMin,
    revenueMin,
    revenueGrowthMin,
    revenueGrowthQoqMin,
    profitGrowthMin,
    profitGrowthQoqMin,
    grossMarginMin,
    netMarginMin,
    roeMin,
    debtRatioMax,
    excludeSt,
    scoreMin,
    scoreMax,
    changePctMin,
    changePctMax,
    prevLimitUp,
    prevLimitDown,
    sortBy,
  ]);

  const industrySelectOptions = industryOptions.map((value) => ({ label: value, value }));
  const conceptSelectOptions = conceptOptions.map((value) => ({ label: value, value }));
  const tagSelectOptions = tagOptions.map((value) => ({ label: value, value }));
  const boardSelectOptions = boardOptions.map((value) => ({ label: value, value }));
  const exchangeSelectOptions = exchangeOptions.map((value) => ({ label: value, value }));
  const recommendationSelectOptions = recommendationOptions.map((value) => ({
    value,
    label: recommendationLabel(value),
  }));
  const dividendScopeLabel = market ?? "全市场";
  const visibleDividendPanelCount = Number(!dividendCalendarHidden) + Number(!highYieldHidden);
  const dividendPanelSpan = visibleDividendPanelCount <= 1 ? 24 : 12;
  const visibleTopicModuleCount = Number(!dividendCenterHidden) + Number(!dividendCalendarHidden) + Number(!highYieldHidden) + Number(!sectorRotationHidden);

  const renderPanelToggleControl = (
    label: string,
    hidden: boolean,
    icon: ReactNode,
    description: string,
    onChange: (checked: boolean) => void,
  ) => (
    <div className={`stocks-panel-toggle-card${hidden ? "" : " is-active"}`}>
      <div className="stocks-panel-toggle-meta">
        <span className="stocks-panel-toggle-icon">{icon}</span>
        <span className="stocks-panel-toggle-copy">
          <span className="stocks-panel-toggle-title">{label}</span>
          <span className="stocks-panel-toggle-desc">{description}</span>
        </span>
      </div>
      <div className="stocks-panel-toggle-action">
        <span className="stocks-panel-toggle-state">{hidden ? "隐藏" : "显示"}</span>
        <Switch size="small" checked={!hidden} onChange={onChange} />
      </div>
    </div>
  );

  const renderQuickTag = (
    key: string,
    label: string,
    count: number,
    active: boolean,
    onClick: () => void,
    activeColor: string = "processing",
    inactiveColor: string = "default"
  ) => (
    <Tag
      key={key}
      color={active ? activeColor : inactiveColor}
      bordered={false}
      style={{
        cursor: "pointer",
        userSelect: "none",
        marginBottom: 8,
        fontWeight: active ? 600 : 500,
        boxShadow: active ? "0 0 0 1px rgba(22, 119, 255, 0.25) inset" : "none",
      }}
      onClick={onClick}
    >
      {label}: {count}
    </Tag>
  );

  return (
    <Space className="stocks-page" direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="stocks-filter-card" title="股票池筛选（全量交易所数据 + 量化筛选）" loading={loading}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Text type="secondary">交易所快捷筛选：</Text>
          <Button
            type={!market ? "primary" : "default"}
            onClick={() => {
              setMarket(undefined);
              setPage(1);
            }}
          >
            全部
          </Button>
          <Button
            type={market === "A股" ? "primary" : "default"}
            onClick={() => {
              setMarket("A股");
              setPage(1);
            }}
          >
            A股
          </Button>
          <Button
            type={market === "港股" ? "primary" : "default"}
            onClick={() => {
              setMarket("港股");
              setPage(1);
            }}
          >
            港股
          </Button>
          <Button
            type={market === "美股" ? "primary" : "default"}
            onClick={() => {
              setMarket("美股");
              setPage(1);
            }}
          >
            美股
          </Button>
          <Button
            type={dividendOnly ? "primary" : "default"}
            onClick={() => {
              setDividendOnly((prev) => !prev);
              setPage(1);
            }}
          >
            仅看分红股
          </Button>
          <Button onClick={clearAllFilters}>清空所有筛选</Button>
        </Space>
        <Space wrap style={{ marginBottom: 12 }}>
          <Text type="secondary">策略快捷筛选：</Text>
          <Button
            onClick={() => {
              setMarketCapMin(1000);
              setPeMax(25);
              setRoeMin(12);
              setDebtRatioMax(65);
              setExcludeSt(true);
              setPage(1);
            }}
          >
            大盘价值
          </Button>
          <Button
            onClick={() => {
              setRevenueGrowthMin(15);
              setRevenueGrowthQoqMin(5);
              setProfitGrowthMin(18);
              setProfitGrowthQoqMin(8);
              setGrossMarginMin(25);
              setNetMarginMin(8);
              setExcludeSt(true);
              setPage(1);
            }}
          >
            成长加速
          </Button>
          <Button
            onClick={() => {
              setMarketCapMax(800);
              setPriceMin(5);
              setPriceMax(80);
              setRevenueGrowthMin(10);
              setProfitGrowthMin(12);
              setExcludeSt(true);
              setPage(1);
            }}
          >
            中小盘弹性
          </Button>
        </Space>

        <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
          <Text type="secondary">已启用筛选：</Text>
          {activeFilterTags.length > 0 ? (
            activeFilterTags.map((filter) => (
              <Tag
                key={filter.key}
                closable
                onClose={(event) => {
                  event.preventDefault();
                  filter.onClose();
                  setPage(1);
                }}
              >
                {filter.label}
              </Tag>
            ))
          ) : (
            <Text type="secondary">无</Text>
          )}
        </Space>

        <Card
          size="small"
          style={{ marginBottom: 12 }}
          title="我的快捷筛选"
        >
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            <Space wrap>
              <Input
                value={quickFilterNameInput}
                placeholder="输入筛选名称，例如：高ROE低负债"
                style={{ width: 280 }}
                maxLength={30}
                onChange={(event) => setQuickFilterNameInput(event.target.value)}
                onPressEnter={saveQuickFilterPreset}
              />
              <Button type="primary" onClick={saveQuickFilterPreset}>
                保存当前筛选
              </Button>
              {quickFilterPresets.length > 0 ? (
                <Button danger onClick={clearQuickFilterPresets}>
                  清空方案
                </Button>
              ) : null}
              <Text type="secondary">共 {quickFilterPresets.length} 个方案</Text>
            </Space>

            <Space wrap>
              {quickFilterPresets.length > 0 ? (
                quickFilterPresets.map((preset) => (
                  <Tag
                    key={preset.id}
                    closable
                    color={activeQuickFilterPresetId === preset.id ? "processing" : "default"}
                    style={{ cursor: "pointer", userSelect: "none", marginBottom: 6 }}
                    onClick={() => applyQuickFilterPreset(preset)}
                    onClose={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      removeQuickFilterPreset(preset.id);
                    }}
                  >
                    {preset.name}
                  </Tag>
                ))
              ) : (
                <Text type="secondary">暂无快捷筛选，先设置条件后保存即可。</Text>
              )}
            </Space>
          </Space>
        </Card>

        <div className="stocks-topic-section">
        <Card
          className="stocks-topic-card"
          size="small"
          title={
            <div className="stocks-topic-card-title">
              <Text className="stocks-topic-card-title-text">专题模块</Text>
              <Text type="secondary" className="stocks-topic-card-title-desc">
                管理分红与板块轮动专题的可见性，让股票池信息层级更清晰。
              </Text>
            </div>
          }
          extra={
            <Tag color={visibleTopicModuleCount > 0 ? "processing" : "default"} bordered={false}>
              已显示 {visibleTopicModuleCount}/4
            </Tag>
          }
        >
          <div className="stocks-panel-toggle-toolbar">
            <div className="stocks-panel-toggle-group">
              {renderPanelToggleControl("分红中心", dividendCenterHidden, <AppstoreOutlined />, "分红筛选总览", (checked) =>
                setDividendCenterHidden(!checked)
              )}
              {renderPanelToggleControl("分红日历", dividendCalendarHidden, <CalendarOutlined />, "近期除权安排", (checked) =>
                setDividendCalendarHidden(!checked)
              )}
              {renderPanelToggleControl("高股息榜", highYieldHidden, <FundOutlined />, "高股息股票榜单", (checked) =>
                setHighYieldHidden(!checked)
              )}
              {renderPanelToggleControl("板块轮动", sectorRotationHidden, <AppstoreOutlined />, "板块概念轮动分析", (checked) =>
                setSectorRotationHidden(!checked)
              )}
            </div>
          </div>
        </Card>

        {!sectorRotationHidden ? (
        <Card size="small" style={{ marginBottom: 0 }} title="板块概念轮动分析（模型推理）">
          {sectorRotation?.next_potential_sector ? (
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              <Text type="secondary">
                分析时间：{new Date(sectorRotation.generated_at).toLocaleString()}，市场范围 {sectorRotation.market_scope}，覆盖概念板块 {sectorRotation.total_sectors} 个，全市场基准涨跌幅 {sectorRotation.benchmark_change_pct >= 0 ? "+" : ""}
                {sectorRotation.benchmark_change_pct.toFixed(2)}%
              </Text>
              <Alert
                type="info"
                showIcon
                message={`下一潜力板块：${sectorRotation.next_potential_sector.name}（${sectorRotation.next_potential_sector.rotation_stage}）`}
                description={`置信度 ${sectorRotation.next_potential_sector.confidence}/100 / 热度 ${sectorRotation.next_potential_sector.heat_score} / 样本 ${sectorRotation.next_potential_sector.stock_count} / 相对强度 ${sectorRotation.next_potential_sector.relative_change_pct >= 0 ? "+" : ""}${sectorRotation.next_potential_sector.relative_change_pct.toFixed(2)}%`}
              />
              <Text type="secondary">样本规则：{sectorRotation.sample_policy}</Text>
              <Space wrap>
                {sectorRotation.current_hot_sectors.map((item) => (
                  <Tag
                    key={item.name}
                    color={item.name === concept ? "magenta" : "processing"}
                    style={{ cursor: "pointer" }}
                    onClick={() => {
                      setConcept(item.name === concept ? undefined : item.name);
                      setPage(1);
                    }}
                  >
                    {item.name} · 置信度{item.confidence} · 样本{item.stock_count}
                  </Tag>
                ))}
              </Space>
              <Text>轮动路径：{sectorRotation.rotation_path.join(" → ") || "暂无"}</Text>
              {sectorRotation.methodology.map((line) => (
                <Text key={line} type="secondary">
                  - {line}
                </Text>
              ))}
              {sectorRotation.reasoning.map((line) => (
                <Text key={line}>
                  - {line}
                </Text>
              ))}
              {sectorRotation.risk_warnings.map((line) => (
                <Text key={line} type="warning">
                  - {line}
                </Text>
              ))}
            </Space>
          ) : (
            <Empty description="当前暂无板块轮动分析结果，请先同步股票池后重试" />
          )}
        </Card>
        ) : null}

        {!dividendCenterHidden ? (
        <Card size="small" style={{ marginBottom: 0 }} title="分红中心（Beta）">
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color="gold">分红股 {dividendSummary.total}</Tag>
              <Tag color="purple">连续分红3年+ {dividendSummary.continuous_3y_count}</Tag>
              <Tag color="green">高股息 {dividendSummary.high_yield_count}</Tag>
              <Tag color="orange">即将除权 {dividendSummary.upcoming_ex_dividend_count}</Tag>
              <Tag>最新分红年度 {dividendSummary.latest_year ?? "未知"}</Tag>
              {Object.entries(dividendSummary.by_market).map(([key, value]) => (
                <Tag key={`div-market-${key}`} bordered={false} color="blue">
                  {key} {value}
                </Tag>
              ))}
            </Space>
            <Space wrap>
              <Button
                size="small"
                type={dividendOnly && !dividendYearsMin ? "primary" : "default"}
                onClick={() => {
                  setDividendOnly(true);
                  setDividendYearsMin(undefined);
                  setSortBy("dividend_years");
                  setPage(1);
                }}
              >
                查看全部分红股
              </Button>
              <Button
                size="small"
                type={dividendYearsMin === 3 ? "primary" : "default"}
                onClick={() => {
                  setDividendOnly(true);
                  setDividendYearsMin(dividendYearsMin === 3 ? undefined : 3);
                  setDividendYieldMin(undefined);
                  setExDividendSoon(false);
                  setSortBy("dividend_years");
                  setPage(1);
                }}
              >
                连续分红 3 年+
              </Button>
              <Button
                size="small"
                type={dividendYieldMin === 3 ? "primary" : "default"}
                onClick={() => {
                  setDividendOnly(true);
                  setDividendYearsMin(undefined);
                  setDividendYieldMin(dividendYieldMin === 3 ? undefined : 3);
                  setExDividendSoon(false);
                  setSortBy("dividend_yield");
                  setPage(1);
                }}
              >
                高股息 3%+
              </Button>
              <Button
                size="small"
                type={exDividendSoon ? "primary" : "default"}
                onClick={() => {
                  setDividendOnly(true);
                  setDividendYearsMin(undefined);
                  setDividendYieldMin(undefined);
                  setExDividendSoon((prev) => !prev);
                  setSortBy("dividend_yield");
                  setPage(1);
                }}
              >
                即将除权
              </Button>
              <Button
                size="small"
                onClick={() => {
                  setDividendOnly(false);
                  setDividendYearsMin(undefined);
                  setDividendYieldMin(undefined);
                  setExDividendSoon(false);
                  setPage(1);
                }}
              >
                清除分红筛选
              </Button>
            </Space>
          </Space>
        </Card>
        ) : null}

        {dividendPanelsError ? (
          <Alert
            style={{ marginBottom: 0 }}
            type="warning"
            showIcon
            message={`分红专题加载失败：${dividendPanelsError}`}
            action={
              <Button size="small" onClick={() => {
                  stocksPagePanelCache.delete(buildDividendPanelsCacheKey(market, lastSyncedAt));
                  setDividendPanelsReloadKey((value) => value + 1);
                }}>
                重试加载
              </Button>
            }
          />
        ) : null}

        {!dividendCalendarHidden || !highYieldHidden ? (
        <Row gutter={[12, 12]} style={{ marginBottom: 0 }}>
          {!dividendCalendarHidden ? (
            <Col xs={24} xl={dividendPanelSpan}>
              <Card
                size="small"
                title={`分红日历 · ${dividendScopeLabel}`}
                loading={dividendPanelsLoading}
                extra={
                  <Space size={4}>
                    <Button
                      size="small"
                      type="link"
                      onClick={() => setDividendCalendarCollapsed((value) => !value)}
                    >
                      {dividendCalendarCollapsed ? "展开" : "收起"}
                    </Button>
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setDividendOnly(true);
                        setDividendYearsMin(undefined);
                        setDividendYieldMin(undefined);
                        setExDividendSoon(true);
                        setSortBy("dividend_yield");
                        setPage(1);
                      }}
                    >
                      查看全部
                    </Button>
                  </Space>
                }
              >
                {dividendCalendarCollapsed ? (
                  <Text type="secondary">
                    {dividendCalendarStocks.length > 0
                      ? `当前共 ${dividendCalendarStocks.length} 只近期即将除权股票，点击展开查看明细。`
                      : "当前无近期即将除权股票，点击展开查看详情。"}
                  </Text>
                ) : dividendCalendarStocks.length === 0 && !dividendPanelsLoading ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="近期暂无即将除权股票" />
                ) : (
                  <List
                    size="small"
                    dataSource={dividendCalendarStocks}
                    renderItem={(stock) => (
                      <List.Item
                        actions={[
                          <Button
                            key={`calendar-detail-${stock.symbol}`}
                            type="link"
                            size="small"
                            onClick={() => navigate(`/stocks/${encodeURIComponent(stock.symbol)}`, { state: { from: currentListPath } })}
                          >
                            查看详情
                          </Button>,
                        ]}
                      >
                        <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          <Space wrap size={6}>
                            <Text strong>{stock.name}</Text>
                            <Text type="secondary">{stock.symbol}</Text>
                            <Tag color="blue">{stock.market}</Tag>
                            <Tag bordered={false}>{stock.board}</Tag>
                          </Space>
                          <Space wrap size={6}>
                            <Tag color="orange">{stock.ex_dividend_date ? `除权日 ${stock.ex_dividend_date}` : "除权日待更新"}</Tag>
                            {stock.dividend_yield ? <Tag color="green">股息率 {stock.dividend_yield.toFixed(2)}%</Tag> : null}
                            <Text type="secondary">{stock.industry}</Text>
                          </Space>
                        </Space>
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            </Col>
          ) : null}

          {!highYieldHidden ? (
            <Col xs={24} xl={dividendPanelSpan}>
              <Card
                size="small"
                title={`高股息榜 · ${dividendScopeLabel}`}
                loading={dividendPanelsLoading}
                extra={
                  <Space size={4}>
                    <Button
                      size="small"
                      type="link"
                      onClick={() => setHighYieldCollapsed((value) => !value)}
                    >
                      {highYieldCollapsed ? "展开" : "收起"}
                    </Button>
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setDividendOnly(true);
                        setDividendYearsMin(undefined);
                        setDividendYieldMin(3);
                        setExDividendSoon(false);
                        setSortBy("dividend_yield");
                        setPage(1);
                      }}
                    >
                      切到筛选
                    </Button>
                  </Space>
                }
              >
                {highYieldCollapsed ? (
                  <Text type="secondary">
                    {highYieldStocks.length > 0
                      ? `当前榜单展示 ${highYieldStocks.length} 只高股息股票，点击展开查看明细。`
                      : "当前暂无达到阈值的高股息股票，点击展开查看详情。"}
                  </Text>
                ) : highYieldStocks.length === 0 && !dividendPanelsLoading ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前暂无达到阈值的高股息股票" />
                ) : (
                  <List
                    size="small"
                    dataSource={highYieldStocks}
                    renderItem={(stock, index) => (
                      <List.Item
                        actions={[
                          <Button
                            key={`yield-detail-${stock.symbol}`}
                            type="link"
                            size="small"
                            onClick={() => navigate(`/stocks/${encodeURIComponent(stock.symbol)}`, { state: { from: currentListPath } })}
                          >
                            详情
                          </Button>,
                        ]}
                      >
                        <Space align="start" size={10} style={{ width: "100%", justifyContent: "space-between" }}>
                          <Space align="start" size={10}>
                            <Tag color={index < 3 ? "gold" : "default"}>#{index + 1}</Tag>
                            <Space direction="vertical" size={4}>
                              <Space wrap size={6}>
                                <Text strong>{stock.name}</Text>
                                <Text type="secondary">{stock.symbol}</Text>
                                <Tag color="purple">{stock.market}</Tag>
                              </Space>
                              <Space wrap size={6}>
                                {stock.dividend_yield ? <Tag color="green">股息率 {stock.dividend_yield.toFixed(2)}%</Tag> : null}
                                {stock.dividend_years ? <Tag color="gold">连续分红 {stock.dividend_years} 年</Tag> : null}
                                <Text type="secondary">评分 {stock.score}</Text>
                              </Space>
                            </Space>
                          </Space>
                        </Space>
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            </Col>
          ) : null}
        </Row>
        ) : null}

        </div>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}>
            <Space.Compact style={{ width: "100%" }}>
              <Input
                placeholder="按代码、名称、行业关键词搜索（失焦自动搜索，回车可立即搜索）"
                value={keywordInput}
                onChange={(event) => {
                  setKeywordInput(event.target.value);
                }}
                onBlur={() => applyKeywordSearch()}
                onCompositionStart={() => setKeywordComposing(true)}
                onCompositionEnd={() => setKeywordComposing(false)}
                onPressEnter={handleKeywordPressEnter}
                allowClear
              />
              <Button type="primary" onClick={applyKeywordSearch}>
                搜索
              </Button>
            </Space.Compact>
          </Col>

          <Col xs={12} md={4}>
            <Select<AnalyzedQuery>
              value={analyzed}
              style={{ width: "100%" }}
              options={[
                { label: "全部", value: "all" },
                { label: "已分析", value: "true" },
                { label: "未分析", value: "false" },
              ]}
              onChange={(value) => {
                setAnalyzed(value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={market}
              style={{ width: "100%" }}
              allowClear
              placeholder="市场"
              options={marketOptions}
              onChange={(value) => {
                setMarket(value as MarketType | undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={board}
              style={{ width: "100%" }}
              allowClear
              placeholder="板块"
              options={boardSelectOptions}
              onChange={(value) => {
                setBoard((value as string | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={exchange}
              style={{ width: "100%" }}
              allowClear
              placeholder="交易所"
              options={exchangeSelectOptions}
              onChange={(value) => {
                setExchange((value as string | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={industry}
              style={{ width: "100%" }}
              allowClear
              placeholder="按行业"
              options={industrySelectOptions}
              onChange={(value) => {
                setIndustry((value as string | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={concept}
              style={{ width: "100%" }}
              allowClear
              placeholder="按概念板块"
              options={conceptSelectOptions}
              onChange={(value) => {
                setConcept((value as string | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={tag}
              style={{ width: "100%" }}
              allowClear
              placeholder="按标签"
              options={tagSelectOptions}
              onChange={(value) => {
                setTag((value as string | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select
              value={recommendation}
              style={{ width: "100%" }}
              allowClear
              placeholder="建议动作"
              options={recommendationSelectOptions}
              onChange={(value) => {
                setRecommendation((value as RecommendationType | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Select<number>
              value={dividendYearsMin}
              style={{ width: "100%" }}
              allowClear
              placeholder="分红年数"
              options={[
                { label: "分红 1 年+", value: 1 },
                { label: "连续分红 3 年+", value: 3 },
                { label: "连续分红 5 年+", value: 5 },
              ]}
              onChange={(value) => {
                setDividendYearsMin((value as number | undefined) ?? undefined);
                setPage(1);
              }}
            />
          </Col>

          <Col span={24}>
            <Text strong>基础面 / 估值</Text>
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={marketCapMin}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最低市值(亿)"
              onChange={(value) => {
                setMarketCapMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={marketCapMax}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最高市值(亿)"
              onChange={(value) => {
                setMarketCapMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={peMax}
              min={0}
              max={500}
              style={{ width: "100%" }}
              placeholder="最高市盈率(PE)"
              onChange={(value) => {
                setPeMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={revenueMin}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最低营收规模(亿)"
              onChange={(value) => {
                setRevenueMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={netProfitMin}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最低净利润(亿)"
              onChange={(value) => {
                setNetProfitMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col span={24}>
            <Text strong>盈利能力 / 成长</Text>
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={revenueGrowthMin}
              min={-100}
              max={300}
              style={{ width: "100%" }}
              placeholder="最低营收增长率(%)"
              onChange={(value) => {
                setRevenueGrowthMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={revenueGrowthQoqMin}
              min={-100}
              max={300}
              style={{ width: "100%" }}
              placeholder="最低营收环比(%)"
              onChange={(value) => {
                setRevenueGrowthQoqMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={profitGrowthMin}
              min={-100}
              max={300}
              style={{ width: "100%" }}
              placeholder="最低净利同比(%)"
              onChange={(value) => {
                setProfitGrowthMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={profitGrowthQoqMin}
              min={-100}
              max={300}
              style={{ width: "100%" }}
              placeholder="最低净利环比(%)"
              onChange={(value) => {
                setProfitGrowthQoqMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={grossMarginMin}
              min={0}
              max={100}
              style={{ width: "100%" }}
              placeholder="最低毛利率(%)"
              onChange={(value) => {
                setGrossMarginMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={netMarginMin}
              min={-100}
              max={100}
              style={{ width: "100%" }}
              placeholder="最低净利率(%)"
              onChange={(value) => {
                setNetMarginMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={roeMin}
              min={-100}
              max={100}
              style={{ width: "100%" }}
              placeholder="最低盈利能力(ROE)"
              onChange={(value) => {
                setRoeMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col span={24}>
            <Text strong>风险 / 交易</Text>
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={debtRatioMax}
              min={0}
              max={100}
              style={{ width: "100%" }}
              placeholder="最高资产负债率"
              onChange={(value) => {
                setDebtRatioMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={priceMin}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最低价格"
              onChange={(value) => {
                setPriceMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <InputNumber
              changeOnBlur
              value={priceMax}
              min={0}
              max={1000000}
              style={{ width: "100%" }}
              placeholder="最高价格"
              onChange={(value) => {
                setPriceMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Button
              style={{ width: "100%" }}
              type={excludeSt ? "primary" : "default"}
              onClick={() => {
                setExcludeSt((value) => !value);
                setPage(1);
              }}
            >
              {excludeSt ? "已剔除 ST" : "剔除 ST"}
            </Button>
          </Col>

          <Col xs={12} md={3}>
            <InputNumber
              changeOnBlur
              value={scoreMin}
              min={1}
              max={99}
              style={{ width: "100%" }}
              placeholder="最低评分"
              onChange={(value) => {
                setScoreMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={3}>
            <InputNumber
              changeOnBlur
              value={scoreMax}
              min={1}
              max={99}
              style={{ width: "100%" }}
              placeholder="最高评分"
              onChange={(value) => {
                setScoreMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={3}>
            <InputNumber
              changeOnBlur
              value={changePctMin}
              min={-30}
              max={30}
              style={{ width: "100%" }}
              placeholder="涨跌幅下限"
              onChange={(value) => {
                setChangePctMin(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={3}>
            <InputNumber
              changeOnBlur
              value={changePctMax}
              min={-30}
              max={30}
              style={{ width: "100%" }}
              placeholder="涨跌幅上限"
              onChange={(value) => {
                setChangePctMax(value === null ? undefined : value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Button
              style={{ width: "100%" }}
              type={prevLimitUp ? "primary" : "default"}
              onClick={() => {
                setPrevLimitUp((value) => !value);
                setPage(1);
              }}
            >
              {prevLimitUp ? "已筛选：上一日涨停" : "筛选：上一日涨停"}
            </Button>
          </Col>

          <Col xs={12} md={4}>
            <Button
              style={{ width: "100%" }}
              type={prevLimitDown ? "primary" : "default"}
              onClick={() => {
                setPrevLimitDown((value) => !value);
                setPage(1);
              }}
            >
              {prevLimitDown ? "已筛选：上一日跌停" : "筛选：上一日跌停"}
            </Button>
          </Col>

          <Col xs={12} md={4}>
            <Select<SortBy>
              value={sortBy}
              style={{ width: "100%" }}
              options={sortOptions}
              onChange={(value) => {
                setSortBy(value);
                setPage(1);
              }}
            />
          </Col>

          <Col xs={12} md={4}>
            <Button
              style={{ width: "100%" }}
              onClick={clearAllFilters}
            >
              重置
            </Button>
          </Col>
        </Row>

        <Space wrap style={{ marginTop: 12 }}>
          <Button loading={loading && !syncing} onClick={() => void handleManualRefresh()}>
            刷新列表
          </Button>
          <Button type="primary" loading={syncing} onClick={() => void handleSync(false)}>
            同步全量股票池
          </Button>
          <Button loading={syncing} onClick={() => void handleSync(true)}>
            强制全量重拉
          </Button>
          <Text type="secondary">股票池最后更新：{lastSyncedAt ? new Date(lastSyncedAt).toLocaleString() : "未知"}</Text>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Text type="secondary">筛选后总标的</Text>
            <div className="overview-number">{overview.total}</div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Text type="secondary">机会标的（当前页）</Text>
            <div className="overview-number">{overview.buyOrWatch}</div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Text type="secondary">全样本平均评分</Text>
            <div className="overview-number">{overview.averageScore}</div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Text type="secondary">上涨占比（筛选后）</Text>
            <div className="overview-number">{overview.positiveRate}%</div>
          </Card>
        </Col>
      </Row>

      <Card
        className="stocks-overview-card"
        title={
          <div className="stocks-overview-card-title">
            <Text className="stocks-overview-card-title-text">量化分布总览</Text>
            <Text type="secondary" className="stocks-overview-card-title-desc">
              点击下方标签可快捷筛选对应股票。
            </Text>
          </div>
        }
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text type="secondary">市场分布</Text>
          <Space wrap>
            {Object.entries(stats.by_market).map(([key, value]) => {
              const marketValue = marketOptions.some((item) => item.value === key) ? (key as MarketType) : null;
              return renderQuickTag(
                `market-${key}`,
                key,
                value,
                marketValue !== null && market === marketValue,
                () => {
                  if (!marketValue) {
                    return;
                  }
                  setMarket(market === marketValue ? undefined : marketValue);
                  setPage(1);
                },
                "blue",
                "blue"
              );
            })}
          </Space>

          <Text type="secondary">板块分布</Text>
          <Space wrap>
            {Object.entries(stats.by_board).map(([key, value]) =>
              renderQuickTag(
                `board-${key}`,
                key,
                value,
                board === key,
                () => {
                  setBoard(board === key ? undefined : key);
                  setPage(1);
                },
                "purple",
                "purple"
              )
            )}
          </Space>

          <Text type="secondary">建议动作分布</Text>
          <Space wrap>
            {Object.entries(stats.by_recommendation).map(([key, value]) => (
              renderQuickTag(
                `recommendation-${key}`,
                recommendationLabel(key as RecommendationType),
                value,
                recommendation === key,
                () => {
                  const nextValue = key as RecommendationType;
                  setRecommendation(recommendation === nextValue ? undefined : nextValue);
                  setPage(1);
                },
                recommendationColor(key as RecommendationType),
                recommendationColor(key as RecommendationType)
              )
            ))}
          </Space>

          <Text type="secondary">Top 行业</Text>
          <Space wrap>
            {Object.entries(stats.top_industries).map(([key, value]) =>
              renderQuickTag(
                `industry-${key}`,
                key,
                value,
                industry === key,
                () => {
                  setIndustry(industry === key ? undefined : key);
                  setPage(1);
                },
                "geekblue",
                "geekblue"
              )
            )}
          </Space>

          <Text type="secondary">Top 概念板块</Text>
          <Space wrap>
            {Object.entries(stats.top_concepts).map(([key, value]) =>
              renderQuickTag(
                `concept-${key}`,
                key,
                value,
                concept === key,
                () => {
                  setConcept(concept === key ? undefined : key);
                  setPage(1);
                },
                "magenta",
                "magenta"
              )
            )}
          </Space>

          <Text type="secondary">Top 标签</Text>
          <Space wrap>
            {Object.entries(stats.top_tags).map(([key, value]) =>
              renderQuickTag(
                `tag-${key}`,
                key,
                value,
                tag === key,
                () => {
                  setTag(tag === key ? undefined : key);
                  setPage(1);
                }
              )
            )}
          </Space>
        </Space>
      </Card>

      {error ? <Alert type="error" showIcon message={`股票池加载失败：${error}`} /> : null}

      <Card
        className="stocks-list-card"
        title={`股票池列表（本页 ${overview.currentPageCount} / 共 ${overview.total}，中位评分 ${overview.medianScore}，分红股 ${overview.dividendCount}）`}
        loading={loading}
        extra={
          <Pagination
            simple
            current={page}
            pageSize={pageSize}
            total={total}
            onChange={(nextPage, nextPageSize) => {
              setPage(nextPage);
              if (nextPageSize !== pageSize) {
                setPageSize(nextPageSize);
              }
            }}
          />
        }
      >
        {stocks.length === 0 && !loading ? (
          <Empty description="未找到符合条件的股票" />
        ) : (
          <List
            dataSource={stocks}
            renderItem={(stock) => (
              <List.Item
                className="stock-list-item"
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`/stocks/${encodeURIComponent(stock.symbol)}`, { state: { from: currentListPath } })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    navigate(`/stocks/${encodeURIComponent(stock.symbol)}`, { state: { from: currentListPath } });
                  }
                }}
                role="button"
                tabIndex={0}
              actions={[
                  <Button
                    key={`cart-${stock.symbol}`}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      addToCart(stock);
                    }}
                    disabled={isInCart(stock.symbol)}
                  >
                    {isInCart(stock.symbol) ? "已添加到购物车" : "添加到购物车"}
                  </Button>,
                  <Button
                    key={`add-my-${stock.symbol}`}
                    type="primary"
                    ghost
                    loading={Boolean(addingSymbols[stock.symbol])}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      void addToMyStocks(stock);
                    }}
                  >
                    添加到我的股票
                  </Button>,
                  <Button
                    key={`detail-${stock.symbol}`}
                    type="link"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      navigate(`/stocks/${encodeURIComponent(stock.symbol)}`, { state: { from: currentListPath } });
                    }}
                  >
                    查看详情
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Link
                      to={`/stocks/${encodeURIComponent(stock.symbol)}`}
                      state={{ from: currentListPath }}
                      onClick={(event) => {
                        event.stopPropagation();
                      }}
                    >
                      {`${stock.name}（${stock.symbol}）`}
                    </Link>
                  }
                  description={
                    <Space direction="vertical" size={3}>
                      <Text type="secondary">
                        市场：{stock.market} / 交易所：{stock.exchange} / 板块：{stock.board} / 行业：{stock.industry} / 价格：
                        {stock.price.toFixed(2)} / 涨跌幅：
                        <Text style={{ color: stock.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>
                          {stock.change_pct >= 0 ? "+" : ""}
                          {stock.change_pct.toFixed(2)}%
                        </Text>
                      </Text>

                      <Text type="secondary">
                        市值：{formatMetric(stock.market_cap, 1)}亿 / 市盈率：{formatMetric(stock.pe, 1)} / 营收：{formatMetric(stock.revenue, 1)}亿 / 净利润：{formatMetric(stock.net_profit, 1)}亿 /
                        营收同比：{formatMetric(stock.revenue_growth, 1)}% / 净利同比：{formatMetric(stock.profit_growth, 1)}% / 毛利率：{formatMetric(stock.gross_margin, 1)}% / 净利率：
                        {formatMetric(stock.net_margin, 1)}% / ROE：{formatMetric(stock.roe, 1)}% / 资产负债率：{formatMetric(stock.debt_ratio, 1)}%
                      </Text>

                      <Text type="secondary">
                        最后更新：{stock.updated_at ? new Date(stock.updated_at).toLocaleString() : lastSyncedAt ? new Date(lastSyncedAt).toLocaleString() : "未知"}
                        {stock.ex_dividend_date ? ` / 除权日：${stock.ex_dividend_date}` : ""}
                      </Text>

                      <Space wrap>
                        <Tag color={stock.analyzed ? "green" : "orange"}>{stock.analyzed ? "已分析" : "未分析"}</Tag>
                        <Tag color={recommendationColor(stock.recommendation)}>{recommendationLabel(stock.recommendation)}</Tag>
                        {stock.has_dividend ? (
                          <Tag color="gold">{stock.dividend_years ? `分红 ${stock.dividend_years}年` : "分红股"}</Tag>
                        ) : null}
                        {stock.is_st ? <Tag color="red">ST</Tag> : null}
                        {stock.dividend_yield ? <Tag color="green">股息率 {stock.dividend_yield.toFixed(2)}%</Tag> : null}
                        {stock.is_ex_dividend_soon ? <Tag color="orange">即将除权</Tag> : null}
                        <Tag color="purple">{stock.industry}</Tag>
                        {stock.concepts.slice(0, 3).map((itemConcept) => (
                          <Tag key={`${stock.symbol}-concept-${itemConcept}`} color="magenta" bordered={false}>
                            {itemConcept}
                          </Tag>
                        ))}
                        <Text type="secondary">评分 {stock.score}</Text>
                      </Space>

                      <Space wrap size={4}>
                        {stock.tags.slice(0, 6).map((itemTag) => (
                          <Tag key={`${stock.symbol}-${itemTag}`} bordered={false} color="default">
                            {itemTag}
                          </Tag>
                        ))}
                      </Space>

                      <Progress percent={stock.score} showInfo={false} size="small" strokeColor="#1677ff" />
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}

        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            showSizeChanger
            pageSizeOptions={["20", "50", "100", "200"]}
            onChange={(nextPage, nextPageSize) => {
              setPage(nextPage);
              if (nextPageSize !== pageSize) {
                setPageSize(nextPageSize);
              }
            }}
            showTotal={(value) => `共 ${value} 只`}
          />
        </div>
      </Card>
    </Space>
  );
}

export default StocksPage;
