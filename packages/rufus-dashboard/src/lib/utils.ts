import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Parse a timestamp string as UTC.
 *
 * PostgreSQL/SQLite store timestamps in UTC but serialize them without a
 * timezone suffix (e.g. "2026-03-09T12:33:00").  JavaScript's Date constructor
 * treats such strings as *local* time, which is wrong.  Appending "Z" forces
 * UTC interpretation, after which toLocale* methods convert to the browser's
 * local timezone automatically.
 */
export function parseUtcDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  // Already has timezone info — leave as-is
  const hasOffset = s.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(s);
  const normalized = hasOffset ? s : s + "Z";
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? null : d;
}

/** Format a UTC timestamp as a short date + time in the browser's local timezone. */
export function formatDateTime(s: string | null | undefined): string {
  const d = parseUtcDate(s);
  if (!d) return "—";
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

/** Format a UTC timestamp as a time-only string in the browser's local timezone. */
export function formatTime(s: string | null | undefined): string {
  const d = parseUtcDate(s);
  if (!d) return "—";
  return d.toLocaleTimeString();
}

export function formatRelativeTime(dateStr: string | null | undefined): string {
  const d = parseUtcDate(dateStr);
  if (!d) return "—";
  const diff = Date.now() - d.getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function truncateId(id: string, length = 8): string {
  return id.length > length ? id.slice(0, length) + "…" : id;
}

export function formatDuration(startedAt: string, completedAt: string | null): string {
  const start = parseUtcDate(startedAt)?.getTime() ?? 0;
  const end = completedAt ? (parseUtcDate(completedAt)?.getTime() ?? Date.now()) : Date.now();
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}
