import {PLATFORMS, monthsBetween, monthLabel, selectRows, summarize, missingMonths} from './report-data.mjs';
import {buildRangeWorkbook} from './workbook.mjs';

const $ = id => document.getElementById(id);
const format = new Intl.NumberFormat('en-IN', {maximumFractionDigits: 0});
let dataset, selected = [], summary = [], months = [], showAll = false, busy = false, workbook;
const selectedPlatforms = () => [...document.querySelectorAll('input[name="platform"]:checked')].map(input => input.value);
const selection = () => ({start: $('start-month').value, end: $('end-month').value, platforms: selectedPlatforms()});

function renderTable() {
  const body = $('summary-body'); body.replaceChildren();
  const entries = [...summary].reverse();
  for (const record of (showAll ? entries : entries.slice(0, 9))) {
    const tr = document.createElement('tr');
    for (const [index, text] of [monthLabel(record.period_end, true), record.platform,
      format.format(record.content), record.grievances == null ? '—' : format.format(record.grievances)].entries()) {
      const td = document.createElement('td'); td.textContent = text;
      if (index >= 2) td.className = 'numeric';
      if (index === 1) {
        const dot = document.createElement('span'); dot.className = `platform-dot ${record.platform.toLowerCase()}`; dot.setAttribute('aria-hidden', 'true'); td.prepend(dot);
      }
      tr.append(td);
    }
    body.append(tr);
  }
  $('show-more').hidden = summary.length <= 9;
  $('show-more').textContent = showAll ? 'Show fewer rows' : `Show all ${summary.length} summary rows`;
}

function renderTrend(start, end) {
  const container = $('trend'); container.replaceChildren();
  if (!selected.length) {
    const p = document.createElement('p'); p.className = 'muted'; p.textContent = 'No validated data in this selection.'; container.append(p); return;
  }
  const totals = new Map(monthsBetween(start, end).map(month => [month, 0]));
  for (const row of summary) totals.set(row.period_end.slice(0, 7), totals.get(row.period_end.slice(0, 7)) + row.content);
  const values = [...totals]; const max = Math.max(...values.map(([, n]) => n), 1);
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 500 130'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Content actioned per reporting month across selected platforms. Exact counts appear in the summary table.');
  const step = 500 / values.length;
  values.forEach(([month, total], index) => {
    const rect = document.createElementNS(ns, 'rect'); const height = Math.max(2, 88 * total / max);
    rect.setAttribute('x', index * step + 1); rect.setAttribute('y', 99 - height); rect.setAttribute('width', Math.max(1, step - 3)); rect.setAttribute('height', height); rect.setAttribute('rx', Math.min(3, step / 4));
    rect.setAttribute('fill', total ? '#567d63' : '#dce3d5');
    const title = document.createElementNS(ns, 'title'); title.textContent = `${monthLabel(month)}: ${total ? format.format(total) : 'no validated data'}`; rect.append(title); svg.append(rect);
  });
  for (const [x, anchor, label] of [[0, 'start', monthLabel(start, true)], [500, 'end', monthLabel(end, true)]]) {
    const text = document.createElementNS(ns, 'text'); text.setAttribute('x', x); text.setAttribute('y', 121); text.setAttribute('text-anchor', anchor); text.setAttribute('fill', '#64716d'); text.setAttribute('font-size', '10'); text.textContent = label; svg.append(text);
  }
  container.append(svg);
}

function refresh() {
  if (!dataset) return;
  const {start, end, platforms} = selection();
  selected = selectRows(dataset.rows, start, end, platforms); summary = summarize(selected); showAll = false;
  const error = start > end ? 'Choose a starting month that is before or equal to the ending month.' :
    !platforms.length ? 'Select at least one platform.' : !selected.length ? 'No validated reports match this range and platform selection. Try another range.' : '';
  $('range-error').textContent = error; $('range-error').hidden = !error;
  $('download').disabled = busy || !!error;
  $('selection-label').textContent = `${monthLabel(start)} – ${monthLabel(end)} · ${platforms.join(', ') || 'No platforms selected'}`;
  $('period-count').textContent = new Set(selected.map(row => row.period_end)).size;
  $('row-count').textContent = format.format(selected.length);
  const active = [...new Set(selected.map(row => row.platform))];
  $('platform-count').textContent = active.length;
  const warnings = [];
  if (!error) {
    const missing = missingMonths(selected, start, end);
    if (missing.length) warnings.push(`No validated data for ${missing.map(month => monthLabel(month, true)).join(', ')}. These months are omitted.`);
    for (const platform of platforms) {
      const missing = missingMonths(selected.filter(row => row.platform === platform), start, end);
      if (missing.length && missing.length !== missingMonths(selected, start, end).length)
        warnings.push(`${platform} has data in ${monthsBetween(start, end).length - missing.length} of ${monthsBetween(start, end).length} selected months.`);
      else if (!active.includes(platform)) warnings.push(`${platform} has no validated data in this range.`);
    }
    if (selected.some(row => row.source_notes)) warnings.push('Some selected grievance totals carry a source logging caveat. See Data Notes in the workbook.');
  }
  $('coverage').textContent = warnings.join(' ');
  renderTable(); renderTrend(start, end);
}

