import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, App as AntdApp, Button, Card, Col, Form, Input, Row, Space, Tabs, Typography } from "antd";

import { forgotPassword, login, register, resetPassword } from "../api/account";
import { migrateGuestDataToCurrentUser } from "../services/guestMigration";
import { getGuestDataSummary } from "../services/guestData";
import { getAuthEventName, isGuestMode, setSession, startGuestSession } from "../utils/auth";

const { Paragraph, Title, Text } = Typography;

interface LoginFormValues {
  account: string;
  password: string;
}

interface RegisterFormValues {
  username: string;
  email: string;
  password: string;
  display_name?: string;
}

interface ForgotPasswordFormValues {
  account: string;
}

interface ResetPasswordFormValues {
  account: string;
  code: string;
  new_password: string;
}

function AuthPage() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [loginLoading, setLoginLoading] = useState(false);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [forgotLoading, setForgotLoading] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [generatedCode, setGeneratedCode] = useState<string | null>(null);
  const [guestMode, setGuestMode] = useState(isGuestMode());
  const [guestSummary, setGuestSummary] = useState(getGuestDataSummary());

  useEffect(() => {
    const sync = () => {
      setGuestMode(isGuestMode());
      setGuestSummary(getGuestDataSummary());
    };

    const authEvent = getAuthEventName();
    window.addEventListener(authEvent, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(authEvent, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const handleMigrateGuestData = async () => {
    const result = await migrateGuestDataToCurrentUser();
    if (!result.hasData) {
      return;
    }

    const importedTotal = result.importedWatchlist + result.importedPositions + result.importedFollowUps + result.importedTradeReviews;
    if (importedTotal > 0) {
      message.success(
        `已合并游客操作：自选 ${result.importedWatchlist}、持仓 ${result.importedPositions}、跟进 ${result.importedFollowUps}、复盘 ${result.importedTradeReviews}`
      );
    }
    if (result.errors.length > 0) {
      message.warning(`游客数据部分合并失败（${result.errors.length} 项），可在“我的股票”页补充。`);
    }
    setGuestSummary(getGuestDataSummary());
    setGuestMode(isGuestMode());
  };

  const handleLogin = async (values: LoginFormValues) => {
    setLoginLoading(true);
    try {
      const wasGuest = isGuestMode();
      const response = await login(values);
      setSession(response.access_token, response.user);
      if (wasGuest) {
        await handleMigrateGuestData();
      }
      message.success(`欢迎回来，${response.user.display_name || response.user.username}`);
      navigate("/my");
    } catch (error) {
      const err = error as Error;
      message.error(`登录失败：${err.message}`);
    } finally {
      setLoginLoading(false);
    }
  };

  const handleRegister = async (values: RegisterFormValues) => {
    setRegisterLoading(true);
    try {
      const wasGuest = isGuestMode();
      const response = await register(values);
      setSession(response.access_token, response.user);
      if (wasGuest) {
        await handleMigrateGuestData();
      }
      message.success("注册成功，已自动登录");
      navigate("/my");
    } catch (error) {
      const err = error as Error;
      message.error(`注册失败：${err.message}`);
    } finally {
      setRegisterLoading(false);
    }
  };

  const handleForgotPassword = async (values: ForgotPasswordFormValues) => {
    setForgotLoading(true);
    try {
      const response = await forgotPassword(values);
      setGeneratedCode(response.reset_code ?? null);
      message.success(response.message);
    } catch (error) {
      const err = error as Error;
      message.error(`获取验证码失败：${err.message}`);
    } finally {
      setForgotLoading(false);
    }
  };

  const handleResetPassword = async (values: ResetPasswordFormValues) => {
    setResetLoading(true);
    try {
      const response = await resetPassword(values);
      message.success(response.message);
      setGeneratedCode(null);
      navigate("/auth");
    } catch (error) {
      const err = error as Error;
      message.error(`重置密码失败：${err.message}`);
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div className="auth-page-shell">
      <div className="auth-page-wrap">
        <Card className="auth-main-card" styles={{ body: { padding: 0 } }}>
          <Row gutter={0}>
            <Col xs={24} lg={10} className="auth-main-left">
              <Space direction="vertical" size={14} style={{ width: "100%" }}>
                <Text className="auth-badge">Stock Assistant</Text>
                <Title level={3} style={{ margin: 0 }}>
                  专业选股与交易决策平台
                </Title>
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  登录后可使用个人自选、个人持仓分析、持仓跟进与复盘闭环能力。
                </Paragraph>
                <Space direction="vertical" size={8} style={{ width: "100%" }}>
                  <Text>• 多市场股票池与行业标签筛选</Text>
                  <Text>• 个股详情、指标仪表板与复盘跟进</Text>
                  <Text>• 游客模式操作可在注册后自动并入</Text>
                </Space>
                <Space wrap>
                  <Button
                    size="large"
                    onClick={() => {
                      startGuestSession();
                      message.success("已进入游客模式");
                      navigate("/home");
                    }}
                  >
                    进入游客模式
                  </Button>
                  <Button size="large" onClick={() => navigate("/stocks")}>
                    仅浏览股票池
                  </Button>
                </Space>
                {guestMode ? (
                  <Alert
                    type="warning"
                    showIcon
                    message={`当前为游客模式：持仓 ${guestSummary.positionCount} 条、跟进 ${guestSummary.followUpCount} 条、复盘 ${guestSummary.tradeReviewCount} 条。注册后将自动并入账号。`}
                  />
                ) : null}
              </Space>
            </Col>

            <Col xs={24} lg={14} className="auth-main-right">
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Title level={4} style={{ margin: 0 }}>
                  账号登录与注册
                </Title>
                <Text type="secondary">请输入账号信息以继续。</Text>
              </Space>

              <Tabs
                style={{ marginTop: 12 }}
                items={[
                  {
                    key: "login",
                    label: "登录",
                    children: (
                      <Form<LoginFormValues> layout="vertical" onFinish={handleLogin}>
                        <Form.Item label="用户名或邮箱" name="account" rules={[{ required: true, message: "请输入用户名或邮箱" }]}>
                          <Input size="large" placeholder="例如：zhangsan 或 zhangsan@example.com" />
                        </Form.Item>
                        <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
                          <Input.Password size="large" placeholder="请输入密码" />
                        </Form.Item>
                        <Form.Item style={{ marginBottom: 0 }}>
                          <Button type="primary" htmlType="submit" loading={loginLoading} size="large" block>
                            登录
                          </Button>
                        </Form.Item>
                      </Form>
                    ),
                  },
                  {
                    key: "register",
                    label: "注册",
                    children: (
                      <Form<RegisterFormValues> layout="vertical" onFinish={handleRegister}>
                        <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
                          <Input size="large" placeholder="3-50 位" />
                        </Form.Item>
                        <Form.Item label="显示名称" name="display_name">
                          <Input size="large" placeholder="可选，用于页面展示" />
                        </Form.Item>
                        <Form.Item label="邮箱" name="email" rules={[{ required: true, message: "请输入邮箱" }]}>
                          <Input size="large" placeholder="your@email.com" />
                        </Form.Item>
                        <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码（至少 8 位）" }]}>
                          <Input.Password size="large" placeholder="至少 8 位" />
                        </Form.Item>
                        <Form.Item style={{ marginBottom: 0 }}>
                          <Button type="primary" htmlType="submit" loading={registerLoading} size="large" block>
                            注册并登录
                          </Button>
                        </Form.Item>
                      </Form>
                    ),
                  },
                  {
                    key: "forgot",
                    label: "找回密码",
                    children: (
                      <Space direction="vertical" size={16} style={{ width: "100%" }}>
                        <Form<ForgotPasswordFormValues> layout="vertical" onFinish={handleForgotPassword}>
                          <Form.Item
                            label="用户名或邮箱"
                            name="account"
                            rules={[{ required: true, message: "请输入用户名或邮箱" }]}
                          >
                            <Input size="large" placeholder="输入你的用户名或邮箱" />
                          </Form.Item>
                          <Form.Item style={{ marginBottom: 0 }}>
                            <Button type="primary" htmlType="submit" loading={forgotLoading} size="large" block>
                              获取验证码
                            </Button>
                          </Form.Item>
                        </Form>

                        {generatedCode ? (
                          <Alert
                            type="info"
                            showIcon
                            message={`当前验证码：${generatedCode}`}
                            description="当前版本为站内演示模式，后续可接入短信/邮件通道。"
                          />
                        ) : (
                          <Paragraph type="secondary">先获取验证码，再使用新密码完成重置。</Paragraph>
                        )}

                        <Form<ResetPasswordFormValues> layout="vertical" onFinish={handleResetPassword}>
                          <Form.Item
                            label="用户名或邮箱"
                            name="account"
                            rules={[{ required: true, message: "请输入用户名或邮箱" }]}
                          >
                            <Input size="large" placeholder="输入你的用户名或邮箱" />
                          </Form.Item>
                          <Form.Item label="验证码" name="code" rules={[{ required: true, message: "请输入验证码" }]}>
                            <Input size="large" placeholder="6 位验证码" />
                          </Form.Item>
                          <Form.Item
                            label="新密码"
                            name="new_password"
                            rules={[{ required: true, message: "请输入新密码（至少 8 位）" }]}
                          >
                            <Input.Password size="large" placeholder="至少 8 位" />
                          </Form.Item>
                          <Form.Item style={{ marginBottom: 0 }}>
                            <Button type="primary" htmlType="submit" loading={resetLoading} size="large" block>
                              重置密码
                            </Button>
                          </Form.Item>
                        </Form>
                      </Space>
                    ),
                  },
                ]}
              />
            </Col>
          </Row>
        </Card>
      </div>
    </div>
  );
}

export default AuthPage;
