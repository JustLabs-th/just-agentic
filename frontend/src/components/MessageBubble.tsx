import AgentBadge from "./AgentBadge";
import type { ChatMessage } from "@/lib/types";

interface Props {
  message: ChatMessage;
  streaming?: boolean;
}

export default function MessageBubble({ message, streaming }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[75%] bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-2.5">
          <p className="text-zinc-100 text-sm whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-4 gap-2">
      <div className="max-w-[80%] space-y-1.5">
        {/* Agent badge */}
        {message.agent && (
          <div className="flex items-center gap-2">
            <AgentBadge
              agent={message.agent}
              intent={message.intent}
              confidence={message.confidence}
            />
          </div>
        )}

        {/* Message content */}
        <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2.5">
          <p
            className={`text-zinc-100 text-sm whitespace-pre-wrap break-words leading-relaxed ${
              streaming ? "streaming-cursor" : ""
            }`}
          >
            {message.content}
          </p>
        </div>
      </div>
    </div>
  );
}
