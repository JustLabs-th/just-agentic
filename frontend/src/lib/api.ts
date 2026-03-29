import type { LoginResponse, SSEEvent, ChatMessage } from "./types";

const API_BASE = "";  // rewrites handle /api/* → FastAPI (non-streaming)

// SSE endpoints must bypass the Next.js rewrite proxy because it buffers the
// entire response body before forwarding — killing streaming. Call FastAPI directly.
const SSE_BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : "http://localhost:8000";

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function loginJwt(token: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "jwt", token }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Login failed");
  }
  return res.json();
}

export async function loginDev(
  user_id: string,
  role: string,
  department: string
): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "dev", user_id, role, department }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Login failed");
  }
  return res.json();
}

export async function loginCredentials(
  user_id: string,
  password: string
): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "credentials", user_id, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Login failed");
  }
  return res.json();
}

export async function checkSetup(): Promise<{ needs_setup: boolean }> {
  const res = await fetch(`${API_BASE}/api/auth/setup`);
  if (!res.ok) throw new Error("Could not reach server");
  return res.json();
}

export async function runSetup(
  user_id: string,
  password: string
): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/auth/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Setup failed");
  }
  return res.json();
}

// ── Streaming helpers ─────────────────────────────────────────────────────────

async function* readSSE(
  response: Response
): AsyncGenerator<SSEEvent> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as SSEEvent;
        } catch {
          // ignore malformed lines
        }
      }
    }
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface StreamCallbacks {
  onThreadId?: (threadId: string) => void;
  onAgentSwitch?: (agent: string, intent: string, confidence: number) => void;
  onToolCall?: (tool: string, input: Record<string, unknown>, agent: string) => void;
  onMessage?: (content: string, agent?: string) => void;
  onApprovalRequired?: (threadId: string, agent: string, intent: string, action: string) => void;
  onPermissionDenied?: (error: string) => void;
  onDone?: (status: string, finalAnswer: string) => void;
  onError?: (error: string) => void;
}

export async function streamChat(
  token: string,
  message: string,
  history: ChatMessage[],
  callbacks: StreamCallbacks,
  threadId?: string,
  image?: string,
): Promise<void> {
  const historyPayload = history.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  const response = await fetch(`${SSE_BASE}/api/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message, history: historyPayload, thread_id: threadId, image }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    callbacks.onError?.(err.detail ?? "Request failed");
    return;
  }

  let currentAgent: string | undefined;
  let activeThreadId = threadId;

  for await (const event of readSSE(response)) {
    switch (event.type) {
      case "thread_id":
        activeThreadId = event.thread_id;
        callbacks.onThreadId?.(event.thread_id!);
        break;

      case "agent_switch":
        currentAgent = event.agent;
        callbacks.onAgentSwitch?.(event.agent!, event.intent ?? "", event.confidence ?? 0);
        break;

      case "tool_call":
        callbacks.onToolCall?.(event.tool!, event.input ?? {}, event.agent ?? currentAgent ?? "");
        break;

      case "message":
        callbacks.onMessage?.(event.content!, currentAgent);
        break;

      case "approval_required":
        callbacks.onApprovalRequired?.(
          activeThreadId!,
          event.agent!,
          event.intent ?? "",
          event.action ?? ""
        );
        break;

      case "permission_denied":
        callbacks.onPermissionDenied?.(event.error ?? "Permission denied");
        break;

      case "done":
        callbacks.onDone?.(event.status ?? "done", event.final_answer ?? "");
        break;

      case "error":
        callbacks.onError?.(event.error ?? "Unknown error");
        break;
    }
  }
}

export async function streamResume(
  token: string,
  threadId: string,
  approved: boolean,
  callbacks: StreamCallbacks
): Promise<void> {
  const response = await fetch(`${SSE_BASE}/api/agent/resume/${threadId}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ approved }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    callbacks.onError?.(err.detail ?? "Resume failed");
    return;
  }

  let currentAgent: string | undefined;

  for await (const event of readSSE(response)) {
    switch (event.type) {
      case "agent_switch":
        currentAgent = event.agent;
        callbacks.onAgentSwitch?.(event.agent!, event.intent ?? "", event.confidence ?? 0);
        break;
      case "message":
        callbacks.onMessage?.(event.content!, currentAgent);
        break;
      case "permission_denied":
        callbacks.onPermissionDenied?.(event.error ?? "Permission denied");
        break;
      case "done":
        callbacks.onDone?.(event.status ?? "done", event.final_answer ?? "");
        break;
      case "error":
        callbacks.onError?.(event.error ?? "Unknown error");
        break;
    }
  }
}
