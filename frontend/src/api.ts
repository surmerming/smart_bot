/** 后端 API 封装：契约对齐 backend/app/models/schemas.py。 */

export interface QuickChip {
  label: string;
  value: string;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface ChatInitResponse {
  session_id: string;
  visitor_token: string;
  expires_in: number;
  brand_name: string;
  quick_chips: QuickChip[];
  history: HistoryMessage[];
  status: string;
}

export interface ChatInitPayload {
  session_id?: string;
  user_id?: string;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}`);
  }
  return resp.json() as Promise<T>;
}

export async function chatInit(payload: ChatInitPayload): Promise<ChatInitResponse> {
  return post<ChatInitResponse>("/api/v1/chat/init", payload);
}

export async function sendFeedback(payload: {
  session_id: string;
  message_id?: string;
  value: "up" | "down";
  query?: string;
  context?: string;
  answer?: string;
}): Promise<{ ok: boolean; feedback_id?: number }> {
  return post("/api/v1/feedback", payload);
}

export async function bindSession(payload: {
  anonymous_session_id: string;
  user_id: string;
}): Promise<{ ok: boolean; session_id: string; user_id: string }> {
  return post("/api/v1/session/bind", payload);
}

export async function manualHandover(payload: {
  session_id: string;
  visitor_token: string;
  contact?: string;
}): Promise<{ ok: boolean; queue_id?: number; message?: string }> {
  return post("/api/v1/handover", payload);
}
