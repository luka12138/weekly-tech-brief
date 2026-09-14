// Pure adapter: load once in functions.exec; retain original results in store().
function normalize(result) {
  if (typeof result === 'string') return {text: result, kind: 'string'};
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new TypeError('Unsupported tool result type; inspect the tool schema first');
  }
  if (typeof result.output === 'string') {
    return {text: result.output, kind: 'command', exit_code: result.exit_code ?? null,
      session_id: result.session_id ?? null};
  }
  if (Array.isArray(result.content)) {
    const blocks = result.content;
    const texts = blocks.filter(b => b && b.type === 'text' && typeof b.text === 'string');
    return {text: texts.map(b => b.text).join('\n\n'), kind: 'mcp',
      is_error: result.isError === true, nontext_blocks: blocks.length - texts.length,
      structured_content_present: result.structuredContent != null};
  }
  throw new TypeError('Unknown tool envelope; use a schema-specific adapter, not Object.keys(raw)');
}

function prepareToolOutput(result, {id, ranges, maxChars = 8000} = {}) {
  if (typeof id !== 'string' || !id || !Number.isInteger(maxChars) || maxChars < 1) {
    throw new TypeError('A stored result id and a positive character budget are required');
  }
  let normalized;
  try {
    normalized = normalize(result);
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    return {id, status: 'needs_adapter', reason: error.message, semantic_verification: 'not_certified'};
  }
  const {text, ...metadata} = normalized;
  const lines = text.split('\n');
  const upstreamTruncated = /truncated output|tokens truncated|output truncated|输出被截断/i.test(text);
  const base = {id, ...metadata, total_chars: text.length, total_lines: lines.length,
    upstream_truncated: upstreamTruncated, semantic_verification: 'not_certified'};
  if (!text && (metadata.structured_content_present || metadata.nontext_blocks)) {
    return {...base, status: 'needs_adapter', action: 'Inspect structured or media content with its dedicated tool'};
  }
  let selected = [{start: 1, end: lines.length}];
  if (ranges !== undefined) {
    if (!Array.isArray(ranges) || ranges.length === 0) throw new TypeError('ranges must be nonempty');
    selected = ranges.map(pair => {
      if (!Array.isArray(pair) || pair.length !== 2 || !pair.every(Number.isInteger)) {
        throw new TypeError('Each range must be [firstLine, lastLine], one-based and inclusive');
      }
      const [start, end] = pair;
      if (start < 1 || end < start || end > lines.length) throw new RangeError('Range outside stored text');
      return {start, end};
    });
  }
  const excerpts = selected.map(r => ({...r, text: lines.slice(r.start - 1, r.end).join('\n')}));
  if (excerpts.reduce((sum, r) => sum + r.text.length, 0) > maxChars) {
    return {...base, status: 'needs_selection', requested_ranges: selected,
      action: 'Locate complete relevant paragraphs/tables/footnotes in the stored result; do not truncate'};
  }
  return {...base, status: ranges ? 'selected_text' : 'complete_text', excerpts,
    omitted_text: !!ranges && !lines.every((_, i) => selected.some(r => r.start <= i + 1 && r.end >= i + 1))};
}

function prepareToolBatch(items, {maxChars = 8000} = {}) {
  if (!Array.isArray(items) || !items.length || !Number.isInteger(maxChars) || maxChars < 1) {
    throw new TypeError('A nonempty batch and positive character budget are required');
  }
  const results = items.map(({result, ...options}) => prepareToolOutput(result, {...options, maxChars}));
  const selectedChars = results.reduce((sum, item) => sum +
    (item.excerpts || []).reduce((n, excerpt) => n + excerpt.text.length, 0), 0);
  if (selectedChars <= maxChars) return {status: 'prepared_batch', selected_chars: selectedChars, results};
  // Individual outputs can fit while their combined payload still exceeds the limit.
  return {status: 'needs_batch_selection', selected_chars: selectedChars, max_chars: maxChars,
    action: 'Select complete source blocks across the batch or return them in separate calls; no text was truncated',
    results: results.map(({excerpts, ...item}) => ({...item,
      status: excerpts ? 'needs_selection' : item.status,
      requested_ranges: excerpts ? excerpts.map(({start, end}) => ({start, end})) : item.requested_ranges}))};
}

module.exports = {normalize, prepareToolOutput, prepareToolBatch};
