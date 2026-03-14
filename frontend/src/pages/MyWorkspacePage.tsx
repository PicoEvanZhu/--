import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";

import {
  createMyFollowUp,
  createMyPosition,
  deleteMyFollowUp,
  deleteMyPosition,
  deleteMyWatchlistItem,
  getMyPositionAnalysis,
  listMyNotifications,
  refreshMyNotifications,
  listMyFollowUps,
  listMyPositions,
  listMyWatchlist,
  runMyWatchlistMonitor,
  runMyWatchlistMonitorAll,
  updateMyWatchlistItem,
} from "../api/account";
import {
  createGuestFollowUp,
  createGuestPosition,
  deleteGuestFollowUp,
  deleteGuestPosition,
  deleteGuestWatchlistItem,
  getGuestWorkspaceSnapshot,
  listGuestNotifications,
  refreshGuestNotifications,
  updateGuestWatchlistItem,
} from "../services/guestData";
import type {
  MonitorIntervalMinutes,
  NotificationItem,
  PositionAnalysisResponse,
  PositionFollowUpCreateRequest,
  PositionFollowUpItem,
  PositionSnapshot,
  WatchlistItem,
  WatchlistItemUpdateRequest,
} from "../types/account";
import { getAuthEventName, getSessionUser, hasSessionAccess, isGuestMode, startGuestSession } from "../utils/auth";

const { Text } = Typography;
const { TextArea } = Input;

interface PositionFormValues {
  symbol: string;
  quantity: number;
  cost_price: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  thesis?: string;
}

interface FollowUpFormValues {
  position_id: number;
  follow_date: string;
  summary: string;
  action_items_text?: string;
  next_follow_date?: string;
  stage: "pre_open" | "holding" | "rebalancing" | "exit_review";
  status: "open" | "in_progress" | "closed";
}

interface WatchlistMonitorFormValues {
  monitor_enabled: boolean;
  monitor_interval_minutes: MonitorIntervalMinutes;
  monitor_focus: string[];
  alert_price_up?: number;
  alert_price_down?: number;
  note?: string;
}

const WATCHLIST_MONITOR_INTERVAL_OPTIONS: Array<{ label: string; value: MonitorIntervalMinutes }> = [
  { label: "1分钟", value: 1 },
  { label: "5分钟", value: 5 },
  { label: "10分钟", value: 10 },
  { label: "15分钟", value: 15 },
  { label: "30分钟", value: 30 },
  { label: "60分钟", value: 60 },
];

const WATCHLIST_MONITOR_FOCUS_OPTIONS = [
  { label: "价格异动", value: "price_move" },
  { label: "接近预警价", value: "near_alert" },
  { label: "突破支撑/压力", value: "trend_breakout" },
  { label: "成交额放大", value: "turnover_spike" },
  { label: "板块轮动共振", value: "sector_rotation" },
];

const WATCHLIST_MONITOR_FOCUS_LABEL_MAP: Record<string, string> = {
  price_move: "价格异动",
  near_alert: "接近预警价",
  trend_breakout: "突破支撑/压力",
  turnover_spike: "成交额放大",
  sector_rotation: "板块轮动共振",
};

function monitorFocusLabel(value: string): string {
  return WATCHLIST_MONITOR_FOCUS_LABEL_MAP[value] ?? value;
}

