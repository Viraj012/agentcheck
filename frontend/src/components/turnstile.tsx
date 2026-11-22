"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef } from "react";

/** Cloudflare's always-pass test key; real deployments set NEXT_PUBLIC_TURNSTILE_SITE_KEY. */
const TEST_SITE_KEY = "1x00000000000000000000AA";
const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || TEST_SITE_KEY;

type TurnstileApi = {
  render: (el: HTMLElement, options: Record<string, unknown>) => string;
  reset: (id: string) => void;
  remove: (id: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** Renders the bot check and reports each new token (null when it expires or fails). */
export function Turnstile({ onToken, resetKey }: { onToken: (token: string | null) => void; resetKey: number }) {
  const container = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);

  const render = useCallback(() => {
    if (!window.turnstile || !container.current || widget.current) return;
    widget.current = window.turnstile.render(container.current, {
      sitekey: SITE_KEY,
      callback: (token: string) => onToken(token),
      "expired-callback": () => onToken(null),
      "error-callback": () => onToken(null),
    });
  }, [onToken]);

  useEffect(() => {
    render();
    return () => {
      if (widget.current) window.turnstile?.remove(widget.current);
      widget.current = null;
    };
  }, [render]);

  useEffect(() => {
    if (resetKey > 0 && widget.current) {
      onToken(null);
      window.turnstile?.reset(widget.current);
    }
  }, [resetKey, onToken]);

  return (
    <>
      <Script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" onReady={render} />
      <div ref={container} className="mt-3 min-h-[65px]" />
    </>
  );
}
