import { useEffect, useMemo, useRef, useState } from "react";
import { Empty, Typography } from "antd";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { KLinePoint } from "../types/stock";

const { Text } = Typography;

interface StockKLineChartProps {
  points: KLinePoint[];
  height?: number;
}

interface HoverState {
  point: KLinePoint;
  index: number;
  x: number;
  y: number;
}

const DEFAULT_HEIGHT = 420;
const UP_COLOR = "#cf1322";
const DOWN_COLOR = "#389e0d";
const MA5_COLOR = "#1677ff";
const MA10_COLOR = "#faad14";
const MA20_COLOR = "#722ed1";

function toChartTime(dateText: string): UTCTimestamp {
  const normalized = dateText.includes(" ")
    ? `${dateText.replace(" ", "T")}:00+08:00`
    : `${dateText}T00:00:00+08:00`;
  return Math.floor(new Date(normalized).getTime() / 1000) as UTCTimestamp;
}

function formatTurnover(value: number): string {
  const amountYi = (Number.isFinite(value) ? value : 0) / 100000000;
  return `${amountYi.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 亿`;
}

function formatTooltipTime(value: string): string {
  return value.includes(" ") ? value : `${value} 00:00`;
}

function buildMovingAverage(points: KLinePoint[], period: number): LineData<Time>[] {
  const results: LineData<Time>[] = [];
  for (let index = 0; index < points.length; index += 1) {
    const slice = points.slice(Math.max(0, index - period + 1), index + 1);
    const avg = slice.reduce((sum, item) => sum + item.close, 0) / slice.length;
    results.push({
      time: toChartTime(points[index].date),
      value: Number(avg.toFixed(4)),
    });
  }
  return results;
}

export default function StockKLineChart({ points, height = DEFAULT_HEIGHT }: StockKLineChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ma10SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [hover, setHover] = useState<HoverState | null>(null);

  const pointIndex = useMemo(() => {
    const mapping = new Map<number, { point: KLinePoint; index: number }>();
    points.forEach((item, index) => {
      mapping.set(toChartTime(item.date), { point: item, index });
    });
    return mapping;
  }, [points]);

  const candleData = useMemo<CandlestickData<Time>[]>(() => {
    return points.map((item) => ({
      time: toChartTime(item.date),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));
  }, [points]);

  const volumeData = useMemo<HistogramData<Time>[]>(() => {
    return points.map((item) => ({
      time: toChartTime(item.date),
      value: item.volume,
      color: item.close >= item.open ? "rgba(207, 19, 34, 0.35)" : "rgba(56, 158, 13, 0.35)",
    }));
  }, [points]);

  const ma5Data = useMemo(() => buildMovingAverage(points, 5), [points]);
  const ma10Data = useMemo(() => buildMovingAverage(points, 10), [points]);
  const ma20Data = useMemo(() => buildMovingAverage(points, 20), [points]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#4b5565",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#f1f5f9" },
        horzLines: { color: "#f1f5f9" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: "#e5e7eb",
        scaleMargins: {
          top: 0.08,
          bottom: 0.28,
        },
      },
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
      localization: {
        locale: "zh-CN",
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78,
        bottom: 0,
      },
    });

    const ma5Series = chart.addSeries(LineSeries, {
      color: MA5_COLOR,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma10Series = chart.addSeries(LineSeries, {
      color: MA10_COLOR,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ma20Series = chart.addSeries(LineSeries, {
      color: MA20_COLOR,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const handleCrosshairMove = (param: MouseEventParams<Time>) => {
      if (!param.point || !param.time) {
        setHover(null);
        return;
      }
      const timeValue = typeof param.time === "number" ? param.time : toChartTime(String(param.time));
      const sourcePoint = pointIndex.get(timeValue);
      if (!sourcePoint) {
        setHover(null);
        return;
      }
      setHover({
        point: sourcePoint.point,
        index: sourcePoint.index,
        x: param.point.x,
        y: param.point.y,
      });
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);

    chartRef.current = chart;
    candleSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;
    ma5SeriesRef.current = ma5Series;
    ma10SeriesRef.current = ma10Series;
    ma20SeriesRef.current = ma20Series;

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ma5SeriesRef.current = null;
      ma10SeriesRef.current = null;
      ma20SeriesRef.current = null;
      setHover(null);
    };
  }, [height, pointIndex]);

  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !ma5SeriesRef.current || !ma10SeriesRef.current || !ma20SeriesRef.current || !chartRef.current) {
      return;
    }

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    ma5SeriesRef.current.setData(ma5Data);
    ma10SeriesRef.current.setData(ma10Data);
    ma20SeriesRef.current.setData(ma20Data);
    chartRef.current.timeScale().fitContent();
  }, [candleData, volumeData, ma5Data, ma10Data, ma20Data]);

  if (!points.length) {
    return <Empty description="暂无 K 线数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const tooltipAlignRight = hover ? hover.x > 700 : false;
  const hoverPrevClose = hover && hover.index > 0 ? points[hover.index - 1].close : hover?.point.open;
  const hoverChange = hover ? hover.point.close - (hoverPrevClose ?? hover.point.open) : 0;
  const hoverChangePct = hover && hoverPrevClose ? (hoverChange / hoverPrevClose) * 100 : 0;

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <div ref={containerRef} style={{ width: "100%", height }} />
      <div style={{ marginTop: 8, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Text type="secondary">图表已支持缩放、拖拽、十字线、成交额柱和 MA5 / MA10 / MA20。</Text>
      </div>
      {hover ? (
        <div
          style={{
            position: "absolute",
            top: 12,
            right: tooltipAlignRight ? 12 : undefined,
            left: tooltipAlignRight ? undefined : 12,
            zIndex: 5,
            minWidth: 230,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid #e5e7eb",
            background: "rgba(255,255,255,0.96)",
            boxShadow: "0 10px 26px rgba(15, 23, 42, 0.10)",
            pointerEvents: "none",
            userSelect: "none",
          }}
        >
          <div style={{ marginBottom: 6, fontWeight: 600 }}>{formatTooltipTime(hover.point.date)}</div>
          <div style={{ display: "grid", gridTemplateColumns: "auto auto", gap: "4px 12px", fontSize: 12 }}>
            <span>开</span><span>{hover.point.open.toFixed(2)}</span>
            <span>高</span><span>{hover.point.high.toFixed(2)}</span>
            <span>低</span><span>{hover.point.low.toFixed(2)}</span>
            <span>收</span><span>{hover.point.close.toFixed(2)}</span>
            <span>涨跌额</span><span style={{ color: hoverChange >= 0 ? UP_COLOR : DOWN_COLOR }}>{hoverChange >= 0 ? "+" : ""}{hoverChange.toFixed(2)}</span>
            <span>涨跌幅</span><span style={{ color: hoverChangePct >= 0 ? UP_COLOR : DOWN_COLOR }}>{hoverChangePct >= 0 ? "+" : ""}{hoverChangePct.toFixed(2)}%</span>
            <span>成交额</span><span>{formatTurnover(hover.point.volume)}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
