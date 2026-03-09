import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { BellOutlined } from "@ant-design/icons";
import { Alert, Badge, Button, Layout, Menu, Space, Spin, Typography } from "antd";

import { listMyNotifications } from "./api/account";
import { appMenus } from "./data/menu";
import { listGuestNotifications } from "./services/guestData";
import { clearSession, getAuthEventName, getSessionUser, hasSessionAccess, isAdmin, isAuthenticated, isGuestMode, startGuestSession } from "./utils/auth";

const FeedbackDrawer = lazy(() => import("./components/FeedbackDrawer"));
const StockCartFloating = lazy(() => import("./components/StockCartFloating"));
const AdminFeedbacksPage = lazy(() => import("./pages/AdminFeedbacksPage"));
const AuthPage = lazy(() => import("./pages/AuthPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const MyWorkspacePage = lazy(() => import("./pages/MyWorkspacePage"));
const NoticePage = lazy(() => import("./pages/NoticePage"));
const StockDetailPage = lazy(() => import("./pages/StockDetailPage"));
const StocksPage = lazy(() => import("./pages/StocksPage"));

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

function resolveSelectedKey(pathname: string, search: string): string | null {
  if (pathname.startsWith("/dashboard")) {
    return "dashboard";
  }

  if (pathname.startsWith("/stocks")) {
    const params = new URLSearchParams(search);
    if (params.get("source") === "my") {
      return "my_workspace";
    }
    return "stocks";
  }

  if (pathname.startsWith("/my")) {
    return "my_workspace";
  }

  if (pathname.startsWith("/auth")) {
    return null;
  }

  if (pathname.startsWith("/admin/feedbacks")) {
    return "admin_feedbacks";
  }

  if (pathname.startsWith("/notice")) {
    return "notice";
  }

  return "home";
}

function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthRoute = location.pathname.startsWith("/auth");
  const [sessionUser, setSessionUser] = useState(getSessionUser());
  const [unreadCount, setUnreadCount] = useState(0);
  const authed = isAuthenticated();
  const guestMode = isGuestMode();
  const hasAccess = hasSessionAccess();

  const selectedKeys = useMemo(() => {
    const key = resolveSelectedKey(location.pathname, location.search);
    return key ? [key] : [];
  }, [location.pathname, location.search]);

  const menuItems = useMemo(() => {
    const visibleMenus = appMenus.filter((item) => {
      if (item.requiresAuth && !sessionUser) {
        return false;
      }
      if (item.requiresAdmin && sessionUser?.role !== "admin") {
        return false;
      }
      return true;
    });

    if (sessionUser) {
      const homeMenu = visibleMenus.find((item) => item.key === "home");
      const otherMenus = visibleMenus.filter((item) => item.key !== "home");
      return homeMenu ? [homeMenu, ...otherMenus] : otherMenus;
    }

    const publicMenus = visibleMenus.filter((item) => !item.requiresAuth);
    const privateMenus = visibleMenus.filter((item) => item.requiresAuth);
    return [...publicMenus, ...privateMenus];
  }, [sessionUser]);

  useEffect(() => {
    const sync = () => {
      setSessionUser(getSessionUser());
    };

    const authEvent = getAuthEventName();
    window.addEventListener(authEvent, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(authEvent, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => {
    let mounted = true;

    const loadUnreadCount = async () => {
      if (!sessionUser) {
        setUnreadCount(0);
        return;
      }

      if (guestMode) {
        const response = listGuestNotifications(true);
        if (mounted) {
          setUnreadCount(response.unread_count);
        }
        return;
      }

      try {
        const response = await listMyNotifications(true);
        if (mounted) {
          setUnreadCount(response.unread_count);
        }
      } catch {
        if (mounted) {
          setUnreadCount(0);
        }
      }
    };

    void loadUnreadCount();
    const timer = window.setInterval(() => {
      void loadUnreadCount();
    }, 30000);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [sessionUser, guestMode, location.pathname]);

  return (
    <Layout className="app-shell">
      {!isAuthRoute ? (
        <Sider className="app-sider" width={230} breakpoint="lg" collapsedWidth={70}>
          <div
            className="brand-block"
            role="button"
            tabIndex={0}
            onClick={() => navigate("/home")}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                navigate("/home");
              }
            }}
          >
            <div className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 48 48" className="brand-mark-svg">
                <defs>
                  <linearGradient id="brandMarkGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#5cc8ff" />
                    <stop offset="100%" stopColor="#1677ff" />
                  </linearGradient>
                </defs>
                <rect x="4" y="4" width="40" height="40" rx="12" fill="url(#brandMarkGradient)" />
                <path d="M14 31L21 24L27 27L35 17" fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M31 17H35V21" fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M14 36H34" fill="none" stroke="rgba(255,255,255,0.42)" strokeWidth="2.4" strokeLinecap="round" />
              </svg>
            </div>
            <div className="brand-text">
              <div className="brand-title">股票助手</div>
              <div className="brand-subtitle">Stock Assistant</div>
            </div>
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={selectedKeys}
            items={menuItems.map((item) => ({
              key: item.key,
              label: item.label,
              onClick: () => navigate(item.path),
            }))}
          />
        </Sider>
      ) : null}

      <Layout className="app-main">
        {!isAuthRoute ? (
          <Header className="top-header">
            <div className="top-header-inner">
              <Text strong>股票助手 · 选股与分析工作台</Text>
              <Space>
                {sessionUser ? (
                  <>
                    <Text type="secondary">当前用户：{sessionUser.display_name || sessionUser.username}</Text>
                    <Badge count={unreadCount} size="small" overflowCount={99}>
                      <Button size="small" icon={<BellOutlined />} onClick={() => navigate("/notice")}>
                        消息
                      </Button>
                    </Badge>
                    <Button size="small" onClick={() => navigate("/my")}>
                      个人中心
                    </Button>
                    {guestMode ? (
                      <Button size="small" type="primary" ghost onClick={() => navigate("/auth")}>
                        注册账号
                      </Button>
                    ) : null}
                    <Button
                      size="small"
                      onClick={() => {
                        clearSession();
                        navigate("/auth");
                      }}
                    >
                      退出登录
                    </Button>
                  </>
                ) : (
                  <Space>
                    <Button size="small" onClick={() => startGuestSession()}>
                      游客模式
                    </Button>
                    <Button size="small" type="primary" ghost onClick={() => navigate("/auth")}>
                      登录 / 注册
                    </Button>
                  </Space>
                )}
              </Space>
            </div>
          </Header>
        ) : null}

        <Content className="app-content">
          {guestMode && !isAuthRoute ? (
            <Alert
              type="warning"
              showIcon
              message="当前为游客模式：数据仅保存在当前浏览器；新增自选需先注册账号，注册后将自动合并游客操作。"
              style={{ marginBottom: 12 }}
            />
          ) : null}
          <Suspense
            fallback={
              <div style={{ display: "grid", placeItems: "center", minHeight: 220 }}>
                <Spin size="large" />
              </div>
            }
          >
            <Routes>
              <Route path="/" element={<Navigate to={hasAccess ? "/home" : "/stocks"} replace />} />
              <Route path="/home" element={hasAccess ? <HomePage /> : <Navigate to="/auth" replace />} />
              <Route path="/dashboard" element={hasAccess ? <DashboardPage /> : <Navigate to="/auth" replace />} />
              <Route path="/stocks" element={<StocksPage />} />
              <Route path="/stocks/:symbol" element={<StockDetailPage />} />
              <Route path="/auth" element={<AuthPage />} />
              <Route path="/my" element={hasAccess ? <MyWorkspacePage /> : <Navigate to="/auth" replace />} />
              <Route
                path="/admin/feedbacks"
                element={
                  authed ? (
                    isAdmin() ? (
                      <AdminFeedbacksPage />
                    ) : (
                      <Navigate to="/home" replace />
                    )
                  ) : (
                    <Navigate to="/auth" replace />
                  )
                }
              />
              <Route path="/notice" element={hasAccess ? <NoticePage /> : <Navigate to="/auth" replace />} />
              <Route path="/settings" element={<Navigate to={hasAccess ? "/home" : "/stocks"} replace />} />
              <Route path="*" element={<Navigate to={hasAccess ? "/home" : "/stocks"} replace />} />
            </Routes>
          </Suspense>
        </Content>
      </Layout>

      {!isAuthRoute ? (
        <Suspense fallback={null}>
          <FeedbackDrawer />
        </Suspense>
      ) : null}

      {!isAuthRoute ? (
        <Suspense fallback={null}>
          <StockCartFloating />
        </Suspense>
      ) : null}
    </Layout>
  );
}

export default App;
