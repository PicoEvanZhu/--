import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";

import { askStockQuestion, createStockTradeReview, getStockKLine, getStockSnapshot, getStockTradeReviews, updateStockTradeReview } from "../api/stocks";
import StockKLineChart from "../components/StockKLineChart";
import { createGuestTradeReview, getGuestTradeReviews, updateGuestTradeReview } from "../services/guestData";
import type {
  DividendRecord,
  FollowUpStatus,
  FinancialReport,
  StockKLineResponse,
  PeerCompany,
  RecommendationType,
  RiskLevel,
  ShareholderRecord,
  StockAnalysis,
  StockDetail,
  StockTradeReviewResponse,
  StockQAMessage,
  TradeReviewAction,
  ValuationHistoryPoint,
} from "../types/stock";
import { getAuthEventName, hasSessionAccess, isGuestMode } from "../utils/auth";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface TradeReviewFormValues {
  trade_date: string;
  action: TradeReviewAction;
  price?: number;
  quantity?: number;
  thesis: string;
  execution_notes?: string;
  outcome_review?: string;
  lessons_learned?: string;
  follow_up_items_text?: string;
  follow_up_status: FollowUpStatus;
  next_review_date?: string;
  confidence_score?: number;
  discipline_score?: number;
}

interface QAChatItem {
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  bullets?: string[];
  references?: string[];
  followUpQuestions?: string[];
  disclaimer?: string;
  searchUsed?: boolean;
  searchQuery?: string | null;
  searchResultCount?: number;
}

type DetailTabKey = "analysis" | "follow_up";
type KLinePeriod = "1mo" | "3mo" | "6mo" | "1y" | "5y";
type KLineInterval = "1d" | "1h";

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

function riskLabel(level: RiskLevel): string {
  if (level === "low") {
    return "低风险";
  }
  if (level === "medium") {
    return "中风险";
  }
  return "高风险";
}

function riskColor(level: RiskLevel): string {
  if (level === "low") {
    return "green";
  }
  if (level === "medium") {
    return "gold";
  }
  return "red";
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === "AbortError";
  }
  return error instanceof Error && error.name === "AbortError";
}

function scoreColor(score: number): string {
  if (score >= 75) {
    return "#389e0d";
  }
  if (score >= 58) {
    return "#1677ff";
  }
  if (score >= 45) {
    return "#d48806";
  }
  return "#cf1322";
}

