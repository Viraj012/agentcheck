"use client";

import { useState } from "react";

export function ShareLink() {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }
  return (
    <button type="button" onClick={copy} className="font-semibold text-accent">
      <span aria-live="polite">{copied ? "Link copied" : "Copy link to this report"}</span>
    </button>
  );
}
