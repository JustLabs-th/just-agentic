"use client";

import type { ApprovalRequest } from "@/lib/types";

interface Props {
  request: ApprovalRequest;
  onApprove: () => void;
  onReject: () => void;
  loading?: boolean;
}

export default function ApprovalDialog({ request, onApprove, onReject, loading }: Props) {
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-amber-700 rounded-lg w-full max-w-md p-6 shadow-2xl">
        {/* Header */}
        <div className="flex items-center gap-2 mb-4">
          <span className="text-amber-400 text-xl">⚠</span>
          <h2 className="text-amber-300 font-bold text-lg">Approval Required</h2>
        </div>

        {/* Details */}
        <div className="space-y-2 mb-6 text-sm">
          <Row label="Agent"  value={request.agent.toUpperCase()} />
          <Row label="Intent" value={request.intent} />
          <Row label="Action" value={request.action || "—"} />
        </div>

        <p className="text-zinc-400 text-xs mb-6">
          This action requires human approval before execution. Review the details above and approve or reject.
        </p>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onApprove}
            disabled={loading}
            className="flex-1 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white font-semibold py-2 rounded transition-colors"
          >
            {loading ? "Processing…" : "Approve"}
          </button>
          <button
            onClick={onReject}
            disabled={loading}
            className="flex-1 bg-red-900 hover:bg-red-800 disabled:opacity-50 text-white font-semibold py-2 rounded transition-colors"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-zinc-500 w-14 shrink-0">{label}:</span>
      <span className="text-zinc-200 break-all">{value}</span>
    </div>
  );
}
