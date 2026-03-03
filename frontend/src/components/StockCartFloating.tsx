import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShoppingCartOutlined } from "@ant-design/icons";
import { App as AntdApp, Badge, Button, Drawer, Empty, Grid, List, Space, Tag, Typography } from "antd";

import { createMyWatchlistItem, listMyWatchlist } from "../api/account";
import { getAuthEventName, isAuthenticated, isGuestMode } from "../utils/auth";
import {
  clearStockCart,
  getStockCartEventName,
  getStockCartItems,
  removeStockFromCart,
  setStockCartItems,
  type CartStockItem,
} from "../utils/stockCart";

const { Text } = Typography;

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function recommendationLabel(recommendation: CartStockItem["recommendation"]): string {
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

function recommendationColor(recommendation: CartStockItem["recommendation"]): string {
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

function StockCartFloating() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const screens = Grid.useBreakpoint();
  const [open, setOpen] = useState(false);
  const [cartItems, setCartItems] = useState<CartStockItem[]>(getStockCartItems());
  const [watchlistSymbols, setWatchlistSymbols] = useState<Set<string>>(new Set());
  const [addingSymbols, setAddingSymbols] = useState<Record<string, boolean>>({});

  const drawerWidth = screens.xl ? 620 : screens.lg ? 560 : screens.md ? 500 : "100%";
  const visibleCartItems = useMemo(
    () => cartItems.filter((item) => !watchlistSymbols.has(normalizeSymbol(item.symbol))),
    [cartItems, watchlistSymbols]
  );

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

  useEffect(() => {
    let cancelled = false;

    const loadWatchlistSymbols = async () => {
      if (!isAuthenticated()) {
        if (!cancelled) {
          setWatchlistSymbols(new Set());
        }
        return;
      }

      try {
        const response = await listMyWatchlist();
        if (cancelled) {
          return;
        }
        const symbols = new Set(response.items.map((item) => normalizeSymbol(item.symbol)));
        setWatchlistSymbols(symbols);
      } catch {
        // 保留当前状态，避免误清空
      }
    };

    void loadWatchlistSymbols();
    const authEvent = getAuthEventName();
    const handleAuthChanged = () => {
      void loadWatchlistSymbols();
    };
    window.addEventListener(authEvent, handleAuthChanged);
    window.addEventListener("storage", handleAuthChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(authEvent, handleAuthChanged);
      window.removeEventListener("storage", handleAuthChanged);
    };
  }, []);

  useEffect(() => {
    if (watchlistSymbols.size === 0) {
      return;
    }

    const current = getStockCartItems();
    const next = current.filter((item) => !watchlistSymbols.has(normalizeSymbol(item.symbol)));
    if (next.length !== current.length) {
      setStockCartItems(next);
      setCartItems(next);
    }
  }, [watchlistSymbols]);

  const addToMyStocks = async (stock: CartStockItem) => {
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
      removeStockFromCart(stock.symbol);
      setWatchlistSymbols((prev) => new Set([...prev, normalizeSymbol(stock.symbol)]));
      message.success(`已添加到“我的股票”并从购物车移除：${stock.name}`);
    } catch (error) {
      const err = error as Error;
      if (/已.*(在|存在)|exists?|duplicate/i.test(err.message)) {
        removeStockFromCart(stock.symbol);
        setWatchlistSymbols((prev) => new Set([...prev, normalizeSymbol(stock.symbol)]));
        message.info(`${stock.name} 已在“我的股票”，已从购物车移除`);
        return;
      }
      message.warning(`添加失败：${err.message}`);
    } finally {
      setAddingSymbols((prev) => ({ ...prev, [stock.symbol]: false }));
    }
  };

  return (
    <>
      <div className="stock-cart-floating-btn">
        <Badge count={visibleCartItems.length} size="small" overflowCount={99}>
          <Button type="primary" shape="circle" size="large" icon={<ShoppingCartOutlined />} onClick={() => setOpen(true)} />
        </Badge>
      </div>

      <Drawer
        title={`股票购物车（${visibleCartItems.length}）`}
        placement="right"
        width={drawerWidth}
        open={open}
        onClose={() => setOpen(false)}
        extra={
          <Button
            danger
            disabled={visibleCartItems.length === 0}
            onClick={() => {
              clearStockCart();
              message.success("购物车已清空");
            }}
          >
            清空
          </Button>
        }
      >
        {visibleCartItems.length === 0 ? (
          <Empty description="购物车为空，先在股票池点“添加到购物车”吧" />
        ) : (
          <List
            itemLayout="vertical"
            dataSource={visibleCartItems}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key={`cart-detail-${item.symbol}`}
                    type="link"
                    onClick={() => {
                      setOpen(false);
                      navigate(`/stocks/${encodeURIComponent(item.symbol)}`);
                    }}
                  >
                    详情
                  </Button>,
                  <Button
                    key={`cart-add-my-${item.symbol}`}
                    type="primary"
                    ghost
                    loading={Boolean(addingSymbols[item.symbol])}
                    onClick={() => void addToMyStocks(item)}
                  >
                    添加到我的股票
                  </Button>,
                  <Button
                    key={`cart-remove-${item.symbol}`}
                    danger
                    type="link"
                    onClick={() => {
                      removeStockFromCart(item.symbol);
                      message.success("已从购物车移除");
                    }}
                  >
                    移除
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={`${item.name}（${item.symbol}）`}
                  description={
                    <Space direction="vertical" size={2}>
                      <Text type="secondary">
                        {item.market} / {item.industry} / 价格 {item.price.toFixed(2)} / 涨跌幅{" "}
                        <Text style={{ color: item.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>
                          {item.change_pct >= 0 ? "+" : ""}
                          {item.change_pct.toFixed(2)}%
                        </Text>
                      </Text>
                      <Space>
                        <Tag color={recommendationColor(item.recommendation)}>{recommendationLabel(item.recommendation)}</Tag>
                        <Text type="secondary">评分 {item.score}</Text>
                      </Space>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>
    </>
  );
}

export default StockCartFloating;
