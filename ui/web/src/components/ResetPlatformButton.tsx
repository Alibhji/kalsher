import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { resetPlatform } from "../api";

const CONFIRM_PHRASE = "RESET PLATFORM";

type Step = "closed" | "warn" | "confirm";

export function ResetPlatformButton() {
  const [step, setStep] = useState<Step>("closed");
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  useEffect(() => {
    if (step === "closed") return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [step]);

  useEffect(() => {
    if (step === "closed") return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) close();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [step, busy]);

  function close() {
    if (busy) return;
    setStep("closed");
    setPhrase("");
    setError(null);
  }

  async function submit() {
    if (phrase.trim() !== CONFIRM_PHRASE) {
      setError(`Type exactly: ${CONFIRM_PHRASE}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await resetPlatform(CONFIRM_PHRASE);
      setSummary("Reset complete — all data cleared. Reloading…");
      setStep("closed");
      setPhrase("");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  }

  const modal =
    step !== "closed" ? (
      <div
        className="fixed inset-0 z-[200] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"
        role="presentation"
        onClick={close}
      >
        <div
          className="w-full max-w-md rounded-xl border border-ink-700 bg-ink-950 p-6 shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="reset-platform-title"
          onClick={(e) => e.stopPropagation()}
        >
          {step === "warn" ? (
            <>
              <h2 id="reset-platform-title" className="text-lg font-semibold text-ink-50">
                Reset the entire platform?
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-ink-400">
                This wipes everything and returns the stack to a brand-new state:
              </p>
              <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-ink-500">
                <li>TimescaleDB — ticks, trades, books, underlying, markets, trading experiments</li>
                <li>Redis — universe, live quotes, order books, streams</li>
              </ul>
              <p className="mt-3 text-sm text-ink-500">
                The fetcher keeps running and will rebuild the live universe on the next discovery
                scan. Historical charts stay empty until new data arrives.
              </p>
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={close}
                  className="rounded-lg px-4 py-2 text-sm text-ink-400 hover:text-ink-200"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setStep("confirm");
                    setError(null);
                  }}
                  className="rounded-lg border border-red-800 bg-red-950/60 px-4 py-2 text-sm text-red-200 hover:bg-red-950"
                >
                  Continue
                </button>
              </div>
            </>
          ) : (
            <>
              <h2 id="reset-platform-title" className="text-lg font-semibold text-red-300">
                Final confirmation
              </h2>
              <p className="mt-3 text-sm text-ink-400">
                Type <span className="font-mono text-red-300">{CONFIRM_PHRASE}</span> to confirm.
                This cannot be undone.
              </p>
              <input
                type="text"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy && phrase.trim() === CONFIRM_PHRASE) {
                    e.preventDefault();
                    void submit();
                  }
                }}
                placeholder={CONFIRM_PHRASE}
                autoFocus
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
                className="mt-4 w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2.5 font-mono text-sm text-ink-100 placeholder:text-ink-600 focus:border-red-700 focus:outline-none focus:ring-1 focus:ring-red-800"
              />
              {error ? <p className="mt-2 text-sm text-red-400">{error}</p> : null}
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setStep("warn");
                    setPhrase("");
                    setError(null);
                  }}
                  disabled={busy}
                  className="rounded-lg px-4 py-2 text-sm text-ink-400 hover:text-ink-200 disabled:opacity-50"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={busy || phrase.trim() !== CONFIRM_PHRASE}
                  className="rounded-lg border border-red-700 bg-red-900/80 px-4 py-2 text-sm font-medium text-red-100 hover:bg-red-900 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {busy ? "Resetting…" : "Reset platform"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    ) : null;

  const toast = summary ? (
    <div className="fixed bottom-4 right-4 z-[200] max-w-sm rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 text-xs text-ink-300 shadow-xl">
      {summary}
    </div>
  ) : null;

  return (
    <>
      <button
        type="button"
        onClick={() => setStep("warn")}
        className="shrink-0 rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300 transition-colors hover:border-red-700 hover:bg-red-950/70 hover:text-red-200"
      >
        Reset platform
      </button>
      {typeof document !== "undefined"
        ? createPortal(
            <>
              {modal}
              {toast}
            </>,
            document.body,
          )
        : null}
    </>
  );
}
