"use client";

import { useEffect, useState } from "react";
import { api, type Meta } from "@/lib/api";

export function AiBadge() {
  const [meta, setMeta] = useState<Meta | null | "offline">(null);

  useEffect(() => {
    api.meta().then(setMeta, () => setMeta("offline"));
  }, []);

  if (meta === null) return null;
  const [dot, text, title] =
    meta === "offline"
      ? ["bg-bad", "Offline", "The API is not reachable"]
      : meta.ai_enabled
        ? ["bg-good", "AI on", `Groq · ${meta.model ?? ""}`]
        : ["bg-muted", "AI off", "Set GROQ_API_KEY on the backend for AI extraction and explanations"];

  return (
    <span title={title} className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.22em] text-muted">
      <span className={`size-1.5 rounded-full ${dot}`} />
      <span className="hidden sm:inline">{text}</span>
    </span>
  );
}
