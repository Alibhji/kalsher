type Props = {
  url: string;
  className?: string;
};

export function KalshiLink({ url, className = "" }: Props) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      title="Open on Kalshi"
      className={`inline-flex items-center gap-1 rounded-md border border-ink-700 bg-ink-900/80 px-2 py-1 text-xs text-accent transition-colors hover:border-accent/50 hover:bg-accent/10 ${className}`}
    >
      <span>Kalshi</span>
      <span aria-hidden className="text-[10px]">
        ↗
      </span>
    </a>
  );
}
