import { getStockDetail } from "../api/stocks";
import type {
  FollowUpStatus,
  NotificationCategory,
  NotificationItem,
  NotificationListResponse,
  NotificationReadResponse,
  NotificationRefreshResponse,
  NotificationSetting,
  NotificationSettingUpdateRequest,
  PositionAnalysisResponse,
  PositionCreateRequest,
  PositionFollowUpCreateRequest,
  PositionFollowUpItem,
  PositionFollowUpListResponse,
  PositionListResponse,
  PositionSnapshot,
  PositionUpdateRequest,
  WatchlistItem,
  WatchlistListResponse,
} from "../types/account";
import type {
  StockTradeReviewCreateRequest,
  StockTradeReviewItem,
  StockTradeReviewResponse,
  StockTradeReviewSummary,
  StockTradeReviewUpdateRequest,
  TradeReviewAction,
} from "../types/stock";

const GUEST_DATA_KEY = "stock_assistant_guest_data_v1";

interface GuestSequence {
  watchlist: number;
  position: number;
  followUp: number;
  notification: number;
  tradeReview: number;
}

interface GuestDataStore {
  watchlist: WatchlistItem[];
  positions: PositionSnapshot[];
  followUps: PositionFollowUpItem[];
  notificationSetting: NotificationSetting;
  notifications: NotificationItem[];
  tradeReviewsBySymbol: Record<string, StockTradeReviewItem[]>;
  seq: GuestSequence;
}

export interface GuestWorkspaceSnapshot {
  watchlist: WatchlistListResponse;
  positions: PositionListResponse;
  analysis: PositionAnalysisResponse;
  followUps: PositionFollowUpListResponse;
}

export interface GuestDataSummary {
  watchlistCount: number;
  positionCount: number;
  followUpCount: number;
  tradeReviewCount: number;
  notificationCount: number;
}

export interface GuestMigrationSnapshot {
  watchlist: WatchlistItem[];
  positions: PositionSnapshot[];
  followUps: PositionFollowUpItem[];
  tradeReviewsBySymbol: Record<string, StockTradeReviewItem[]>;
  notificationSetting: NotificationSetting;
}

function nowIso(): string {
  return new Date().toISOString();
}

function todayText(): string {
  return new Date().toISOString().slice(0, 10);
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function defaultNotificationSetting(): NotificationSetting {
  return {
    enable_price_alert: true,
    enable_report_alert: true,
    enable_followup_due_alert: true,
    updated_at: nowIso(),
  };
}

function emptyStore(): GuestDataStore {
  return {
    watchlist: [],
    positions: [],
    followUps: [],
    notificationSetting: defaultNotificationSetting(),
    notifications: [],
    tradeReviewsBySymbol: {},
    seq: {
      watchlist: 1,
      position: 1,
      followUp: 1,
      notification: 1,
      tradeReview: 1,
    },
  };
}

function safeNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return fallback;
}

function safeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function sortByDateDesc<T>(rows: T[], dateGetter: (item: T) => string): T[] {
  return [...rows].sort((left, right) => {
    const leftText = dateGetter(left);
    const rightText = dateGetter(right);
    return rightText.localeCompare(leftText);
  });
}

function parseStore(raw: string | null): GuestDataStore {
  if (!raw) {
    return emptyStore();
  }

  try {
    const parsed = JSON.parse(raw) as Partial<GuestDataStore>;
    const base = emptyStore();
    const seq: Partial<GuestSequence> = parsed.seq ?? {};

    return {
      watchlist: Array.isArray(parsed.watchlist) ? parsed.watchlist : base.watchlist,
      positions: Array.isArray(parsed.positions) ? parsed.positions : base.positions,
      followUps: Array.isArray(parsed.followUps) ? parsed.followUps : base.followUps,
      notificationSetting: parsed.notificationSetting ?? base.notificationSetting,
      notifications: Array.isArray(parsed.notifications) ? parsed.notifications : base.notifications,
      tradeReviewsBySymbol: parsed.tradeReviewsBySymbol ?? base.tradeReviewsBySymbol,
      seq: {
        watchlist: safeNumber(seq.watchlist, 1),
        position: safeNumber(seq.position, 1),
        followUp: safeNumber(seq.followUp, 1),
        notification: safeNumber(seq.notification, 1),
        tradeReview: safeNumber(seq.tradeReview, 1),
      },
    };
  } catch {
    return emptyStore();
  }
}

