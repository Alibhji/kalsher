import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { fetchMarketRules } from "../api";

type Props = {
  ticker: string;
  active: boolean;
};

type LoadState = "idle" | "loading" | "ready" | "error";

export function MarketRulesPanel({ ticker, active }: Props) {
  const [state, setState] = useState<LoadState>("idle");
  const [markdown, setMarkdown] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    setState("loading");
    setError(null);

    fetchMarketRules(ticker)
      .then((payload) => {
        if (cancelled) return;
        setMarkdown(payload.markdown);
        setState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setState("error");
        setError(err instanceof Error ? err.message : "Failed to load rules");
      });

    return () => {
      cancelled = true;
    };
  }, [active, ticker]);

  if (state === "loading" || state === "idle") {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-md border border-ink-800/80 text-sm text-ink-500">
        Loading market rules…
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-md border border-ink-800/80 px-6 text-center text-sm text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-y-auto rounded-md border border-ink-800/80 bg-ink-950/60 px-4 py-4">
      <article className="market-rules-md text-sm leading-relaxed text-ink-200">
        <ReactMarkdown>{markdown}</ReactMarkdown>
      </article>
    </div>
  );
}
