// Time-axis helpers for the chart. Kept free of React and of imports so they
// can be tested on their own.

const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

const TICK_STEPS = [
  5 * MINUTE,
  10 * MINUTE,
  15 * MINUTE,
  30 * MINUTE,
  HOUR,
  2 * HOUR,
  3 * HOUR,
  6 * HOUR,
  12 * HOUR,
  DAY,
  2 * DAY,
  7 * DAY,
  14 * DAY,
  // From here on, calendar months (a "step" of 30 days stands for one month).
  30 * DAY,
  60 * DAY,
  90 * DAY,
  180 * DAY,
  365 * DAY,
];

const MONTH_STEP = 30 * DAY;

/**
 * Tick positions on round local-clock times (on the hour, at local
 * midnight...), with the smallest step that keeps the count at or below
 * `maxTicks`. A category axis can't do this: it puts a label wherever the
 * data happens to be.
 */
export function niceTicks(start: number, end: number, maxTicks = 5): { ticks: number[]; step: number } {
  const step = TICK_STEPS.find((candidate) => (end - start) / candidate <= maxTicks) ?? 365 * DAY;
  const ticks: number[] = [];
  const midnight = new Date(start);
  midnight.setHours(0, 0, 0, 0);

  if (step >= MONTH_STEP) {
    const months = Math.round(step / MONTH_STEP);
    const cursor = new Date(start);
    cursor.setDate(1);
    cursor.setHours(0, 0, 0, 0);
    if (cursor.getTime() < start) {
      cursor.setMonth(cursor.getMonth() + 1);
    }
    while (cursor.getTime() <= end) {
      ticks.push(cursor.getTime());
      cursor.setMonth(cursor.getMonth() + months);
    }
  } else if (step >= DAY) {
    const stepDays = step / DAY;
    const cursor = new Date(midnight);
    if (cursor.getTime() < start) {
      cursor.setDate(cursor.getDate() + 1);
    }
    while (cursor.getTime() <= end) {
      ticks.push(cursor.getTime());
      cursor.setDate(cursor.getDate() + stepDays);
    }
  } else {
    let tick = midnight.getTime();
    while (tick < start) {
      tick += step;
    }
    for (; tick <= end; tick += step) {
      ticks.push(tick);
    }
  }
  return { ticks, step };
}

export function tickLabel(time: number, step: number): string {
  const date = new Date(time);
  if (step >= MONTH_STEP) {
    return date.toLocaleDateString([], date.getMonth() === 0 ? { month: "short", year: "numeric" } : { month: "short" });
  }
  if (step >= DAY) {
    return step >= 7 * DAY
      ? date.toLocaleDateString([], { day: "numeric", month: "short" })
      : date.toLocaleDateString([], { weekday: "short", day: "numeric" });
  }
  const atMidnight = date.getHours() === 0 && date.getMinutes() === 0;
  if (atMidnight) {
    return date.toLocaleDateString([], { weekday: "short", day: "numeric" });
  }
  return date.toLocaleTimeString([], date.getMinutes() === 0 ? { hour: "numeric" } : { hour: "numeric", minute: "2-digit" });
}

export interface SunEventLike {
  time: string;
  kind: "sunrise" | "sunset";
}

/**
 * The stretches of [start, end] that are dark, from sunrise/sunset events
 * that reach beyond both ends (so the state at the window's edges is known).
 */
export function nightSpans(events: SunEventLike[], start: number, end: number): [number, number][] {
  const sorted = events.map((event) => ({ time: Date.parse(event.time), kind: event.kind })).sort((a, b) => a.time - b.time);
  if (sorted.length === 0) {
    return [];
  }

  const before = sorted.filter((event) => event.time <= start);
  const dark = before.length > 0 ? before[before.length - 1].kind === "sunset" : sorted[0].kind === "sunrise";

  const spans: [number, number][] = [];
  let from: number | null = dark ? start : null;
  for (const event of sorted) {
    if (event.time <= start) {
      continue;
    }
    if (event.time >= end) {
      break;
    }
    if (event.kind === "sunset") {
      from = event.time;
    } else if (from !== null) {
      spans.push([from, event.time]);
      from = null;
    }
  }
  if (from !== null) {
    spans.push([from, end]);
  }
  return spans;
}

/**
 * Insert an empty row after any gap longer than a few buckets, so the line
 * breaks where the station wasn't reporting instead of drawing a straight
 * line across the outage as though readings existed.
 */
export function withGapBreaks<T extends { t: number }>(rows: T[], bucketMs: number, tolerance = 3): (T | { t: number })[] {
  const result: (T | { t: number })[] = [];
  rows.forEach((row, index) => {
    if (index > 0 && row.t - rows[index - 1].t > bucketMs * tolerance) {
      result.push({ t: rows[index - 1].t + bucketMs });
    }
    result.push(row);
  });
  return result;
}
