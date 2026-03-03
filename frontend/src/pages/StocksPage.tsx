import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
  Tag,
  Typography,
} from "antd";

import { createMyWatchlistItem } from "../api/account";
import { listStocks, syncStockUniverse } from "../api/stocks";
import type { MarketType, RecommendationType, StockItem, StockListStats } from "../types/stock";
import { isAuthenticated, isGuestMode } from "../utils/auth";
import { addStockToCart, getStockCartEventName, getStockCartItems } from "../utils/stockCart";

const { Text } = Typography;

type SortBy = "score" | "change_pct" | "price";
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
  top_tags: {},
};

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

function StocksPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { message } = AntdApp.useApp();

  const initialAnalyzed = (searchParams.get("analyzed") as AnalyzedQuery | null) ?? "all";
  const initialMarket = (searchParams.get("market") as MarketType | null) ?? undefined;
  const initialBoard = searchParams.get("board") ?? undefined;
  const initialExchange = searchParams.get("exchange") ?? undefined;
  const initialIndustry = searchParams.get("industry") ?? undefined;
  const initialTag = searchParams.get("tag") ?? undefined;
  const initialRecommendation = (searchParams.get("recommendation") as RecommendationType | null) ?? undefined;
  const initialScoreMin = parseOptionalNumber(searchParams.get("score_min"));
  const initialScoreMax = parseOptionalNumber(searchParams.get("score_max"));
  const initialChangePctMin = parseOptionalNumber(searchParams.get("change_pct_min"));
  const initialChangePctMax = parseOptionalNumber(searchParams.get("change_pct_max"));
  const initialSort = (searchParams.get("sort_by") as SortBy | null) ?? "score";
  const initialKeyword = searchParams.get("q") ?? "";
  const initialPage = parsePositiveInt(searchParams.get("page"), 1);
  const initialPageSize = Math.min(200, Math.max(10, parsePositiveInt(searchParams.get("page_size"), 50)));

  const [analyzed, setAnalyzed] = useState<AnalyzedQuery>(initialAnalyzed);
  const [market, setMarket] = useState<MarketType | undefined>(initialMarket);
  const [board, setBoard] = useState<string | undefined>(initialBoard);
  const [exchange, setExchange] = useState<string | undefined>(initialExchange);
  const [industry, setIndustry] = useState<string | undefined>(initialIndustry);
  const [tag, setTag] = useState<string | undefined>(initialTag);
  const [recommendation, setRecommendation] = useState<RecommendationType | undefined>(initialRecommendation);
  const [scoreMin, setScoreMin] = useState<number | undefined>(initialScoreMin);
  const [scoreMax, setScoreMax] = useState<number | undefined>(initialScoreMax);
  const [changePctMin, setChangePctMin] = useState<number | undefined>(initialChangePctMin);
  const [changePctMax, setChangePctMax] = useState<number | undefined>(initialChangePctMax);
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
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [boardOptions, setBoardOptions] = useState<string[]>([]);
  const [exchangeOptions, setExchangeOptions] = useState<string[]>([]);
  const [recommendationOptions, setRecommendationOptions] = useState<RecommendationType[]>([]);
  const [stats, setStats] = useState<StockListStats>(emptyStats);
  const [cartItems, setCartItems] = useState(getStockCartItems());
  const [addingSymbols, setAddingSymbols] = useState<Record<string, boolean>>({});

  const applyQueryToUrl = (next: {
    analyzed: AnalyzedQuery;
    market?: MarketType;
    board?: string;
    exchange?: string;
    industry?: string;
    tag?: string;
    recommendation?: RecommendationType;
    score_min?: number;
    score_max?: number;
    change_pct_min?: number;
    change_pct_max?: number;
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
    if (next.tag?.trim()) {
      params.set("tag", next.tag.trim());
    }
    if (next.recommendation) {
      params.set("recommendation", next.recommendation);
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
    const nextTag = searchParams.get("tag") ?? undefined;
    const nextRecommendation = (searchParams.get("recommendation") as RecommendationType | null) ?? undefined;
    const nextScoreMin = parseOptionalNumber(searchParams.get("score_min"));
    const nextScoreMax = parseOptionalNumber(searchParams.get("score_max"));
    const nextChangePctMin = parseOptionalNumber(searchParams.get("change_pct_min"));
    const nextChangePctMax = parseOptionalNumber(searchParams.get("change_pct_max"));
    const nextSort = (searchParams.get("sort_by") as SortBy | null) ?? "score";
    const nextKeyword = searchParams.get("q") ?? "";
    const nextPage = parsePositiveInt(searchParams.get("page"), 1);
    const nextPageSize = Math.min(200, Math.max(10, parsePositiveInt(searchParams.get("page_size"), 50)));

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
    if (nextTag !== tag) {
      setTag(nextTag);
    }
    if (nextRecommendation !== recommendation) {
      setRecommendation(nextRecommendation);
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

  const loadStocks = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await listStocks({
        analyzed: toAnalyzedFlag(analyzed),
        market,
        board: board || undefined,
        exchange: exchange || undefined,
        industry: industry || undefined,
        tag: tag || undefined,
        recommendation,
        score_min: scoreMin,
        score_max: scoreMax,
        change_pct_min: changePctMin,
        change_pct_max: changePctMax,
        q: keyword.trim() || undefined,
        sort_by: sortBy,
        page,
        page_size: pageSize,
      });

      setStocks(response.items);
      setTotal(response.total);
      setLastSyncedAt(response.last_synced_at ?? null);
      setIndustryOptions(response.industries ?? []);
      setTagOptions(response.tags ?? []);
      setBoardOptions(response.boards ?? []);
      setExchangeOptions(response.exchanges ?? []);
      setRecommendationOptions(response.recommendations ?? []);
      setStats(response.stats ?? emptyStats);
    } catch (err) {
      const messageText = err instanceof Error ? err.message : "加载失败";
      setError(messageText);
      setStocks([]);
      setTotal(0);
      setStats(emptyStats);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    applyQueryToUrl({
      analyzed,
      market,
      board,
      exchange,
      industry,
      tag,
      recommendation,
      score_min: scoreMin,
      score_max: scoreMax,
      change_pct_min: changePctMin,
      change_pct_max: changePctMax,
      sort_by: sortBy,
      q: keyword,
      page,
      page_size: pageSize,
    });
    void loadStocks();
  }, [
    analyzed,
    market,
    board,
    exchange,
    industry,
    tag,
    recommendation,
    scoreMin,
    scoreMax,
    changePctMin,
    changePctMax,
    keyword,
    sortBy,
    page,
    pageSize,
  ]);

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

    return {
      total,
      currentPageCount,
      buyOrWatch,
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
      setPage(1);
      await loadStocks();
    } catch (err) {
      const messageText = err instanceof Error ? err.message : "同步失败";
      message.error(`同步失败：${messageText}`);
    } finally {
      setSyncing(false);
    }
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
      const messageText = err instanceof Error ? err.message : "添加失败";
      message.warning(`添加失败：${messageText}`);
    } finally {
      setAddingSymbols((prev) => ({ ...prev, [stock.symbol]: false }));
    }
  };

  const isInCart = (symbol: string) => cartItems.some((item) => item.symbol.trim().toUpperCase() === symbol.trim().toUpperCase());

  const industrySelectOptions = industryOptions.map((value) => ({ label: value, value }));
  const tagSelectOptions = tagOptions.map((value) => ({ label: value, value }));
  const boardSelectOptions = boardOptions.map((value) => ({ label: value, value }));
  const exchangeSelectOptions = exchangeOptions.map((value) => ({ label: value, value }));
  const recommendationSelectOptions = recommendationOptions.map((value) => ({
    value,
    label: recommendationLabel(value),
  }));

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
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="股票池筛选（全量交易所数据 + 量化筛选）" loading={loading}>
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
        </Space>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}>
            <Space.Compact style={{ width: "100%" }}>
              <Input
                placeholder="按代码、名称、行业关键词搜索（输入后按回车或点搜索）"
                value={keywordInput}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  setKeywordInput(nextValue);
                  if (!nextValue.trim() && keyword) {
                    setKeyword("");
                    setPage(1);
                  }
                }}
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

          <Col xs={12} md={3}>
            <InputNumber
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
              onClick={() => {
                setKeywordInput("");
                setKeyword("");
                setAnalyzed("all");
                setMarket(undefined);
                setBoard(undefined);
                setExchange(undefined);
                setIndustry(undefined);
                setTag(undefined);
                setRecommendation(undefined);
                setScoreMin(undefined);
                setScoreMax(undefined);
                setChangePctMin(undefined);
                setChangePctMax(undefined);
                setSortBy("score");
                setPage(1);
                setPageSize(50);
              }}
            >
              重置
            </Button>
          </Col>
        </Row>

        <Space wrap style={{ marginTop: 12 }}>
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

      <Card title="量化分布总览">
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text type="secondary">点击下方标签可快捷筛选对应股票。</Text>
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
        title={`股票池列表（本页 ${overview.currentPageCount} / 共 ${overview.total}，中位评分 ${overview.medianScore}）`}
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
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`/stocks/${encodeURIComponent(stock.symbol)}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    navigate(`/stocks/${encodeURIComponent(stock.symbol)}`);
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
                      navigate(`/stocks/${encodeURIComponent(stock.symbol)}`);
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
                        最后更新：{stock.updated_at ? new Date(stock.updated_at).toLocaleString() : lastSyncedAt ? new Date(lastSyncedAt).toLocaleString() : "未知"}
                      </Text>

                      <Space wrap>
                        <Tag color={stock.analyzed ? "green" : "orange"}>{stock.analyzed ? "已分析" : "未分析"}</Tag>
                        <Tag color={recommendationColor(stock.recommendation)}>{recommendationLabel(stock.recommendation)}</Tag>
                        <Tag color="purple">{stock.industry}</Tag>
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
