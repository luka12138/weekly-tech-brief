const assert = require('node:assert/strict');
const {test} = require('node:test');
const {prepareToolOutput: prepare, prepareToolBatch} = require('../scripts/tool_output.cjs');

test('strings stay text, never numeric property indexes', () => {
  assert.equal(prepare('official release', {id: 'S1'}).excerpts[0].text, 'official release');
});
test('oversized results require selection; no silent head truncation', () => {
  const r = prepare('a'.repeat(9000), {id: 'S1'});
  assert.equal(r.status, 'needs_selection');
  assert.equal(r.total_chars, 9000);
  assert.equal(r.excerpts, undefined);
});
test('explicit ranges preserve dates, units, negations and footnotes exactly', () => {
  const raw = 'Navigation\n2026-09-01\nUSD million | FY2026 guidance\nNot realized revenue\n[1] Ends December 2026\nRelated links';
  const r = prepare(raw, {id: 'S1', ranges: [[2, 5]]});
  assert.equal(r.excerpts[0].text, raw.split('\n').slice(1, 5).join('\n'));
  assert.equal(r.omitted_text, true);
  assert.equal(r.semantic_verification, 'not_certified');
});
test('command failure and running session remain visible', () => {
  const r = prepare({output: 'x'.repeat(9000), exit_code: 1, session_id: 8}, {id: 'C1'});
  assert.equal(r.exit_code, 1);
  assert.equal(r.session_id, 8);
  assert.equal(r.status, 'needs_selection');
});
test('MCP text blocks work without dumping image data or structured content', () => {
  const r = prepare({isError: true, content: [{type: 'text', text: 'Error'},
    {type: 'image', data: 'secret-binary'}], structuredContent: {large: 'hidden'}}, {id: 'M1'});
  assert.equal(r.is_error, true);
  assert.equal(r.nontext_blocks, 1);
  assert.equal(r.structured_content_present, true);
  assert.ok(!JSON.stringify(r).includes('secret-binary'));
});
test('unknown envelopes and invalid ranges fail closed', () => {
  for (const raw of [null, ['x'], {unexpected: 'x'}]) {
    assert.equal(prepare(raw, {id: 'S1'}).status, 'needs_adapter');
  }
  assert.throws(() => prepare('text', {id: 'S1', ranges: [[1, 2]]}), RangeError);
});
test('nontext-only content requires its own inspection', () => {
  assert.equal(prepare({content: [], structuredContent: {x: 1}}, {id: 'M1'}).status, 'needs_adapter');
});
test('upstream truncation cannot be turned into complete source verification', () => {
  assert.equal(prepare('Warning: truncated output', {id: 'S1'}).upstream_truncated, true);
});
test('combined payload must fit even when each source fits individually', () => {
  const r = prepareToolBatch([{id: 'A', result: 'a'.repeat(5000)},
    {id: 'B', result: {output: 'b'.repeat(5000), exit_code: 1}}]);
  assert.equal(r.status, 'needs_batch_selection');
  assert.equal(r.selected_chars, 10000);
  assert.equal(r.results[1].exit_code, 1);
  assert.ok(r.results.every(item => !item.excerpts));
});
test('a selected batch retains full date, unit and restriction blocks', () => {
  const raw = 'Navigation\n2026-09-01 | USD million | FY2026\nForecast, not revenue\nFooter';
  const r = prepareToolBatch([{id: 'A', result: raw, ranges: [[2, 3]]},
    {id: 'B', result: {content: [{type: 'text', text: '403 Forbidden'}], isError: true}}]);
  assert.equal(r.status, 'prepared_batch');
  assert.equal(r.results[0].excerpts[0].text, raw.split('\n').slice(1, 3).join('\n'));
  assert.equal(r.results[1].is_error, true);
});
test('batch preserves unknown envelopes and truncated-source diagnostics', () => {
  const r = prepareToolBatch([{id: 'A', result: {unexpected: true}},
    {id: 'B', result: 'Warning: truncated output'}]);
  assert.equal(r.results[0].status, 'needs_adapter');
  assert.equal(r.results[1].upstream_truncated, true);
  assert.throws(() => prepareToolBatch([]), TypeError);
});
