"use client";

import { useState } from "react";
import { loginJwt, loginDev, loginCredentials } from "@/lib/api";
import type { UserSession } from "@/lib/types";

interface Props {
  onLogin: (session: UserSession) => void;
}

type Mode = "credentials" | "jwt" | "dev";

const ROLES = ["viewer", "analyst", "manager", "admin"];
const DEPARTMENTS = ["engineering", "devops", "qa", "data", "security", "all"];

export default function LoginForm({ onLogin }: Props) {
  const [mode, setMode] = useState<Mode>("credentials");
  const [token, setToken] = useState("");
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("analyst");
  const [department, setDepartment] = useState("engineering");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let session: UserSession;
      if (mode === "credentials") {
        if (!userId.trim() || !password) throw new Error("Username and password are required");
        session = await loginCredentials(userId.trim(), password);
      } else if (mode === "jwt") {
        session = await loginJwt(token.trim());
      } else {
        session = await loginDev(userId.trim() || "anonymous", role, department);
      }
      onLogin(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="text-center mb-8">
          <p className="text-5xl mb-3">◈</p>
          <h1 className="text-zinc-100 text-xl font-bold tracking-widest uppercase">just-agentic</h1>
          <p className="text-zinc-500 text-xs mt-1">Secure Multi-Agent Team</p>
        </div>

        {/* Mode toggle */}
        <div className="flex border border-zinc-700 rounded-lg overflow-hidden mb-6">
          {(["credentials", "jwt", "dev"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                mode === m
                  ? "bg-zinc-700 text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {m === "credentials" ? "Password" : m === "jwt" ? "JWT" : "Dev"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          {mode === "credentials" && (
            <>
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Username</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="your username"
                  autoFocus
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
                />
              </div>
            </>
          )}

          {mode === "jwt" && (
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Bearer token</label>
              <textarea
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="eyJ..."
                rows={4}
                className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 resize-none focus:outline-none focus:border-zinc-500"
              />
            </div>
          )}

          {mode === "dev" && (
            <>
              <div>
                <label className="block text-xs text-zinc-500 mb-1">User ID</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="alice"
                  className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Role</label>
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Department</label>
                  <select
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-zinc-500"
                  >
                    {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </div>
              </div>
            </>
          )}

          {error && (
            <p className="text-red-400 text-xs bg-red-950/50 border border-red-900 rounded px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || (mode === "jwt" && !token.trim())}
            className="w-full bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
          >
            {loading ? "Authenticating…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
