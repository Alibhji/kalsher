import { useSyncExternalStore } from "react";
import { notificationStore } from "../store/notificationStore";

export function useNotifications() {
  return useSyncExternalStore(
    (cb) => notificationStore.subscribe(cb),
    () => notificationStore.getSnapshot(),
    () => notificationStore.getSnapshot(),
  );
}
