"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import LoginForm from "@/components/LoginForm";
import type { UserSession } from "@/lib/types";

const SESSION_KEY = "ja_session";

export default function HomePage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored) {
      router.replace("/chat");
    } else {
      setChecking(false);
    }
  }, [router]);

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center text-zinc-600 text-sm">
        Loading…
      </div>
    );
  }

  const handleLogin = (session: UserSession) => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    router.push("/chat");
  };

  return <LoginForm onLogin={handleLogin} />;
}
