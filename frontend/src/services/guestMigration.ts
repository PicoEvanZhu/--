import {
  createMyFollowUp,
  createMyPosition,
  createMyWatchlistItem,
  listMyPositions,
  listMyWatchlist,
  updateMyNotificationSettings,
} from "../api/account";
import { createStockTradeReview } from "../api/stocks";
import { clearGuestData, getGuestMigrationSnapshot } from "./guestData";

export interface GuestMigrationResult {
  hasData: boolean;
  importedWatchlist: number;
  importedPositions: number;
  importedFollowUps: number;
  importedTradeReviews: number;
  errors: string[];
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

export async function migrateGuestDataToCurrentUser(): Promise<GuestMigrationResult> {
  const snapshot = getGuestMigrationSnapshot();
  if (!snapshot) {
    return {
      hasData: false,
      importedWatchlist: 0,
      importedPositions: 0,
      importedFollowUps: 0,
      importedTradeReviews: 0,
      errors: [],
    };
  }

  let importedWatchlist = 0;
  let importedPositions = 0;
  let importedFollowUps = 0;
  let importedTradeReviews = 0;
  const errors: string[] = [];

  const positionIdMap = new Map<number, number>();

  try {
    const existingWatchlist = await listMyWatchlist();
    const existingWatchSymbols = new Set(existingWatchlist.items.map((item) => normalizeSymbol(item.symbol)));

    for (const item of snapshot.watchlist) {
      const symbol = normalizeSymbol(item.symbol);
      if (!symbol || existingWatchSymbols.has(symbol)) {
        continue;
      }

      try {
        await createMyWatchlistItem({
          symbol,
          group_name: item.group_name,
          tags: item.tags,
          note: item.note ?? undefined,
          alert_price_up: item.alert_price_up ?? undefined,
          alert_price_down: item.alert_price_down ?? undefined,
          target_position_pct: item.target_position_pct ?? undefined,
        });
        importedWatchlist += 1;
        existingWatchSymbols.add(symbol);
      } catch (error) {
        const err = error as Error;
        errors.push(`自选 ${symbol} 导入失败：${err.message}`);
      }
    }
  } catch (error) {
    const err = error as Error;
    errors.push(`加载现有自选失败：${err.message}`);
  }

  let existingPositionsBySymbol = new Map<string, number>();
  try {
    const existingPositions = await listMyPositions();
    existingPositionsBySymbol = new Map(existingPositions.items.map((item) => [normalizeSymbol(item.symbol), item.id]));
  } catch (error) {
    const err = error as Error;
    errors.push(`加载现有持仓失败：${err.message}`);
  }

  for (const row of snapshot.positions) {
    const symbol = normalizeSymbol(row.symbol);
    if (!symbol) {
      continue;
    }

    const existingId = existingPositionsBySymbol.get(symbol);
    if (existingId) {
      positionIdMap.set(row.id, existingId);
      continue;
    }

    try {
      const created = await createMyPosition({
        symbol,
        quantity: row.quantity,
        cost_price: row.cost_price,
        stop_loss_price: row.stop_loss_price ?? undefined,
        take_profit_price: row.take_profit_price ?? undefined,
        status: row.status,
        thesis: row.thesis ?? undefined,
      });
      importedPositions += 1;
      existingPositionsBySymbol.set(symbol, created.id);
      positionIdMap.set(row.id, created.id);
    } catch (error) {
      const err = error as Error;
      errors.push(`持仓 ${symbol} 导入失败：${err.message}`);
    }
  }

  for (const row of snapshot.followUps) {
    const mappedPositionId = positionIdMap.get(row.position_id);
    if (!mappedPositionId) {
      continue;
    }

    try {
      await createMyFollowUp({
        position_id: mappedPositionId,
        follow_date: row.follow_date,
        stage: row.stage,
        status: row.status,
        summary: row.summary,
        action_items: row.action_items,
        next_follow_date: row.next_follow_date ?? undefined,
        confidence_score: row.confidence_score ?? undefined,
        discipline_score: row.discipline_score ?? undefined,
      });
      importedFollowUps += 1;
    } catch (error) {
      const err = error as Error;
      errors.push(`跟进 ${row.symbol} 导入失败：${err.message}`);
    }
  }

  for (const [symbol, rows] of Object.entries(snapshot.tradeReviewsBySymbol)) {
    for (const row of rows) {
      try {
        await createStockTradeReview(symbol, {
          trade_date: row.trade_date,
          action: row.action,
          price: row.price ?? undefined,
          quantity: row.quantity ?? undefined,
          thesis: row.thesis,
          execution_notes: row.execution_notes ?? undefined,
          outcome_review: row.outcome_review ?? undefined,
          lessons_learned: row.lessons_learned ?? undefined,
          follow_up_items: row.follow_up_items,
          follow_up_status: row.follow_up_status,
          next_review_date: row.next_review_date ?? undefined,
          confidence_score: row.confidence_score ?? undefined,
          discipline_score: row.discipline_score ?? undefined,
        });
        importedTradeReviews += 1;
      } catch (error) {
        const err = error as Error;
        errors.push(`复盘 ${symbol} 导入失败：${err.message}`);
      }
    }
  }

  try {
    await updateMyNotificationSettings({
      enable_price_alert: snapshot.notificationSetting.enable_price_alert,
      enable_report_alert: snapshot.notificationSetting.enable_report_alert,
      enable_followup_due_alert: snapshot.notificationSetting.enable_followup_due_alert,
    });
  } catch (error) {
    const err = error as Error;
    errors.push(`通知设置导入失败：${err.message}`);
  }

  if (errors.length === 0) {
    clearGuestData();
  }

  return {
    hasData: true,
    importedWatchlist,
    importedPositions,
    importedFollowUps,
    importedTradeReviews,
    errors,
  };
}