function loadStore(): GuestDataStore {
  return parseStore(localStorage.getItem(GUEST_DATA_KEY));
}

function saveStore(store: GuestDataStore): void {
  localStorage.setItem(GUEST_DATA_KEY, JSON.stringify(store));
}

function isFollowUpDue(status: FollowUpStatus, nextReviewDate?: string | null): boolean {
  if (!nextReviewDate || status === "closed") {
    return false;
  }
  return nextReviewDate <= todayText();
}

function buildPositionAnalysis(positions: PositionSnapshot[]): PositionAnalysisResponse {
  const totalPositions = positions.length;
  const totalCost = positions.reduce((sum, row) => sum + row.cost_value, 0);
  const totalMarketValue = positions.reduce((sum, row) => sum + row.market_value, 0);
  const totalPnl = positions.reduce((sum, row) => sum + row.pnl, 0);
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
  const winCount = positions.filter((row) => row.pnl > 0).length;
  const lossCount = positions.filter((row) => row.pnl < 0).length;
  const sortedByMarketValue = [...positions].sort((left, right) => right.market_value - left.market_value);
  const top3Value = sortedByMarketValue.slice(0, 3).reduce((sum, row) => sum + row.market_value, 0);
  const concentrationTop3Pct = totalMarketValue > 0 ? (top3Value / totalMarketValue) * 100 : 0;

  const marketDistribution: Record<string, number> = {};
  const industryDistribution: Record<string, number> = {};

  for (const row of positions) {
    marketDistribution[row.market] = safeNumber(marketDistribution[row.market]) + row.market_value;
    industryDistribution[row.industry] = safeNumber(industryDistribution[row.industry]) + row.market_value;
  }

  const riskNotes: string[] = [];
  if (totalPositions === 0) {
    riskNotes.push("当前暂无持仓，建议先建立观察池与试验仓位。");
  }
  if (concentrationTop3Pct >= 70) {
    riskNotes.push("前 3 大持仓集中度较高，建议评估单一风险暴露。");
  }
  if (lossCount > winCount && totalPositions > 0) {
    riskNotes.push("亏损持仓数量高于盈利持仓，建议复盘止损与仓位控制。");
  }
  if (riskNotes.length === 0) {
    riskNotes.push("当前组合风险可控，继续按计划执行跟踪。");
  }

  return {
    total_positions: totalPositions,
    total_cost: Number(totalCost.toFixed(2)),
    total_market_value: Number(totalMarketValue.toFixed(2)),
    total_pnl: Number(totalPnl.toFixed(2)),
    total_pnl_pct: Number(totalPnlPct.toFixed(2)),
    win_count: winCount,
    loss_count: lossCount,
    concentration_top3_pct: Number(concentrationTop3Pct.toFixed(2)),
    market_distribution: marketDistribution,
    industry_distribution: industryDistribution,
    risk_notes: riskNotes,
  };
}

function refreshPositionDerivedFields(store: GuestDataStore): void {
  const followUpsByPosition = new Map<number, PositionFollowUpItem[]>();
  for (const followUp of store.followUps) {
    const existing = followUpsByPosition.get(followUp.position_id) ?? [];
    existing.push(followUp);
    followUpsByPosition.set(followUp.position_id, existing);
  }

  const totalMarketValue = store.positions.reduce((sum, row) => sum + row.market_value, 0);

  for (const position of store.positions) {
    const related = sortByDateDesc(followUpsByPosition.get(position.id) ?? [], (row) => `${row.follow_date}_${row.updated_at}`);
    const latest = related[0];
    position.latest_follow_up_status = latest?.status ?? null;
    position.latest_follow_up_date = latest?.follow_date ?? null;
    position.weight = totalMarketValue > 0 ? Number(((position.market_value / totalMarketValue) * 100).toFixed(2)) : 0;
  }
}

