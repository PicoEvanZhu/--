export interface AppMenuItem {
  key: string;
  label: string;
  path: string;
  requiresAuth?: boolean;
  requiresAdmin?: boolean;
}

export const appMenus: AppMenuItem[] = [
  { key: "home", label: "首页", path: "/home", requiresAuth: true },
  { key: "dashboard", label: "仪表板", path: "/dashboard", requiresAuth: true },
  { key: "stocks", label: "股票池", path: "/stocks" },
  { key: "main_force", label: "主力操盘分析", path: "/main-force", requiresAuth: true },
  { key: "my_workspace", label: "我的股票", path: "/my", requiresAuth: true },
  { key: "admin_feedbacks", label: "反馈管理", path: "/admin/feedbacks", requiresAuth: true, requiresAdmin: true },
];