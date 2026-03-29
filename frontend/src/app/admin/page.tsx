"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

// ── types ────────────────────────────────────────────────────────────────────

interface Session {
  access_token: string;
  role: string;
  user_id: string;
}

interface AgentDef {
  id: number;
  name: string;
  display_name: string;
  system_prompt: string;
  allowed_tools: string[];
  department: string;
  is_active: boolean;
  is_default: boolean;
}

interface MCPServer {
  id: number;
  name: string;
  url: string;
  transport: string;
  description: string;
  is_active: boolean;
}

interface KnowledgeDoc {
  document_id: string;
  document_name: string;
  chunk_count: number;
  clearance_level: number;
  department: string | null;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function authHeaders(token: string) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="text-zinc-300 text-sm font-semibold uppercase tracking-widest mb-4 border-b border-zinc-800 pb-2">
        {title}
      </h2>
      {children}
    </section>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [tab, setTab] = useState<"agents" | "mcp" | "knowledge">("agents");

  // Agents state
  const [agents, setAgents] = useState<AgentDef[]>([]);
  const [newAgent, setNewAgent] = useState({ name: "", display_name: "", system_prompt: "", allowed_tools: "", department: "engineering" });
  const [agentMsg, setAgentMsg] = useState("");

  // MCP state
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [newMcp, setNewMcp] = useState({ name: "", url: "", transport: "sse", description: "" });
  const [mcpMsg, setMcpMsg] = useState("");

  // Knowledge state
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [newDoc, setNewDoc] = useState({ document_name: "", content: "", clearance_level: 1, department: "" });
  const [docMsg, setDocMsg] = useState("");

  useEffect(() => {
    const raw = localStorage.getItem("ja_session");
    if (!raw) { router.push("/"); return; }
    const s: Session = JSON.parse(raw);
    if (s.role !== "admin") { router.push("/chat"); return; }
    setSession(s);
  }, [router]);