export function getGuestDataSummary(): GuestDataSummary {
  const store = loadStore();
  const tradeReviewCount = Object.values(store.tradeReviewsBySymbol).reduce((sum, rows) => sum + rows.length, 0);

  return {
    watchlistCount: store.watchlist.length,
    positionCount: store.positions.length,
    followUpCount: store.followUps.length,
    tradeReviewCount,
    notificationCount: store.notifications.length,
  };
}

export function clearGuestData(): void {
  localStorage.removeItem(GUEST_DATA_KEY);
}

export function getGuestMigrationSnapshot(): GuestMigrationSnapshot | null {
  const store = loadStore();
  const summary = getGuestDataSummary();
  const hasAnyData =
    summary.watchlistCount > 0 ||
    summary.positionCount > 0 ||
    summary.followUpCount > 0 ||
    summary.tradeReviewCount > 0 ||
    summary.notificationCount > 0;

  if (!hasAnyData) {
    return null;
  }

  return {
    watchlist: deepClone(store.watchlist),
    positions: deepClone(store.positions),
    followUps: deepClone(store.followUps),
    tradeReviewsBySymbol: deepClone(store.tradeReviewsBySymbol),
    notificationSetting: deepClone(store.notificationSetting),
  };
}

export function getGuestWorkspaceSnapshot(): GuestWorkspaceSnapshot {
  const store = loadStore();
  refreshPositionDerivedFields(store);
  saveStore(store);

  const groups = Array.from(new Set(store.watchlist.map((row) => row.group_name))).sort();
  const followUps = sortByDateDesc(store.followUps, (row) => `${row.follow_date}_${row.updated_at}`);
  const dueCount = followUps.filter((row) => row.is_due).length;

  return {
    watchlist: {
      total: store.watchlist.length,
      groups,
      items: sortByDateDesc(store.watchlist, (row) => row.updated_at),
    },
    positions: {
      total: store.positions.length,
      items: sortByDateDesc(store.positions, (row) => row.updated_at),
    },
    analysis: buildPositionAnalysis(store.positions),
    followUps: {
      total: followUps.length,
      due_count: dueCount,
      items: followUps,
    },
  };
}

export function deleteGuestWatchlistItem(itemId: number): boolean {
  const store = loadStore();
  const beforeCount = store.watchlist.length;
  store.watchlist = store.watchlist.filter((row) => row.id !== itemId);
  if (store.watchlist.length === beforeCount) {
    return false;
  }
  saveStore(store);
  return true;
}

export async function createGuestPosition(payload: PositionCreateRequest): Promise<PositionSnapshot> {
  const symbol = normalizeSymbol(payload.symbol);
  if (!symbol) {
    throw new Error("股票代码不能为空");
  }
  if (payload.quantity <= 0 || payload.cost_price <= 0) {
    throw new Error("持仓数量与成本价必须大于 0");
  }

  const store = loadStore();
  if (store.positions.some((row) => row.symbol === symbol)) {
    throw new Error("该股票已在持仓中");
  }

  let name = symbol;
  let market = "A股";
  let industry = "未分类";
  let currentPrice = payload.cost_price;

  try {
    const detail = await getStockDetail(symbol);
    name = detail.name;
    market = detail.market;
    industry = detail.sector;
    currentPrice = detail.price;
  } catch {
    // 保持回退值
  }

  const now = nowIso();
  const quantity = Number(payload.quantity);
  const costPrice = Number(payload.cost_price);
  const marketPrice = Number(currentPrice);
  const costValue = quantity * costPrice;
  const marketValue = quantity * marketPrice;
  const pnl = marketValue - costValue;
  const pnlPct = costValue > 0 ? (pnl / costValue) * 100 : 0;

  const item: PositionSnapshot = {
    id: store.seq.position++,
    symbol,
    name,
    market,
    industry,
    quantity,
    cost_price: costPrice,
    current_price: marketPrice,
    cost_value: Number(costValue.toFixed(2)),
    market_value: Number(marketValue.toFixed(2)),
    pnl: Number(pnl.toFixed(2)),
    pnl_pct: Number(pnlPct.toFixed(2)),
    weight: 0,
    stop_loss_price: payload.stop_loss_price ?? null,
    take_profit_price: payload.take_profit_price ?? null,
    status: payload.status ?? "holding",
    thesis: payload.thesis ?? null,
    latest_follow_up_status: null,
    latest_follow_up_date: null,
    created_at: now,
    updated_at: now,
  };

  store.positions.unshift(item);
  refreshPositionDerivedFields(store);
  saveStore(store);
  return item;
}

