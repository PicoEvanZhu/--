import { useEffect, useMemo, useState } from "react";
import { App as AntdApp, Button, Card, Select, Space, Table, Tag, Typography } from "antd";

import { listFeedbacks, updateFeedbackStatus } from "../api/feedback";
import type { FeedbackListItem, FeedbackScope, FeedbackStatus, FeedbackType } from "../types/feedback";

const { Text } = Typography;

const statusOptions: { label: string; value: FeedbackStatus }[] = [
  { label: "新建", value: "new" },
  { label: "已分诊", value: "triaged" },
  { label: "已完成", value: "done" },
];

const typeOptions: { label: string; value: FeedbackType }[] = [
  { label: "Bug", value: "bug" },
  { label: "功能建议", value: "feature" },
  { label: "数据问题", value: "data" },
  { label: "体验问题", value: "ux" },
  { label: "其他", value: "other" },
];

const scopeOptions: { label: string; value: FeedbackScope }[] = [
  { label: "首页", value: "home" },
  { label: "仪表板", value: "dashboard" },
  { label: "股票池", value: "stocks" },
  { label: "个股页", value: "stock_detail" },
  { label: "分析报告", value: "report" },
  { label: "新闻", value: "news" },
  { label: "其他", value: "other" },
];

interface FilterState {
  status?: FeedbackStatus;
  type?: FeedbackType;
  scope?: FeedbackScope;
}

function renderStatusTag(status: FeedbackStatus) {
  if (status === "done") {
    return <Tag color="green">已完成</Tag>;
  }
  if (status === "triaged") {
    return <Tag color="gold">已分诊</Tag>;
  }
  return <Tag color="blue">新建</Tag>;
}

function AdminFeedbacksPage() {
  const { message } = AntdApp.useApp();
  const [filters, setFilters] = useState<FilterState>({});
  const [loading, setLoading] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [rows, setRows] = useState<FeedbackListItem[]>([]);

  const loadFeedbacks = async () => {
    setLoading(true);
    try {
      const data = await listFeedbacks({ limit: 200, ...filters });
      setRows(data);
    } catch (error) {
      const err = error as Error;
      message.error(`加载反馈失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadFeedbacks();
  }, [filters.status, filters.type, filters.scope]);

  const handleStatusChange = async (record: FeedbackListItem, nextStatus: FeedbackStatus) => {
    if (record.status === nextStatus) {
      return;
    }

    setUpdatingId(record.id);
    try {
      await updateFeedbackStatus(record.id, nextStatus);
      message.success(`反馈 #${record.id} 状态已更新`);
      await loadFeedbacks();
    } catch (error) {
      const err = error as Error;
      message.error(`状态更新失败：${err.message}`);
    } finally {
      setUpdatingId(null);
    }
  };

  const columns = useMemo(
    () => [
      {
        title: "ID",
        dataIndex: "id",
        width: 80,
      },
      {
        title: "页面",
        dataIndex: "page",
        width: 180,
        ellipsis: true,
      },
      {
        title: "类型/范围",
        width: 140,
        render: (_: unknown, record: FeedbackListItem) => (
          <Space direction="vertical" size={0}>
            <Text>{record.type}</Text>
            <Text type="secondary">{record.scope}</Text>
          </Space>
        ),
      },
      {
        title: "反馈内容",
        dataIndex: "content",
        ellipsis: true,
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 120,
        render: (status: FeedbackStatus) => renderStatusTag(status),
      },
      {
        title: "创建时间",
        dataIndex: "created_at",
        width: 200,
        render: (value: string) => new Date(value).toLocaleString(),
      },
      {
        title: "操作",
        width: 180,
        render: (_: unknown, record: FeedbackListItem) => (
          <Select
            value={record.status}
            style={{ width: 150 }}
            loading={updatingId === record.id}
            options={statusOptions}
            onChange={(value) => {
              void handleStatusChange(record, value as FeedbackStatus);
            }}
          />
        ),
      },
    ],
    [updatingId]
  );

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="反馈处理看板">
        <Space wrap>
          <Select
            allowClear
            placeholder="按状态过滤"
            style={{ width: 180 }}
            options={statusOptions}
            value={filters.status}
            onChange={(value) => setFilters((prev) => ({ ...prev, status: value as FeedbackStatus | undefined }))}
          />
          <Select
            allowClear
            placeholder="按类型过滤"
            style={{ width: 180 }}
            options={typeOptions}
            value={filters.type}
            onChange={(value) => setFilters((prev) => ({ ...prev, type: value as FeedbackType | undefined }))}
          />
          <Select
            allowClear
            placeholder="按范围过滤"
            style={{ width: 180 }}
            options={scopeOptions}
            value={filters.scope}
            onChange={(value) => setFilters((prev) => ({ ...prev, scope: value as FeedbackScope | undefined }))}
          />
          <Button onClick={() => void loadFeedbacks()} loading={loading}>
            刷新
          </Button>
        </Space>
      </Card>

      <Card>
        <Table<FeedbackListItem>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 1100 }}
        />
      </Card>
    </Space>
  );
}

export default AdminFeedbacksPage;
