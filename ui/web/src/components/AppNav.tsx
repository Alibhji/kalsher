type Props = {
  active: "markets" | "history";
};

export function AppNav({ active }: Props) {
  const link = (page: "markets" | "history", href: string, label: string) => (
    <a
      href={href}
      className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
        active === page
          ? "bg-accent/15 text-accent"
          : "text-ink-400 hover:bg-ink-800/80 hover:text-ink-200"
      }`}
    >
      {label}
    </a>
  );

  return (
    <nav className="flex flex-wrap items-center gap-1">
      {link("markets", "#/", "Markets")}
      {link("history", "#/history", "Trade History")}
    </nav>
  );
}