export function updateGuestPosition(positionId: number, payload: PositionUpdateRequest): PositionSnapshot {
  const store = loadStore();
  const row = store.positions.find((item) => item.id === positionId);
  if (!row) {
    throw new Error("持仓不存在");
  }

  if (payload.quantity !== undefined && payload.quantity <= 0) {
    throw new Error("持仓数量必须大于 0");
  }
  if (payload.cost_price !== undefined && payload.cost_price <= 0) {
    throw new Error("成本价必须大于 0");
  }

  row.quantity = payload.quantity ?? row.quantity;
  row.cost_price = payload.cost_price ?? row.cost_price;
  row.stop_loss_price = payload.stop_loss_price ?? row.stop_loss_price;
  row.take_profit_price = payload.take_profit_price ?? row.take_profit_price;
  row.status = payload.status ?? row.status;
  row.thesis = payload.thesis ?? row.thesis;
  row.updated_at = nowIso();

  row.cost_value = Number((row.quantity * row.cost_price).toFixed(2));
  row.market_value = Number((row.quantity * row.current_price).toFixed(2));
  row.pnl = Number((row.market_value - row.cost_value).toFixed(2));
  row.pnl_pct = row.cost_value > 0 ? Number(((row.pnl / row.cost_value) * 100).toFixed(2)) : 0;

  refreshPositionDerivedFields(store);
  saveStore(store);
  return row;
}

export function deleteGuestPosition(positionId: number): boolean {
  const store = loadStore();
  const beforeCount = store.positions.length;
  store.positions = store.positions.filter((row) => row.id !== positionId);
  if (store.positions.length === beforeCount) {
    return false;
  }

  store.followUps = store.followUps.filter((row) => row.position_id !== positionId);
  refreshPositionDerivedFields(store);
  saveStore(store);
  return true;
}

export function createGuestFollowUp(payload: PositionFollowUpCreateRequest): PositionFollowUpItem {
  const store = loadStore();
  const position = store.positions.find((row) => row.id === payload.position_id);
  if (!position) {
    throw new Error("对应持仓不存在");
  }
  if (!payload.summary.trim()) {
    throw new Error("跟进摘要不能为空");
  }

  const now = nowIso();
  const status = payload.status ?? "open";
  const nextFollowDate = payload.next_follow_date ?? null;
  const followDate = safeString(payload.follow_date).slice(0, 10);
  const item: PositionFollowUpItem = {
    id: store.seq.followUp++,
    position_id: payload.position_id,
    symbol: position.symbol,
    position_name: position.name,
    follow_date: followDate,
    stage: payload.stage ?? "holding",
    status,
    summary: payload.summary.trim(),
    action_items: (payload.action_items ?? []).map((value) => value.trim()).filter(Boolean),
    next_follow_date: nextFollowDate,
    confidence_score: payload.confidence_score ?? null,
    discipline_score: payload.discipline_score ?? null,
    is_due: isFollowUpDue(status, nextFollowDate),
    created_at: now,
    updated_at: now,
  };

  store.followUps.unshift(item);
  refreshPositionDerivedFields(store);
  saveStore(store);
  return item;
}

export function deleteGuestFollowUp(followUpId: number): boolean {
  const store = loadStore();
  const beforeCount = store.followUps.length;
  store.followUps = store.followUps.filter((row) => row.id !== followUpId);
  if (store.followUps.length === beforeCount) {
    return false;
  }

  refreshPositionDerivedFields(store);
  saveStore(store);
  return true;
}

