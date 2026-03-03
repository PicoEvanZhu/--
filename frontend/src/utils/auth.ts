import type { UserPublic } from "../types/account";

const TOKEN_KEY = "stock_assistant_access_token";
const USER_KEY = "stock_assistant_user";
const SESSION_MODE_KEY = "stock_assistant_session_mode";
const AUTH_EVENT = "stock-assistant-auth-changed";

function emitAuthChanged() {
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function getAuthEventName(): string {
  return AUTH_EVENT;
}

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getSessionUser(): UserPublic | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as UserPublic;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: UserPublic): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(SESSION_MODE_KEY, "user");
  emitAuthChanged();
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(SESSION_MODE_KEY);
  emitAuthChanged();
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken());
}

export function isGuestMode(): boolean {
  const mode = localStorage.getItem(SESSION_MODE_KEY);
  if (mode === "guest") {
    return true;
  }

  if (mode === "user") {
    return false;
  }

  const user = getSessionUser();
  return Boolean(user && user.role === "guest" && !getAccessToken());
}

export function hasSessionAccess(): boolean {
  return isAuthenticated() || isGuestMode();
}

export function startGuestSession(): UserPublic {
  const guestUser: UserPublic = {
    id: 0,
    username: "guest",
    email: "guest@local.stock",
    display_name: "游客",
    role: "guest",
    is_active: true,
    created_at: new Date().toISOString(),
    last_login_at: null,
  };

  localStorage.removeItem(TOKEN_KEY);
  localStorage.setItem(USER_KEY, JSON.stringify(guestUser));
  localStorage.setItem(SESSION_MODE_KEY, "guest");
  emitAuthChanged();
  return guestUser;
}

export function isAdmin(): boolean {
  const user = getSessionUser();
  return user?.role === "admin";
}
