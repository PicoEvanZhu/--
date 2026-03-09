import { useEffect, useMemo, useRef } from "react";
import { Alert, Typography } from "antd";
import type { MarketType } from "../types/stock";

const { Text, Link } = Typography;

interface TradingViewWidgetProps {
  symbol: string;
  exchange: string;
  market: MarketType;
  height?: number;
}

function normalizeUsExchange(exchange: string): string {
  const normalized = exchange.trim().toUpperCase();
  if (normalized === "NYSEMKT" || normalized === "NYSEARCA") {
    return "AMEX";
  }
  if (normalized === "US") {
    return "NASDAQ";
  }
  return normalized;
}

export function resolveTradingViewSymbol(symbol: string, exchange: string, market: MarketType): string | null {
  const [rawCode, rawSuffix] = symbol.split(".");
  const code = (rawCode || "").trim().toUpperCase();
  const suffix = (rawSuffix || "").trim().toUpperCase();
  const normalizedExchange = exchange.trim().toUpperCase();

  if (!code) {
    return null;
  }

  if (suffix === "SH" || normalizedExchange === "SSE") {
    return `SSE:${code}`;
  }
  if (suffix === "SZ" || normalizedExchange === "SZSE") {
    return `SZSE:${code}`;
  }
  if (suffix === "HK" || normalizedExchange === "HKEX" || market === "港股") {
    const hkCode = String(Number.parseInt(code, 10));
    return hkCode && hkCode !== "NaN" ? `HKEX:${hkCode}` : `HKEX:${code}`;
  }
  if (suffix === "US" || market === "美股") {
    const usExchange = normalizeUsExchange(normalizedExchange);
    if (["NASDAQ", "NYSE", "AMEX", "BATS", "IEX"].includes(usExchange)) {
      return `${usExchange}:${code}`;
    }
    return `NASDAQ:${code}`;
  }

  return null;
}

export default function TradingViewWidget({ symbol, exchange, market, height = 560 }: TradingViewWidgetProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const tradingViewSymbol = useMemo(
    () => resolveTradingViewSymbol(symbol, exchange, market),
    [symbol, exchange, market],
  );

  useEffect(() => {
    if (!hostRef.current || !tradingViewSymbol) {
      return;
    }

    const host = hostRef.current;
    host.innerHTML = "";

    const widgetContainer = document.createElement("div");
    widgetContainer.className = "tradingview-widget-container";
    widgetContainer.style.width = "100%";
    widgetContainer.style.height = `${height}px`;

    const widgetBody = document.createElement("div");
    widgetBody.className = "tradingview-widget-container__widget";
    widgetBody.style.width = "100%";
    widgetBody.style.height = `${height - 28}px`;

    const copyright = document.createElement("div");
    copyright.className = "tradingview-widget-copyright";
    copyright.style.marginTop = "8px";
    copyright.innerHTML =
      '<a href="https://www.tradingview.com/" rel="noreferrer noopener" target="_blank"><span class="blue-text">Charts by TradingView</span></a>';

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.innerHTML = JSON.stringify({
      width: "100%",
      height: height - 28,
      symbol: tradingViewSymbol,
      interval: "60",
      timezone: "Asia/Shanghai",
      theme: "light",
      style: "1",
      locale: "zh_CN",
      enable_publishing: false,
      allow_symbol_change: false,
      withdateranges: true,
      hide_side_toolbar: false,
      hide_top_toolbar: false,
      save_image: true,
      details: true,
      calendar: false,
      hotlist: false,
      studies: ["Volume@tv-basicstudies"],
      support_host: "https://www.tradingview.com",
    });

    widgetContainer.appendChild(widgetBody);
    widgetContainer.appendChild(copyright);
    widgetContainer.appendChild(script);
    host.appendChild(widgetContainer);

    return () => {
      host.innerHTML = "";
    };
  }, [height, tradingViewSymbol]);

  if (!tradingViewSymbol) {
    return (
      <Alert
        type="info"
        showIcon
        message="当前股票暂不支持直接切换到 TradingView 图表"
        description="该市场或交易所代码未完成映射，暂时无法直接加载 TradingView。"
      />
    );
  }

  return (
    <div>
      <div ref={hostRef} style={{ width: "100%", minHeight: height }} />
      <div
        style={{
          marginTop: 8,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <Text type="secondary">当前图表代码：{tradingViewSymbol}</Text>
        <Link href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tradingViewSymbol)}`} target="_blank" rel="noreferrer">
          在 TradingView 打开
        </Link>
      </div>
    </div>
  );
}
