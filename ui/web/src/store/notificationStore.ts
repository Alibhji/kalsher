export type NotificationLevel = "success" | "error" | "warning" | "info";

export type Notification = {
  id: string;
  level: NotificationLevel;
  title: string;
  message?: string;
  durationMs: number;
  createdAt: number;
};

type Listener = () => void;

const DEFAULT_DURATION: Record<NotificationLevel, number> = {
  success: 4500,
  error: 8000,
  warning: 7000,
  info: 5000,
};

class NotificationStore {
  private items: Notification[] = [];
  private listeners = new Set<Listener>();
  private timers = new Map<string, number>();
  private snapshot: Notification[] = [];

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getSnapshot(): Notification[] {
    return this.snapshot;
  }

  private emit() {
    this.snapshot = [...this.items];
    for (const l of this.listeners) l();
  }

  notify(input: {
    level: NotificationLevel;
    title: string;
    message?: string;
    durationMs?: number;
    id?: string;
  }): string {
    const id = input.id ?? `n-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const durationMs = input.durationMs ?? DEFAULT_DURATION[input.level];

    const existingIdx = input.id ? this.items.findIndex((n) => n.id === input.id) : -1;
    const next: Notification = {
      id,
      level: input.level,
      title: input.title,
      message: input.message,
      durationMs,
      createdAt: Date.now(),
    };

    if (existingIdx >= 0) {
      this.items[existingIdx] = next;
    } else {
      this.items = [next, ...this.items].slice(0, 6);
    }

    const prevTimer = this.timers.get(id);
    if (prevTimer != null) window.clearTimeout(prevTimer);
    this.timers.set(
      id,
      window.setTimeout(() => this.dismiss(id), durationMs),
    );

    this.emit();
    return id;
  }

  dismiss(id: string) {
    const timer = this.timers.get(id);
    if (timer != null) {
      window.clearTimeout(timer);
      this.timers.delete(id);
    }
    const next = this.items.filter((n) => n.id !== id);
    if (next.length === this.items.length) return;
    this.items = next;
    this.emit();
  }

  clearAll() {
    for (const timer of this.timers.values()) window.clearTimeout(timer);
    this.timers.clear();
    this.items = [];
    this.emit();
  }
}

export const notificationStore = new NotificationStore();

export function notifySuccess(title: string, message?: string) {
  notificationStore.notify({ level: "success", title, message });
}

export function notifyError(title: string, message?: string) {
  notificationStore.notify({ level: "error", title, message });
}

export function notifyWarning(title: string, message?: string, id?: string) {
  notificationStore.notify({ level: "warning", title, message, id });
}

export function notifyInfo(title: string, message?: string) {
  notificationStore.notify({ level: "info", title, message });
}