export function listGuestNotifications(unreadOnly = false): NotificationListResponse {
  const store = loadStore();
  const rows = sortByDateDesc(store.notifications, (item) => item.created_at);
  const filtered = unreadOnly ? rows.filter((item) => !item.is_read) : rows;
  const unreadCount = rows.filter((item) => !item.is_read).length;

  return {
    total: filtered.length,
    unread_count: unreadCount,
    items: filtered,
  };
}

export function getGuestNotificationSettings(): NotificationSetting {
  const store = loadStore();
  return store.notificationSetting;
}

export function updateGuestNotificationSettings(payload: NotificationSettingUpdateRequest): NotificationSetting {
  const store = loadStore();
  store.notificationSetting = {
    enable_price_alert: payload.enable_price_alert ?? store.notificationSetting.enable_price_alert,
    enable_report_alert: payload.enable_report_alert ?? store.notificationSetting.enable_report_alert,
    enable_followup_due_alert: payload.enable_followup_due_alert ?? store.notificationSetting.enable_followup_due_alert,
    updated_at: nowIso(),
  };
  saveStore(store);
  return store.notificationSetting;
}

function notificationEventKeyFromPayload(payload: Record<string, unknown>): string {
  const value = payload.event_key;
  return typeof value === "string" ? value : "";
}

function toNotification(
  store: GuestDataStore,
  category: NotificationCategory,
  title: string,
  content: string,
  symbol: string | null,
  eventKey: string
): NotificationItem {
  return {
    id: store.seq.notification++,
    category,
    symbol,
    title,
    content,
    payload: { event_key: eventKey, source: "guest" },
    is_read: false,
    created_at: nowIso(),
    read_at: null,
  };
}

export function refreshGuestNotifications(): NotificationRefreshResponse {
  const store = loadStore();
  const createdByType: Record<NotificationCategory, number> = {
    price_alert: 0,
    report_alert: 0,
    followup_due: 0,
  };
  const existingKeys = new Set(store.notifications.map((item) => notificationEventKeyFromPayload(item.payload)));
  const today = todayText();

  if (store.notificationSetting.enable_followup_due_alert) {
    for (const row of store.followUps) {
      const due = isFollowUpDue(row.status, row.next_follow_date);
      if (!due) {
        continue;
      }

      const eventKey = `followup:${row.id}:${row.next_follow_date}`;
      if (existingKeys.has(eventKey)) {
        continue;
      }

      store.notifications.unshift(
        toNotification(
          store,
          "followup_due",
          `跟进到期：${row.position_name}`,
          `跟进任务已到期（计划日期 ${row.next_follow_date ?? today}），请尽快复盘。`,
          row.symbol,
          eventKey
        )
      );
      existingKeys.add(eventKey);
      createdByType.followup_due += 1;
    }

    for (const rows of Object.values(store.tradeReviewsBySymbol)) {
      for (const item of rows) {
        const due = isFollowUpDue(item.follow_up_status, item.next_review_date ?? null);
        if (!due) {
          continue;
        }

        const eventKey = `trade_review:${item.id}:${item.next_review_date}`;
        if (existingKeys.has(eventKey)) {
          continue;
        }

        store.notifications.unshift(
          toNotification(
            store,
            "followup_due",
            `复盘到期：${item.symbol}`,
            `交易复盘跟进已到期（计划日期 ${item.next_review_date ?? today}），请更新状态。`,
            item.symbol,
            eventKey
          )
        );
        existingKeys.add(eventKey);
        createdByType.followup_due += 1;
      }
    }
  }

  saveStore(store);
  const createdCount = createdByType.price_alert + createdByType.report_alert + createdByType.followup_due;

  return {
    created_count: createdCount,
    created_by_type: createdByType,
  };
}

export function markGuestNotificationRead(notificationId: number): NotificationReadResponse {
  const store = loadStore();
  const row = store.notifications.find((item) => item.id === notificationId);
  if (!row) {
    throw new Error("通知不存在");
  }
  row.is_read = true;
  row.read_at = nowIso();
  saveStore(store);
  return { item: row };
}

