import { useEffect, useState } from "react";
import { Alert, App as AntdApp, Button, Card, Divider, InputNumber, Space, Switch, Table, Tag, Typography } from "antd";

import { getMainForceLatest, getMainForceSettings, scanMainForce, updateMainForceSettings } from "../api/stocks";
import type { MainForceCandidate, MainForceSettingResponse, MainForceSignalLevel, MainForceStage } from "../types/stock";

const { Title, Paragraph, Text } = Typography;

const stageColorMap: Record<MainForceStage, string> = {
  accumulation: "green",
  pullback: "gold",
  markup: "blue",
  distribution: "red",
  neutral: "default",
};

const signalColorMap: Record<MainForceSignalLevel, string> = {
  high: "green",
  medium: "gold",
  low: "default",
};

function formatRatio(value: number, decimals = 2) {
  return Number.isFinite(value) ? value.toFixed(decimals) : "-";
}

function MainForcePage() {
  const { message } = AntdApp.useApp();
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<MainForceCandidate[]>([]);
  const [totalScanned, setTotalScanned] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<MainForceSettingResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [configDraft, setConfigDraft] = useState<Record<string, number | boolean>>({});

  const loadSettings = async () => {
    try {
      const data = await getMainForceSettings();
      setSettings(data);
      setConfigDraft({
        main_force_scan_limit: Number(data.effective.main_force_scan_limit ?? 200),
        main_force_scan_top_n: Number(data.effective.main_force_scan_top_n ?? 30),
        main_force_scan_with_llm: Boolean(data.effective.main_force_scan_with_llm ?? true),
        main_force_scan_llm_top_n: Number(data.effective.main_force_scan_llm_top_n ?? 10),
        main_force_scan_with_web: Boolean(data.effective.main_force_scan_with_web ?? true),
        main_force_scan_sentiment_top_n: Number(data.effective.main_force_scan_sentiment_top_n ?? 30),
        main_force_accumulation_score_min: Number(data.effective.main_force_accumulation_score_min ?? 65),
        main_force_signal_high_score_min: Number(data.effective.main_force_signal_high_score_min ?? 70),
        main_force_signal_medium_score_min: Number(data.effective.main_force_signal_medium_score_min ?? 62),
        main_force_sentiment_high: Number(data.effective.main_force_sentiment_high ?? 70),
        main_force_sentiment_low: Number(data.effective.main_force_sentiment_low ?? 35),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载设置失败";
      message.error(msg);
    }
  };

  const loadLatest = async () => {
    try {
      const latest = await getMainForceLatest();
      setRows(latest.candidates || []);
      setTotalScanned(latest.total_scanned || 0);
    } catch {
      setRows([]);
      setTotalScanned(0);
    }
  };

  useEffect(() => {
    void loadSettings();
    void loadLatest();
  }, []);

  const handleScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await scanMainForce({
        market: "A股",
        limit: Number(configDraft.main_force_scan_limit ?? 200),
        top_n: Number(configDraft.main_force_scan_top_n ?? 30),
        with_llm: Boolean(configDraft.main_force_scan_with_llm ?? true),
        llm_top_n: Number(configDraft.main_force_scan_llm_top_n ?? 10),
        with_web: Boolean(configDraft.main_force_scan_with_web ?? true),
        sentiment_top_n: Number(configDraft.main_force_scan_sentiment_top_n ?? 30),
        use_settings: true,
        persist: true,
      });
      setRows(response.candidates || []);
      setTotalScanned(response.total_scanned || 0);
      message.success("扫描完成，结果已保存");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "未知错误";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!settings) {
      return;
    }
    setSaving(true);
    try {
      const payload = {
        enabled: settings.enabled,
        scan_interval_minutes: settings.scan_interval_minutes,
        overrides: {
          main_force_scan_limit: configDraft.main_force_scan_limit,
          main_force_scan_top_n: configDraft.main_force_scan_top_n,
          main_force_scan_with_llm: configDraft.main_force_scan_with_llm,
          main_force_scan_llm_top_n: configDraft.main_force_scan_llm_top_n,
          main_force_scan_with_web: configDraft.main_force_scan_with_web,
          main_force_scan_sentiment_top_n: configDraft.main_force_scan_sentiment_top_n,
          main_force_accumulation_score_min: configDraft.main_force_accumulation_score_min,
          main_force_signal_high_score_min: configDraft.main_force_signal_high_score_min,
          main_force_signal_medium_score_min: configDraft.main_force_signal_medium_score_min,
          main_force_sentiment_high: configDraft.main_force_sentiment_high,
          main_force_sentiment_low: configDraft.main_force_sentiment_low,
        },
      };
      const updated = await updateMainForceSettings(payload);
      setSettings(updated);
      message.success("设置已保存");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "保存失败";
      message.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Title level={3} style={{ marginBottom: 0 }}>
            主力操盘分析
          </Title>
          <Text type="secondary">分析范围：A股（含主板、创业板、科创板）。</Text>
          <Space wrap>
            <Button type="primary" onClick={handleScan} loading={loading}>
              开始扫描
            </Button>
            <Button onClick={loadLatest}>加载最近结果</Button>
            <Text type="secondary">当前样本：{totalScanned} 只</Text>
            {settings?.last_run_at ? <Text type="secondary">最近任务：{settings.last_run_at}</Text> : null}
          </Space>
        </Space>
      </Card>

      <Alert
        type="info"
        showIcon
        message="说明"
        description="以量价收敛、OBV 上行、波动收缩等结构性信号筛选候选池；同时引入新闻舆情评分进行修正。"
      />

      {error ? <Alert type="error" showIcon message="扫描失败" description={error} /> : null}

      <Card title="扫描配置">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Text>启用定时扫描</Text>
            <Switch
              checked={settings?.enabled ?? false}
              onChange={(value) => settings && setSettings({ ...settings, enabled: value })}
            />
            <Text>间隔(分钟)</Text>
            <InputNumber
              min={5}
              max={1440}
              value={settings?.scan_interval_minutes ?? 180}
              onChange={(value) => settings && setSettings({ ...settings, scan_interval_minutes: Number(value || 180) })}
            />
          </Space>

          <Divider style={{ margin: "8px 0" }} />

          <Space wrap>
            <Text>扫描样本</Text>
            <InputNumber
              min={50}
              max={2000}
              value={Number(configDraft.main_force_scan_limit ?? 200)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_limit: Number(value || 200) })}
            />
            <Text>输出数量</Text>
            <InputNumber
              min={5}
              max={200}
              value={Number(configDraft.main_force_scan_top_n ?? 30)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_top_n: Number(value || 30) })}
            />
            <Text>启用舆情</Text>
            <Switch
              checked={Boolean(configDraft.main_force_scan_with_web ?? true)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_with_web: value })}
            />
            <Text>舆情样本</Text>
            <InputNumber
              min={0}
              max={200}
              value={Number(configDraft.main_force_scan_sentiment_top_n ?? 30)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_sentiment_top_n: Number(value || 30) })}
            />
            <Text>启用LLM</Text>
            <Switch
              checked={Boolean(configDraft.main_force_scan_with_llm ?? true)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_with_llm: value })}
            />
            <Text>LLM 条数</Text>
            <InputNumber
              min={0}
              max={50}
              value={Number(configDraft.main_force_scan_llm_top_n ?? 10)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_scan_llm_top_n: Number(value || 10) })}
            />
          </Space>

          <Divider style={{ margin: "8px 0" }} />

          <Space wrap>
            <Text>吸筹最低分</Text>
            <InputNumber
              min={40}
              max={90}
              value={Number(configDraft.main_force_accumulation_score_min ?? 65)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_accumulation_score_min: Number(value || 65) })}
            />
            <Text>高信号分</Text>
            <InputNumber
              min={40}
              max={90}
              value={Number(configDraft.main_force_signal_high_score_min ?? 70)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_signal_high_score_min: Number(value || 70) })}
            />
            <Text>中信号分</Text>
            <InputNumber
              min={40}
              max={90}
              value={Number(configDraft.main_force_signal_medium_score_min ?? 62)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_signal_medium_score_min: Number(value || 62) })}
            />
            <Text>舆情偏多</Text>
            <InputNumber
              min={50}
              max={100}
              value={Number(configDraft.main_force_sentiment_high ?? 70)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_sentiment_high: Number(value || 70) })}
            />
            <Text>舆情偏空</Text>
            <InputNumber
              min={0}
              max={50}
              value={Number(configDraft.main_force_sentiment_low ?? 35)}
              onChange={(value) => setConfigDraft({ ...configDraft, main_force_sentiment_low: Number(value || 35) })}
            />
            <Button type="primary" onClick={handleSave} loading={saving}>
              保存设置
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="候选池（评分越高越接近吸筹阶段）">
        <Table<MainForceCandidate>
          rowKey={(record) => record.symbol}
          dataSource={rows}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: "标的",
              dataIndex: "symbol",
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <Text strong>
                    {record.name} ({record.symbol})
                  </Text>
                  <Text type="secondary">{record.market}</Text>
                </Space>
              ),
            },
            {
              title: "评分",
              dataIndex: "score",
              width: 90,
            },
            {
              title: "阶段",
              dataIndex: "stage",
              width: 120,
              render: (value: MainForceStage) => <Tag color={stageColorMap[value]}>{value}</Tag>,
            },
            {
              title: "信号层级",
              dataIndex: "signal_level",
              width: 110,
              render: (value: MainForceSignalLevel) => <Tag color={signalColorMap[value]}>{value}</Tag>,
            },
            {
              title: "舆情",
              dataIndex: "sentiment_score",
              width: 160,
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <Text type="secondary">评分：{record.sentiment_score != null ? record.sentiment_score.toFixed(0) : "-"}</Text>
                  <Text type="secondary">来源：{record.sentiment_sources ?? 0}</Text>
                  <Text type="secondary" ellipsis={{ tooltip: record.sentiment_summary || "" }}>
                    {record.sentiment_summary || "-"}
                  </Text>
                </Space>
              ),
            },
            {
              title: "指标",
              dataIndex: "metrics",
              render: (metrics: MainForceCandidate["metrics"]) => (
                <Space direction="vertical" size={0}>
                  <Text type="secondary">区间收敛：{formatRatio(metrics.range_squeeze)}</Text>
                  <Text type="secondary">波动收缩：{formatRatio(metrics.vol_squeeze)}</Text>
                  <Text type="secondary">OBV 斜率：{formatRatio(metrics.obv_slope_20, 4)}</Text>
                  <Text type="secondary">多头占比：{formatRatio(metrics.up_volume_ratio_20)}</Text>
                </Space>
              ),
            },
            {
              title: "理由",
              dataIndex: "reason",
              render: (value: string) => <Text>{value}</Text>,
            },
            {
              title: "模型解读",
              dataIndex: "llm_summary",
              render: (value?: string | null) => (
                <Paragraph ellipsis={{ rows: 3, expandable: true, symbol: "展开" }}>{value || "-"}</Paragraph>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}

export default MainForcePage;
