import { useEffect, useState } from "react";

export type AppRoute =
  | { page: "markets" }
  | { page: "history" }
  | { page: "history-detail"; experimentId: string };

export function parseRoute(hash: string): AppRoute {
  const path = hash.replace(/^#/, "") || "/";
  if (path === "/history" || path === "/experiments") {
    return { page: "history" };
  }
  const detail = path.match(/^\/history\/([0-9a-f-]{36})$/i);
  if (detail) {
    return { page: "history-detail", experimentId: detail[1] };
  }
  return { page: "markets" };
}

export function navigateTo(route: AppRoute) {
  if (route.page === "markets") {
    window.location.hash = "/";
  } else if (route.page === "history") {
    window.location.hash = "/history";
  } else {
    window.location.hash = `/history/${route.experimentId}`;
  }
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
