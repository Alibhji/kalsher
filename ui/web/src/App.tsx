import { useEffect, useMemo, useState } from "react";
import { fetchMarkets } from "./api";
import { marketStore } from "./store/marketStore";
import { useMarketStoreConnected, useStructuralMarketRows, useThrottledMarketRows } from "./store/useMarketStore";
import { ResetPlatformButton } from "./components/ResetPlatformButton";
import { MarketFiltersBar } from "./components/MarketFilters";
import { MarketsGrouped } from "./components/MarketsGrouped";
import { OpenExposurePanel } from "./components/OpenExposurePanel";
import { TradingSidebar } from "./components/TradingSidebar";
import { NotificationCenter } from "./components/NotificationCenter";
import { AppNav } from "./components/AppNav";
import { ExperimentHistoryPage } from "./pages/ExperimentHistoryPage";
import { ExperimentDetailPage } from "./pages/ExperimentDetailPage";
import { ArchivePage } from "./pages/ArchivePage";
import { ArchiveDetailPage } from "./pages/ArchiveDetailPage";
import { useHashRoute } from "./lib/routes";
import {
  applyMarketFilters,
  countLive,
  DEFAULT_FILTERS,
  type MarketFilters,
} from "./lib/filters";
import { groupMarkets } from "./lib/groupMarkets";

const GROUP_RECOMPUTE_MS = 500;
const GROUP_SORT_MS = 10000;
const FILTER_TICK_MS = 2000;

type LoadState = "loading" | "ready" | "error";

export default function App() {
  const route = useHashRoute();

  if (route.page === "history") {
    return <ExperimentHistoryPage />;
  }
  if (route.page === "history-detail") {
    return <ExperimentDetailPage experimentId={route.experimentId} />;
  }
  if (route.page === "archive") {
    return <ArchivePage />;
  }
  if (route.page === "archive-detail") {
    return (
      <ArchiveDetailPage
        eventTicker={route.eventTicker}
        experimentId={route.experimentId}
      />
    );
  }

  return <MarketsDashboard />;
}

function MarketsDashboard() {
  const structuralMarkets = useStructuralMarketRows();
  const liveMarkets = useThrottledMarketRows(GROUP_RECOMPUTE_MS);
  const connected = useMarketStoreConnected();
  const [filters, setFilters] = useState<MarketFilters>(DEFAULT_FILTERS);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [groupNowMs, setGroupNowMs] = useState(() => Date.now());
  const [sortTick, setSortTick] = useState(0);
  const [tradeDrawerOpen, setTradeDrawerOpen] = useState(false);

  // sortTick only matters when the ordering itself depends on live volume.
  const volumeSorted = filters.sortBy === "volume" || filters.sortParentByVolume;
  const sortSeed = volumeSorted ? sortTick : 0;
  const structureMarkets = useMemo(
    () => applyMarketFilters(structuralMarkets, filters, groupNowMs, { keepNoLiquidity: true }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sortSeed forces a periodic re-sort
    [structuralMarkets, filters, groupNowMs, sortSeed],
  );

  const visibleSubCount = useMemo(
    () =>
      groupMarkets(structureMarkets, {
        sortSubByVolume: filters.sortSubByVolume,
        hideNoLiquidity: filters.hideNoLiquidity,
      }).reduce((n, s) => n + s.events.reduce((m, e) => m + e.markets.length, 0), 0),
    [structureMarkets, filters.sortSubByVolume, filters.hideNoLiquidity],
  );

  const liveCount = useMemo(() => countLive(liveMarkets, groupNowMs), [liveMarkets, groupNowMs]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const payload = await fetchMarkets();
        if (cancelled) return;
        marketStore.seed(payload.markets);
        setState("ready");
        setError(null);
        setUpdatedAt(new Date());
      } catch (err) {
        if (cancelled) return;
        setState("error");
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    }

    bootstrap();
    marketStore.connect();

    const unsub = marketStore.subscribeAll(() => {
      if (marketStore.getSnapshot().length > 0) {
        setState("ready");
        setError(null);
      }
    });

    return () => {
      cancelled = true;
      unsub();
      marketStore.disconnect();
    };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setGroupNowMs(Date.now()), FILTER_TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!volumeSorted) return;
    const id = window.setInterval(() => setSortTick((t) => t + 1), GROUP_SORT_MS);
    return () => window.clearInterval(id);
  }, [volumeSorted]);

  return (
    <div className="flex min-h-screen">
      <NotificationCenter />
      <OpenExposurePanel />
      <TradingSidebar mobileOpen={tradeDrawerOpen} onCloseMobile={() => setTradeDrawerOpen(false)} />
      <div className="mx-auto min-h-screen min-w-0 flex-1 max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="sticky top-0 z-50 -mx-4 mb-4 border-b border-ink-800/80 bg-[#0b1220]/95 px-4 py-2 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <AppNav active="markets" />
            <button
              type="button"
              className="rounded border border-ink-700 px-2 py-1 text-xs text-ink-300 lg:hidden"
              onClick={() => setTradeDrawerOpen(true)}
            >
              Trade
            </button>
            <span className="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900/80 px-3 py-1.5 text-sm text-ink-400">
              <span className={`live-dot h-2 w-2 rounded-full ${connected ? "bg-accent" : "bg-amber-500"}`} />
              {state === "loading"
                ? "Connecting"
                : `${liveCount} live / ${structuralMarkets.length} total`}
            </span>
            {updatedAt ? (
              <span className="font-mono text-xs">Updated {updatedAt.toLocaleTimeString()}</span>
            ) : null}
          </div>
          <ResetPlatformButton />
        </div>
      </div>

      <header className="mb-6 animate-fade-in">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">Kalshi live</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-50">Active Markets</h1>
            <p className="mt-2 max-w-xl text-sm text-ink-400">
              Live dashboard only — open bets for the current window. Settled markets appear in the
              Archive tab.
            </p>
          </div>
        </div>
      </header>

      {state === "loading" ? (
        <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center animate-fade-in">
          <p className="text-ink-300">Loading markets…</p>
        </div>
      ) : null}

      {state === "error" ? (
        <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-6 py-10 text-center animate-fade-in">
          <p className="font-medium text-red-300">Could not reach the API</p>
          <p className="mt-2 font-mono text-sm text-red-400">{error}</p>
        </div>
      ) : null}

      {state === "ready" ? (
        <>
          <MarketFiltersBar
            markets={liveMarkets}
            filters={filters}
            filteredCount={visibleSubCount}
            onChange={setFilters}
          />
          <MarketsGrouped
            markets={structureMarkets}
            hideNoLiquidity={filters.hideNoLiquidity}
            sortSubByVolume={filters.sortSubByVolume}
            sortParentByVolume={filters.sortParentByVolume}
            onToggleSortParentByVolume={() =>
              setFilters((prev) => ({ ...prev, sortParentByVolume: !prev.sortParentByVolume }))
            }
            filtersActive={
              filters.search !== "" ||
              !filters.liveOnly ||
              filters.hasQuotes ||
              filters.hideNoLiquidity ||
              !filters.sortSubByVolume ||
              filters.category !== "all" ||
              filters.series !== "all" ||
              filters.closingWithinMinutes != null ||
              filters.minVolume > 0
            }
          />
        </>
      ) : null}
      </div>
    </div>
  );
}