function applyPreset(range) {
  const end = months.at(-1);
  $('end-month').value = end;
  $('start-month').value = range === 'all' ? months[0] : range === 'latest' ? end : months[Math.max(0, months.length - Number(range))];
  $('download-status').textContent = ''; refresh();
}

$('filters').addEventListener('change', () => { $('download-status').textContent = ''; refresh(); });
for (const button of document.querySelectorAll('[data-range]')) button.addEventListener('click', () => applyPreset(button.dataset.range));
$('show-more').addEventListener('click', () => { showAll = !showAll; renderTable(); });
$('filters').addEventListener('submit', async event => {
  event.preventDefault(); if (!selected.length || busy) return;
  busy = true; const rows = [...selected]; const options = selection();
  $('download').disabled = true; $('download-status').textContent = 'Preparing your workbook…';
  try {
    if (!workbook) {
      const response = await fetch(`${dataset.status.download}?v=${encodeURIComponent(dataset.status.generated_at)}`, {cache: 'no-cache'});
      if (!response.ok) throw new Error('The source workbook could not be downloaded. Please try again.');
      workbook = await response.arrayBuffer();
    }
    // Let the progress message paint before ZIP/XML processing begins.
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const bytes = buildRangeWorkbook(workbook, rows, dataset.rows, options);
    const blob = new Blob([bytes], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    const label = options.platforms.length === PLATFORMS.length ? 'all-platforms' : options.platforms.join('-').toLowerCase();
    link.href = url; link.download = `meta-india_${options.start}_to_${options.end}_${label}.xlsx`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    $('download-status').textContent = `Download started · ${format.format(rows.length)} policy rows in your workbook.`;
  } catch (error) {
    $('download-status').textContent = error.message || 'Export failed. Please reload and try again.';
    workbook = null;
  } finally { busy = false; $('download').disabled = !selected.length; }
});

async function init() {
  try {
    const response = await fetch('data.json', {cache: 'no-cache'});
    if (!response.ok) throw new Error('The dataset is temporarily unavailable.');
    dataset = await response.json();
    if (dataset.schema_version !== 1 || !dataset.rows?.length) throw new Error('No validated data is available yet.');
    const ends = dataset.rows.map(row => row.period_end.slice(0, 7)).sort(); months = monthsBetween(ends[0], ends.at(-1));
    for (const id of ['start-month', 'end-month']) {
      for (const month of months) { const option = document.createElement('option'); option.value = month; option.textContent = monthLabel(month, true); $(id).append(option); }
    }
    for (const input of document.querySelectorAll('#filters select, #filters input, [data-range]')) input.disabled = false;
    const s = dataset.status;
    const date = new Intl.DateTimeFormat('en-IN', {dateStyle: 'medium', timeZone: 'Asia/Kolkata'}).format(new Date(s.generated_at));
    $('dataset-status').textContent = `${s.reports} validated reporting periods · ${format.format(s.rows)} policy rows · Latest: ${monthLabel(s.latest_period_end)} · Dataset updated ${date}`;
    $('excluded-count').textContent = `(${dataset.excluded_reports.length} excluded)`;
    for (const report of dataset.excluded_reports) { const li = document.createElement('li'); li.textContent = report.message; $('excluded-list').append(li); }
    const caveats = [...new Set(dataset.rows.filter(row => row.source_notes).map(row => row.month))];
    $('source-caveats').textContent = caveats.length ? `Source caveat for ${caveats.join(', ')}: Meta reports that grievance totals may be larger than stated because of a logging issue.` : '';
    applyPreset('12');
  } catch (error) {
    $('dataset-status').textContent = `${error.message} You can still try downloading the complete workbook.`;
    $('trend').textContent = 'Preview unavailable. Reload the page to try again.';
  }
}
init();
