import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PLATFORMS, selectRows, summarize, missingMonths, monthsBetween} from '../docs/assets/report-data.mjs';

const data = JSON.parse(readFileSync(new URL('../docs/data.json', import.meta.url)));

test('published dataset matches workbook row order and has no private source metadata', () => {
  assert.equal(data.schema_version, 1);
  assert.equal(data.rows.length, data.status.rows);
  assert.equal(new Set(data.rows.map(r => r.period_end)).size, data.status.reports);
  data.rows.forEach((row, index) => {
    assert.equal(row.workbook_row, index + 2);
    assert.ok(row.period_end && row.platform && row.policy_category);
    assert.equal(row.source_url, undefined);
    assert.equal(row.raw_policy_category, undefined);
  });
});

test('range uses reporting months, with both endpoints inclusive', () => {
  const rows = selectRows(data.rows, '2025-04', '2025-04', PLATFORMS);
  assert.equal(rows.filter(r => r.platform === 'Facebook').length, 13);
  assert.equal(rows.filter(r => r.platform === 'Instagram').length, 12);
  assert.equal(rows.length, 25);
  assert.ok(rows.every(r => r.report_published === '2025-05-31'));
  const totals = summarize(rows);
  assert.equal(totals.find(r => r.platform === 'Facebook').grievances, 54320);
  assert.equal(totals.find(r => r.platform === 'Instagram').grievances, 21532);
  // Grievances must never be multiplied by the number of policy rows.
  assert.equal(totals.reduce((n, r) => n + r.grievances, 0), 75852);
  const span = selectRows(data.rows, '2025-03', '2025-05', ['Instagram']);
  assert.deepEqual([...new Set(span.map(r => r.period_end.slice(0, 7)))], ['2025-03', '2025-04', '2025-05']);
});

test('empty platform and reversed ranges cannot export data', () => {
  assert.deepEqual(selectRows(data.rows, '2025-04', '2025-04', []), []);
  assert.deepEqual(selectRows(data.rows, '2025-06', '2025-04', PLATFORMS), []);
  assert.deepEqual(selectRows(data.rows, '2020-01', '2020-02', PLATFORMS), []);
});

test('gaps and missing grievance totals remain explicit', () => {
  assert.deepEqual(monthsBetween('2024-12', '2025-02'), ['2024-12', '2025-01', '2025-02']);
  assert.deepEqual(missingMonths([{period_end: '2024-12-31'}, {period_end: '2025-02-28'}], '2024-12', '2025-02'), ['2025-01']);
  const rows = selectRows(data.rows, '2021-06', '2021-06', ['Facebook']);
  assert.equal(summarize(rows)[0].grievances, null);
  assert.equal(rows[0].period_start, '2021-05-15');
});