function computeFloatingPnl(
  action: TradeReviewAction,
  price: number | null | undefined,
  quantity: number | null | undefined,
  currentPrice: number | null | undefined
): { pnl: number | null; pnlPct: number | null } {
  if (price == null || quantity == null || currentPrice == null || price <= 0 || quantity <= 0) {
    return { pnl: null, pnlPct: null };
  }
  if (action === "observe") {
    return { pnl: null, pnlPct: null };
  }

  const direction = action === "buy" || action === "add" ? 1 : -1;
  const pnl = direction * (currentPrice - price) * quantity;
  const pnlPct = direction * ((currentPrice / price) - 1) * 100;
  return {
    pnl: Number(pnl.toFixed(2)),
    pnlPct: Number(pnlPct.toFixed(2)),
  };
}

function normalizeTradeReviewItems(items: string[] | undefined): string[] {
  if (!items?.length) {
    return [];
  }
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean)));
}

function buildTradeReviewSummary(items: StockTradeReviewItem[]): StockTradeReviewSummary {
  const confidenceScores = items.map((row) => row.confidence_score).filter((value): value is number => value != null);
  const disciplineScores = items.map((row) => row.discipline_score).filter((value): value is number => value != null);
  const pnlRows = items.map((row) => row.floating_pnl).filter((value): value is number => value != null);
  const pnlPctRows = items.map((row) => row.floating_pnl_pct).filter((value): value is number => value != null);

  const avgConfidence = confidenceScores.length > 0 ? confidenceScores.reduce((sum, value) => sum + value, 0) / confidenceScores.length : 0;
  const avgDiscipline = disciplineScores.length > 0 ? disciplineScores.reduce((sum, value) => sum + value, 0) / disciplineScores.length : 0;
  const netFloatingPnl = pnlRows.reduce((sum, value) => sum + value, 0);
  const netFloatingPnlPct = pnlPctRows.length > 0 ? pnlPctRows.reduce((sum, value) => sum + value, 0) / pnlPctRows.length : 0;

  return {
    total_reviews: items.length,
    open_follow_ups: items.filter((row) => row.follow_up_status === "open").length,
    in_progress_follow_ups: items.filter((row) => row.follow_up_status === "in_progress").length,
    closed_follow_ups: items.filter((row) => row.follow_up_status === "closed").length,
    due_follow_ups: items.filter((row) => row.is_follow_up_due).length,
    avg_confidence_score: Number(avgConfidence.toFixed(1)),
    avg_discipline_score: Number(avgDiscipline.toFixed(1)),
    net_floating_pnl: Number(netFloatingPnl.toFixed(2)),
    net_floating_pnl_pct: Number(netFloatingPnlPct.toFixed(2)),
  };
}

function sortedTradeReviews(rows: StockTradeReviewItem[]): StockTradeReviewItem[] {
  return [...rows].sort((left, right) => {
    const dateCompare = right.trade_date.localeCompare(left.trade_date);
    if (dateCompare !== 0) {
      return dateCompare;
    }
    return right.updated_at.localeCompare(left.updated_at);
  });
}

function withDerivedTradeReview(row: StockTradeReviewItem, currentPrice: number | null | undefined): StockTradeReviewItem {
  const { pnl, pnlPct } = computeFloatingPnl(row.action, row.price, row.quantity, currentPrice);
  return {
    ...row,
    floating_pnl: pnl,
    floating_pnl_pct: pnlPct,
    is_follow_up_due: isFollowUpDue(row.follow_up_status, row.next_review_date ?? null),
  };
}

export function getGuestTradeReviews(symbol: string, currentPrice?: number | null): StockTradeReviewResponse {
  const store = loadStore();
  const normalizedSymbol = normalizeSymbol(symbol);
  const sourceRows = store.tradeReviewsBySymbol[normalizedSymbol] ?? [];
  const rows = sortedTradeReviews(sourceRows).map((row) => withDerivedTradeReview(row, currentPrice));

  return {
    symbol: normalizedSymbol,
    current_price: currentPrice ?? null,
    items: rows,
    summary: buildTradeReviewSummary(rows),
  };
}

