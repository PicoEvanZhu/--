import type { StockItem } from "../types/stock";

export type CartStockItem = Pick<
  StockItem,
  "symbol" | "name" | "market" | "industry" | "price" | "change_pct" | "score" | "recommendation" | "updated_at"
>;

const STOCK_CART_KEY = "stock_assistant_stock_cart";
const STOCK_CART_EVENT = "stock-assistant-cart-changed";

function emitStockCartChanged() {
  window.dispatchEvent(new Event(STOCK_CART_EVENT));
}

export function getStockCartEventName(): string {
  return STOCK_CART_EVENT;
}

export function getStockCartItems(): CartStockItem[] {
  const raw = localStorage.getItem(STOCK_CART_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as CartStockItem[];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item) => Boolean(item?.symbol));
  } catch {
    return [];
  }
}

export function setStockCartItems(items: CartStockItem[]): void {
  localStorage.setItem(STOCK_CART_KEY, JSON.stringify(items));
  emitStockCartChanged();
}

export function clearStockCart(): void {
  setStockCartItems([]);
}

export function isInStockCart(symbol: string): boolean {
  const target = symbol.trim().toUpperCase();
  return getStockCartItems().some((item) => item.symbol.trim().toUpperCase() === target);
}

export function addStockToCart(item: CartStockItem): boolean {
  const target = item.symbol.trim().toUpperCase();
  const current = getStockCartItems();
  if (current.some((row) => row.symbol.trim().toUpperCase() === target)) {
    return false;
  }

  const next = [item, ...current];
  setStockCartItems(next);
  return true;
}

export function removeStockFromCart(symbol: string): void {
  const target = symbol.trim().toUpperCase();
  const next = getStockCartItems().filter((item) => item.symbol.trim().toUpperCase() !== target);
  setStockCartItems(next);
}