  useEffect(() => {
    if (!session) return;
    fetchAgents();
    fetchMcp();
    fetchDocs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function fetchAgents() {
    const res = await fetch("/api/admin/agents", { headers: authHeaders(session!.access_token) });
    if (res.ok) setAgents(await res.json());
  }
  async function fetchMcp() {
    const res = await fetch("/api/admin/mcp", { headers: authHeaders(session!.access_token) });
    if (res.ok) setMcpServers(await res.json());
  }
  async function fetchDocs() {
    const res = await fetch("/api/admin/knowledge", { headers: authHeaders(session!.access_token) });
    if (res.ok) setDocs(await res.json());
  }

  // ── Agent CRUD ──────────────────────────────────────────────────────────────

  async function createAgent() {
    setAgentMsg("");
    const res = await fetch("/api/admin/agents", {
      method: "POST",
      headers: authHeaders(session!.access_token),
      body: JSON.stringify({
        ...newAgent,
        allowed_tools: newAgent.allowed_tools.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    });
    if (res.ok) {
      setAgentMsg("Agent created ✓");
      setNewAgent({ name: "", display_name: "", system_prompt: "", allowed_tools: "", department: "engineering" });
      fetchAgents();
    } else {
      const e = await res.json();
      setAgentMsg(`Error: ${e.detail}`);
    }
  }

  async function toggleAgent(name: string, is_active: boolean) {
    await fetch(`/api/admin/agents/${name}`, {
      method: "PATCH",
      headers: authHeaders(session!.access_token),
      body: JSON.stringify({ is_active: !is_active }),
    });
    fetchAgents();
  }

  // ── MCP CRUD ────────────────────────────────────────────────────────────────

  async function createMcp() {
    setMcpMsg("");
    const res = await fetch("/api/admin/mcp", {
      method: "POST",
      headers: authHeaders(session!.access_token),
      body: JSON.stringify(newMcp),
    });
    if (res.ok) {
      setMcpMsg("MCP server registered ✓");
      setNewMcp({ name: "", url: "", transport: "sse", description: "" });
      fetchMcp();
    } else {
      const e = await res.json();
      setMcpMsg(`Error: ${e.detail}`);
    }
  }

  async function toggleMcp(name: string, is_active: boolean) {
    await fetch(`/api/admin/mcp/${name}?is_active=${!is_active}`, {
      method: "PATCH",
      headers: authHeaders(session!.access_token),
    });
    fetchMcp();
  }

  async function deleteMcp(name: string) {
    await fetch(`/api/admin/mcp/${name}`, {
      method: "DELETE",
      headers: authHeaders(session!.access_token),
    });
    fetchMcp();
  }

  // ── Knowledge CRUD ──────────────────────────────────────────────────────────

  async function uploadDoc() {
    setDocMsg("");
    const res = await fetch("/api/admin/knowledge", {
      method: "POST",
      headers: authHeaders(session!.access_token),
      body: JSON.stringify({ ...newDoc, department: newDoc.department || null }),
    });
    if (res.ok) {
      setDocMsg("Document uploaded ✓");
      setNewDoc({ document_name: "", content: "", clearance_level: 1, department: "" });
      fetchDocs();
    } else {
      const e = await res.json();
      setDocMsg(`Error: ${e.detail}`);
    }
  }

  async function deleteDoc(docId: string) {
    await fetch(`/api/admin/knowledge/${docId}`, {
      method: "DELETE",
      headers: authHeaders(session!.access_token),
    });
    fetchDocs();
  }

  if (!session) return null;

  const tabs = ["agents", "mcp", "knowledge"] as const;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-mono">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-4">
          <span className="text-zinc-400 font-bold tracking-wider text-sm">just-agentic</span>
          <span className="text-zinc-600 text-xs">admin panel</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-zinc-500 text-xs">{session.user_id}</span>
          <button onClick={() => router.push("/chat")} className="text-zinc-500 hover:text-zinc-300 text-xs transition-colors">← back to chat</button>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="flex gap-1 mb-8 border-b border-zinc-800">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-xs uppercase tracking-wider transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-zinc-400 text-zinc-200"
                  : "border-transparent text-zinc-600 hover:text-zinc-400"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* ── Agents tab ── */}
        {tab === "agents" && (
          <>
            <Section title="Agent Definitions">
              <div className="space-y-2 mb-6">
                {agents.map((a) => (
                  <div key={a.id} className="flex items-center justify-between px-4 py-2 rounded border border-zinc-800 bg-zinc-900">
                    <div>
                      <span className={`text-sm font-semibold ${a.is_active ? "text-zinc-200" : "text-zinc-600 line-through"}`}>{a.display_name}</span>
                      <span className="ml-2 text-zinc-600 text-xs">/{a.name}</span>
                      <span className="ml-2 text-zinc-600 text-xs">[{a.department}]</span>
                      {a.is_default && <span className="ml-2 text-zinc-700 text-xs">default</span>}
                    </div>
                    <button
                      onClick={() => toggleAgent(a.name, a.is_active)}
                      className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                        a.is_active
                          ? "border-zinc-700 text-zinc-500 hover:text-red-400 hover:border-red-800"
                          : "border-zinc-700 text-zinc-600 hover:text-green-400 hover:border-green-800"
                      }`}
                    >
                      {a.is_active ? "disable" : "enable"}
                    </button>
                  </div>
                ))}
              </div>

              <div className="border border-zinc-800 rounded p-4 space-y-3">
                <p className="text-zinc-500 text-xs uppercase tracking-wider">Create Agent</p>
                <div className="grid grid-cols-2 gap-3">
                  <input value={newAgent.name} onChange={(e) => setNewAgent({ ...newAgent, name: e.target.value })} placeholder="slug (e.g. data_analyst)" className="input-field" />
                  <input value={newAgent.display_name} onChange={(e) => setNewAgent({ ...newAgent, display_name: e.target.value })} placeholder="Display Name" className="input-field" />
                  <input value={newAgent.department} onChange={(e) => setNewAgent({ ...newAgent, department: e.target.value })} placeholder="department" className="input-field" />
                  <input value={newAgent.allowed_tools} onChange={(e) => setNewAgent({ ...newAgent, allowed_tools: e.target.value })} placeholder="tools (comma-separated)" className="input-field" />
                </div>
                <textarea value={newAgent.system_prompt} onChange={(e) => setNewAgent({ ...newAgent, system_prompt: e.target.value })} placeholder="System prompt..." rows={4} className="input-field w-full resize-none" />
                <div className="flex items-center gap-3">
                  <button onClick={createAgent} className="btn-primary">Create Agent</button>
                  {agentMsg && <span className="text-xs text-zinc-500">{agentMsg}</span>}
                </div>
              </div>
            </Section>
          </>
        )}

        {/* ── MCP tab ── */}
        {tab === "mcp" && (
          <Section title="MCP Servers">
            <div className="space-y-2 mb-6">
              {mcpServers.length === 0 && <p className="text-zinc-600 text-sm">No MCP servers registered.</p>}
              {mcpServers.map((s) => (
                <div key={s.id} className="flex items-center justify-between px-4 py-2 rounded border border-zinc-800 bg-zinc-900">
                  <div>
                    <span className={`text-sm font-semibold ${s.is_active ? "text-zinc-200" : "text-zinc-600"}`}>{s.name}</span>
                    <span className="ml-2 text-zinc-600 text-xs">{s.url}</span>
                    <span className="ml-2 text-zinc-700 text-xs">[{s.transport}]</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => toggleMcp(s.name, s.is_active)} className="text-xs px-2 py-0.5 rounded border border-zinc-700 text-zinc-500 hover:text-zinc-300 transition-colors">
                      {s.is_active ? "disable" : "enable"}
                    </button>
                    <button onClick={() => deleteMcp(s.name)} className="text-xs px-2 py-0.5 rounded border border-zinc-800 text-zinc-600 hover:text-red-400 hover:border-red-800 transition-colors">delete</button>
                  </div>
                </div>
              ))}
            </div>

            <div className="border border-zinc-800 rounded p-4 space-y-3">
              <p className="text-zinc-500 text-xs uppercase tracking-wider">Register MCP Server</p>
              <div className="grid grid-cols-2 gap-3">
                <input value={newMcp.name} onChange={(e) => setNewMcp({ ...newMcp, name: e.target.value })} placeholder="name (e.g. github)" className="input-field" />
                <input value={newMcp.url} onChange={(e) => setNewMcp({ ...newMcp, url: e.target.value })} placeholder="URL (e.g. http://localhost:3001/sse)" className="input-field" />
                <select value={newMcp.transport} onChange={(e) => setNewMcp({ ...newMcp, transport: e.target.value })} className="input-field">
                  <option value="sse">SSE</option>
                  <option value="stdio">stdio</option>
                </select>
                <input value={newMcp.description} onChange={(e) => setNewMcp({ ...newMcp, description: e.target.value })} placeholder="Description (optional)" className="input-field" />
              </div>
              <div className="flex items-center gap-3">
                <button onClick={createMcp} className="btn-primary">Register</button>
                {mcpMsg && <span className="text-xs text-zinc-500">{mcpMsg}</span>}
              </div>
            </div>
          </Section>
        )}

        {/* ── Knowledge tab ── */}
        {tab === "knowledge" && (
          <Section title="Knowledge Base">
            <div className="space-y-2 mb-6">
              {docs.length === 0 && <p className="text-zinc-600 text-sm">No documents uploaded.</p>}
              {docs.map((d) => (
                <div key={d.document_id} className="flex items-center justify-between px-4 py-2 rounded border border-zinc-800 bg-zinc-900">
                  <div>
                    <span className="text-sm text-zinc-200">{d.document_name}</span>
                    <span className="ml-2 text-zinc-600 text-xs">{d.chunk_count} chunks</span>
                    <span className="ml-2 text-zinc-700 text-xs">L{d.clearance_level}</span>
                    {d.department && <span className="ml-2 text-zinc-700 text-xs">[{d.department}]</span>}
                  </div>
                  <button onClick={() => deleteDoc(d.document_id)} className="text-xs px-2 py-0.5 rounded border border-zinc-800 text-zinc-600 hover:text-red-400 hover:border-red-800 transition-colors">delete</button>
                </div>
              ))}
            </div>

            <div className="border border-zinc-800 rounded p-4 space-y-3">
              <p className="text-zinc-500 text-xs uppercase tracking-wider">Upload Document</p>
              <div className="grid grid-cols-2 gap-3">
                <input value={newDoc.document_name} onChange={(e) => setNewDoc({ ...newDoc, document_name: e.target.value })} placeholder="Document name" className="input-field" />
                <select value={newDoc.clearance_level} onChange={(e) => setNewDoc({ ...newDoc, clearance_level: Number(e.target.value) })} className="input-field">
                  <option value={1}>L1 — PUBLIC</option>
                  <option value={2}>L2 — INTERNAL</option>
                  <option value={3}>L3 — CONFIDENTIAL</option>
                  <option value={4}>L4 — SECRET</option>
                </select>
                <input value={newDoc.department} onChange={(e) => setNewDoc({ ...newDoc, department: e.target.value })} placeholder="Department (leave blank = all)" className="input-field col-span-2" />
              </div>
              <textarea value={newDoc.content} onChange={(e) => setNewDoc({ ...newDoc, content: e.target.value })} placeholder="Paste document content here..." rows={6} className="input-field w-full resize-none" />
              <div className="flex items-center gap-3">
                <button onClick={uploadDoc} className="btn-primary">Upload</button>
                {docMsg && <span className="text-xs text-zinc-500">{docMsg}</span>}
              </div>
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}
