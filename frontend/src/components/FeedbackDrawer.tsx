import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { App as AntdApp, Button, Drawer, Form, Input, Select, Space, Upload } from "antd";
import { MessageOutlined, UploadOutlined } from "@ant-design/icons";

import { createFeedback } from "../api/feedback";
import type { FeedbackPayload, FeedbackScope, FeedbackType } from "../types/feedback";
import { FEEDBACK_OPEN_EVENT, type FeedbackOpenPayload } from "../utils/feedbackEvent";

const feedbackTypeOptions: { label: string; value: FeedbackType }[] = [
  { label: "Bug", value: "bug" },
  { label: "功能建议", value: "feature" },
  { label: "数据问题", value: "data" },
  { label: "体验问题", value: "ux" },
  { label: "其他", value: "other" },
];

const feedbackScopeOptions: { label: string; value: FeedbackScope }[] = [
  { label: "首页", value: "home" },
  { label: "仪表板", value: "dashboard" },
  { label: "股票池", value: "stocks" },
  { label: "个股页", value: "stock_detail" },
  { label: "分析报告", value: "report" },
  { label: "新闻", value: "news" },
  { label: "其他", value: "other" },
];

interface FeedbackFormValues {
  type: FeedbackType;
  scope: FeedbackScope;
  content: string;
  contact?: string;
}

function inferScope(pathname: string): FeedbackScope {
  if (pathname.startsWith("/home")) {
    return "home";
  }
  if (pathname.startsWith("/dashboard")) {
    return "dashboard";
  }
  if (pathname.startsWith("/stocks/")) {
    return "stock_detail";
  }
  if (pathname.startsWith("/stocks")) {
    return "stocks";
  }
  if (pathname.startsWith("/reports") || pathname.startsWith("/report")) {
    return "report";
  }
  if (pathname.startsWith("/news")) {
    return "news";
  }
  return "other";
}

function extractSymbol(pathname: string, search: string): string | undefined {
  const symbolFromStockPath = pathname.match(/^\/stocks\/([^/]+)$/)?.[1];
  if (symbolFromStockPath) {
    return decodeURIComponent(symbolFromStockPath);
  }

  const symbolFromReportPath = pathname.match(/^\/reports\/([^/]+)$/)?.[1];
  if (symbolFromReportPath) {
    return decodeURIComponent(symbolFromReportPath);
  }

  const params = new URLSearchParams(search);
  const symbolFromQuery = params.get("symbol");
  return symbolFromQuery ?? undefined;
}

function getOrCreateDeviceId(): string {
  const key = "stock_assistant_device_id";
  const current = window.localStorage.getItem(key);
  if (current) {
    return current;
  }

  const generated =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `device_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

  window.localStorage.setItem(key, generated);
  return generated;
}

function FeedbackDrawer() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [preset, setPreset] = useState<FeedbackOpenPayload | null>(null);
  const [form] = Form.useForm<FeedbackFormValues>();
  const { message } = AntdApp.useApp();

  const defaultScope = useMemo(() => inferScope(location.pathname), [location.pathname]);

  useEffect(() => {
    const handler = (event: Event) => {
      const customEvent = event as CustomEvent<FeedbackOpenPayload>;
      const payload = customEvent.detail || {};

      setPreset(payload);
      form.setFieldsValue({
        type: payload.type ?? "feature",
        scope: payload.scope ?? defaultScope,
        content: payload.content ?? "",
      });
      setOpen(true);
    };

    window.addEventListener(FEEDBACK_OPEN_EVENT, handler);
    return () => {
      window.removeEventListener(FEEDBACK_OPEN_EVENT, handler);
    };
  }, [defaultScope, form]);

  const onOpen = () => {
    setPreset(null);
    form.setFieldsValue({
      type: "feature",
      scope: defaultScope,
      content: "",
    });
    setOpen(true);
  };

  const onClose = () => {
    setOpen(false);
    setPreset(null);
    form.resetFields();
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const params = new URLSearchParams(location.search);
      const payload: FeedbackPayload = {
        page: preset?.page || `${location.pathname}${location.search}`,
        type: values.type,
        scope: values.scope,
        content: values.content,
        contact: values.contact || null,
        meta_json: {
          path: location.pathname,
          query: Object.fromEntries(params.entries()),
          symbol: extractSymbol(location.pathname, location.search),
          app_version: import.meta.env.VITE_APP_VERSION ?? "0.1.0",
          user_agent: window.navigator.userAgent,
          device_id: getOrCreateDeviceId(),
          ...(preset?.extra_meta ?? {}),
        },
      };

      await createFeedback(payload);
      message.success("反馈提交成功，感谢你的建议！");
      onClose();
    } catch (error) {
      const err = error as { errorFields?: unknown[]; message?: string };
      if (err?.errorFields && err.errorFields.length > 0) {
        return;
      }
      message.error(`提交失败：${err?.message ?? "请稍后再试"}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button type="primary" icon={<MessageOutlined />} className="feedback-floating-btn" onClick={onOpen}>
        反馈
      </Button>

      <Drawer
        title="产品反馈"
        placement="right"
        width={420}
        onClose={onClose}
        open={open}
        extra={
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={submitting} onClick={handleSubmit}>
              提交
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="type" label="反馈类型" rules={[{ required: true, message: "请选择反馈类型" }]}>
            <Select options={feedbackTypeOptions} />
          </Form.Item>

          <Form.Item name="scope" label="影响范围" rules={[{ required: true, message: "请选择影响范围" }]}>
            <Select options={feedbackScopeOptions} />
          </Form.Item>

          <Form.Item
            name="content"
            label="描述"
            rules={[
              { required: true, message: "请填写反馈内容" },
              { min: 10, message: "反馈描述至少 10 个字" },
            ]}
          >
            <Input.TextArea rows={5} placeholder="请尽量描述场景、预期和实际结果" maxLength={4000} showCount />
          </Form.Item>

          <Form.Item name="contact" label="联系方式（可选）">
            <Input placeholder="邮箱 / 微信" maxLength={120} />
          </Form.Item>

          <Form.Item label="附件（可选，MVP 占位）">
            <Upload maxCount={1} beforeUpload={() => false}>
              <Button icon={<UploadOutlined />}>上传截图</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Drawer>
    </>
  );
}

export default FeedbackDrawer;
