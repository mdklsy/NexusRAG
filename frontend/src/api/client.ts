/** API 客户端：token 注入 + 统一错误处理 */

const BASE = import.meta.env.VITE_API_BASE || "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem("nx_token");
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    let msg = `${resp.status}`;
    try {
      const data = await resp.json();
      msg = data.detail || msg;
    } catch {
      /* ignore */
    }
    if (resp.status === 401 && location.pathname !== "/login") {
      localStorage.removeItem("nx_token");
      location.href = "/login";
    }
    throw new ApiError(resp.status, msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export async function upload(path: string, file: File): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken() || ""}` },
    body: form,
  });
  if (!resp.ok) throw new ApiError(resp.status, await resp.text());
  return resp.json();
}

/** SSE 流式对话：POST + ReadableStream 解析 */
export async function chatStream(
  body: object,
  onEvent: (event: any) => void,
  signal?: AbortSignal
) {
  const resp = await fetch(`${BASE}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken() || ""}`,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) throw new ApiError(resp.status, "对话请求失败");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const line = block.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") return;
      try {
        onEvent(JSON.parse(payload));
      } catch {
        /* 忽略坏帧 */
      }
    }
  }
}
