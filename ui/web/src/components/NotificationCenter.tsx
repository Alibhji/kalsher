import { createPortal } from "react-dom";
import { useNotifications } from "../hooks/useNotifications";
import { notificationStore, type NotificationLevel } from "../store/notificationStore";

const LEVEL_STYLES: Record<
  NotificationLevel,
  { border: string; bg: string; icon: string; title: string; accent: string }
> = {
  success: {
    border: "border-emerald-800/60",
    bg: "bg-emerald-950/95",
    icon: "text-emerald-400",
    title: "text-emerald-100",
    accent: "bg-emerald-500/20",
  },
  error: {
    border: "border-red-800/60",
    bg: "bg-red-950/95",
    icon: "text-red-400",
    title: "text-red-100",
    accent: "bg-red-500/20",
  },
  warning: {
    border: "border-amber-800/60",
    bg: "bg-amber-950/95",
    icon: "text-amber-400",
    title: "text-amber-100",
    accent: "bg-amber-500/20",
  },
  info: {
    border: "border-sky-800/60",
    bg: "bg-sky-950/95",
    icon: "text-sky-400",
    title: "text-sky-100",
    accent: "bg-sky-500/20",
  },
};

function LevelIcon({ level }: { level: NotificationLevel }) {
  const cls = LEVEL_STYLES[level].icon;
  if (level === "success") {
    return (
      <svg viewBox="0 0 20 20" className={`h-5 w-5 shrink-0 ${cls}`} fill="currentColor" aria-hidden="true">
        <path
          fillRule="evenodd"
          d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z"
          clipRule="evenodd"
        />
      </svg>
    );
  }
  if (level === "error") {
    return (
      <svg viewBox="0 0 20 20" className={`h-5 w-5 shrink-0 ${cls}`} fill="currentColor" aria-hidden="true">
        <path
          fillRule="evenodd"
          d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM8.28 7.22a.75.75 0 0 0-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 1 0 1.06 1.06L10 11.06l1.72 1.72a.75.75 0 1 0 1.06-1.06L11.06 10l1.72-1.72a.75.75 0 0 0-1.06-1.06L10 8.94 8.28 7.22Z"
          clipRule="evenodd"
        />
      </svg>
    );
  }
  if (level === "warning") {
    return (
      <svg viewBox="0 0 20 20" className={`h-5 w-5 shrink-0 ${cls}`} fill="currentColor" aria-hidden="true">
        <path
          fillRule="evenodd"
          d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
          clipRule="evenodd"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" className={`h-5 w-5 shrink-0 ${cls}`} fill="currentColor" aria-hidden="true">
      <path
        fillRule="evenodd"
        d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export function NotificationCenter() {
  const items = useNotifications();
  if (items.length === 0) return null;

  const panel = (
    <div
      className="pointer-events-none fixed right-4 top-4 z-[300] flex w-full max-w-sm flex-col gap-2"
      aria-live="polite"
      aria-relevant="additions"
    >
      {items.map((item) => {
        const styles = LEVEL_STYLES[item.level];
        return (
          <div
            key={item.id}
            role="alert"
            className={`pointer-events-auto animate-toast-in overflow-hidden rounded-lg border shadow-2xl shadow-black/40 backdrop-blur-sm ${styles.border} ${styles.bg}`}
          >
            <div className="flex gap-3 px-4 py-3">
              <div className={`mt-0.5 flex h-8 w-8 items-center justify-center rounded-full ${styles.accent}`}>
                <LevelIcon level={item.level} />
              </div>
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-semibold leading-snug ${styles.title}`}>{item.title}</p>
                {item.message ? (
                  <p className="mt-1 text-xs leading-relaxed text-ink-300/90">{item.message}</p>
                ) : null}
              </div>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => notificationStore.dismiss(item.id)}
                className="shrink-0 rounded p-1 text-ink-500 transition-colors hover:bg-ink-900/60 hover:text-ink-200"
              >
                <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden="true">
                  <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.72 10l-3.5 3.5a.75.75 0 1 0 1.06 1.06L10 11.06l3.5 3.5a.75.75 0 1 0 1.06-1.06L11.06 10l3.5-3.5a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                </svg>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );

  return typeof document !== "undefined" ? createPortal(panel, document.body) : null;
}
