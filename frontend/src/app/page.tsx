"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import LoginForm from "@/components/LoginForm";
import SetupForm from "@/components/SetupForm";
import { checkSetup } from "@/lib/api";
import type { UserSession } from "@/lib/types";

const SESSION_KEY = "ja_session";

type PageState = "loading" | "setup" | "login";

export default function HomePage() {
  const router = useRouter();
  const [pageState, setPageState] = useState<PageState>("loading");

  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored) {
      router.replace("/chat");
      return;
    }
    checkSetup()
      .then(({ needs_setup }) => setPageState(needs_setup ? "setup" : "login"))
      .catch(() => setPageState("login")); // fallback to login on network error
  }, [router]);

  if (pageState === "loading") {
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

  if (pageState === "setup") {
    return <SetupForm onSetupComplete={handleLogin} />;
  }

  return <LoginForm onLogin={handleLogin} />;
}
