"use client";

import { useState, useRef, useEffect, useCallback } from "react";

const nanoid = () => crypto.randomUUID();
import { useRouter } from "next/navigation";
import MessageBubble from "./MessageBubble";
import ToolCallBubble from "./ToolCallBubble";
import ApprovalDialog from "./ApprovalDialog";
import AgentBadge from "./AgentBadge";
import { streamChat, streamResume } from "@/lib/api";
import type { ChatMessage, ApprovalRequest, UserSession } from "@/lib/types";

interface Props {
  session: UserSession;
  onLogout: () => void;
}

export default function ChatWindow({ session, onLogout }: Props) {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [attachedImage, setAttachedImage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [activeIntent, setActiveIntent] = useState<string>("");
  const [activeConfidence, setActiveConfidence] = useState<number>(0);
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [currentThreadId, setCurrentThreadId] = useState<string | undefined>();

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const streamingMsgId = useRef<string | null>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const appendMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateLastAssistantMessage = useCallback((content: string, agent?: string) => {
    setMessages((prev) => {
      if (!streamingMsgId.current) return prev;
      return prev.map((m) =>
        m.id === streamingMsgId.current
          ? { ...m, content: m.content + content, agent: agent ?? m.agent }
          : m
      );
    });
  }, []);

  const buildCallbacks = useCallback(
    (threadId?: string) => ({
      onThreadId: (id: string) => setCurrentThreadId(id),

      onAgentSwitch: (agent: string, intent: string, confidence: number) => {
        setActiveAgent(agent);
        setActiveIntent(intent);
        setActiveConfidence(confidence);
        const id = nanoid();
        streamingMsgId.current = id;
        appendMessage({ id, role: "assistant", content: "", agent, intent, confidence });
      },

      onToolCall: (tool: string, input: Record<string, unknown>, agent: string) => {
        appendMessage({
          id: nanoid(),
          role: "tool_call",
          content: "",
          toolCall: { tool, input, agent },
        });
      },

      onMessage: (content: string, agent?: string) => {
        if (streamingMsgId.current) {
          updateLastAssistantMessage(content, agent);
        } else {
          const id = nanoid();
          streamingMsgId.current = id;
          appendMessage({ id, role: "assistant", content, agent });
        }
      },

      onApprovalRequired: (tid: string, agent: string, intent: string, action: string) => {
        setApproval({ thread_id: tid, agent, intent, action });
        setLoading(false);
        setActiveAgent(null);
        streamingMsgId.current = null;
      },

      onPermissionDenied: (error: string) => {
        appendMessage({
          id: nanoid(),
          role: "system" as const,
          content: `Permission denied: ${error}`,
        });
        setLoading(false);
        setActiveAgent(null);
        streamingMsgId.current = null;
      },

      onDone: (_status: string, _finalAnswer: string) => {
        setLoading(false);
        setActiveAgent(null);
        streamingMsgId.current = null;
      },

      onError: (error: string) => {
        appendMessage({ id: nanoid(), role: "system" as const, content: `Error: ${error}` });
        setLoading(false);
        setActiveAgent(null);
        streamingMsgId.current = null;
      },
    }),
    [appendMessage, updateLastAssistantMessage]
  );

  const handleImageAttach = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setAttachedImage(reader.result as string);
    reader.readAsDataURL(file);
    // Reset input so same file can be re-attached
    e.target.value = "";
  };

  const sendMessage = async () => {
    const text = input.trim();
    if ((!text && !attachedImage) || loading) return;

    const image = attachedImage;
    setInput("");
    setAttachedImage(null);
    setLoading(true);
    streamingMsgId.current = null;
    setActiveAgent(null);

    appendMessage({ id: nanoid(), role: "user", content: text || "(image)", image: image ?? undefined });

    await streamChat(
      session.access_token,
      text || "What do you see in this image?",
      messages.filter((m) => m.role !== "system" && m.role !== "tool_call"),
      buildCallbacks(),
      currentThreadId,
      image ?? undefined,
    );
  };

  const handleApproval = async (approved: boolean) => {
    if (!approval || !currentThreadId) return;
    setApprovalLoading(true);
    setApproval(null);
    setLoading(true);
    streamingMsgId.current = null;

    await streamResume(
      session.access_token,
      currentThreadId,
      approved,
      buildCallbacks(currentThreadId)
    );
    setApprovalLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-zinc-400 font-bold tracking-wider text-sm">just-agentic</span>
          <span className="text-zinc-600">|</span>
          <span className="text-zinc-500 text-xs">
            {session.user_id} · {session.role} · {session.department} · L{session.clearance_level}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {activeAgent && (
            <AgentBadge
              agent={activeAgent}
              intent={activeIntent}
              confidence={activeConfidence}
              active
            />
          )}
          {session.role === "admin" && (
            <button
              onClick={() => router.push("/admin")}
              className="text-zinc-600 hover:text-zinc-400 text-xs transition-colors"
            >
              admin
            </button>
          )}
          <button
            onClick={onLogout}
            className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors"
          >
            logout
          </button>
        </div>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-zinc-600 gap-2">
            <p className="text-4xl">◈</p>
            <p className="text-sm">Secure multi-agent team ready.</p>
            <p className="text-xs">Agents: Backend · DevOps · QA</p>
          </div>
        )}
        {messages.map((msg) =>
          msg.role === "tool_call" && msg.toolCall ? (
            <ToolCallBubble key={msg.id} event={msg.toolCall} />
          ) : (
            <MessageBubble
              key={msg.id}
              message={msg}
              streaming={msg.id === streamingMsgId.current}
            />
          )
        )}
        <div ref={bottomRef} />
      </main>

      {/* Input */}
      <footer className="shrink-0 px-4 py-3 border-t border-zinc-800 bg-zinc-950">
        {/* Image preview */}
        {attachedImage && (
          <div className="mb-2 flex items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={attachedImage} alt="attached" className="h-16 rounded border border-zinc-700 object-cover" />
            <button
              onClick={() => setAttachedImage(null)}
              className="text-zinc-500 hover:text-zinc-300 text-xs"
            >
              ✕ remove
            </button>
          </div>
        )}
        <div className="flex gap-2 items-end">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleImageAttach}
          />
          {/* Attach image button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            title="Attach image"
            className="shrink-0 text-zinc-600 hover:text-zinc-400 disabled:opacity-30 transition-colors pb-2.5"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={loading ? "Working…" : "Ask the agents… (Enter to send, Shift+Enter for newline)"}
            disabled={loading}
            rows={1}
            className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 resize-none focus:outline-none focus:border-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed leading-relaxed"
            style={{ minHeight: "40px", maxHeight: "160px" }}
            onInput={(e) => {
              const t = e.currentTarget;
              t.style.height = "auto";
              t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
            }}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors shrink-0"
          >
            {loading ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-bounce [animation-delay:-0.3s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-bounce [animation-delay:-0.15s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-bounce" />
              </span>
            ) : (
              "Send"
            )}
          </button>
        </div>
      </footer>

      {/* Human approval modal */}
      {approval && (
        <ApprovalDialog
          request={approval}
          onApprove={() => handleApproval(true)}
          onReject={() => handleApproval(false)}
          loading={approvalLoading}
        />
      )}
    </div>
  );
}
