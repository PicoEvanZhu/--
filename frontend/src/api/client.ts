const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL?.trim() || "/api/v1").replace(/\/$/, "");

interface RequestConfig extends RequestInit {
  path: string;
  skipAuth?: boolean;
}

function normalizeErrorMessage(value: unknown, fallback: string): string {
  if (typeof value === "string") {
    const normalized = value.trim();
    return normalized || fallback;
  }

  if (Array.isArray(value)) {
    const parts = value
      .map((item) => normalizeErrorMessage(item, ""))
      .map((item) => item.trim())
      .filter(Boolean);
    if (parts.length > 0) {
      return parts.join("；");
    }
    return fallback;
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;

    const msg = record.msg;
    if (typeof msg === "string" && msg.trim()) {
      return msg.trim();
    }

    const candidate = record.detail ?? record.message ?? record.error;
    if (candidate !== undefined && candidate !== value) {
      const resolved = normalizeErrorMessage(candidate, "");
      if (resolved) {
        return resolved;
      }
    }

    try {
      const serialized = JSON.stringify(value);
      if (serialized && serialized !== "{}" && serialized !== "null") {
        return serialized;
      }
    } catch {
      return fallback;
    }
  }

  return fallback;
}

function getAccessToken(): string | null {
  return localStorage.getItem("stock_assistant_access_token");
}

export async function request<T>({ path, headers, skipAuth, ...config }: RequestConfig): Promise<T> {
  const token = skipAuth ? null : getAccessToken();

  const requestUrl = `${API_BASE_URL}${path}`;
  let response: Response;

  try {
    response = await fetch(requestUrl, {
      ...config,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "未知网络错误";
    throw new Error(`网络请求失败：${requestUrl}（${errorMessage}）`);
  }

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    let message = `HTTP ${response.status}`;

    if (contentType.includes("application/json")) {
      const body = (await response.json()) as unknown;
      message = normalizeErrorMessage(body, message);
    } else {
      const text = await response.text();
      message = text || message;
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
}
