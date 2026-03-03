import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Card, Col, Row, Space, Typography } from "antd";

import { getDashboardSummary } from "../api/stocks";
import type { DashboardSummary } from "../types/stock";

const { Title, Paragraph, Text } = Typography;

function HomePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  useEffect(() => {
    let mounted = true;

    const run = async () => {
      setLoading(true);
      setError(null);

      try {
        const response = await getDashboardSummary();
        if (mounted) {
          setSummary(response);
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
      <Card className="hero-card">
        <Space direction="vertical" size={8}>
          <Title level={2} style={{ margin: 0 }}>
            让普通用户避险
          </Title>
          <Text type="secondary" style={{ fontSize: 18 }}>
            让优秀的企业找到支持
          </Text>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            这是一个面向散户的 C 端股票助手：先识别风险，再筛选机会，最后提供可执行交易计划与解释。
          </Paragraph>
        </Space>
      </Card>

      {error ? <Alert type="warning" showIcon message={`仪表板数据暂不可用：${error}`} /> : null}

      <Card title="快捷入口">
        <Space wrap>
          <Button type="primary" onClick={() => navigate("/dashboard")}>去仪表板</Button>
          <Button onClick={() => navigate("/stocks")}>去股票池</Button>
          <Button onClick={() => navigate("/stocks?analyzed=false")}>去未分析</Button>
          <Button onClick={() => navigate("/stocks?analyzed=true")}>去已分析</Button>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="今日风险摘要" loading={loading}>
            <Text type="secondary">
              风险预警数量：{summary?.risk_alert_count ?? 0} / 股票池总数：{summary?.total_stocks ?? 0}
            </Text>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="热门分析" loading={loading}>
            <Text type="secondary">
              当前平均评分：{summary?.average_score ?? 0}，可在仪表板查看高分标的与风险分层。
            </Text>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="最近更新" loading={loading}>
            <Text type="secondary">已分析股票数：{summary?.analyzed_count ?? 0}，建议每个交易日复核模型输出。</Text>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

export default HomePage;