function toSignedPercent(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function MyWorkspacePage() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [currentUser, setCurrentUser] = useState(getSessionUser());
  const [guestMode, setGuestMode] = useState(isGuestMode());
  const hasAccess = hasSessionAccess();

  const [positionForm] = Form.useForm<PositionFormValues>();
  const [followUpForm] = Form.useForm<FollowUpFormValues>();
  const [watchlistMonitorForm] = Form.useForm<WatchlistMonitorFormValues>();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [analysis, setAnalysis] = useState<PositionAnalysisResponse | null>(null);
  const [followUps, setFollowUps] = useState<PositionFollowUpItem[]>([]);
  const [monitorNotifications, setMonitorNotifications] = useState<NotificationItem[]>([]);

  const [positionSubmitting, setPositionSubmitting] = useState(false);
  const [followUpSubmitting, setFollowUpSubmitting] = useState(false);
  const [watchlistMonitorOpen, setWatchlistMonitorOpen] = useState(false);
  const [watchlistMonitorSubmitting, setWatchlistMonitorSubmitting] = useState(false);
  const [watchlistMonitorRunning, setWatchlistMonitorRunning] = useState(false);
  const [watchlistMonitorBatchSaving, setWatchlistMonitorBatchSaving] = useState(false);
  const [watchlistMonitorItem, setWatchlistMonitorItem] = useState<WatchlistItem | null>(null);
  const [monitorKeyword, setMonitorKeyword] = useState("");
  const [monitorSignalFilter, setMonitorSignalFilter] = useState<string | undefined>(undefined);
  const [monitorIntervalFilter, setMonitorIntervalFilter] = useState<MonitorIntervalMinutes | undefined>(undefined);
  const [watchlistKeyword, setWatchlistKeyword] = useState("");
  const [watchlistGroupFilter, setWatchlistGroupFilter] = useState<string | undefined>(undefined);

  useEffect(() => {
    const syncAuth = () => {
      setCurrentUser(getSessionUser());
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

  const loadAll = async () => {
    if (!hasAccess) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    if (guestMode) {
      try {
        const guestSnapshot = getGuestWorkspaceSnapshot();
        const guestNotifications = listGuestNotifications(false).items.filter((item) => item.category === "watch_monitor");
        setWatchlist(guestSnapshot.watchlist.items);
        setPositions(guestSnapshot.positions.items);
        setAnalysis(guestSnapshot.analysis);
        setFollowUps(guestSnapshot.followUps.items);
        setMonitorNotifications(guestNotifications);
      } catch (errorObject) {
        const err = errorObject as Error;
        setError(err.message);
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      const [watchlistResponse, positionsResponse, analysisResponse, followUpResponse, notificationResponse] = await Promise.all([
        listMyWatchlist(),
        listMyPositions(),
        getMyPositionAnalysis(),
        listMyFollowUps(),
        listMyNotifications(false),
      ]);
      setWatchlist(watchlistResponse.items);
      setPositions(positionsResponse.items);
      setAnalysis(analysisResponse);
      setFollowUps(followUpResponse.items);
      setMonitorNotifications(notificationResponse.items.filter((item) => item.category === "watch_monitor"));
    } catch (errorObject) {
      const err = errorObject as Error;
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!hasAccess) {
      return;
    }

    void loadAll();
    followUpForm.setFieldsValue({
      follow_date: new Date().toISOString().slice(0, 10),
      stage: "holding",
      status: "open",
    });
  }, [currentUser?.id, guestMode, hasAccess]);

  const handleCreatePosition = async (values: PositionFormValues) => {
    setPositionSubmitting(true);
    try {
      if (guestMode) {
        await createGuestPosition({
          symbol: values.symbol.trim(),
          quantity: values.quantity,
          cost_price: values.cost_price,
          stop_loss_price: values.stop_loss_price,
          take_profit_price: values.take_profit_price,
          thesis: values.thesis?.trim(),
        });
      } else {
        await createMyPosition({
          symbol: values.symbol.trim(),
          quantity: values.quantity,
          cost_price: values.cost_price,
          stop_loss_price: values.stop_loss_price,
          take_profit_price: values.take_profit_price,
          thesis: values.thesis?.trim(),
        });
      }
      message.success("持仓已记录");
      positionForm.resetFields();
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`添加持仓失败：${err.message}`);
    } finally {
      setPositionSubmitting(false);
    }
  };

  const handleCreateFollowUp = async (values: FollowUpFormValues) => {
    setFollowUpSubmitting(true);
    try {
      const payload: PositionFollowUpCreateRequest = {
        position_id: values.position_id,
        follow_date: values.follow_date,
        summary: values.summary.trim(),
        action_items: values.action_items_text
          ? values.action_items_text.split("\n").map((item) => item.trim()).filter(Boolean)
          : [],
        next_follow_date: values.next_follow_date,
        stage: values.stage,
        status: values.status,
      };

      if (guestMode) {
        createGuestFollowUp(payload);
      } else {
        await createMyFollowUp(payload);
      }
      message.success("跟进记录已保存");
      followUpForm.setFieldsValue({
        follow_date: new Date().toISOString().slice(0, 10),
        summary: "",
        action_items_text: "",
        next_follow_date: undefined,
        stage: "holding",
        status: "open",
      });
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`保存跟进失败：${err.message}`);
    } finally {
      setFollowUpSubmitting(false);
    }
  };

  const watchlistGroupOptions = useMemo(() => {
    const groups = Array.from(new Set(watchlist.map((item) => item.group_name).filter(Boolean)));
    return groups.map((group) => ({ label: group, value: group }));
  }, [watchlist]);

  const monitorEnabledWatchlist = useMemo(
    () => watchlist.filter((item) => item.monitor_enabled),
    [watchlist],
  );

  const recentMonitorNotifications = useMemo(
    () => monitorNotifications.slice(0, 12),
    [monitorNotifications],
  );

  const filteredMonitorWatchlist = useMemo(() => {
    const normalizedKeyword = monitorKeyword.trim().toUpperCase();
    return monitorEnabledWatchlist.filter((item) => {
      if (monitorSignalFilter && (item.monitor_last_signal_level ?? "low") !== monitorSignalFilter) {
        return false;
      }
      if (monitorIntervalFilter && (item.monitor_interval_minutes ?? 15) !== monitorIntervalFilter) {
        return false;
      }
      if (!normalizedKeyword) {
        return true;
      }
      const haystack = `${item.symbol} ${item.name} ${item.industry} ${item.group_name} ${item.monitor_last_summary ?? ""}`.toUpperCase();
      return haystack.includes(normalizedKeyword);
    });
  }, [monitorEnabledWatchlist, monitorIntervalFilter, monitorKeyword, monitorSignalFilter]);

  const monitorMediumSignalCount = useMemo(
    () => watchlist.filter((item) => item.monitor_enabled && item.monitor_last_signal_level === "medium").length,
    [watchlist],
  );

  const monitorHighSignalCount = useMemo(
    () => watchlist.filter((item) => item.monitor_enabled && item.monitor_last_signal_level === "high").length,
    [watchlist],
  );

  const monitorCheckedTodayCount = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return watchlist.filter((item) => item.monitor_last_checked_at?.slice(0, 10) === today).length;
  }, [watchlist]);

  const filteredWatchlist = useMemo(() => {
    const normalizedKeyword = watchlistKeyword.trim().toUpperCase();
    return watchlist.filter((item) => {
      if (watchlistGroupFilter && item.group_name !== watchlistGroupFilter) {
        return false;
      }

      if (!normalizedKeyword) {
        return true;
      }

      const haystack = `${item.symbol} ${item.name} ${item.industry} ${item.market} ${item.group_name}`.toUpperCase();
      return haystack.includes(normalizedKeyword);
    });
  }, [watchlist, watchlistKeyword, watchlistGroupFilter]);

  const openWatchlistDetail = (symbol: string) => {
    navigate(`/stocks/${encodeURIComponent(symbol)}?source=my`, {
      state: { from: "/my" },
    });
  };

  const openWatchlistMonitor = (item: WatchlistItem) => {
    setWatchlistMonitorItem(item);
    watchlistMonitorForm.setFieldsValue({
      monitor_enabled: item.monitor_enabled ?? false,
      monitor_interval_minutes: item.monitor_interval_minutes ?? 15,
      monitor_focus: item.monitor_focus && item.monitor_focus.length > 0 ? item.monitor_focus : ["price_move", "near_alert", "trend_breakout"],
      alert_price_up: item.alert_price_up ?? undefined,
      alert_price_down: item.alert_price_down ?? undefined,
      note: item.note ?? undefined,
    });
    setWatchlistMonitorOpen(true);
  };

  const handleSaveWatchlistMonitor = async (values: WatchlistMonitorFormValues) => {
    if (!watchlistMonitorItem) {
      return;
    }
    setWatchlistMonitorSubmitting(true);
    try {
      const payload = {
        monitor_enabled: values.monitor_enabled,
        monitor_interval_minutes: values.monitor_interval_minutes,
        monitor_focus: values.monitor_focus,
        alert_price_up: values.alert_price_up,
        alert_price_down: values.alert_price_down,
        note: values.note?.trim(),
      };
      if (guestMode) {
        const updated = updateGuestWatchlistItem(watchlistMonitorItem.id, payload);
        if (!updated) {
          throw new Error("自选项不存在");
        }
      } else {
        await updateMyWatchlistItem(watchlistMonitorItem.id, payload);
      }
      message.success("盯盘设置已保存");
      setWatchlistMonitorOpen(false);
      setWatchlistMonitorItem(null);
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`保存盯盘设置失败：${err.message}`);
    } finally {
      setWatchlistMonitorSubmitting(false);
    }
  };

  const handleRunWatchlistMonitor = async (targetItem?: WatchlistItem) => {
    const item = targetItem ?? watchlistMonitorItem;
    if (!item) {
      return;
    }
    if (guestMode) {
      message.info("游客模式当前仅支持保存盯盘设置，登录后可执行服务端盯盘检查。", 3);
      return;
    }
    setWatchlistMonitorRunning(true);
    try {
      const result = await runMyWatchlistMonitor(item.id);
      message.success(result.created_notification ? "已完成盯盘检查并生成提醒" : "已完成盯盘检查");
      await loadAll();
      setWatchlistMonitorItem((current) =>
        current && current.id === item.id
          ? {
              ...current,
              monitor_last_checked_at: result.checked_at,
              monitor_last_summary: result.summary,
              monitor_last_signal_level: result.signal_level,
            }
          : current,
      );
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`执行盯盘检查失败：${err.message}`);
    } finally {
      setWatchlistMonitorRunning(false);
    }
  };

  const positionColumns = useMemo(
    () => [
      {
        title: "股票",
        key: "symbol",
        render: (_: unknown, row: PositionSnapshot) => (
          <Space direction="vertical" size={1}>
            <Text strong>{row.name}</Text>
            <Text type="secondary">
              {row.symbol} / 权重 {row.weight.toFixed(2)}%
            </Text>
          </Space>
        ),
      },
      {
        title: "仓位",
        key: "quantity",
        width: 110,
        render: (_: unknown, row: PositionSnapshot) => row.quantity.toLocaleString("zh-CN", { maximumFractionDigits: 2 }),
      },
      {
        title: "成本/现价",
        key: "price",
        width: 150,
        render: (_: unknown, row: PositionSnapshot) => `${row.cost_price.toFixed(2)} / ${row.current_price.toFixed(2)}`,
      },
      {
        title: "市值",
        key: "market_value",
        width: 130,
        render: (_: unknown, row: PositionSnapshot) => row.market_value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }),
      },
      {
        title: "浮盈亏",
        key: "pnl",
        width: 180,
        render: (_: unknown, row: PositionSnapshot) => (
          <Text style={{ color: row.pnl >= 0 ? "#389e0d" : "#cf1322" }}>
            {row.pnl >= 0 ? "+" : ""}
            {row.pnl.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}（{toSignedPercent(row.pnl_pct)}）
          </Text>
        ),
      },
      {
        title: "跟进",
        key: "followup",
        width: 170,
        render: (_: unknown, row: PositionSnapshot) =>
          row.latest_follow_up_status ? (
            <Space direction="vertical" size={0}>
              <Tag>{row.latest_follow_up_status}</Tag>
              <Text type="secondary">{row.latest_follow_up_date}</Text>
            </Space>
          ) : (
            <Text type="secondary">暂无</Text>
          ),
      },
      {
        title: "操作",
        key: "actions",
        width: 100,
        render: (_: unknown, row: PositionSnapshot) => (
          <Button danger type="link" onClick={() => void handleDeletePosition(row.id)}>
            删除
          </Button>
        ),
      },
    ],
    []
  );

  const followUpColumns = useMemo(
    () => [
      { title: "日期", dataIndex: "follow_date", key: "follow_date", width: 110 },
      {
        title: "持仓",
        key: "position_name",
        render: (_: unknown, row: PositionFollowUpItem) => (
          <Space direction="vertical" size={1}>
            <Text strong>{row.position_name}</Text>
            <Text type="secondary">{row.symbol}</Text>
          </Space>
        ),
      },
      { title: "阶段", dataIndex: "stage", key: "stage", width: 120 },
      {
        title: "状态",
        key: "status",
        width: 140,
        render: (_: unknown, row: PositionFollowUpItem) => (
          <Space direction="vertical" size={0}>
            <Tag color={row.status === "closed" ? "green" : row.status === "in_progress" ? "blue" : "gold"}>{row.status}</Tag>
            {row.is_due ? <Text type="danger">已到复盘时间</Text> : null}
          </Space>
        ),
      },
      {
        title: "摘要",
        dataIndex: "summary",
        key: "summary",
        ellipsis: true,
      },
      {
        title: "操作",
        key: "actions",
        width: 100,
        render: (_: unknown, row: PositionFollowUpItem) => (
          <Button danger type="link" onClick={() => void handleDeleteFollowUp(row.id)}>
            删除
          </Button>
        ),
      },
    ],
    []
  );

  const applyMonitorTemplate = (template: "steady" | "short_term" | "dividend") => {
    const templateMap = {
      steady: {
        monitor_enabled: true,
        monitor_interval_minutes: 15 as MonitorIntervalMinutes,
        monitor_focus: ["price_move", "near_alert", "trend_breakout", "sector_rotation"],
      },
      short_term: {
        monitor_enabled: true,
        monitor_interval_minutes: 5 as MonitorIntervalMinutes,
        monitor_focus: ["price_move", "turnover_spike", "trend_breakout"],
      },
      dividend: {
        monitor_enabled: true,
        monitor_interval_minutes: 30 as MonitorIntervalMinutes,
        monitor_focus: ["near_alert", "sector_rotation"],
      },
    };
    watchlistMonitorForm.setFieldsValue(templateMap[template]);
  };

  const handleBatchMonitorUpdate = async (payload: WatchlistItemUpdateRequest) => {
    if (filteredMonitorWatchlist.length === 0) {
      message.info("当前筛选结果为空");
      return;
    }
    setWatchlistMonitorBatchSaving(true);
    try {
      if (guestMode) {
        for (const item of filteredMonitorWatchlist) {
          updateGuestWatchlistItem(item.id, payload);
        }
      } else {
        await Promise.all(filteredMonitorWatchlist.map((item) => updateMyWatchlistItem(item.id, payload)));
      }
      message.success(`已批量更新 ${filteredMonitorWatchlist.length} 只股票的盯盘设置`);
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`批量更新失败：${err.message}`);
    } finally {
      setWatchlistMonitorBatchSaving(false);
    }
  };


  const handleDeleteWatchlistItem = async (itemId: number) => {
    try {
      if (guestMode) {
        const deleted = deleteGuestWatchlistItem(itemId);
        if (!deleted) {
          throw new Error("自选项不存在");
        }
      } else {
        await deleteMyWatchlistItem(itemId);
      }
      message.success("自选已删除");
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`删除自选失败：${err.message}`);
    }
  };

  const handleDeletePosition = async (positionId: number) => {
    try {
      if (guestMode) {
        const deleted = deleteGuestPosition(positionId);
        if (!deleted) {
          throw new Error("持仓不存在");
        }
      } else {
        await deleteMyPosition(positionId);
      }
      message.success("持仓已删除");
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`删除持仓失败：${err.message}`);
    }
  };

  const handleDeleteFollowUp = async (followUpId: number) => {
    try {
      if (guestMode) {
        const deleted = deleteGuestFollowUp(followUpId);
        if (!deleted) {
          throw new Error("跟进记录不存在");
        }
      } else {
        await deleteMyFollowUp(followUpId);
      }
      message.success("跟进记录已删除");
      await loadAll();
    } catch (errorObject) {
      const err = errorObject as Error;
      message.error(`删除跟进失败：${err.message}`);
    }
  };

  if (!hasAccess || !currentUser) {
    return (
      <Card title="我的股票">
        <Space direction="vertical" size={12}>
          <Text type="secondary">登录或进入游客模式后可使用个人自选、个人持仓分析与持仓跟进功能。</Text>
          <Space>
            <Button type="primary" onClick={() => navigate("/auth")}>
              去登录 / 注册
            </Button>
            <Button
              onClick={() => {
                startGuestSession();
                navigate("/my");
              }}
            >
              游客模式
            </Button>
          </Space>
        </Space>
      </Card>
    );
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {guestMode ? (
        <Alert
          type="warning"
          showIcon
          message="当前为游客模式：操作仅保存在当前浏览器。新增自选需先注册，注册后会自动合并游客操作。"
        />
      ) : null}
      <Card className="hero-card">
        <Text type="secondary">
          {currentUser.display_name || currentUser.username}
          ，这里是你的个人投资工作台：自选、持仓、跟进与复盘全在这里闭环。
        </Text>
      </Card>

      {error ? <Alert type="error" showIcon message={`个人数据加载失败：${error}`} /> : null}

      <Tabs
        items={[
          {
            key: "watchlist",
            label: `个人自选 (${watchlist.length})`,
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Card title="自选筛选">
                  <Row gutter={12}>
                    <Col xs={24} md={12}>
                      <Input
                        allowClear
                        value={watchlistKeyword}
                        placeholder="按代码、名称、行业搜索"
                        onChange={(event) => setWatchlistKeyword(event.target.value)}
                      />
                    </Col>
                    <Col xs={24} md={8}>
                      <Select
                        allowClear
                        value={watchlistGroupFilter}
                        style={{ width: "100%" }}
                        options={watchlistGroupOptions}
                        placeholder="按分组筛选"
                        onChange={(value) => setWatchlistGroupFilter((value as string | undefined) ?? undefined)}
                      />
                    </Col>
                    <Col xs={24} md={4}>
                      <Button
                        style={{ width: "100%" }}
                        onClick={() => {
                          setWatchlistKeyword("");
                          setWatchlistGroupFilter(undefined);
                        }}
                      >
                        重置
                      </Button>
                    </Col>
                  </Row>
                </Card>

                <Card title={`自选列表（筛选后 ${filteredWatchlist.length}）`} loading={loading}>
                  <List
                    dataSource={filteredWatchlist}
                    locale={{ emptyText: "暂无自选股票" }}
                    pagination={{ pageSize: 10 }}
                    renderItem={(item) => (
                      <List.Item
                        style={{ cursor: "pointer" }}
                        onClick={() => openWatchlistDetail(item.symbol)}
                        actions={[
                          <Button
                            key={`watch-monitor-${item.id}`}
                            type="link"
                            onClick={(event) => {
                              event.stopPropagation();
                              openWatchlistMonitor(item);
                            }}
                          >
                            盯盘设置
                          </Button>,
                          <Button
                            key={`watch-detail-${item.id}`}
                            type="link"
                            onClick={(event) => {
                              event.stopPropagation();
                              openWatchlistDetail(item.symbol);
                            }}
                          >
                            查看详情
                          </Button>,
                          <Button
                            key={`watch-delete-${item.id}`}
                            danger
                            type="link"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleDeleteWatchlistItem(item.id);
                            }}
                          >
                            删除
                          </Button>,
                        ]}
                      >
                        <List.Item.Meta
                          title={`${item.name}（${item.symbol}）`}
                          description={
                            <Space direction="vertical" size={4}>
                              <Text type="secondary">
                                市场：{item.market} / 行业：{item.industry} / 分组：{item.group_name} / 现价：{item.current_price.toFixed(2)} / 涨跌幅：
                                <Text style={{ color: item.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>
                                  {toSignedPercent(item.change_pct)}
                                </Text>
                              </Text>
                              <Text type="secondary">更新时间：{new Date(item.updated_at).toLocaleString()}</Text>
                              <Space wrap>
                                <Tag color="blue">{item.group_name}</Tag>
                                <Tag color={item.change_pct >= 0 ? "green" : "red"}>{toSignedPercent(item.change_pct)}</Tag>
                                <Tag color={item.monitor_enabled ? "processing" : "default"}>
                                  {item.monitor_enabled ? `盯盘 ${item.monitor_interval_minutes ?? 15}m` : "未盯盘"}
                                </Tag>
                                {item.monitor_focus && item.monitor_focus.length > 0
                                  ? item.monitor_focus.slice(0, 3).map((focus) => (
                                      <Tag key={`${item.id}-${focus}`} bordered={false} color="purple">
                                        {monitorFocusLabel(focus)}
                                      </Tag>
                                    ))
                                  : null}
                                {item.tags.length > 0
                                  ? item.tags.slice(0, 6).map((tag) => (
                                      <Tag key={`${item.id}-${tag}`} bordered={false}>
                                        {tag}
                                      </Tag>
                                    ))
                                  : <Text type="secondary">暂无标签</Text>}
                              </Space>
                              {item.monitor_last_summary ? <Text type="secondary">最近盯盘：{item.monitor_last_summary}</Text> : null}
                              {item.monitor_last_checked_at ? <Text type="secondary">最近检查：{new Date(item.monitor_last_checked_at).toLocaleString()}</Text> : null}
                              {item.note ? <Text type="secondary">备注：{item.note}</Text> : null}
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "monitor",
            label: `盯盘中心 (${monitorEnabledWatchlist.length})`,
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="已开启盯盘" value={monitorEnabledWatchlist.length} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="高优先级信号" value={monitorHighSignalCount} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="今日已检查" value={monitorCheckedTodayCount} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="盯盘提醒" value={recentMonitorNotifications.length} />
                    </Card>
                  </Col>
                </Row>

                <Card
                  title="盯盘操作"
                  extra={
                    <Space>
                      {!guestMode ? (
                        <Button
                          loading={watchlistMonitorRunning}
                          onClick={() =>
                            void (async () => {
                              setWatchlistMonitorRunning(true);
                              try {
                                const result = await runMyWatchlistMonitorAll();
                                message.success(`已检查 ${result.checked_count} 只股票，新增 ${result.created_notification_count} 条盯盘提醒`);
                                await loadAll();
                              } catch (errorObject) {
                                const err = errorObject as Error;
                                message.error(`批量盯盘失败：${err.message}`);
                              } finally {
                                setWatchlistMonitorRunning(false);
                              }
                            })()
                          }
                        >
                          全部检查
                        </Button>
                      ) : null}
                      <Button onClick={() => void loadAll()}>刷新数据</Button>
                    </Space>
                  }
                >
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Text type="secondary">
                      盯盘中心会根据你在“我的股票”中配置的频率与规则，周期检查价格异动、接近预警价、技术位与板块联动，并将重要结果写入消息中心。
                    </Text>
                    <Space wrap>
                      <Button loading={watchlistMonitorBatchSaving} onClick={() => void handleBatchMonitorUpdate({ monitor_enabled: true, monitor_interval_minutes: 5, monitor_focus: ["price_move", "turnover_spike", "trend_breakout"] })}>
                        批量切换为 5m
                      </Button>
                      <Button loading={watchlistMonitorBatchSaving} onClick={() => void handleBatchMonitorUpdate({ monitor_enabled: true, monitor_interval_minutes: 15, monitor_focus: ["price_move", "near_alert", "trend_breakout", "sector_rotation"] })}>
                        批量切换为 15m
                      </Button>
                      <Button danger loading={watchlistMonitorBatchSaving} onClick={() => void handleBatchMonitorUpdate({ monitor_enabled: false })}>
                        批量关闭盯盘
                      </Button>
                    </Space>
                  </Space>
                </Card>

                <Card title={`盯盘股票（${filteredMonitorWatchlist.length} / 已开启 ${monitorEnabledWatchlist.length}）`} loading={loading}>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Row gutter={12}>
                      <Col xs={24} md={10}>
                        <Input
                          allowClear
                          value={monitorKeyword}
                          placeholder="按代码、名称、摘要搜索"
                          onChange={(event) => setMonitorKeyword(event.target.value)}
                        />
                      </Col>
                      <Col xs={12} md={7}>
                        <Select
                          allowClear
                          value={monitorSignalFilter}
                          style={{ width: "100%" }}
                          placeholder="按信号级别筛选"
                          options={[
                            { label: "高优先级", value: "high" },
                            { label: "中优先级", value: "medium" },
                            { label: "低优先级", value: "low" },
                          ]}
                          onChange={(value) => setMonitorSignalFilter((value as string | undefined) ?? undefined)}
                        />
                      </Col>
                      <Col xs={12} md={7}>
                        <Select<MonitorIntervalMinutes>
                          allowClear
                          value={monitorIntervalFilter}
                          style={{ width: "100%" }}
                          placeholder="按频率筛选"
                          options={WATCHLIST_MONITOR_INTERVAL_OPTIONS}
                          onChange={(value) => setMonitorIntervalFilter((value as MonitorIntervalMinutes | undefined) ?? undefined)}
                        />
                      </Col>
                    </Row>

                    <Space wrap>
                      <Tag color="red">高优先级 {monitorHighSignalCount}</Tag>
                      <Tag color="gold">中优先级 {monitorMediumSignalCount}</Tag>
                      <Tag color="processing">今日已检查 {monitorCheckedTodayCount}</Tag>
                    </Space>

                    <List
                      dataSource={filteredMonitorWatchlist}
                      locale={{ emptyText: "当前没有开启盯盘的股票，先去自选列表里开启一只。" }}
                      pagination={{ pageSize: 8 }}
                      renderItem={(item) => (
                      <List.Item
                        actions={[
                          <Button
                            key={`monitor-run-${item.id}`}
                            type="link"
                            onClick={() => void handleRunWatchlistMonitor(item)}
                          >
                            立即检查
                          </Button>,
                          <Button
                            key={`monitor-setting-${item.id}`}
                            type="link"
                            onClick={() => openWatchlistMonitor(item)}
                          >
                            设置
                          </Button>,
                          <Button
                            key={`monitor-detail-${item.id}`}
                            type="link"
                            onClick={() => openWatchlistDetail(item.symbol)}
                          >
                            详情
                          </Button>,
                        ]}
                      >
                        <List.Item.Meta
                          title={`${item.name}（${item.symbol}）`}
                          description={
                            <Space direction="vertical" size={4}>
                              <Space wrap>
                                <Tag color="processing">频率 {item.monitor_interval_minutes ?? 15}m</Tag>
                                <Tag color={item.monitor_last_signal_level === "high" ? "red" : item.monitor_last_signal_level === "medium" ? "gold" : "default"}>
                                  信号 {item.monitor_last_signal_level ?? "low"}
                                </Tag>
                                {(item.monitor_focus ?? []).slice(0, 4).map((focus) => (
                                  <Tag key={`${item.id}-${focus}`} bordered={false} color="purple">
                                    {monitorFocusLabel(focus)}
                                  </Tag>
                                ))}
                              </Space>
                              <Text type="secondary">
                                现价：{item.current_price.toFixed(2)} / 涨跌幅：
                                <Text style={{ color: item.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>{toSignedPercent(item.change_pct)}</Text>
                              </Text>
                              <Text type="secondary">最近检查：{item.monitor_last_checked_at ? new Date(item.monitor_last_checked_at).toLocaleString() : "暂无"}</Text>
                              <Text type="secondary">最近摘要：{item.monitor_last_summary ?? "暂无盯盘摘要"}</Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                    />
                  </Space>
                </Card>

                <Card title={`最近盯盘提醒（${recentMonitorNotifications.length}）`} loading={loading}>
                  <List
                    dataSource={recentMonitorNotifications}
                    locale={{ emptyText: "暂无盯盘提醒，执行一次检查或等待周期扫描。" }}
                    renderItem={(item) => (
                      <List.Item>
                        <Space direction="vertical" size={2} style={{ width: "100%" }}>
                          <Space wrap>
                            <Tag color="purple">盯盘提醒</Tag>
                            {item.symbol ? <Tag>{item.symbol}</Tag> : null}
                            <Text strong>{item.title}</Text>
                          </Space>
                          <Text type="secondary">{item.content}</Text>
                          <Text type="secondary">{new Date(item.created_at).toLocaleString()}</Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "positions",
            label: `个人持仓 (${positions.length})`,
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Row gutter={[12, 12]}>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="持仓数量" value={analysis?.total_positions ?? 0} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="总成本" value={analysis?.total_cost ?? 0} precision={2} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="总市值" value={analysis?.total_market_value ?? 0} precision={2} />
                    </Card>
                  </Col>
                  <Col xs={12} md={6}>
                    <Card loading={loading}>
                      <Statistic title="总浮盈亏" value={analysis?.total_pnl ?? 0} precision={2} valueStyle={{ color: (analysis?.total_pnl ?? 0) >= 0 ? "#389e0d" : "#cf1322" }} />
                    </Card>
                  </Col>
                </Row>

                <Card title="新增持仓">
                  <Form<PositionFormValues> form={positionForm} layout="vertical" onFinish={handleCreatePosition}>
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Form.Item label="股票代码" name="symbol" rules={[{ required: true, message: "请输入股票代码" }]}>
                          <Input placeholder="如 600519.SH" />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="持仓数量" name="quantity" rules={[{ required: true, message: "请输入持仓数量" }]}>
                          <InputNumber min={0.0001} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="成本价" name="cost_price" rules={[{ required: true, message: "请输入成本价" }]}>
                          <InputNumber min={0.0001} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Form.Item label="止损价" name="stop_loss_price">
                          <InputNumber min={0.0001} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="止盈价" name="take_profit_price">
                          <InputNumber min={0.0001} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="交易逻辑" name="thesis">
                          <Input placeholder="可选" />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Button type="primary" htmlType="submit" loading={positionSubmitting}>
                      记录持仓
                    </Button>
                  </Form>
                </Card>

                <Card title="持仓列表" loading={loading}>
                  <Table rowKey="id" dataSource={positions} columns={positionColumns} pagination={{ pageSize: 10 }} />
                </Card>

                <Card title="风险提醒" loading={loading}>
                  <Space direction="vertical" size={6}>
                    {(analysis?.risk_notes ?? []).map((item) => (
                      <Text key={item}>- {item}</Text>
                    ))}
                  </Space>
                </Card>
              </Space>
            ),
          },
          {
            key: "followups",
            label: `持仓跟进 (${followUps.length})`,
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Card title="新增跟进记录">
                  <Form<FollowUpFormValues> form={followUpForm} layout="vertical" onFinish={handleCreateFollowUp}>
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Form.Item label="对应持仓" name="position_id" rules={[{ required: true, message: "请选择持仓" }]}>
                          <Select
                            options={positions.map((item) => ({
                              label: `${item.name} (${item.symbol})`,
                              value: item.id,
                            }))}
                            placeholder="请选择持仓"
                          />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="跟进日期" name="follow_date" rules={[{ required: true, message: "请选择日期" }]}>
                          <Input placeholder="YYYY-MM-DD" />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={8}>
                        <Form.Item label="下次跟进日期" name="next_follow_date">
                          <Input placeholder="YYYY-MM-DD" />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Row gutter={12}>
                      <Col xs={24} md={12}>
                        <Form.Item label="阶段" name="stage" rules={[{ required: true, message: "请选择阶段" }]}>
                          <Select
                            options={[
                              { label: "建仓前", value: "pre_open" },
                              { label: "持有中", value: "holding" },
                              { label: "再平衡", value: "rebalancing" },
                              { label: "退出复盘", value: "exit_review" },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                      <Col xs={24} md={12}>
                        <Form.Item label="状态" name="status" rules={[{ required: true, message: "请选择状态" }]}>
                          <Select
                            options={[
                              { label: "待跟进", value: "open" },
                              { label: "跟进中", value: "in_progress" },
                              { label: "已关闭", value: "closed" },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Form.Item label="跟进摘要" name="summary" rules={[{ required: true, message: "请输入跟进摘要" }]}>
                      <TextArea rows={3} placeholder="本次跟进结论与决策依据" />
                    </Form.Item>
                    <Form.Item label="行动项（每行一条）" name="action_items_text">
                      <TextArea rows={3} placeholder={"例如：\n1) 跟踪财报披露\n2) 跟踪行业政策"} />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={followUpSubmitting}>
                      保存跟进
                    </Button>
                  </Form>
                </Card>

                <Card title="跟进列表" loading={loading}>
                  <Table rowKey="id" dataSource={followUps} columns={followUpColumns} pagination={{ pageSize: 10 }} />
                </Card>
              </Space>
            ),
          },
        ]}
      />

      <Drawer
        title={watchlistMonitorItem ? `盯盘设置 · ${watchlistMonitorItem.name}（${watchlistMonitorItem.symbol}）` : "盯盘设置"}
        open={watchlistMonitorOpen}
        width={520}
        onClose={() => {
          setWatchlistMonitorOpen(false);
          setWatchlistMonitorItem(null);
        }}
        destroyOnHidden
        extra={
          <Space>
            {!guestMode ? (
              <Button loading={watchlistMonitorRunning} onClick={() => void handleRunWatchlistMonitor()}>
                立即检查
              </Button>
            ) : null}
            <Button type="primary" loading={watchlistMonitorSubmitting} onClick={() => watchlistMonitorForm.submit()}>
              保存设置
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Alert
            type={guestMode ? "warning" : "info"}
            showIcon
            message={guestMode ? "游客模式仅保存盯盘配置，登录后可接入服务端自动提醒。" : "系统会按频率对这只股票执行盯盘检查，并将重要信号写入消息中心。"}
          />

          {watchlistMonitorItem ? (
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="现价">{watchlistMonitorItem.current_price.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="涨跌幅">
                <Text style={{ color: watchlistMonitorItem.change_pct >= 0 ? "#389e0d" : "#cf1322" }}>
                  {toSignedPercent(watchlistMonitorItem.change_pct)}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="最近检查">
                {watchlistMonitorItem.monitor_last_checked_at ? new Date(watchlistMonitorItem.monitor_last_checked_at).toLocaleString() : "暂无"}
              </Descriptions.Item>
              <Descriptions.Item label="最近信号级别">{watchlistMonitorItem.monitor_last_signal_level ?? "暂无"}</Descriptions.Item>
              <Descriptions.Item label="最近摘要" span={2}>
                {watchlistMonitorItem.monitor_last_summary ?? "暂无盯盘摘要"}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          <Card size="small" title="盯盘模板">
            <Space wrap>
              <Button onClick={() => applyMonitorTemplate("steady")}>稳健跟踪</Button>
              <Button onClick={() => applyMonitorTemplate("short_term")}>短线波动</Button>
              <Button onClick={() => applyMonitorTemplate("dividend")}>分红防守</Button>
            </Space>
          </Card>

          <Form<WatchlistMonitorFormValues>
            form={watchlistMonitorForm}
            layout="vertical"
            onFinish={handleSaveWatchlistMonitor}
            initialValues={{
              monitor_enabled: false,
              monitor_interval_minutes: 15,
              monitor_focus: ["price_move", "near_alert", "trend_breakout"],
            }}
          >
            <Form.Item label="启用盯盘" name="monitor_enabled" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>

            <Form.Item label="检查频率" name="monitor_interval_minutes">
              <Select options={WATCHLIST_MONITOR_INTERVAL_OPTIONS} />
            </Form.Item>

            <Form.Item label="重点规则" name="monitor_focus">
              <Select mode="multiple" options={WATCHLIST_MONITOR_FOCUS_OPTIONS} placeholder="选择盯盘规则" />
            </Form.Item>

            <Form.Item label="上沿提醒价" name="alert_price_up">
              <InputNumber min={0} style={{ width: "100%" }} placeholder="可选" />
            </Form.Item>

            <Form.Item label="下沿提醒价" name="alert_price_down">
              <InputNumber min={0} style={{ width: "100%" }} placeholder="可选" />
            </Form.Item>

            <Form.Item label="备注" name="note">
              <TextArea rows={3} placeholder="记录你想盯盘时重点观察的逻辑，例如：放量突破、接近目标价、板块共振。" />
            </Form.Item>
          </Form>
        </Space>
      </Drawer>
    </Space>
  );
}

export default MyWorkspacePage;
