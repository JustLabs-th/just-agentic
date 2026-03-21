"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import ChatWindow from "@/components/ChatWindow";
import type { UserSession } from "@/lib/types";

const SESSION_KEY = "ja_session";

export default function ChatPage() {
  const router = useRouter();
  const [session, setSession] = useState<UserSession | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY);
    if (!stored) {
      router.replace("/");
      return;
    }
    try {
      setSession(JSON.parse(stored) as UserSession);
    } catch {
      localStorage.removeItem(SESSION_KEY);
      router.replace("/");
    }
  }, [router]);

  const handleLogout = () => {
    localStorage.removeItem(SESSION_KEY);
    router.push("/");
  };

  if (!session) {
    return (
      <div className="min-h-screen flex items-center justify-center text-zinc-600 text-sm">
        Loading…
      </div>
    );
  }

  return <ChatWindow session={session} onLogout={handleLogout} />;
}
