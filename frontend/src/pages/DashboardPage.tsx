import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Card, Col, List, Progress, Row, Space, Statistic, Tag, Typography } from "antd";

import { getDashboardSummary } from "../api/stocks";
import type { DashboardSummary, RecommendationType, StockItem } from "../types/stock";

const { Text, Paragraph } = Typography;

function recommendationLabel(type: RecommendationType): string {
  if (type === "buy") {
    return "关注买入";
  }
  if (type === "watch") {
    return "继续观察";
  }
  if (type === "hold_cautious") {
    return "谨慎持有";
  }
  return "暂时回避";
}

function recommendationColor(type: RecommendationType): string {
  if (type === "buy") {
    return "green";
  }
  if (type === "watch") {
    return "blue";
  }
  if (type === "hold_cautious") {
    return "gold";
  }
  return "red";
}

function scoreColor(score: number): string {
  if (score >= 75) {
    return "#389e0d";
  }
  if (score >= 55) {
    return "#1677ff";
  }
  if (score >= 45) {
    return "#d48806";
  }
  return "#cf1322";
}

function StockMiniRow({ item }: { item: StockItem }) {
  return (
    <Space direction="vertical" size={2} style={{ width: "100%" }}>
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <Link to={`/stocks/${encodeURIComponent(item.symbol)}`}>{item.name}</Link>
        <Tag color={recommendationColor(item.recommendation)}>{recommendationLabel(item.recommendation)}</Tag>
      </Space>
      <Text type="secondary">
        {item.symbol} / {item.market} / 评分 {item.score}
      </Text>
      <Progress percent={item.score} strokeColor={scoreColor(item.score)} showInfo={false} size="small" />
    </Space>
  );
}

function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DashboardSummary | null>(null);

  useEffect(() => {
    let mounted = true;

    const run = async () => {
      setLoading(true);
      setError(null);

      try {
        const response = await getDashboardSummary();
        if (mounted) {
          setData(response);
        }
      } catch (err) {
        if (mounted) {
          const message = err instanceof Error ? err.message : "加载失败";
          setError(message);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    void run();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card className="hero-card" loading={loading}>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          面向散户的风险优先决策面板：先看风险，再看机会，最后给出可执行计划。
        </Paragraph>
      </Card>

      {error ? <Alert type="error" message={`仪表板加载失败：${error}`} showIcon /> : null}

      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="股票池总数" value={data?.total_stocks ?? 0} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="已分析" value={data?.analyzed_count ?? 0} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="风险预警" value={data?.risk_alert_count ?? 0} valueStyle={{ color: "#cf1322" }} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="平均评分" value={data?.average_score ?? 0} precision={1} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="机会池（优先跟踪）" loading={loading}>
            <List
              dataSource={data?.best_opportunities ?? []}
              locale={{ emptyText: "暂无数据" }}
              renderItem={(item) => (
                <List.Item>
                  <StockMiniRow item={item} />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="高风险提醒" loading={loading}>
            <List
              dataSource={data?.high_risk_stocks ?? []}
              locale={{ emptyText: "暂无数据" }}
              renderItem={(item) => (
                <List.Item>
                  <StockMiniRow item={item} />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Card title="研究与执行提示" loading={loading}>
        <List
          dataSource={data?.latest_updates ?? []}
          locale={{ emptyText: "暂无更新" }}
          renderItem={(item) => (
            <List.Item>
              <Text>{item}</Text>
            </List.Item>
          )}
        />
      </Card>
    </Space>
  );
}

export default DashboardPage;
