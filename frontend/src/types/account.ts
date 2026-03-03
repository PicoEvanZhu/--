export type FollowUpStatus = "open" | "in_progress" | "closed";
export type FollowUpStage = "pre_open" | "holding" | "rebalancing" | "exit_review";
export type PositionStatus = "holding" | "closed" | "watch_only";

export interface UserPublic {
  id: number;
  username: string;
  email: string;
  display_name?: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserPublic;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginRequest {
  account: string;
  password: string;
}

export interface PasswordForgotRequest {
  account: string;
}

export interface PasswordForgotResponse {
  message: string;
  expires_in_minutes: number;
  reset_code?: string | null;
}

export interface PasswordResetRequest {
  account: string;
  code: string;
  new_password: string;
}

export interface PasswordResetResponse {
  message: string;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  name: string;
  market: string;
  industry: string;
  current_price: number;
  change_pct: number;
  group_name: string;
  tags: string[];
  note?: string | null;
  alert_price_up?: number | null;
  alert_price_down?: number | null;
  target_position_pct?: number | null;
  created_at: string;
  updated_at: string;
}

export interface WatchlistListResponse {
  total: number;
  groups: string[];
  items: WatchlistItem[];
}

export interface WatchlistItemCreateRequest {
  symbol: string;
  group_name?: string;
  tags?: string[];
  note?: string;
  alert_price_up?: number;
  alert_price_down?: number;
  target_position_pct?: number;
}

export interface WatchlistItemUpdateRequest {
  group_name?: string;
  tags?: string[];
  note?: string;
  alert_price_up?: number;
  alert_price_down?: number;
  target_position_pct?: number;
}

export interface PositionSnapshot {
  id: number;
  symbol: string;
  name: string;
  market: string;
  industry: string;
  quantity: number;
  cost_price: number;
  current_price: number;
  cost_value: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  weight: number;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  status: PositionStatus;
  thesis?: string | null;
  latest_follow_up_status?: FollowUpStatus | null;
  latest_follow_up_date?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PositionListResponse {
  total: number;
  items: PositionSnapshot[];
}

export interface PositionCreateRequest {
  symbol: string;
  quantity: number;
  cost_price: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  status?: PositionStatus;
  thesis?: string;
}

export interface PositionUpdateRequest {
  quantity?: number;
  cost_price?: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  status?: PositionStatus;
  thesis?: string;
}

export interface PositionAnalysisResponse {
  total_positions: number;
  total_cost: number;
  total_market_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  win_count: number;
  loss_count: number;
  concentration_top3_pct: number;
  market_distribution: Record<string, number>;
  industry_distribution: Record<string, number>;
  risk_notes: string[];
}

export interface PositionFollowUpItem {
  id: number;
  position_id: number;
  symbol: string;
  position_name: string;
  follow_date: string;
  stage: FollowUpStage;
  status: FollowUpStatus;
  summary: string;
  action_items: string[];
  next_follow_date?: string | null;
  confidence_score?: number | null;
  discipline_score?: number | null;
  is_due: boolean;
  created_at: string;
  updated_at: string;
}

export interface PositionFollowUpListResponse {
  total: number;
  due_count: number;
  items: PositionFollowUpItem[];
}

export interface PositionFollowUpCreateRequest {
  position_id: number;
  follow_date: string;
  stage?: FollowUpStage;
  status?: FollowUpStatus;
  summary: string;
  action_items?: string[];
  next_follow_date?: string;
  confidence_score?: number;
  discipline_score?: number;
}

export interface PositionFollowUpUpdateRequest {
  follow_date?: string;
  stage?: FollowUpStage;
  status?: FollowUpStatus;
  summary?: string;
  action_items?: string[];
  next_follow_date?: string;
  confidence_score?: number;
  discipline_score?: number;
}

export type NotificationCategory = "price_alert" | "report_alert" | "followup_due";

export interface NotificationSetting {
  enable_price_alert: boolean;
  enable_report_alert: boolean;
  enable_followup_due_alert: boolean;
  updated_at: string;
}

export interface NotificationSettingUpdateRequest {
  enable_price_alert?: boolean;
  enable_report_alert?: boolean;
  enable_followup_due_alert?: boolean;
}

export interface NotificationItem {
  id: number;
  category: NotificationCategory;
  symbol?: string | null;
  title: string;
  content: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
  read_at?: string | null;
}

export interface NotificationListResponse {
  total: number;
  unread_count: number;
  items: NotificationItem[];
}

export interface NotificationRefreshResponse {
  created_count: number;
  created_by_type: Record<NotificationCategory, number>;
}

export interface NotificationReadResponse {
  item: NotificationItem;
}
