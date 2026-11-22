"use client";

import { useEffect, useState } from "react";

import { fetchHealth, type BackendHealth } from "@/lib/api";

export function HealthStatus() {
  const [health, setHealth] = useState<BackendHealth | "checking">("checking");

  useEffect(() => {
    fetchHealth().then(setHealth);
  }, []);

  const color =
    health === "ok" ? "text-green-700" : health === "unreachable" ? "text-red-700" : "text-zinc-500";

  return (
    <p role="status" className={`font-mono ${color}`}>
      backend: {health === "checking" ? "checking…" : health}
    </p>
  );
}
