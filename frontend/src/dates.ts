/**
 * A YYYY-MM-DD string for a date input, in the user's local calendar.
 * `toISOString()` would give the UTC date instead, which for anyone east of
 * UTC is yesterday's date for the first part of every day.
 */
export function localDateInputValue(daysAgo = 0): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** The browser's current offset from UTC in minutes east (UTC+10 is 600). */
export function utcOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

/** Midnight at the start of the local day `daysAgo` days back. */
export function localMidnight(daysAgo = 0): Date {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - daysAgo);
  return date;
}

export function formatClock(value: string | number | Date): string {
  return new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** A YYYY-MM-DD local date string, shown as e.g. "18 Oct". */
export function formatLocalDate(isoDate: string, withYear = false): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(
    [],
    withYear ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" },
  );
}

export function formatDateTime(value: string | number | Date): string {
  return new Date(value).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

/** "just now", "12 min ago", "3 h ago", "2 days ago". */
export function formatAgo(value: string | number | Date, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 90) {
    return "just now";
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) {
    return `${minutes} min ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.round(hours / 24)} days ago`;
}

/** "3 h 2 min", "45 s": a duration given in seconds. */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.round(totalSeconds);
  if (seconds < 90) {
    return `${seconds} s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}
