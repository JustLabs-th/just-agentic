"use client";

import { useState } from "react";
import type { ToolCallEvent } from "@/lib/types";

const TOOL_ICONS: Record<string, string> = {
  read_file:       "📄",
  write_file:      "✏️",
  edit_file:       "✏️",
  list_files:      "📁",
  search_code:     "🔍",
  read_log:        "📋",
  run_shell:       "⚡",
  git_status:      "🌿",
  execute_python:  "🐍",
  run_tests:       "🧪",
  get_env:         "🔐",
  web_search:      "🌐",
  scrape_page:     "🕷️",
  query_db:        "🗄️",
  scan_secrets:    "🔒",
  search_knowledge:"📚",
};

interface Props {
  event: ToolCallEvent;
}

export default function ToolCallBubble({ event }: Props) {
  const [expanded, setExpanded] = useState(false);
  const icon = TOOL_ICONS[event.tool] ?? "🔧";
  const hasInput = Object.keys(event.input).length > 0;

  // Pretty-print the most relevant input field inline
  const primaryArg = (() => {
    const args = event.input;
    for (const k of ["path", "keyword", "query", "command", "url", "code"]) {
      if (typeof args[k] === "string") return args[k] as string;
    }
    return null;
  })();

  return (
    <div className="flex justify-start mb-1 ml-1">
      <button
        onClick={() => hasInput && setExpanded((v) => !v)}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs text-zinc-500 border border-zinc-800 bg-zinc-950 transition-colors ${
          hasInput ? "hover:border-zinc-700 hover:text-zinc-400 cursor-pointer" : "cursor-default"
        }`}
      >
        <span>{icon}</span>
        <span className="font-mono">{event.tool}</span>
        {primaryArg && !expanded && (
          <span className="text-zinc-600 max-w-[200px] truncate">
            {primaryArg}
          </span>
        )}
        {hasInput && (
          <span className="text-zinc-700">{expanded ? "▴" : "▾"}</span>
        )}
      </button>

      {expanded && hasInput && (
        <div className="ml-2 mt-1 px-2 py-1 rounded border border-zinc-800 bg-zinc-950 text-xs font-mono text-zinc-500 max-w-[400px] overflow-auto whitespace-pre">
          {JSON.stringify(event.input, null, 2)}
        </div>
      )}
    </div>
  );
}
