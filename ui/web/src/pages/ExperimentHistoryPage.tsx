import { useEffect, useMemo, useState } from "react";
import {
  deleteExperiment,
  fetchProfile,
  listExperiments,
  type Experiment,
  type Profile,
} from "../api/trading";
import { AppNav } from "../components/AppNav";
import { NotificationCenter } from "../components/NotificationCenter";
import { TagList } from "../components/TagList";
import { formatUsd } from "../lib/format";
import { experimentReturn, formatPnl, formatPnlPct, pnlColorClass, pnlTone } from "../lib/pnl";

type ExperimentSummary = {
  experiment: Experiment;
  profile: Profile;
};

export function ExperimentHistoryPage() {
  const [rows, setRows] = useState<ExperimentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const experiments = await listExperiments(true, tagFilter.trim() || undefined);
      const profiles = await Promise.all(experiments.map((e) => fetchProfile(e.id)));
      setRows(experiments.map((experiment, i) => ({ experiment, profile: profiles[i] })));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load experiments");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [tagFilter]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      for (const tag of row.experiment.tags ?? []) set.add(tag);
    }
    return [...set].sort();
  }, [rows]);

  async function handleDelete(experiment: Experiment) {
    if (
      !window.confirm(
        `Delete "${experiment.name}" permanently? All trades and history for this paper experiment will be removed from the database.`,
      )
    ) {
      return;
    }
    setDeletingId(experiment.id);
    try {
      await deleteExperiment(experiment.id, true);
      setRows((prev) => prev.filter((r) => r.experiment.id !== experiment.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#0b1220]">
      <NotificationCenter />
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="sticky top-0 z-40 -mx-4 mb-6 border-b border-ink-800/80 bg-[#0b1220]/95 px-4 py-3 backdrop-blur-sm sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <AppNav active="history" />
        </div>

        <header className="mb-6 animate-fade-in">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent">Trading ledger</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-50">Trade History</h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-400">
            Filter paper experiments by tag. Live and paper sessions each have their own history page.
          </p>
        </header>

        <div className="mb-6 flex flex-wrap items-end gap-3">
          <label className="block text-xs text-ink-500">
            Filter by tag
            <input
              type="text"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="e.g. strategy-a"
              className="mt-1 block w-48 rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
            />
          </label>
          {allTags.length > 0 ? (
            <div className="flex flex-wrap gap-1 pb-1">
              {allTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => setTagFilter(tag)}
                  className={`rounded-full px-2 py-0.5 text-xs ${
                    tagFilter === tag
                      ? "bg-violet-900/60 text-violet-200 ring-1 ring-violet-700"
                      : "bg-ink-800 text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {tag}
                </button>
              ))}
              {tagFilter ? (
                <button
                  type="button"
                  onClick={() => setTagFilter("")}
                  className="rounded-full px-2 py-0.5 text-xs text-ink-500 hover:text-ink-300"
                >
                  Clear
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        {loading ? (
          <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center">
            <p className="text-ink-300">Loading experiments…</p>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-6 py-10 text-center">
            <p className="font-medium text-red-300">Could not load trade history</p>
            <p className="mt-2 font-mono text-sm text-red-400">{error}</p>
          </div>
        ) : null}

        {!loading && !error ? (
          rows.length === 0 ? (
            <div className="rounded-lg border border-ink-800 bg-ink-900/80 px-6 py-16 text-center">
              <p className="text-ink-300">No experiments match this filter.</p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {rows.map(({ experiment, profile }) => (
                <ExperimentCard
                  key={experiment.id}
                  experiment={experiment}
                  profile={profile}
                  deleting={deletingId === experiment.id}
                  onDelete={() => void handleDelete(experiment)}
                />
              ))}
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}

function ExperimentCard({
  experiment,
  profile,
  deleting,
  onDelete,
}: ExperimentSummary & { deleting: boolean; onDelete: () => void }) {
  const { totalUsd, pct } = experimentReturn(profile);
  const tone = pnlTone(totalUsd);
  const isArchived = Boolean(experiment.archived_at);
  const isPaper = experiment.mode === "paper";

  return (
    <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-5 transition-colors hover:border-accent/40 hover:bg-ink-900">
      <div className="flex items-start justify-between gap-2">
        <a href={`#/history/${experiment.id}`} className="min-w-0 flex-1">
          <h2 className="truncate text-lg font-semibold text-ink-50 hover:text-accent">{experiment.name}</h2>
          <p className="mt-0.5 font-mono text-xs text-ink-500">{experiment.id.slice(0, 8)}…</p>
        </a>
        <ModeBadge mode={experiment.mode} />
      </div>

      {(experiment.tags?.length ?? 0) > 0 ? (
        <div className="mt-2">
          <TagList tags={experiment.tags ?? []} />
        </div>
      ) : null}

      <a href={`#/history/${experiment.id}`} className="mt-4 block">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Metric label="Total P&L" value={formatPnl(totalUsd)} tone={tone} />
          <Metric label="Return" value={formatPnlPct(pct)} tone={tone} />
          <Metric label="Equity" value={formatUsd(Number(profile.equity))} />
          <Metric label="Realized" value={formatPnl(Number(profile.realized_pnl))} tone={pnlTone(Number(profile.realized_pnl))} />
        </div>
      </a>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-ink-500">
        {experiment.created_at ? (
          <span>Started {new Date(experiment.created_at).toLocaleDateString()}</span>
        ) : null}
        {isArchived ? <span className="rounded bg-ink-800 px-2 py-0.5 text-ink-400">Archived</span> : null}
        <span className="rounded bg-ink-800 px-2 py-0.5 capitalize text-ink-400">{experiment.status}</span>
        {isPaper ? (
          <button
            type="button"
            disabled={deleting}
            onClick={onDelete}
            className="ml-auto rounded border border-red-900/50 px-2 py-0.5 text-red-400 hover:bg-red-950/40 disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function ModeBadge({ mode }: { mode: string }) {
  const live = mode === "live";
  return (
    <span
      className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${
        live ? "bg-red-950/80 text-red-300 ring-1 ring-red-800/60" : "bg-sky-950/80 text-sky-300 ring-1 ring-sky-800/60"
      }`}
    >
      {mode}
    </span>
  );
}

function Metric({
  label,
  value,
  tone = "flat",
}: {
  label: string;
  value: string;
  tone?: "profit" | "loss" | "flat";
}) {
  return (
    <div>
      <p className="text-xs text-ink-500">{label}</p>
      <p className={`font-mono text-sm ${pnlColorClass(tone)}`}>{value}</p>
    </div>
  );
}
