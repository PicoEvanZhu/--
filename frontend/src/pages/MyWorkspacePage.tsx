import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Statistic,
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
  listMyFollowUps,
  listMyPositions,
  listMyWatchlist,
} from "../api/account";
import {
  createGuestFollowUp,
  createGuestPosition,
  deleteGuestFollowUp,
  deleteGuestPosition,
  deleteGuestWatchlistItem,
  getGuestWorkspaceSnapshot,
} from "../services/guestData";
import type {
  PositionAnalysisResponse,
  PositionFollowUpCreateRequest,
  PositionFollowUpItem,
  PositionSnapshot,
  WatchlistItem,
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

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [analysis, setAnalysis] = useState<PositionAnalysisResponse | null>(null);
  const [followUps, setFollowUps] = useState<PositionFollowUpItem[]>([]);

  const [positionSubmitting, setPositionSubmitting] = useState(false);
  const [followUpSubmitting, setFollowUpSubmitting] = useState(false);
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
        setWatchlist(guestSnapshot.watchlist.items);
        setPositions(guestSnapshot.positions.items);
        setAnalysis(guestSnapshot.analysis);
        setFollowUps(guestSnapshot.followUps.items);
      } catch (errorObject) {
        const err = errorObject as Error;
        setError(err.message);
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      const [watchlistResponse, positionsResponse, analysisResponse, followUpResponse] = await Promise.all([
        listMyWatchlist(),
        listMyPositions(),
        getMyPositionAnalysis(),
        listMyFollowUps(),
      ]);
      setWatchlist(watchlistResponse.items);
      setPositions(positionsResponse.items);
      setAnalysis(analysisResponse);
      setFollowUps(followUpResponse.items);
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
                                {item.tags.length > 0
                                  ? item.tags.slice(0, 6).map((tag) => (
                                      <Tag key={`${item.id}-${tag}`} bordered={false}>
                                        {tag}
                                      </Tag>
                                    ))
                                  : <Text type="secondary">暂无标签</Text>}
                              </Space>
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
    </Space>
  );
}

export default MyWorkspacePage;
