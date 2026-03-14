import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, App as AntdApp, Badge, Button, Card, Empty, Space, Switch, Table, Tag, Typography } from "antd";

import {
  getMyNotificationSettings,
  listMyNotifications,
  markMyNotificationRead,
  refreshMyNotifications,
  updateMyNotificationSettings,
} from "../api/account";
import {
  getGuestNotificationSettings,
  listGuestNotifications,
  markGuestNotificationRead,
  refreshGuestNotifications,
  updateGuestNotificationSettings,
} from "../services/guestData";
import type { NotificationItem, NotificationSetting, NotificationSettingUpdateRequest } from "../types/account";
import { hasSessionAccess, isAuthenticated, isGuestMode, startGuestSession } from "../utils/auth";

const { Text } = Typography;

function categoryLabel(category: NotificationItem["category"]): string {
  if (category === "price_alert") {
    return "价格提醒";
  }
  if (category === "report_alert") {
    return "财报提醒";
  }
  if (category === "watch_monitor") {
    return "盯盘提醒";
  }
  return "跟进到期";
}

function categoryColor(category: NotificationItem["category"]): string {
  if (category === "price_alert") {
    return "gold";
  }
  if (category === "report_alert") {
    return "blue";
  }
  if (category === "watch_monitor") {
    return "purple";
  }
  return "volcano";
}

function NoticePage() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();

  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [savingSetting, setSavingSetting] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [settings, setSettings] = useState<NotificationSetting | null>(null);
  const [rows, setRows] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);

  const authed = isAuthenticated();
  const guestMode = isGuestMode();
  const hasAccess = hasSessionAccess();

  const loadData = async () => {
    if (!hasAccess) {
      return;
    }

    if (guestMode) {
      const settingData = getGuestNotificationSettings();
      const listData = listGuestNotifications(unreadOnly);
      setSettings(settingData);
      setRows(listData.items);
      setTotal(listData.total);
      setUnreadCount(listData.unread_count);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const [settingData, listData] = await Promise.all([getMyNotificationSettings(), listMyNotifications(unreadOnly)]);
      setSettings(settingData);
      setRows(listData.items);
      setTotal(listData.total);
      setUnreadCount(listData.unread_count);
    } catch (error) {
      const err = error as Error;
      message.error(`加载通知失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [unreadOnly, authed, guestMode, hasAccess]);

  const handleRefresh = async () => {
    if (guestMode) {
      const result = refreshGuestNotifications();
      message.success(`已刷新，新增 ${result.created_count} 条通知`);
      await loadData();
      return;
    }

    setRefreshing(true);
    try {
      const result = await refreshMyNotifications();
      message.success(`已刷新，新增 ${result.created_count} 条通知`);
      await loadData();
    } catch (error) {
      const err = error as Error;
      message.error(`刷新失败：${err.message}`);
    } finally {
      setRefreshing(false);
    }
  };

  const handleUpdateSetting = async (payload: NotificationSettingUpdateRequest) => {
    if (guestMode) {
      const data = updateGuestNotificationSettings(payload);
      setSettings(data);
      message.success("通知设置已更新");
      return;
    }

    setSavingSetting(true);
    try {
      const data = await updateMyNotificationSettings(payload);
      setSettings(data);
      message.success("通知设置已更新");
    } catch (error) {
      const err = error as Error;
      message.error(`设置保存失败：${err.message}`);
    } finally {
      setSavingSetting(false);
    }
  };

  const handleMarkRead = async (notificationId: number) => {
    if (guestMode) {
      try {
        markGuestNotificationRead(notificationId);
        await loadData();
      } catch (error) {
        const err = error as Error;
        message.error(`标记已读失败：${err.message}`);
      }
      return;
    }

    try {
      await markMyNotificationRead(notificationId);
      await loadData();
    } catch (error) {
      const err = error as Error;
      message.error(`标记已读失败：${err.message}`);
    }
  };

  const columns = [
    {
      title: "类型",
      dataIndex: "category",
      width: 120,
      render: (value: NotificationItem["category"]) => <Tag color={categoryColor(value)}>{categoryLabel(value)}</Tag>,
    },
    {
      title: "股票",
      dataIndex: "symbol",
      width: 120,
      render: (value?: string) => value || "-",
    },
    {
      title: "标题",
      dataIndex: "title",
      width: 220,
    },
    {
      title: "内容",
      dataIndex: "content",
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "状态",
      width: 100,
      render: (_: unknown, record: NotificationItem) =>
        record.is_read ? <Tag color="default">已读</Tag> : <Tag color="processing">未读</Tag>,
    },
    {
      title: "操作",
      width: 120,
      render: (_: unknown, record: NotificationItem) => (
        <Button type="link" disabled={record.is_read} onClick={() => void handleMarkRead(record.id)}>
          标记已读
        </Button>
      ),
    },
  ];

  if (!hasAccess) {
    return (
      <Card title="通知中心">
        <Space direction="vertical" size={12}>
          <Text type="secondary">登录或进入游客模式后可开启价格提醒、财报提醒、跟进到期提醒。</Text>
          <Space>
            <Button type="primary" onClick={() => navigate("/auth")}>
              去登录 / 注册
            </Button>
            <Button
              onClick={() => {
                startGuestSession();
                navigate("/notice");
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
          message="当前为游客模式：通知数据仅保存在当前浏览器，注册后可继续使用正式账号能力。"
        />
      ) : null}
      <Card
        title={
          <Space>
            <span>通知中心</span>
            <Badge count={unreadCount} overflowCount={999} />
          </Space>
        }
      >
        <Space wrap>
          <Button type="primary" onClick={() => void handleRefresh()} loading={refreshing}>
            刷新通知
          </Button>
          <Switch checked={unreadOnly} onChange={setUnreadOnly} />
          <Text type="secondary">仅看未读</Text>
          <Text type="secondary">总计：{total}</Text>
        </Space>
      </Card>

      <Card title="提醒设置">
        <Space direction="vertical" size={12}>
          <Space>
            <Switch
              checked={settings?.enable_price_alert ?? false}
              loading={savingSetting}
              onChange={(checked) => void handleUpdateSetting({ enable_price_alert: checked })}
            />
            <Text>价格提醒（预警价触发）</Text>
          </Space>
          <Space>
            <Switch
              checked={settings?.enable_report_alert ?? false}
              loading={savingSetting}
              onChange={(checked) => void handleUpdateSetting({ enable_report_alert: checked })}
            />
            <Text>财报提醒（财报窗口更新）</Text>
          </Space>
          <Space>
            <Switch
              checked={settings?.enable_followup_due_alert ?? false}
              loading={savingSetting}
              onChange={(checked) => void handleUpdateSetting({ enable_followup_due_alert: checked })}
            />
            <Text>跟进提醒（复盘任务到期）</Text>
          </Space>
          <Space>
            <Switch
              checked={settings?.enable_watch_monitor_alert ?? false}
              loading={savingSetting}
              onChange={(checked) => void handleUpdateSetting({ enable_watch_monitor_alert: checked })}
            />
            <Text>盯盘提醒（自选股周期扫描）</Text>
          </Space>
        </Space>
      </Card>

      <Card title="通知列表">
        {rows.length === 0 ? (
          <Empty description="暂无通知，点击“刷新通知”后将按规则生成提醒" />
        ) : (
          <Table<NotificationItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 1080 }}
          />
        )}
      </Card>
    </Space>
  );
}

export default NoticePage;
