export function formatVolume(value: string | null): string {
  if (!value) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatCents(bid: number | null, ask: number | null): string {
  if (bid == null && ask == null) return "—";
  if (bid != null && ask != null) return `${bid}¢ / ${ask}¢`;
  if (bid != null) return `${bid}¢`;
  return `${ask}¢`;
}

export function formatStrike(
  floor: number | null,
  cap: number | null,
  strikeType: string | null,
): string {
  if (floor == null && cap == null) return "—";
  if (floor != null && cap != null) return `${floor} – ${cap}`;
  if (floor != null) return String(floor);
  return String(cap);
}

export function formatCountdown(seconds: number | null, nowMs: number, closeTime: string | null): string {
  let remaining = seconds;
  if (closeTime) {
    const closeMs = Date.parse(closeTime);
    if (!Number.isNaN(closeMs)) {
      remaining = Math.max(0, Math.floor((closeMs - nowMs) / 1000));
    }
  }
  if (remaining == null) return "—";
  if (remaining <= 0) return "closed";

  const h = Math.floor(remaining / 3600);
  const m = Math.floor((remaining % 3600) / 60);
  const s = remaining % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

export function countdownTone(seconds: number | null, nowMs: number, closeTime: string | null): "normal" | "warn" | "urgent" {
  let remaining = seconds;
  if (closeTime) {
    const closeMs = Date.parse(closeTime);
    if (!Number.isNaN(closeMs)) {
      remaining = Math.max(0, Math.floor((closeMs - nowMs) / 1000));
    }
  }
  if (remaining == null) return "normal";
  if (remaining <= 60) return "urgent";
  if (remaining <= 300) return "warn";
  return "normal";
}
