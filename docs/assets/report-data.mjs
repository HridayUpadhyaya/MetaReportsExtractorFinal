export const PLATFORMS = ['Facebook', 'Instagram', 'Threads'];

export function monthsBetween(start, end) {
  const months = [];
  const date = new Date(`${start}-01T00:00:00Z`);
  while (date.toISOString().slice(0, 7) <= end) {
    months.push(date.toISOString().slice(0, 7));
    date.setUTCMonth(date.getUTCMonth() + 1);
  }
  return months;
}

export function selectRows(rows, start, end, platforms) {
  if (!start || !end || start > end || !platforms.length) return [];
  return rows.filter(row => row.period_end.slice(0, 7) >= start &&
    row.period_end.slice(0, 7) <= end && platforms.includes(row.platform));
}

export function summarize(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = `${row.period_end}|${row.platform}`;
    if (!groups.has(key)) groups.set(key, {period_end: row.period_end,
      platform: row.platform, content: 0, grievances: null, count: 0});
    const group = groups.get(key);
    group.content += Number(row.content_actioned_numeric || 0);
    group.count++;
    if (row.total_user_grievances != null) group.grievances = row.total_user_grievances;
  }
  return [...groups.values()].sort((a, b) => a.period_end.localeCompare(b.period_end) ||
    a.platform.localeCompare(b.platform));
}

export function missingMonths(rows, start, end) {
  const present = new Set(rows.map(row => row.period_end.slice(0, 7)));
  return monthsBetween(start, end).filter(month => !present.has(month));
}

export function monthLabel(month, short = false) {
  return new Intl.DateTimeFormat('en', {month: short ? 'short' : 'long', year: 'numeric', timeZone: 'UTC'})
    .format(new Date(`${month.slice(0, 7)}-01T00:00:00Z`));
}
