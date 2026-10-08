// Copy cells from the validated workbook instead of reinterpreting PDF values.
// Only worksheet rows, selection notes, and chart references change. All styles,
// themes, number formats, and native Excel charts remain in the XLSX package.
const SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart';
const REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const nodes = (root, name) => [...root.getElementsByTagNameNS('*', name)];
const first = (root, name) => nodes(root, name)[0];
const cell = (row, column) => nodes(row, 'c').find(c => c.getAttribute('r').replace(/\d+/g, '') === column);
const value = c => c ? (c.getAttribute('t') === 'inlineStr' ? nodes(c, 't').map(t => t.textContent).join('') : first(c, 'v')?.textContent ?? '') : '';
const excelDate = iso => String(Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.UTC(1899, 11, 30)) / 86400000));

function readXML(files, path) {
  if (!files[path]) throw new Error(`Workbook component missing: ${path}`);
  const doc = new DOMParser().parseFromString(fflate.strFromU8(files[path]), 'application/xml');
  if (nodes(doc, 'parsererror').length) throw new Error('The source workbook could not be read.');
  return doc;
}
function writeXML(files, path, doc) { files[path] = fflate.strToU8(new XMLSerializer().serializeToString(doc)); }
function renumber(row, index) {
  row.setAttribute('r', index);
  for (const c of nodes(row, 'c')) c.setAttribute('r', c.getAttribute('r').replace(/\d+$/, index));
  return row;
}
function replaceRows(doc, selected, lastColumn, note) {
  const data = first(doc, 'sheetData');
  const header = first(data, 'row').cloneNode(true);
  data.replaceChildren(header, ...selected.map((row, index) => renumber(row.cloneNode(true), index + 2)));
  if (note) data.append(renumber(note.cloneNode(true), selected.length + 3));
  first(doc, 'dimension').setAttribute('ref', `A1:${lastColumn}${selected.length + (note ? 3 : 1)}`);
  for (const filter of nodes(doc, 'autoFilter')) filter.setAttribute('ref', `A1:${lastColumn}${selected.length + 1}`);
  for (const selection of nodes(doc, 'selection')) {
    selection.setAttribute('activeCell', 'A2'); selection.setAttribute('sqref', 'A2');
  }
}
function setText(doc, address, text) {
  const c = nodes(doc, 'c').find(c => c.getAttribute('r') === address);
  if (!c) return;
  c.setAttribute('t', 'inlineStr');
  const is = doc.createElementNS(SHEET, 'is');
  const t = doc.createElementNS(SHEET, 't'); t.textContent = text;
  is.append(t); c.replaceChildren(is);
}

