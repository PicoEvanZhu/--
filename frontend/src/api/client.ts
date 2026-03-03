const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ??
  (import.meta.env.DEV ? "http://127.0.0.1:8000/api/v1" : "/api/v1");

interface RequestConfig extends RequestInit {
  path: string;
  skipAuth?: boolean;
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
      const body = (await response.json()) as { detail?: string; message?: string };
      message = body.detail ?? body.message ?? JSON.stringify(body);
    } else {
      const text = await response.text();
      message = text || message;
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
}