export function createGuestTradeReview(
  symbol: string,
  payload: StockTradeReviewCreateRequest,
  currentPrice?: number | null
): StockTradeReviewItem {
  const normalizedSymbol = normalizeSymbol(symbol);
  if (!payload.thesis.trim()) {
    throw new Error("交易逻辑不能为空");
  }
  if (payload.action !== "observe" && (!payload.price || !payload.quantity)) {
    throw new Error("买入/卖出/加减仓记录请填写成交价和数量");
  }

  const store = loadStore();
  const now = nowIso();
  const rows = store.tradeReviewsBySymbol[normalizedSymbol] ?? [];

  const item: StockTradeReviewItem = {
    id: store.seq.tradeReview++,
    symbol: normalizedSymbol,
    owner_user_id: null,
    owner_username: "游客",
    trade_date: safeString(payload.trade_date).slice(0, 10),
    action: payload.action,
    price: payload.price ?? null,
    quantity: payload.quantity ?? null,
    thesis: payload.thesis.trim(),
    execution_notes: payload.execution_notes?.trim() || null,
    outcome_review: payload.outcome_review?.trim() || null,
    lessons_learned: payload.lessons_learned?.trim() || null,
    follow_up_items: normalizeTradeReviewItems(payload.follow_up_items),
    follow_up_status: payload.follow_up_status ?? "open",
    next_review_date: payload.next_review_date ?? null,
    confidence_score: payload.confidence_score ?? null,
    discipline_score: payload.discipline_score ?? null,
    created_at: now,
    updated_at: now,
    floating_pnl: null,
    floating_pnl_pct: null,
    is_follow_up_due: false,
  };

  const itemWithDerived = withDerivedTradeReview(item, currentPrice);
  rows.unshift(itemWithDerived);
  store.tradeReviewsBySymbol[normalizedSymbol] = sortedTradeReviews(rows);
  saveStore(store);
  return itemWithDerived;
}

export function updateGuestTradeReview(
  symbol: string,
  reviewId: number,
  payload: StockTradeReviewUpdateRequest,
  currentPrice?: number | null
): StockTradeReviewItem {
  const normalizedSymbol = normalizeSymbol(symbol);
  const store = loadStore();
  const rows = store.tradeReviewsBySymbol[normalizedSymbol] ?? [];
  const row = rows.find((item) => item.id === reviewId);
  if (!row) {
    throw new Error("复盘记录不存在");
  }

  const nextAction = payload.action ?? row.action;
  const nextPrice = payload.price ?? row.price ?? null;
  const nextQuantity = payload.quantity ?? row.quantity ?? null;
  const nextThesis = payload.thesis ?? row.thesis;

  if (!nextThesis.trim()) {
    throw new Error("交易逻辑不能为空");
  }
  if (nextAction !== "observe" && (!nextPrice || !nextQuantity)) {
    throw new Error("买入/卖出/加减仓记录请填写成交价和数量");
  }

  row.trade_date = payload.trade_date ? payload.trade_date.slice(0, 10) : row.trade_date;
  row.action = nextAction;
  row.price = nextPrice;
  row.quantity = nextQuantity;
  row.thesis = nextThesis.trim();
  row.execution_notes = payload.execution_notes !== undefined ? payload.execution_notes?.trim() || null : row.execution_notes;
  row.outcome_review = payload.outcome_review !== undefined ? payload.outcome_review?.trim() || null : row.outcome_review;
  row.lessons_learned = payload.lessons_learned !== undefined ? payload.lessons_learned?.trim() || null : row.lessons_learned;
  row.follow_up_items = payload.follow_up_items !== undefined ? normalizeTradeReviewItems(payload.follow_up_items) : row.follow_up_items;
  row.follow_up_status = payload.follow_up_status ?? row.follow_up_status;
  row.next_review_date = payload.next_review_date !== undefined ? payload.next_review_date ?? null : row.next_review_date;
  row.confidence_score = payload.confidence_score !== undefined ? payload.confidence_score ?? null : row.confidence_score;
  row.discipline_score = payload.discipline_score !== undefined ? payload.discipline_score ?? null : row.discipline_score;
  row.updated_at = nowIso();

  const updatedRow = withDerivedTradeReview(row, currentPrice);
  store.tradeReviewsBySymbol[normalizedSymbol] = sortedTradeReviews(rows);
  saveStore(store);
  return updatedRow;
}