export function buildRangeWorkbook(buffer, selected, allRows, {start, end, platforms}) {
  if (!selected.length) throw new Error('No validated rows in this selection.');
  const files = fflate.unzipSync(new Uint8Array(buffer));
  const wb = readXML(files, 'xl/workbook.xml');
  const relations = readXML(files, 'xl/_rels/workbook.xml.rels');
  const sheetPath = name => {
    const s = nodes(wb, 'sheet').find(s => s.getAttribute('name') === name);
    const r = nodes(relations, 'Relationship').find(r => r.getAttribute('Id') === s?.getAttributeNS(REL, 'id'));
    return r?.getAttribute('Target').replace(/^\//, '') || '';
  };
  const resolveSheet = name => {
    const path = sheetPath(name);
    return path.startsWith('xl/') ? path : `xl/${path}`;
  };
  const masterPath = resolveSheet('Master Data');
  const master = readXML(files, masterPath);
  const ids = new Set(selected.map(row => row.workbook_row));
  const masterRows = nodes(first(master, 'sheetData'), 'row');
  const chosen = masterRows.filter(row => ids.has(Number(row.getAttribute('r'))));
  if (chosen.length !== selected.length || allRows.length !== masterRows.filter(row => value(cell(row, 'E')) && Number(row.getAttribute('r')) > 1).length)
    throw new Error('The dataset and workbook versions differ. Reload this page and try again.');
  for (const row of selected) {
    const original = masterRows.find(r => Number(r.getAttribute('r')) === row.workbook_row);
    if (value(cell(original, 'C')) !== excelDate(row.period_end) || value(cell(original, 'E')) !== row.platform || value(cell(original, 'F')) !== row.policy_category)
      throw new Error('The dataset changed during download. Reload this page and try again.');
  }
  const note = masterRows.find(row => Number(row.getAttribute('r')) === allRows.length + 3);
  replaceRows(master, chosen, 'K', note);
  for (const merge of nodes(master, 'mergeCells')) merge.remove();
  if (note) {
    const merges = master.createElementNS(SHEET, 'mergeCells'); merges.setAttribute('count', '1');
    const merge = master.createElementNS(SHEET, 'mergeCell'); merge.setAttribute('ref', `A${selected.length + 3}:K${selected.length + 3}`); merges.append(merge);
    const margin = first(master, 'pageMargins'); master.documentElement.insertBefore(merges, margin || null);
  }
  writeXML(files, masterPath, master);
  const periods = new Set(selected.map(row => excelDate(row.period_end)));
  const keys = new Set(selected.map(row => `${excelDate(row.period_end)}|${row.platform}`));
  const summaryPath = resolveSheet('Monthly Summary');
  const summary = readXML(files, summaryPath);
  const summaryRows = nodes(first(summary, 'sheetData'), 'row').slice(1)
    .filter(row => keys.has(`${value(cell(row, 'B'))}|${value(cell(row, 'C'))}`));
  replaceRows(summary, summaryRows, 'G'); writeXML(files, summaryPath, summary);
  const trendPath = resolveSheet('Trend Charts');
  const trend = readXML(files, trendPath);
  const trendRows = nodes(first(trend, 'sheetData'), 'row').slice(1).filter(row => periods.has(value(cell(row, 'B'))));
  for (const row of trendRows) {
    for (const [platform, columns] of [['Facebook', ['C', 'D']], ['Instagram', ['E', 'F']], ['Threads', ['G', 'H']]]) {
      if (!platforms.includes(platform)) for (const col of columns) cell(row, col)?.replaceChildren();
    }
  }
  replaceRows(trend, trendRows, 'H'); writeXML(files, trendPath, trend);
  const activePlatforms = new Set(selected.map(row => row.platform));
  const chartPlatforms = new Map();
  for (const path of Object.keys(files).filter(path => /^xl\/charts\/chart\d+\.xml$/.test(path))) {
    const chart = readXML(files, path);
    const title = nodes(first(chart, 'title'), 't').map(t => t.textContent).join('');
    chartPlatforms.set(path, title.split(':')[0]);
    for (const series of nodes(chart, 'ser')) {
      const cat = first(series, 'cat');
      const strRef = chart.createElementNS(CHART, 'strRef');
      const f = chart.createElementNS(CHART, 'f'); f.textContent = `'Trend Charts'!$A$2:$A$${trendRows.length + 1}`;
      const cache = chart.createElementNS(CHART, 'strCache');
      const count = chart.createElementNS(CHART, 'ptCount'); count.setAttribute('val', trendRows.length); cache.append(count);
      trendRows.forEach((row, index) => {
        const point = chart.createElementNS(CHART, 'pt'); point.setAttribute('idx', index);
        const v = chart.createElementNS(CHART, 'v'); v.textContent = value(cell(row, 'A')); point.append(v); cache.append(point);
      });
      strRef.append(f, cache); cat.replaceChildren(strRef);
      const ref = first(first(series, 'val'), 'numRef');
      const formula = first(ref, 'f');
      const col = formula.textContent.match(/!\$([A-Z]+)\$/)[1];
      formula.textContent = `'Trend Charts'!$${col}$2:$${col}$${trendRows.length + 1}`;
      for (const old of nodes(ref, 'numCache')) old.remove();
      const numbers = chart.createElementNS(CHART, 'numCache');
      const format = chart.createElementNS(CHART, 'formatCode'); format.textContent = '#,##0'; numbers.append(format);
      const total = chart.createElementNS(CHART, 'ptCount'); total.setAttribute('val', trendRows.length); numbers.append(total);
      trendRows.forEach((row, index) => {
        const val = value(cell(row, col)); if (val === '') return;
        const point = chart.createElementNS(CHART, 'pt'); point.setAttribute('idx', index);
        const v = chart.createElementNS(CHART, 'v'); v.textContent = val; point.append(v); numbers.append(point);
      });
      ref.append(numbers);
    }
    writeXML(files, path, chart);
  }
  // Remove charts for unselected platforms, and keep the remaining charts together.
  for (const path of Object.keys(files).filter(path => /^xl\/drawings\/drawing\d+\.xml$/.test(path))) {
    const drawing = readXML(files, path);
    const relPath = path.replace(/\/([^/]+)$/, '/_rels/$1.rels');
    if (!files[relPath]) continue;
    const rels = readXML(files, relPath); let index = 0;
    for (const anchor of [...drawing.documentElement.children]) {
      const chart = first(anchor, 'chart'); if (!chart) continue;
      const target = nodes(rels, 'Relationship').find(r => r.getAttribute('Id') === chart.getAttributeNS(REL, 'id'))?.getAttribute('Target');
      const chartPath = target?.startsWith('/') ? target.slice(1) : target?.replace(/^\.\.\//, 'xl/');
      if (!activePlatforms.has(chartPlatforms.get(chartPath))) { anchor.remove(); continue; }
      const from = first(anchor, 'from'); if (from) first(from, 'row').textContent = index++ * 25;
    }
    writeXML(files, path, drawing);
  }
  const notesPath = resolveSheet('Data Notes'); const notes = readXML(files, notesPath);
  const dates = selected.map(row => row.period_end).sort();
  setText(notes, 'A11', `${new Set(dates).size} reporting period(s), ${dates[0]} – ${dates.at(-1)}. Platforms: ${[...activePlatforms].join(', ')}. Selected reporting months: ${start} – ${end}.`);
  const caveats = [...new Set(selected.filter(row => row.source_notes).map(row => row.month))];
  setText(notes, 'A12', caveats.length ? `Source caveat for ${caveats.join(', ')}: Meta reports that grievance totals may be larger than stated because of a logging issue.` : 'No source logging caveat applies to the selected periods.');
  setText(notes, 'A36', `Custom range exported on ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC. Original validated cells and number formats retained.`);
  nodes(notes, 'row').find(row => row.getAttribute('r') === '11')?.setAttribute('ht', '60');
  writeXML(files, notesPath, notes);
  return fflate.zipSync(files, {level: 6});
}
