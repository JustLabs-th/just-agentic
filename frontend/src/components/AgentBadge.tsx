const AGENT_COLORS: Record<string, string> = {
  backend: "bg-blue-900 text-blue-300 border-blue-700",
  devops:  "bg-orange-900 text-orange-300 border-orange-700",
  qa:      "bg-green-900 text-green-300 border-green-700",
};

interface Props {
  agent: string;
  intent?: string;
  confidence?: number;
  active?: boolean;
}

export default function AgentBadge({ agent, intent, confidence, active }: Props) {
  const colors = AGENT_COLORS[agent] ?? "bg-zinc-800 text-zinc-300 border-zinc-600";
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-semibold uppercase tracking-wider ${colors} ${
        active ? "ring-1 ring-offset-1 ring-offset-zinc-950 ring-current" : ""
      }`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${active ? "bg-current animate-pulse" : "bg-current opacity-40"}`}
      />
      {agent}
      {intent && (
        <span className="opacity-60 normal-case font-normal tracking-normal">
          {intent}
          {confidence !== undefined && ` ${(confidence * 100).toFixed(0)}%`}
        </span>
      )}
    </span>
  );
}