function signedPercent(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toYi(value: number): string {
  return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })} 亿`;
}

function yuanToYi(value: number): string {
  const amountYi = (Number.isFinite(value) ? value : 0) / 100000000;
  return `${amountYi.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 亿`;
}

function factorColor(score: number): string {
  if (score >= 75) {
    return "#389e0d";
  }
  if (score >= 55) {
    return "#1677ff";
  }
  if (score >= 40) {
    return "#d48806";
  }
  return "#cf1322";
}

function tradeActionLabel(action: TradeReviewAction): string {
  if (action === "buy") {
    return "买入";
  }
  if (action === "sell") {
    return "卖出";
  }
  if (action === "add") {
    return "加仓";
  }
  if (action === "reduce") {
    return "减仓";
  }
  return "观察";
}

function tradeActionColor(action: TradeReviewAction): string {
  if (action === "buy" || action === "add") {
    return "green";
  }
  if (action === "sell" || action === "reduce") {
    return "volcano";
  }
  return "default";
}

function followUpStatusLabel(status: FollowUpStatus): string {
  if (status === "open") {
    return "待跟进";
  }
  if (status === "in_progress") {
    return "跟进中";
  }
  return "已关闭";
}

function followUpStatusColor(status: FollowUpStatus): string {
  if (status === "open") {
    return "gold";
  }
  if (status === "in_progress") {
    return "blue";
  }
  return "green";
}

function extractYearNumber(value: string): number | null {
  const matched = value.match(/(19|20)\d{2}/);
  if (!matched) {
    return null;
  }

  const parsed = Number(matched[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildDividendObservationWindow(exDividendDate?: string | null): string {
  if (!exDividendDate) {
    return "重点跟踪年报、董事会预案、股东大会与实施公告。";
  }

  const parsed = new Date(exDividendDate);
  if (Number.isNaN(parsed.getTime())) {
    return "重点跟踪年报、董事会预案、股东大会与实施公告。";
  }

  const month = parsed.getMonth() + 1;
  const forwardMonth = Math.max(1, month - 2);
  return `通常可在 ${forwardMonth}-${month} 月提前跟踪预案、审议与实施节奏。`;
}

function StockDetailPage() {
  const { symbol = "" } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { message } = AntdApp.useApp();
  const [tradeReviewForm] = Form.useForm<TradeReviewFormValues>();
  const [klinePeriod, setKlinePeriod] = useState<KLinePeriod>("6mo");
  const [klineInterval, setKlineInterval] = useState<KLineInterval>("1d");
  const [authed, setAuthed] = useState(hasSessionAccess());
  const [guestMode, setGuestMode] = useState(isGuestMode());

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null);
  const [tradeReviews, setTradeReviews] = useState<StockTradeReviewResponse | null>(null);
  const [tradeReviewLoading, setTradeReviewLoading] = useState(false);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineError, setKlineError] = useState<string | null>(null);
  const [klineData, setKlineData] = useState<StockKLineResponse | null>(null);
  const [tradeReviewSubmitting, setTradeReviewSubmitting] = useState(false);
  const [tradeReviewError, setTradeReviewError] = useState<string | null>(null);
  const [detailActiveTab, setDetailActiveTab] = useState<DetailTabKey>("analysis");
  const [qaQuestionInput, setQaQuestionInput] = useState("");
  const [qaComposing, setQaComposing] = useState(false);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaMessages, setQaMessages] = useState<QAChatItem[]>([]);
  const qaRequestIdRef = useRef(0);
  const qaAbortRef = useRef<AbortController | null>(null);

  const today = new Date().toISOString().slice(0, 10);
  const detailSource = searchParams.get("source");
  const detailLinkSuffix = detailSource === "my" ? "?source=my" : "";
  const fallbackBackPath = detailSource === "my" ? "/my" : "/stocks";

  const handleGoBack = () => {
    const fromPath = ((location.state as { from?: string } | null) ?? null)?.from;
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate(fromPath ?? fallbackBackPath);
  };

  const loadKLine = async (targetSymbol: string, period: KLinePeriod, interval: KLineInterval, isMounted?: () => boolean) => {
    setKlineLoading(true);
    setKlineError(null);

    try {
      const response = await getStockKLine(targetSymbol, period, interval);
      if (isMounted && !isMounted()) {
        return;
      }
      setKlineData(response);
    } catch (err) {
      if (isMounted && !isMounted()) {
        return;
      }
      const messageText = err instanceof Error ? err.message : "K线加载失败";
      setKlineError(messageText);
      setKlineData(null);
    } finally {
      if (!isMounted || isMounted()) {
        setKlineLoading(false);
      }
    }
  };

  const loadTradeReviews = async (targetSymbol: string, isMounted?: () => boolean) => {
    setTradeReviewLoading(true);

    try {
      const response = await getStockTradeReviews(targetSymbol);
      if (isMounted && !isMounted()) {
        return;
      }
      setTradeReviews(response);
      setTradeReviewError(null);
    } catch (err) {
      if (isMounted && !isMounted()) {
        return;
      }
      const messageText = err instanceof Error ? err.message : "复盘加载失败";
      setTradeReviewError(messageText);
      setTradeReviews(null);
    } finally {
      if (!isMounted || isMounted()) {
        setTradeReviewLoading(false);
      }
    }
  };

  useEffect(() => {
    const syncAuth = () => {
      setAuthed(hasSessionAccess());
      setGuestMode(isGuestMode());
    };

    const authEvent = getAuthEventName();
    window.addEventListener(authEvent, syncAuth);
    window.addEventListener("storage", syncAuth);
    return () => {
      window.removeEventListener(authEvent, syncAuth);
      window.removeEventListener("storage", syncAuth);
    };
  }, []);

  useEffect(() => {
    let mounted = true;

    const run = async () => {
      setLoading(true);
      setError(null);
      setTradeReviewError(null);

      try {
        const snapshotResponse = await getStockSnapshot(symbol);

        if (mounted) {
          setDetail(snapshotResponse.detail);
          setAnalysis(snapshotResponse.analysis);
        }
      } catch (err) {
        if (mounted) {
          const message = err instanceof Error ? err.message : "加载失败";
          setError(message);
          setDetail(null);
          setAnalysis(null);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    if (symbol) {
      setDetailActiveTab("analysis");
      setKlinePeriod("6mo");
      setKlineInterval("1d");
      qaAbortRef.current?.abort();
      setQaQuestionInput("");
      setQaComposing(false);
      setQaLoading(false);
      setQaError(null);
      setQaMessages([
        {
          role: "assistant",
          content: "你可以问我估值、风险、买卖计划、分红、财报等问题，我会基于当前股票详情数据给出回答。",
        },
      ]);
      void run();
      tradeReviewForm.setFieldsValue({
        trade_date: today,
        action: "observe",
        follow_up_status: "open",
      });
    }

    return () => {
      mounted = false;
      qaAbortRef.current?.abort();
    };
  }, [symbol]);

  useEffect(() => {
    let mounted = true;
    if (!symbol) {
      return () => {
        mounted = false;
      };
    }

    void loadKLine(symbol, klinePeriod, klineInterval, () => mounted);
    return () => {
      mounted = false;
    };
  }, [symbol, klinePeriod, klineInterval]);

  useEffect(() => {
    if (!symbol) {
      return undefined;
    }

    const timerId = window.setInterval(() => {
      if (document.hidden) {
        return;
      }
      void getStockKLine(symbol, klinePeriod, klineInterval)
        .then((response) => {
          setKlineData(response);
          setKlineError(null);
        })
        .catch((err) => {
          const messageText = err instanceof Error ? err.message : "K线刷新失败";
          setKlineError(messageText);
        });
    }, 15000);

    return () => {
      window.clearInterval(timerId);
    };
  }, [symbol, klinePeriod, klineInterval]);

  useEffect(() => {
    let mounted = true;
    if (!symbol) {
      return () => {
        mounted = false;
      };
    }

    if (!authed) {
      setTradeReviews(null);
      setTradeReviewError(null);
      setTradeReviewLoading(false);
      if (detailActiveTab === "follow_up") {
        setDetailActiveTab("analysis");
      }
      return () => {
        mounted = false;
      };
    }

    if (guestMode) {
      const localResponse = getGuestTradeReviews(symbol, detail?.price ?? null);
      setTradeReviews(localResponse);
      setTradeReviewError(null);
      setTradeReviewLoading(false);
      return () => {
        mounted = false;
      };
    }

    void loadTradeReviews(symbol, () => mounted);
    return () => {
      mounted = false;
    };
  }, [authed, guestMode, symbol, detail?.price]);

  const detailTabItems = useMemo(
    () => [
      { key: "analysis", label: "数据分析" },
      ...(authed ? [{ key: "follow_up", label: "跟进复盘" }] : []),
    ],
    [authed]
  );

  const score = analysis?.score ?? 0;
  const qaQuickQuestions = useMemo(
    () => [
      `${detail?.name ?? "这只股票"}现在估值高吗？`,
      `${detail?.name ?? "这只股票"}最大的风险点是什么？`,
      "如果我分批建仓，止损和仓位怎么设置？",
      `${detail?.name ?? "这只股票"}分红质量怎么样？`,
    ],
    [detail?.name]
  );
  const showOwnerColumn = useMemo(
    () => Boolean(tradeReviews?.items.some((item) => Boolean(item.owner_username))),
    [tradeReviews]
  );

  const klineSummary = useMemo(() => {
    const points = klineData?.points ?? [];
    if (!points.length) {
      return null;
    }
    const latest = points[points.length - 1];
    const highest = Math.max(...points.map((item) => item.high));
    const lowest = Math.min(...points.map((item) => item.low));
    const avgTurnover = points.reduce((sum, item) => sum + item.volume, 0) / points.length;
    return {
      latest,
      highest,
      lowest,
      avgTurnover,
      samples: points.length,
    };
  }, [klineData]);

  const klineSourceLabel = useMemo(() => {
    const source = klineData?.source ?? "";
    if (!source) {
      return "未知";
    }
    if (source.startsWith("tencent:")) {
      return "腾讯行情";
    }
    if (source.startsWith("akshare:")) {
      return "AkShare/东方财富";
    }
    if (source.startsWith("yfinance:")) {
      return "Yahoo Finance";
    }
    if (source === "synthetic_fallback") {
      return "备用估算";
    }
    return source;
  }, [klineData]);

  const klineAdjustmentLabel = useMemo(() => {
    const source = klineData?.source ?? "";
    if (source.includes(":qfq")) {
      return "前复权";
    }
    if (source === "synthetic_fallback") {
      return "估算";
    }
    return "原始";
  }, [klineData]);

  const dividendAnalysis = useMemo(() => {
    if (!detail) {
      return null;
    }

    const records = [...detail.dividend_history]
      .filter((item) => item.cash_dividend_per_share > 0)
      .sort((left, right) => {
        const leftYear = extractYearNumber(left.year) ?? 0;
        const rightYear = extractYearNumber(right.year) ?? 0;
        return rightYear - leftYear;
      });

    if (records.length === 0) {
      return null;
    }

    const latest = records[0];
    const count = records.length;
    const avgCashDividend = records.reduce((sum, item) => sum + item.cash_dividend_per_share, 0) / count;
    const avgPayoutRatio = records.reduce((sum, item) => sum + item.payout_ratio, 0) / count;
    const estimatedDividendYield = detail.price > 0 ? (latest.cash_dividend_per_share / detail.price) * 100 : null;
    const maxCashDividend = Math.max(...records.map((item) => item.cash_dividend_per_share));
    const minCashDividend = Math.min(...records.map((item) => item.cash_dividend_per_share));
    const variationRatio = maxCashDividend > 0 ? (maxCashDividend - minCashDividend) / maxCashDividend : 0;

    let consecutiveYears = 1;
    for (let index = 1; index < records.length; index += 1) {
      const previousYear = extractYearNumber(records[index - 1].year);
      const currentYear = extractYearNumber(records[index].year);
      if (previousYear && currentYear && previousYear - currentYear === 1) {
        consecutiveYears += 1;
      } else {
        break;
      }
    }

    let stabilityLabel = "样本有限";
    if (count >= 5 && variationRatio <= 0.35) {
      stabilityLabel = "分红稳定";
    } else if (count >= 3 && variationRatio <= 0.6) {
      stabilityLabel = "分红较稳";
    } else if (count >= 2) {
      stabilityLabel = "分红有波动";
    }

    const highlightTags = [
      consecutiveYears >= 3 ? `连续分红 ${consecutiveYears} 年` : null,
      estimatedDividendYield !== null && estimatedDividendYield >= 4 ? "当前股息吸引力较强" : null,
      avgPayoutRatio >= 50 ? "分红率偏高" : null,
      latest.ex_dividend_date ? `最近除权 ${latest.ex_dividend_date}` : null,
    ].filter((item): item is string => Boolean(item));

    const commentary = [
      `${detail.name} 近 ${count} 个年度存在现金分红记录，最近一次每股分红 ${latest.cash_dividend_per_share.toFixed(2)} 元。`,
      consecutiveYears >= 3 ? `已连续分红 ${consecutiveYears} 年，具备一定股东回报连续性。` : "连续分红样本较短，需结合年报继续观察。",
      estimatedDividendYield !== null
        ? `按当前股价粗略估算，静态股息率约 ${estimatedDividendYield.toFixed(2)}%。`
        : "当前无法估算静态股息率。",
      `${stabilityLabel}，建议结合盈利增长、现金流与分红实施节奏综合判断。`,
    ].join("");

    return {
      count,
      latest,
      avgCashDividend,
      avgPayoutRatio,
      estimatedDividendYield,
      consecutiveYears,
      stabilityLabel,
      observationWindow: buildDividendObservationWindow(latest.ex_dividend_date),
      highlightTags,
      commentary,
    };
  }, [detail]);

  const factorRows = useMemo(
    () =>
      detail
        ? [
            { label: "PE", value: detail.pe },
            { label: "PB", value: detail.pb },
            { label: "ROE", value: `${detail.roe}%` },
            { label: "负债率", value: `${detail.debt_ratio}%` },
            { label: "营收增速", value: `${detail.revenue_growth}%` },
            { label: "利润增速", value: `${detail.profit_growth}%` },
            { label: "动量", value: `${detail.momentum}%` },
            { label: "波动率", value: `${detail.volatility}%` },
            { label: "舆情情绪", value: detail.news_sentiment.toFixed(2) },
          ]
        : [],
    [detail]
  );

  const factorScoreRows = useMemo(() => {
    if (!analysis) {
      return [];
    }

    return [
      { label: "基本面", value: analysis.factor_scores.fundamental },
      { label: "估值", value: analysis.factor_scores.valuation },
      { label: "趋势动量", value: analysis.factor_scores.momentum },
      { label: "情绪", value: analysis.factor_scores.sentiment },
      { label: "风控", value: analysis.factor_scores.risk_control },
    ];
  }, [analysis]);

  const financialColumns = useMemo(
    () => [
      { title: "年度", dataIndex: "year", key: "year", width: 90 },
      {
        title: "营收(亿)",
        dataIndex: "revenue",
        key: "revenue",
        render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 1 }),
      },
      {
        title: "净利润(亿)",
        dataIndex: "net_profit",
        key: "net_profit",
        render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 1 }),
      },
      { title: "ROE", dataIndex: "roe", key: "roe", render: (value: number) => `${value.toFixed(1)}%` },
      {
        title: "负债率",
        dataIndex: "debt_ratio",
        key: "debt_ratio",
        render: (value: number) => `${value.toFixed(1)}%`,
      },
      {
        title: "经营现金流(亿)",
        dataIndex: "operating_cashflow",
        key: "operating_cashflow",
        render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 1 }),
      },
      {
        title: "报告",
        key: "report_url",
        render: (_: unknown, record: FinancialReport) => (
          <a href={record.report_url} target="_blank" rel="noreferrer">
            查看
          </a>
        ),
      },
    ],
    []
  );

  const valuationColumns = useMemo(
    () => [
      { title: "年度", dataIndex: "year", key: "year", width: 90 },
      { title: "PE", dataIndex: "pe", key: "pe", render: (value: number) => value.toFixed(1) },
      { title: "PB", dataIndex: "pb", key: "pb", render: (value: number) => value.toFixed(2) },
      {
        title: "市值(亿)",
        dataIndex: "market_cap",
        key: "market_cap",
        render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 1 }),
      },
    ],
    []
  );

  const dividendColumns = useMemo(
    () => [
      { title: "年度", dataIndex: "year", key: "year", width: 90 },
      {
        title: "每股分红",
        dataIndex: "cash_dividend_per_share",
        key: "cash_dividend_per_share",
        render: (value: number) => value.toFixed(2),
      },
      {
        title: "分红率",
        dataIndex: "payout_ratio",
        key: "payout_ratio",
        render: (value: number) => `${value.toFixed(1)}%`,
      },
      { title: "除权日", dataIndex: "ex_dividend_date", key: "ex_dividend_date" },
    ],
    []
  );

  const shareholderColumns = useMemo(
    () => [
      { title: "股东", dataIndex: "name", key: "name" },
      { title: "类型", dataIndex: "holder_type", key: "holder_type" },
      {
        title: "持股比例",
        dataIndex: "holding_ratio",
        key: "holding_ratio",
        render: (value: number) => `${value.toFixed(2)}%`,
      },
      {
        title: "同比变化",
        dataIndex: "change_yoy",
        key: "change_yoy",
        render: (value: number) => (
          <Text style={{ color: value >= 0 ? "#389e0d" : "#cf1322" }}>{value >= 0 ? "+" : ""}{value.toFixed(2)}%</Text>
        ),
      },
    ],
    []
  );

  const peerColumns = useMemo(
    () => [
      {
        title: "同行",
        key: "symbol",
        render: (_: unknown, record: PeerCompany) => (
          <Space>
            <Link to={`/stocks/${encodeURIComponent(record.symbol)}${detailLinkSuffix}`} state={{ from: fallbackBackPath }}>
              {record.name}
            </Link>
            <Text type="secondary">{record.symbol}</Text>
          </Space>
        ),
      },
      { title: "市场", dataIndex: "market", key: "market" },
      { title: "PE", dataIndex: "pe", key: "pe", render: (value: number) => value.toFixed(1) },
      {
        title: "营收增速",
        dataIndex: "revenue_growth",
        key: "revenue_growth",
        render: (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`,
      },
      { title: "ROE", dataIndex: "roe", key: "roe", render: (value: number) => `${value.toFixed(1)}%` },
      {
        title: "市值(亿)",
        dataIndex: "market_cap",
        key: "market_cap",
        render: (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 1 }),
      },
    ],
    [detailLinkSuffix, fallbackBackPath]
  );

  const tradeReviewColumns = useMemo(
    () => [
      ...(showOwnerColumn
        ? [
            {
              title: "用户",
              key: "owner_username",
              width: 120,
              render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => (
                <Text>{record.owner_username || "未知"}</Text>
              ),
            },
          ]
        : []),
      { title: "日期", dataIndex: "trade_date", key: "trade_date", width: 110 },
      {
        title: "动作",
        key: "action",
        width: 90,
        render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => (
          <Tag color={tradeActionColor(record.action)}>{tradeActionLabel(record.action)}</Tag>
        ),
      },
      {
        title: "成交",
        key: "fill",
        width: 160,
        render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => {
          if (!record.price || !record.quantity) {
            return <Text type="secondary">-</Text>;
          }
          return (
            <Text>
              {record.price.toFixed(2)} × {record.quantity.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}
            </Text>
          );
        },
      },
      {
        title: "浮动收益",
        key: "floating_pnl",
        width: 140,
        render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => {
          if (record.floating_pnl == null || record.floating_pnl_pct == null) {
            return <Text type="secondary">-</Text>;
          }

          return (
            <Text style={{ color: record.floating_pnl >= 0 ? "#389e0d" : "#cf1322" }}>
              {record.floating_pnl >= 0 ? "+" : ""}
              {record.floating_pnl.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}（{record.floating_pnl_pct >= 0 ? "+" : ""}
              {record.floating_pnl_pct.toFixed(2)}%）
            </Text>
          );
        },
      },
      {
        title: "跟进状态",
        key: "follow_up_status",
        width: 180,
        render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => (
          <Space direction="vertical" size={2}>
            <Tag color={followUpStatusColor(record.follow_up_status)}>{followUpStatusLabel(record.follow_up_status)}</Tag>
            {record.next_review_date ? <Text type="secondary">下次复盘：{record.next_review_date}</Text> : null}
            {record.follow_up_items.length > 0 ? <Text type="secondary">事项：{record.follow_up_items.slice(0, 2).join("；")}</Text> : null}
            {record.is_follow_up_due ? <Text type="danger">已到复盘时间</Text> : null}
          </Space>
        ),
      },
      {
        title: "交易逻辑",
        dataIndex: "thesis",
        key: "thesis",
        ellipsis: true,
      },
      {
        title: "操作",
        key: "actions",
        width: 180,
        render: (_: unknown, record: StockTradeReviewResponse["items"][number]) => (
          <Space wrap>
            {record.follow_up_status === "open" ? (
              <Button
                size="small"
                onClick={() => void handleChangeFollowUpStatus(record.id, "in_progress")}
                loading={tradeReviewSubmitting}
              >
                开始跟进
              </Button>
            ) : null}
            {record.follow_up_status !== "closed" ? (
              <Button
                size="small"
                type="primary"
                ghost
                onClick={() => void handleChangeFollowUpStatus(record.id, "closed")}
                loading={tradeReviewSubmitting}
              >
                关闭跟进
              </Button>
            ) : null}
          </Space>
        ),
      },
    ],
    [showOwnerColumn, tradeReviewSubmitting, symbol]
  );

  const handleChangeFollowUpStatus = async (reviewId: number, status: FollowUpStatus) => {
    if (!symbol) {
      return;
    }
    if (!authed) {
      message.warning("请先登录或进入游客模式后再使用跟进功能");
      return;
    }

    if (guestMode) {
      setTradeReviewSubmitting(true);
      try {
        updateGuestTradeReview(symbol, reviewId, { follow_up_status: status }, detail?.price ?? null);
        setTradeReviews(getGuestTradeReviews(symbol, detail?.price ?? null));
        message.success("跟进状态已更新");
      } catch (err) {
        const messageText = err instanceof Error ? err.message : "更新跟进状态失败";
        message.error(messageText);
      } finally {
        setTradeReviewSubmitting(false);
      }
      return;
    }

    setTradeReviewSubmitting(true);
    try {
      await updateStockTradeReview(symbol, reviewId, { follow_up_status: status });
      message.success("跟进状态已更新");
      await loadTradeReviews(symbol);
    } catch (err) {
      const messageText = err instanceof Error ? err.message : "更新跟进状态失败";
      message.error(messageText);
    } finally {
      setTradeReviewSubmitting(false);
    }
  };

  const handleCreateTradeReview = async (values: TradeReviewFormValues) => {
    if (!symbol) {
      return;
    }
    if (!authed) {
      message.warning("请先登录或进入游客模式后再使用复盘功能");
      return;
    }

    if (values.action !== "observe" && (!values.price || !values.quantity)) {
      message.warning("买入/卖出/加减仓记录请填写成交价和数量");
      return;
    }

    const followUpItems = (values.follow_up_items_text ?? "")
      .split(/\n|；|;/)
      .map((item) => item.trim())
      .filter(Boolean);

    setTradeReviewSubmitting(true);
    try {
      const payload = {
        trade_date: values.trade_date,
        action: values.action,
        price: values.price,
        quantity: values.quantity,
        thesis: values.thesis,
        execution_notes: values.execution_notes,
        outcome_review: values.outcome_review,
        lessons_learned: values.lessons_learned,
        follow_up_items: followUpItems,
        follow_up_status: values.follow_up_status,
        next_review_date: values.next_review_date,
        confidence_score: values.confidence_score,
        discipline_score: values.discipline_score,
      };

      if (guestMode) {
        createGuestTradeReview(symbol, payload, detail?.price ?? null);
        setTradeReviews(getGuestTradeReviews(symbol, detail?.price ?? null));
      } else {
        await createStockTradeReview(symbol, payload);
        await loadTradeReviews(symbol);
      }

      message.success("复盘记录已保存");
      tradeReviewForm.resetFields();
      tradeReviewForm.setFieldsValue({
        trade_date: today,
        action: "observe",
        follow_up_status: "open",
      });
    } catch (err) {
      const messageText = err instanceof Error ? err.message : "保存复盘失败";
      message.error(messageText);
    } finally {
      setTradeReviewSubmitting(false);
    }
  };

  const handleAskQuestion = async (rawQuestion?: string) => {
    const normalizedQuestion = (rawQuestion ?? qaQuestionInput).trim();
    if (!normalizedQuestion) {
      message.warning("请先输入问题");
      return;
    }
    if (!symbol || qaLoading) {
      return;
    }

    const requestId = ++qaRequestIdRef.current;
    qaAbortRef.current?.abort();
    const controller = new AbortController();
    qaAbortRef.current = controller;

    const historyPayload: StockQAMessage[] = qaMessages
      .filter((item) => item.role === "user" || item.role === "assistant")
      .slice(-8)
      .map((item) => ({
        role: item.role,
        content: item.content,
      }));

    setQaQuestionInput("");
    setQaError(null);
    setQaMessages((prev) => [...prev, { role: "user", content: normalizedQuestion }]);
    setQaLoading(true);

    try {
      const response = await askStockQuestion(
        symbol,
        {
          question: normalizedQuestion,
          history: historyPayload,
        },
        { signal: controller.signal },
      );

      if (controller.signal.aborted || requestId !== qaRequestIdRef.current) {
        return;
      }

      setQaMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer,
          confidence: response.confidence,
          bullets: response.bullets,
          references: response.references,
          followUpQuestions: response.follow_up_questions,
          disclaimer: response.disclaimer,
          searchUsed: response.search_used,
          searchQuery: response.search_query,
          searchResultCount: response.search_result_count,
        },
      ]);
    } catch (err) {
      if (isAbortError(err) || controller.signal.aborted || requestId !== qaRequestIdRef.current) {
        return;
      }
      const messageText = err instanceof Error ? err.message : "AI问答失败";
      setQaError(messageText);
      setQaMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `本次问答暂时失败：${messageText}`,
          disclaimer: "你可以稍后重试，或换一个更具体的问题。",
        },
      ]);
      message.error(messageText);
    } finally {
      if (!controller.signal.aborted && requestId === qaRequestIdRef.current) {
        setQaLoading(false);
      }
    }
  };

  return (
    <Space className="stock-detail-page" direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="stock-detail-hero">
        <Row gutter={[16, 16]} align="middle" justify="space-between">
          <Col xs={24} lg={16}>
            <Space direction="vertical" size={6}>
              <Title level={4} style={{ margin: 0 }}>
                {detail?.name ?? "个股详情"}（{symbol}）
              </Title>
              <Space wrap>
                {detail ? <Tag color="blue">{detail.market}</Tag> : null}
                {detail ? <Tag>{detail.exchange}</Tag> : null}
                {detail ? <Tag>{detail.board}</Tag> : null}
                {analysis ? (
                  <Tag color={recommendationColor(analysis.recommendation)}>{recommendationLabel(analysis.recommendation)}</Tag>
                ) : null}
                {analysis ? <Tag color={riskColor(analysis.risk_level)}>{riskLabel(analysis.risk_level)}</Tag> : null}
              </Space>
              <Space wrap>
                <Button type="link" style={{ paddingInline: 0 }} onClick={handleGoBack}>
                  返回上一级
                </Button>
                {detail ? (
                  <>
                    <a href={detail.company_website} target="_blank" rel="noreferrer">
                      官网
                    </a>
                    <a href={detail.investor_relations_url} target="_blank" rel="noreferrer">
                      投资者关系
                    </a>
                    <a href={detail.exchange_profile_url} target="_blank" rel="noreferrer">
                      交易所资料
                    </a>
                    <a href={detail.quote_url} target="_blank" rel="noreferrer">
                      行情页
                    </a>
                  </>
                ) : null}
              </Space>
            </Space>
          </Col>

          <Col xs={24} lg={8}>
            {detail ? (
              <Space direction="vertical" size={0} style={{ width: "100%", textAlign: "right" }}>
                <Statistic title="最新价" value={detail.price} precision={2} suffix={detail.currency} />
                <Text style={{ color: detail.change_pct >= 0 ? "#389e0d" : "#cf1322", fontSize: 16 }}>
                  {signedPercent(detail.change_pct)}
                </Text>
                {analysis ? <Text type="secondary">分析置信度：{analysis.confidence}/100</Text> : null}
                {detail ? <Text type="secondary">数据可信度：{detail.data_quality.reliability_score}/100</Text> : null}
                <Space style={{ width: "100%", justifyContent: "flex-end" }} wrap size={6}>
                  <Tag bordered={false} color="blue">PE {detail.pe.toFixed(1)}</Tag>
                  <Tag bordered={false} color="purple">PB {detail.pb.toFixed(2)}</Tag>
                  <Tag bordered={false} color="cyan">ROE {detail.roe.toFixed(1)}%</Tag>
                </Space>
              </Space>
            ) : null}
          </Col>
        </Row>
      </Card>

      {loading ? (
        <Card>
          <div style={{ display: "grid", placeItems: "center", minHeight: 240 }}>
            <Spin size="large" />
          </div>
        </Card>
      ) : null}

      {error ? <Alert type="error" showIcon message={`加载个股数据失败：${error}`} /> : null}

      {!loading && detail && analysis ? (
        <>
          <Card className="stock-detail-tab-card">
            <Tabs
              activeKey={detailActiveTab}
              onChange={(value) => setDetailActiveTab(value as DetailTabKey)}
              items={detailTabItems}
            />
            {!authed ? <Text type="secondary">登录或进入游客模式后可查看并维护你的个人跟进复盘记录。</Text> : null}
          </Card>

          {detailActiveTab === "analysis" ? (
            <>
              <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <Card title="智能评分与结论">
                <div style={{ display: "grid", placeItems: "center" }}>
                  <Progress type="dashboard" percent={score} strokeColor={scoreColor(score)} format={(value) => `${value}`} />
                </div>
                <Paragraph type="secondary" style={{ marginBottom: 8, marginTop: 10 }}>
                  {analysis.summary}
                </Paragraph>
                <Progress
                  percent={analysis.confidence}
                  strokeColor={factorColor(analysis.confidence)}
                  format={(value) => `置信度 ${value}`}
                />
              </Card>
            </Col>

            <Col xs={24} lg={16}>
              <Card title="行情与估值快照">
                <Descriptions column={3} size="small" bordered>
                  <Descriptions.Item label="最新价">{detail.price.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="涨跌幅">
                    <Text style={{ color: detail.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>{signedPercent(detail.change_pct)}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="货币">{detail.currency}</Descriptions.Item>

                  <Descriptions.Item label="总市值">{toYi(detail.market_cap)}</Descriptions.Item>
                  <Descriptions.Item label="流通市值">{toYi(detail.free_float_cap)}</Descriptions.Item>
                  <Descriptions.Item label="换手率">{detail.turnover_rate.toFixed(2)}%</Descriptions.Item>

                  <Descriptions.Item label="日振幅">{detail.amplitude.toFixed(2)}%</Descriptions.Item>
                  <Descriptions.Item label="5日均成交额">{toYi(detail.avg_volume_5d)}</Descriptions.Item>
                  <Descriptions.Item label="20日均成交额">{toYi(detail.avg_volume_20d)}</Descriptions.Item>

                  <Descriptions.Item label="支撑位">{detail.support_price.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="压力位">{detail.resistance_price.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="最近财报日">{detail.last_report_date}</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
          </Row>

          <Card
            title="AI问答（Beta）"
            extra={<Text type="secondary">基于当前股票详情数据回答</Text>}
          >
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              <Space wrap>
                {qaQuickQuestions.map((item) => (
                  <Tag
                    key={item}
                    style={{ cursor: "pointer", userSelect: "none" }}
                    onClick={() => void handleAskQuestion(item)}
                  >
                    {item}
                  </Tag>
                ))}
              </Space>

              <TextArea
                value={qaQuestionInput}
                rows={3}
                showCount
                maxLength={500}
                placeholder="例如：这只股票现在估值高吗？主要风险是什么？适合怎么分批买入？"
                onChange={(event) => setQaQuestionInput(event.target.value)}
                onCompositionStart={() => setQaComposing(true)}
                onCompositionEnd={() => setQaComposing(false)}
                onPressEnter={(event) => {
                  if (qaComposing || event.nativeEvent.isComposing) {
                    return;
                  }
                  if (!event.shiftKey) {
                    event.preventDefault();
                    void handleAskQuestion();
                  }
                }}
              />

              <Space>
                <Button type="primary" loading={qaLoading} onClick={() => void handleAskQuestion()}>
                  发送问题
                </Button>
                <Text type="secondary">按 Enter 发送，Shift + Enter 换行</Text>
              </Space>

              {qaError ? <Alert type="warning" showIcon message={`问答失败：${qaError}`} /> : null}

              <List
                size="small"
                dataSource={qaMessages}
                locale={{ emptyText: "输入问题后，这里会显示问答记录" }}
                renderItem={(item) => (
                  <List.Item>
                    <div
                      style={{
                        width: "100%",
                        background: item.role === "assistant" ? "#f6ffed" : "#f5f5f5",
                        border: "1px solid #f0f0f0",
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    >
                      <Space direction="vertical" size={6} style={{ width: "100%" }}>
                        <Space wrap>
                          <Tag color={item.role === "assistant" ? "green" : "blue"}>
                            {item.role === "assistant" ? "AI" : "你"}
                          </Tag>
                          {item.role === "assistant" && item.confidence ? <Tag>置信度 {item.confidence}/99</Tag> : null}
                          {item.role === "assistant" && item.searchUsed ? <Tag color="processing">已联网检索 {item.searchResultCount ?? 0} 条</Tag> : null}
                        </Space>

                        <Paragraph style={{ marginBottom: 0 }}>{item.content}</Paragraph>

                        {item.bullets && item.bullets.length > 0 ? (
                          <List
                            size="small"
                            dataSource={item.bullets}
                            renderItem={(bullet) => (
                              <List.Item style={{ paddingBlock: 4 }}>
                                <Text type="secondary">- {bullet}</Text>
                              </List.Item>
                            )}
                          />
                        ) : null}

                        {item.searchUsed && item.searchQuery ? <Text type="secondary">检索词：{item.searchQuery}</Text> : null}

                        {item.references && item.references.length > 0 ? (
                          <Space direction="vertical" size={2}>
                            <Text strong>关键依据</Text>
                            {item.references.map((reference) => (
                              <Text key={reference} type="secondary">
                                · {reference}
                              </Text>
                            ))}
                          </Space>
                        ) : null}

                        {item.followUpQuestions && item.followUpQuestions.length > 0 ? (
                          <Space wrap>
                            {item.followUpQuestions.map((followUp) => (
                              <Tag
                                key={followUp}
                                color="processing"
                                style={{ cursor: "pointer" }}
                                onClick={() => void handleAskQuestion(followUp)}
                              >
                                {followUp}
                              </Tag>
                            ))}
                          </Space>
                        ) : null}

                        {item.disclaimer ? <Text type="secondary">{item.disclaimer}</Text> : null}
                      </Space>
                    </div>
                  </List.Item>
                )}
              />
            </Space>
          </Card>

          <Card
            title="K线走势"
            extra={
              <Space>
                <Button
                  size="small"
                  type={klineInterval === "1d" ? "primary" : "default"}
                  onClick={() => setKlineInterval("1d")}
                >
                  日线
                </Button>
                <Button
                  size="small"
                  type={klineInterval === "1h" ? "primary" : "default"}
                  onClick={() => setKlineInterval("1h")}
                >
                  小时线
                </Button>
                <Divider type="vertical" />
                {[
                  { label: "1M", value: "1mo" },
                  { label: "3M", value: "3mo" },
                  { label: "6M", value: "6mo" },
                  { label: "1Y", value: "1y" },
                  { label: "5Y", value: "5y" },
                ].map((item) => (
                  <Button
                    key={item.value}
                    size="small"
                    type={klinePeriod === item.value ? "primary" : "default"}
                    onClick={() => setKlinePeriod(item.value as KLinePeriod)}
                  >
                    {item.label}
                  </Button>
                ))}
              </Space>
            }
          >
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              <Space wrap>
                <Tag color={klineData?.is_fallback ? "warning" : "success"}>{klineData?.is_fallback ? "备用K线" : "真实K线"}</Tag>
                <Tag color="blue">{klineInterval === "1h" ? "小时级" : "日级"}</Tag>
                <Tag>{klineAdjustmentLabel}</Tag>
                <Text type="secondary">数据源：{klineSourceLabel}</Text>
                <Text type="secondary">自动刷新：15秒</Text>
                {klineData?.change_pct !== undefined && klineData?.change_pct !== null ? (
                  <Text type="secondary">区间涨跌幅 {klineData.change_pct >= 0 ? "+" : ""}{klineData.change_pct.toFixed(2)}%</Text>
                ) : null}
              </Space>
              {klineSummary ? (
                <Descriptions size="small" column={4} bordered>
                  <Descriptions.Item label="最新收盘">{klineSummary.latest.close.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="区间最高">{klineSummary.highest.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="区间最低">{klineSummary.lowest.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="平均成交额">{yuanToYi(klineSummary.avgTurnover)}</Descriptions.Item>
                </Descriptions>
              ) : null}
              {klineData?.warning ? <Alert type="warning" showIcon message={klineData.warning} /> : null}
              {klineError ? <Alert type="warning" showIcon message={`K线加载失败：${klineError}`} /> : null}
              <Card loading={klineLoading} bodyStyle={{ padding: 12 }}>
                <StockKLineChart points={klineData?.points ?? []} />
              </Card>
            </Space>
          </Card>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={10}>
              <Card title="数据可信度与来源">
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="数据来源">{detail.data_quality.source}</Descriptions.Item>
                  <Descriptions.Item label="行情来源">{detail.data_quality.price_source}</Descriptions.Item>
                  <Descriptions.Item label="基本面来源">{detail.data_quality.fundamentals_source}</Descriptions.Item>
                  <Descriptions.Item label="联网补齐">{detail.data_quality.is_enriched ? "已补齐" : "基础模式"}</Descriptions.Item>
                  <Descriptions.Item label="覆盖率">{detail.data_quality.coverage_score.toFixed(1)}%</Descriptions.Item>
                  <Descriptions.Item label="可信度">{detail.data_quality.reliability_score}/100</Descriptions.Item>
                  <Descriptions.Item label="最后更新时间">{detail.data_quality.updated_at ? new Date(detail.data_quality.updated_at).toLocaleString() : "未知"}</Descriptions.Item>
                  <Descriptions.Item label="距今天数">{detail.data_quality.freshness_days ?? "未知"}</Descriptions.Item>
                </Descriptions>

                <Divider style={{ margin: "12px 0" }} />
                <List
                  size="small"
                  header={<Text strong>可信度提醒</Text>}
                  dataSource={detail.data_quality.warnings.length > 0 ? detail.data_quality.warnings : ["当前无额外可信度警告。"]}
                  renderItem={(item) => (
                    <List.Item>
                      <Text type={detail.data_quality.warnings.length > 0 ? "warning" : undefined}>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>

            <Col xs={24} lg={14}>
              <Card title="分析依据与适配提示">
                <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  {analysis.methodology}
                </Paragraph>
                <Paragraph style={{ marginBottom: 8 }}>{analysis.suitability_note}</Paragraph>
                <Paragraph type="secondary" style={{ marginBottom: 12 }}>
                  {analysis.disclaimer}
                </Paragraph>

                <List
                  size="small"
                  header={<Text strong>本次结论的主要依据</Text>}
                  dataSource={analysis.evidence_points}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="公司档案与基本介绍">
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="公司全称">{detail.company_full_name}</Descriptions.Item>
                  <Descriptions.Item label="英文名">{detail.english_name}</Descriptions.Item>
                  <Descriptions.Item label="上市日期">{detail.listing_date}</Descriptions.Item>
                  <Descriptions.Item label="总部">{detail.headquarters}</Descriptions.Item>
                  <Descriptions.Item label="法定代表人">{detail.legal_representative}</Descriptions.Item>
                  <Descriptions.Item label="员工规模">{detail.employees.toLocaleString("zh-CN")}</Descriptions.Item>
                </Descriptions>

                <Alert
                  style={{ marginTop: 12, marginBottom: 12 }}
                  type="info"
                  showIcon
                  message="行业定位"
                  description={detail.industry_positioning}
                />

                <Paragraph style={{ marginBottom: 8 }}>{detail.company_intro}</Paragraph>
                <Paragraph type="secondary" style={{ marginBottom: 12 }}>
                  主营业务：{detail.main_business}
                </Paragraph>

                <Text strong>主要产品与服务</Text>
                <Space wrap style={{ marginTop: 8, marginBottom: 12 }}>
                  {detail.products_services.map((item) => (
                    <Tag key={item} color="geekblue">
                      {item}
                    </Tag>
                  ))}
                </Space>

                <Text strong>业务范围</Text>
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={detail.business_scope}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />

                <Divider style={{ margin: "12px 0" }} />
                <Text strong>主要覆盖市场</Text>
                <Space wrap style={{ marginTop: 8, marginBottom: 12 }}>
                  {detail.market_coverage.map((item) => (
                    <Tag key={item} color="cyan">
                      {item}
                    </Tag>
                  ))}
                </Space>

                <Text strong>公司亮点</Text>
                <List
                  size="small"
                  style={{ marginTop: 8 }}
                  dataSource={detail.company_highlights}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />

                <Divider style={{ margin: "12px 0" }} />
                <Text strong>业务标签</Text>
                <Space wrap style={{ marginTop: 8 }}>
                  {detail.business_tags.map((tag) => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </Space>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="研究主线与事件跟踪">
                <List
                  size="small"
                  header={<Text strong>核心逻辑</Text>}
                  dataSource={detail.core_logic}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
                <Divider style={{ margin: "12px 0" }} />
                <List
                  size="small"
                  header={<Text strong>近期跟踪事件</Text>}
                  dataSource={detail.recent_events}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <Card title="历年财报摘要（近6年）">
                <Table<FinancialReport>
                  size="small"
                  pagination={false}
                  rowKey={(record) => record.year}
                  dataSource={detail.financial_reports}
                  columns={financialColumns}
                  scroll={{ x: 760 }}
                />
              </Card>
            </Col>

            <Col xs={24} lg={10}>
              <Card title="估值历史与分红记录">
                <Text strong>估值历史</Text>
                <Table<ValuationHistoryPoint>
                  size="small"
                  pagination={false}
                  rowKey={(record) => record.year}
                  dataSource={detail.valuation_history}
                  columns={valuationColumns}
                  style={{ marginTop: 8 }}
                />

                <Divider style={{ margin: "14px 0" }} />

                <Text strong>分红分析</Text>
                {dividendAnalysis ? (
                  <Space direction="vertical" size={12} style={{ width: "100%", marginTop: 8 }}>
                    <Row gutter={[12, 12]}>
                      <Col xs={12} sm={6}>
                        <Statistic title="分红年数" value={dividendAnalysis.count} suffix="年" />
                      </Col>
                      <Col xs={12} sm={6}>
                        <Statistic title="最近每股分红" value={dividendAnalysis.latest.cash_dividend_per_share} precision={2} suffix="元" />
                      </Col>
                      <Col xs={12} sm={6}>
                        <Statistic
                          title="估算股息率"
                          value={dividendAnalysis.estimatedDividendYield == null ? "待估算" : dividendAnalysis.estimatedDividendYield}
                          precision={dividendAnalysis.estimatedDividendYield == null ? undefined : 2}
                          suffix="%"
                        />
                      </Col>
                      <Col xs={12} sm={6}>
                        <Statistic title="平均分红率" value={dividendAnalysis.avgPayoutRatio} precision={1} suffix="%" />
                      </Col>
                    </Row>

                    <Descriptions column={2} size="small" bordered>
                      <Descriptions.Item label="连续分红判断">{dividendAnalysis.consecutiveYears} 年</Descriptions.Item>
                      <Descriptions.Item label="分红稳定性">{dividendAnalysis.stabilityLabel}</Descriptions.Item>
                      <Descriptions.Item label="平均每股分红">{dividendAnalysis.avgCashDividend.toFixed(2)} 元</Descriptions.Item>
                      <Descriptions.Item label="最近除权日">{dividendAnalysis.latest.ex_dividend_date || "待披露"}</Descriptions.Item>
                      <Descriptions.Item label="下次观察窗口" span={2}>
                        {dividendAnalysis.observationWindow}
                      </Descriptions.Item>
                    </Descriptions>

                    <Space wrap>
                      {dividendAnalysis.highlightTags.map((item) => (
                        <Tag key={item} color="gold">
                          {item}
                        </Tag>
                      ))}
                    </Space>

                    <Alert type="info" showIcon message="分红分析结论" description={dividendAnalysis.commentary} />
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可分析的分红历史" style={{ marginTop: 12 }} />
                )}

                <Divider style={{ margin: "14px 0" }} />

                <Text strong>分红记录</Text>
                <Table<DividendRecord>
                  size="small"
                  pagination={false}
                  rowKey={(record) => record.year}
                  dataSource={detail.dividend_history}
                  columns={dividendColumns}
                  style={{ marginTop: 8 }}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="股东结构（主要持有人）">
                <Table<ShareholderRecord>
                  size="small"
                  pagination={false}
                  rowKey={(record) => `${record.name}-${record.holder_type}`}
                  dataSource={detail.shareholder_structure}
                  columns={shareholderColumns}
                />
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="同行公司对比">
                <Table<PeerCompany>
                  size="small"
                  pagination={false}
                  rowKey={(record) => record.symbol}
                  dataSource={detail.peer_companies}
                  columns={peerColumns}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <Card title="新闻与舆情要点">
                <List
                  size="small"
                  dataSource={detail.news_highlights}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
            <Col xs={24} lg={8}>
              <Card title="潜在催化事件">
                <List
                  size="small"
                  dataSource={detail.catalyst_events}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
            <Col xs={24} lg={8}>
              <Card title="关键风险清单">
                <List
                  size="small"
                  dataSource={detail.key_risks}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="五维因子评分">
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  {factorScoreRows.map((item) => (
                    <div key={item.label}>
                      <Space style={{ width: "100%", justifyContent: "space-between" }}>
                        <Text>{item.label}</Text>
                        <Text strong>{item.value}</Text>
                      </Space>
                      <Progress percent={item.value} showInfo={false} strokeColor={factorColor(item.value)} />
                    </div>
                  ))}
                </Space>

                <Divider style={{ margin: "14px 0" }} />
                <Descriptions column={2} size="small">
                  {factorRows.map((row) => (
                    <Descriptions.Item key={row.label} label={row.label}>
                      {row.value}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="情景推演（30-60天）">
                <List
                  dataSource={analysis.scenario_analysis}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title="优势亮点">
                <List
                  dataSource={analysis.strengths}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="风险提示（模型视角）">
                <List
                  dataSource={analysis.risks}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>

              <Card title="交易计划与执行清单">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="建议入场区间">{analysis.trade_plan.entry_range}</Descriptions.Item>
              <Descriptions.Item label="建议止损位">{analysis.trade_plan.stop_loss}</Descriptions.Item>
              <Descriptions.Item label="第一目标位">{analysis.trade_plan.take_profit}</Descriptions.Item>
              <Descriptions.Item label="仓位建议">{analysis.trade_plan.position_advice}</Descriptions.Item>
            </Descriptions>

            <Divider style={{ margin: "14px 0" }} />

            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <List
                  size="small"
                  header={<Text strong>执行动作清单</Text>}
                  dataSource={analysis.action_items}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Col>
              <Col xs={24} lg={12}>
                <List
                  size="small"
                  header={<Text strong>持续监控清单</Text>}
                  dataSource={analysis.monitoring_points}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Col>
            </Row>

            <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 12 }}>
              免责声明：以上内容用于研究辅助与风险管理，不构成任何收益承诺或投资建议。
            </Paragraph>
              </Card>
            </>
          ) : null}

          {detailActiveTab === "follow_up" ? (
            <Card title="交易复盘与跟进（计划 → 执行 → 复盘）" loading={tradeReviewLoading && !tradeReviews}>
            {tradeReviewError ? <Alert type="warning" showIcon message={`复盘数据加载失败：${tradeReviewError}`} style={{ marginBottom: 12 }} /> : null}

            {tradeReviews ? (
              <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
                <Col xs={12} md={6}>
                  <Statistic title="复盘总数" value={tradeReviews.summary.total_reviews} />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="待/进行中" value={tradeReviews.summary.open_follow_ups + tradeReviews.summary.in_progress_follow_ups} />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="到期跟进" value={tradeReviews.summary.due_follow_ups} valueStyle={{ color: tradeReviews.summary.due_follow_ups > 0 ? "#cf1322" : undefined }} />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="净浮动收益"
                    value={tradeReviews.summary.net_floating_pnl}
                    precision={2}
                    valueStyle={{ color: tradeReviews.summary.net_floating_pnl >= 0 ? "#389e0d" : "#cf1322" }}
                  />
                </Col>
              </Row>
            ) : null}

            <Row gutter={[16, 16]}>
              <Col xs={24} lg={10}>
                <Card type="inner" title="新增复盘记录" styles={{ body: { paddingBottom: 8 } }}>
                  <Form<TradeReviewFormValues>
                    layout="vertical"
                    form={tradeReviewForm}
                    initialValues={{ trade_date: today, action: "observe", follow_up_status: "open" }}
                    onFinish={(values) => void handleCreateTradeReview(values)}
                  >
                    <Row gutter={12}>
                      <Col span={12}>
                        <Form.Item name="trade_date" label="交易日期" rules={[{ required: true, message: "请输入交易日期" }]}> 
                          <Input placeholder="YYYY-MM-DD" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="action" label="交易动作" rules={[{ required: true, message: "请选择交易动作" }]}> 
                          <Select
                            options={[
                              { label: "观察", value: "observe" },
                              { label: "买入", value: "buy" },
                              { label: "卖出", value: "sell" },
                              { label: "加仓", value: "add" },
                              { label: "减仓", value: "reduce" },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Row gutter={12}>
                      <Col span={12}>
                        <Form.Item name="price" label="成交价">
                          <InputNumber style={{ width: "100%" }} min={0} precision={3} placeholder="可选" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="quantity" label="数量">
                          <InputNumber style={{ width: "100%" }} min={0} precision={0} placeholder="可选" />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Form.Item name="thesis" label="交易逻辑" rules={[{ required: true, message: "请填写交易逻辑" }]}> 
                      <TextArea rows={3} placeholder="为什么买/卖？核心假设是什么？" />
                    </Form.Item>

                    <Form.Item name="execution_notes" label="执行记录">
                      <TextArea rows={2} placeholder="盘中观察、执行偏差、仓位变化等" />
                    </Form.Item>

                    <Form.Item name="follow_up_items_text" label="跟进事项（每行一条）">
                      <TextArea rows={3} placeholder="例如：1) 下次财报前检查现金流\n2) 观察北向资金流入" />
                    </Form.Item>

                    <Row gutter={12}>
                      <Col span={12}>
                        <Form.Item name="follow_up_status" label="跟进状态">
                          <Select
                            options={[
                              { label: "待跟进", value: "open" },
                              { label: "跟进中", value: "in_progress" },
                              { label: "已关闭", value: "closed" },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="next_review_date" label="下次复盘日">
                          <Input placeholder="YYYY-MM-DD" />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Row gutter={12}>
                      <Col span={12}>
                        <Form.Item name="confidence_score" label="信心分(0-100)">
                          <InputNumber style={{ width: "100%" }} min={0} max={100} precision={0} placeholder="可选" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="discipline_score" label="纪律分(0-100)">
                          <InputNumber style={{ width: "100%" }} min={0} max={100} precision={0} placeholder="可选" />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Form.Item name="outcome_review" label="结果复盘">
                      <TextArea rows={2} placeholder="结果是否符合预期？" />
                    </Form.Item>

                    <Form.Item name="lessons_learned" label="经验教训">
                      <TextArea rows={2} placeholder="可复用经验、需避免错误" />
                    </Form.Item>

                    <Space>
                      <Button type="primary" htmlType="submit" loading={tradeReviewSubmitting}>
                        保存复盘
                      </Button>
                      <Button
                        onClick={() => {
                          tradeReviewForm.resetFields();
                          tradeReviewForm.setFieldsValue({
                            trade_date: today,
                            action: "observe",
                            follow_up_status: "open",
                          });
                        }}
                      >
                        重置
                      </Button>
                    </Space>
                  </Form>
                </Card>
              </Col>

              <Col xs={24} lg={14}>
                <Card
                  type="inner"
                  title="复盘记录列表"
                  extra={
                    <Button loading={tradeReviewLoading} onClick={() => void loadTradeReviews(symbol)}>
                      刷新
                    </Button>
                  }
                >
                  <Space direction="vertical" size={8} style={{ width: "100%" }}>
                    {tradeReviews?.current_price ? (
                      <Text type="secondary">当前参考价：{tradeReviews.current_price.toFixed(2)}</Text>
                    ) : (
                      <Text type="secondary">当前参考价暂不可用</Text>
                    )}

                    <Table
                      size="small"
                      rowKey={(record) => record.id}
                      loading={tradeReviewLoading}
                      pagination={{ pageSize: 8, showSizeChanger: false }}
                      dataSource={tradeReviews?.items ?? []}
                      columns={tradeReviewColumns}
                      scroll={{ x: 980 }}
                      locale={{ emptyText: "暂无复盘记录，先新增一条吧" }}
                    />
                  </Space>
                </Card>
              </Col>
            </Row>
          </Card>
          ) : null}
        </>
      ) : null}
    </Space>
  );
}

export default StockDetailPage;
