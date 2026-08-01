import { useMemo, useState } from "react";
import {
  DEFAULT_FILTERS,
  extractFilterOptions,
  type MarketFilters,
  type SortKey,
} from "../lib/filters";
import type { MarketRow } from "../api";

type Props = {
  markets: MarketRow[];
  filters: MarketFilters;
  filteredCount: number;
  onChange: (filters: MarketFilters) => void;
};

const CLOSING_OPTIONS: { label: string; value: number | null }[] = [
  { label: "Any time", value: null },
  { label: "≤ 15 min", value: 15 },
  { label: "≤ 1 hour", value: 60 },
  { label: "≤ 3 hours", value: 180 },
];

const SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: "Soonest close", value: "close_time" },
  { label: "Highest volume", value: "volume" },
  { label: "Series A–Z", value: "series" },
];

export function MarketFiltersBar({ markets, filters, filteredCount, onChange }: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const options = useMemo(() => extractFilterOptions(markets), [markets]);

  function patch(partial: Partial<MarketFilters>) {
    onChange({ ...filters, ...partial });
  }

  function reset() {
    onChange(DEFAULT_FILTERS);
  }

  const activeAdvanced =
    filters.category !== "all" ||
    filters.series !== "all" ||
    filters.fifteenMinOnly ||
    filters.closingWithinMinutes != null ||
    filters.minVolume > 0 ||
    filters.hasQuotes ||
    !filters.hideNoLiquidity ||
    !filters.sortSubByVolume ||
    filters.sortParentByVolume ||
    filters.sortBy !== "close_time";

  return (
    <div className="mb-4 space-y-3 animate-fade-in">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[240px] flex-1">
          <input
            type="search"
            value={filters.search}
            onChange={(e) => patch({ search: e.target.value })}
            placeholder="Search ticker, title, series…"
            className="w-full rounded-lg border border-ink-700 bg-ink-950/80 px-4 py-2.5 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-ink-700 bg-ink-950/80 px-3 py-2.5 text-sm">
          <input
            type="checkbox"
            checked={filters.liveOnly}
            onChange={(e) => patch({ liveOnly: e.target.checked })}
            className="accent-accent"
          />
          <span className="text-ink-200">Live bets only</span>
        </label>

        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-ink-700 bg-ink-950/80 px-3 py-2.5 text-sm">
          <input
            type="checkbox"
            checked={filters.hideNoLiquidity}
            onChange={(e) => patch({ hideNoLiquidity: e.target.checked })}
            className="accent-accent"
          />
          <span className="text-ink-200">Hide no liquidity</span>
        </label>

        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-ink-700 bg-ink-950/80 px-3 py-2.5 text-sm">
          <input
            type="checkbox"
            checked={filters.sortSubByVolume}
            onChange={(e) => patch({ sortSubByVolume: e.target.checked })}
            className="accent-accent"
          />
          <span className="text-ink-200">Sort strikes by volume</span>
        </label>

        <button
          type="button"
          onClick={() => patch({ fifteenMinOnly: !filters.fifteenMinOnly })}
          className={`rounded-lg border px-3 py-2.5 text-sm transition-colors ${
            filters.fifteenMinOnly
              ? "border-accent/50 bg-accent/10 text-accent"
              : "border-ink-700 bg-ink-950/80 text-ink-300 hover:border-ink-600"
          }`}
        >
          15-min only
        </button>

        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className={`rounded-lg border px-3 py-2.5 text-sm transition-colors ${
            advancedOpen || activeAdvanced
              ? "border-accent/50 bg-accent/10 text-accent"
              : "border-ink-700 bg-ink-950/80 text-ink-300 hover:border-ink-600"
          }`}
        >
          Advanced filters{activeAdvanced ? " •" : ""}
        </button>

        {(filters.search ||
          !filters.liveOnly ||
          filters.fifteenMinOnly ||
          filters.hasQuotes ||
          !filters.hideNoLiquidity ||
          !filters.sortSubByVolume ||
          filters.sortParentByVolume ||
          activeAdvanced) && (
          <button
            type="button"
            onClick={reset}
            className="rounded-lg px-3 py-2.5 text-sm text-ink-400 hover:text-ink-200"
          >
            Reset
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
        <span>
          Showing <span className="font-mono text-ink-300">{filteredCount}</span> of{" "}
          <span className="font-mono text-ink-300">{markets.length}</span>
        </span>
        {filters.liveOnly ? (
          <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent">
            live + active
          </span>
        ) : null}
        {filters.fifteenMinOnly ? (
          <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent">
            15-min series
          </span>
        ) : null}
        {filters.hideNoLiquidity ? (
          <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent">
            liquid only
          </span>
        ) : null}
        {filters.sortSubByVolume ? (
          <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent">
            vol sort (strikes)
          </span>
        ) : null}
        {filters.sortParentByVolume ? (
          <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-accent">
            vol sort (parents)
          </span>
        ) : null}
      </div>

      {advancedOpen ? (
        <div className="grid gap-4 rounded-lg border border-ink-800 bg-ink-950/60 p-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <label className="block text-xs text-ink-400">
            Category
            <select
              value={filters.category}
              onChange={(e) => patch({ category: e.target.value })}
              className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-ink-100"
            >
              <option value="all">All categories</option>
              {options.categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs text-ink-400">
            Series
            <select
              value={filters.series}
              onChange={(e) => patch({ series: e.target.value })}
              className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-ink-100"
            >
              <option value="all">All series</option>
              {options.series.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs text-ink-400">
            Closing within
            <select
              value={filters.closingWithinMinutes ?? ""}
              onChange={(e) =>
                patch({
                  closingWithinMinutes: e.target.value === "" ? null : Number(e.target.value),
                })
              }
              className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-ink-100"
            >
              {CLOSING_OPTIONS.map((o) => (
                <option key={o.label} value={o.value ?? ""}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs text-ink-400">
            Min volume
            <input
              type="number"
              min={0}
              step={1}
              value={filters.minVolume || ""}
              onChange={(e) => patch({ minVolume: Number(e.target.value) || 0 })}
              placeholder="0"
              className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-ink-100"
            />
          </label>

          <label className="block text-xs text-ink-400">
            Sort by
            <select
              value={filters.sortBy}
              onChange={(e) => patch({ sortBy: e.target.value as SortKey })}
              className="mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-2 py-2 text-sm text-ink-100"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-end gap-2 pb-2 text-sm text-ink-200">
            <input
              type="checkbox"
              checked={filters.hasQuotes}
              onChange={(e) => patch({ hasQuotes: e.target.checked })}
              className="accent-accent"
            />
            Has YES quotes
          </label>
        </div>
      ) : null}
    </div>
  );
}
