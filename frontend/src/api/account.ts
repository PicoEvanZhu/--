import { request } from "./client";
import type {
  AuthTokenResponse,
  LoginRequest,
  NotificationListResponse,
  NotificationReadResponse,
  NotificationRefreshResponse,
  NotificationSetting,
  NotificationSettingUpdateRequest,
  PasswordForgotRequest,
  PasswordForgotResponse,
  PasswordResetRequest,
  PasswordResetResponse,
  PositionAnalysisResponse,
  PositionCreateRequest,
  PositionFollowUpCreateRequest,
  PositionFollowUpItem,
  PositionFollowUpListResponse,
  PositionFollowUpUpdateRequest,
  PositionListResponse,
  PositionSnapshot,
  PositionUpdateRequest,
  RegisterRequest,
  UserPublic,
  WatchlistItem,
  WatchlistItemCreateRequest,
  WatchlistItemUpdateRequest,
  WatchlistListResponse,
  WatchlistMonitorBatchRunResponse,
  WatchlistMonitorRunResponse,
} from "../types/account";

export async function register(payload: RegisterRequest): Promise<AuthTokenResponse> {
  return request<AuthTokenResponse>({
    path: "/auth/register",
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

export async function login(payload: LoginRequest): Promise<AuthTokenResponse> {
  return request<AuthTokenResponse>({
    path: "/auth/login",
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

export async function forgotPassword(payload: PasswordForgotRequest): Promise<PasswordForgotResponse> {
  return request<PasswordForgotResponse>({
    path: "/auth/password/forgot",
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

export async function resetPassword(payload: PasswordResetRequest): Promise<PasswordResetResponse> {
  return request<PasswordResetResponse>({
    path: "/auth/password/reset",
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

export async function getMe(): Promise<UserPublic> {
  return request<UserPublic>({
    path: "/auth/me",
    method: "GET",
  });
}

export async function listMyWatchlist(): Promise<WatchlistListResponse> {
  return request<WatchlistListResponse>({
    path: "/me/watchlist",
    method: "GET",
  });
}

export async function createMyWatchlistItem(payload: WatchlistItemCreateRequest): Promise<WatchlistItem> {
  return request<WatchlistItem>({
    path: "/me/watchlist",
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateMyWatchlistItem(itemId: number, payload: WatchlistItemUpdateRequest): Promise<WatchlistItem> {
  return request<WatchlistItem>({
    path: `/me/watchlist/${itemId}`,
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function runMyWatchlistMonitor(itemId: number): Promise<WatchlistMonitorRunResponse> {
  return request<WatchlistMonitorRunResponse>({
    path: `/me/watchlist/${itemId}/monitor/run`,
    method: "POST",
  });
}

export async function runMyWatchlistMonitorAll(): Promise<WatchlistMonitorBatchRunResponse> {
  return request<WatchlistMonitorBatchRunResponse>({
    path: `/me/watchlist/monitor/run-all`,
    method: "POST",
  });
}

export async function deleteMyWatchlistItem(itemId: number): Promise<void> {
  await request<void>({
    path: `/me/watchlist/${itemId}`,
    method: "DELETE",
  });
}

export async function listMyPositions(): Promise<PositionListResponse> {
  return request<PositionListResponse>({
    path: "/me/positions",
    method: "GET",
  });
}

export async function createMyPosition(payload: PositionCreateRequest): Promise<PositionSnapshot> {
  return request<PositionSnapshot>({
    path: "/me/positions",
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateMyPosition(positionId: number, payload: PositionUpdateRequest): Promise<PositionSnapshot> {
  return request<PositionSnapshot>({
    path: `/me/positions/${positionId}`,
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteMyPosition(positionId: number): Promise<void> {
  await request<void>({
    path: `/me/positions/${positionId}`,
    method: "DELETE",
  });
}

export async function getMyPositionAnalysis(): Promise<PositionAnalysisResponse> {
  return request<PositionAnalysisResponse>({
    path: "/me/positions/analysis",
    method: "GET",
  });
}

export async function listMyFollowUps(positionId?: number): Promise<PositionFollowUpListResponse> {
  const params = new URLSearchParams();
  if (positionId !== undefined) {
    params.set("position_id", String(positionId));
  }

  return request<PositionFollowUpListResponse>({
    path: `/me/followups${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
  });
}

export async function createMyFollowUp(payload: PositionFollowUpCreateRequest): Promise<PositionFollowUpItem> {
  return request<PositionFollowUpItem>({
    path: "/me/followups",
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateMyFollowUp(followUpId: number, payload: PositionFollowUpUpdateRequest): Promise<PositionFollowUpItem> {
  return request<PositionFollowUpItem>({
    path: `/me/followups/${followUpId}`,
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteMyFollowUp(followUpId: number): Promise<void> {
  await request<void>({
    path: `/me/followups/${followUpId}`,
    method: "DELETE",
  });
}

export async function getMyNotificationSettings(): Promise<NotificationSetting> {
  return request<NotificationSetting>({
    path: "/me/notification-settings",
    method: "GET",
  });
}

export async function updateMyNotificationSettings(
  payload: NotificationSettingUpdateRequest
): Promise<NotificationSetting> {
  return request<NotificationSetting>({
    path: "/me/notification-settings",
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function refreshMyNotifications(): Promise<NotificationRefreshResponse> {
  return request<NotificationRefreshResponse>({
    path: "/me/notifications/refresh",
    method: "POST",
  });
}

export async function listMyNotifications(unreadOnly = false): Promise<NotificationListResponse> {
  const params = new URLSearchParams();
  if (unreadOnly) {
    params.set("unread_only", "true");
  }

  return request<NotificationListResponse>({
    path: `/me/notifications${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
  });
}

export async function markMyNotificationRead(notificationId: number): Promise<NotificationReadResponse> {
  return request<NotificationReadResponse>({
    path: `/me/notifications/${notificationId}/read`,
    method: "POST",
  });
}
