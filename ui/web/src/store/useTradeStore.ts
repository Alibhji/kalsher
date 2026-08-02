import { tradeStore } from "../store/tradeStore";

const seedGeneration = new Map<string, number>();

export async function seedTradesSinceOpen(ticker: string, sinceIso: string | null | undefined): Promise<void> {
  if (!sinceIso) return;
  // Rapid expand/collapse can overlap fetches; only the newest result may land.
  const generation = (seedGeneration.get(ticker) ?? 0) + 1;
  seedGeneration.set(ticker, generation);

  tradeStore.ensureWindow(ticker, sinceIso);
  const { fetchMarketTrades } = await import("../api");
  const trades = await fetchMarketTrades(ticker, { since: sinceIso, limit: 5000 });
  if (seedGeneration.get(ticker) !== generation) return;
  tradeStore.seedTrades(ticker, trades, sinceIso);
}
