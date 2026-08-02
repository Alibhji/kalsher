import { useEffect, useState } from "react";

export type AppRoute =
  | { page: "markets" }
  | { page: "archive" }
  | { page: "archive-detail"; eventTicker: string; experimentId?: string }
  | { page: "history" }
  | { page: "history-detail"; experimentId: string };

export function parseRoute(hash: string): AppRoute {
  const raw = hash.replace(/^#/, "") || "/";
  const qIdx = raw.indexOf("?");
  const path = qIdx >= 0 ? raw.slice(0, qIdx) : raw;
  const query = qIdx >= 0 ? raw.slice(qIdx + 1) : "";
  const params = new URLSearchParams(query);

  if (path === "/history" || path === "/experiments") {
    return { page: "history" };
  }
  const detail = path.match(/^\/history\/([0-9a-f-]{36})$/i);
  if (detail) {
    return { page: "history-detail", experimentId: detail[1] };
  }
  if (path === "/archive") {
    return { page: "archive" };
  }
  const archiveDetail = path.match(/^\/archive\/(.+)$/);
  if (archiveDetail) {
    return {
      page: "archive-detail",
      eventTicker: decodeURIComponent(archiveDetail[1]),
      experimentId: params.get("exp") ?? undefined,
    };
  }
  return { page: "markets" };
}

export function useHashRoute(): AppRoute {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return route;
}
