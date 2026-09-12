import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { extractOpenAIUsage, openaiCall, openaiStream } from '../../examples/native-capture/guardian_openai.mjs';

const UNKNOWN = { input_tokens: null, output_tokens: null, total_tokens: null };
const metadata = { agent_name: 'sdk-fixture', model: 'synthetic/model' };
const usage = { input_tokens: 8, output_tokens: 2, total_tokens: 10 };
const response = (status = 'completed', changes = {}) => ({ object: 'response', id: 'resp_fixture', status,
  usage: { ...usage }, output: 'private-source-canary', ...changes });
const terminal = (status = 'completed', changes = {}) => ({ type: 'response.' + status, response: response(status, changes) });
const chunk = (reason = null, changes = {}) => ({ id: 'chatcmpl-fixture', object: 'chat.completion.chunk',
  choices: [{ index: 0, finish_reason: reason, delta: { content: 'private-source-canary' } }], ...changes });
const usageChunk = (changes = {}) => chunk(null, { choices: [], usage: { prompt_tokens: 8, completion_tokens: 2, total_tokens: 10 }, ...changes });
function capture() {
  const events = [], starts = [];
  return { events, starts, startCall(value) { starts.push(value); let finished = false;
    return { finish(event) { if (!finished) { events.push(event); finished = true; } } }; } };
}
async function collect(stream) { const result = []; for await (const value of stream) result.push(value); return result; }
const fixtures = JSON.parse(readFileSync(new URL('../fixtures/openai-usage.json', import.meta.url)));
for (const fixture of fixtures) test('shared usage: ' + fixture.name, () => {
  assert.deepEqual(extractOpenAIUsage(fixture.response, fixture.api), fixture.expected);
});

test('no custom getter, proxy trap or serializer is invoked', () => {
  let touched = 0;
  const unsafe = { get usage() { touched++; throw new Error(); }, toJSON() { touched++; throw new Error(); } };
  assert.deepEqual(extractOpenAIUsage(unsafe), UNKNOWN);
  assert.deepEqual(extractOpenAIUsage(new Proxy({}, { get() { touched++; throw new Error(); }, getPrototypeOf() { touched++; throw new Error(); } })), UNKNOWN);
  const good = { usage, get output() { touched++; throw new Error(); }, toJSON() { touched++; throw new Error(); } };
  assert.deepEqual(extractOpenAIUsage(good), usage);
  assert.equal(touched, 0);
});
test('malformed or huge usage remains unknown and returns fresh maps', () => {
  for (const value of [undefined, [], { usage: [] }, { usage: { input_tokens: NaN } }, { usage: { total_tokens: Infinity } }]) {
    assert.deepEqual(extractOpenAIUsage(value), UNKNOWN);
  }
  const first = extractOpenAIUsage({}); first.input_tokens = 99;
  assert.deepEqual(extractOpenAIUsage({}), UNKNOWN);
});
test('call returns exact provider response and captures only usage', async () => {
  const exporter = capture(), value = response();
  assert.equal(await openaiCall(exporter, metadata, async () => value), value);
  assert.deepEqual(exporter.events, [{ status: 'success', ...usage }]);
  assert.equal(JSON.stringify(exporter.events).includes('private-source-canary'), false);
});
test('Responses terminal states differ from queued incomplete and cancelled', async () => {
  for (const [status, expected, known] of [['completed', 'success', true], ['failed', 'error', true], ['incomplete', 'unknown', true],
    ['cancelled', 'unknown', false], ['queued', 'unknown', false], ['in_progress', 'unknown', false], ['unexpected', 'unknown', false]]) {
    const exporter = capture(); await openaiCall(exporter, metadata, () => response(status));
    assert.deepEqual(exporter.events, [{ status: expected, ...(known ? usage : UNKNOWN) }]);
  }
});
test('chat finish reason requires one completed choice without inspecting message', async () => {
  for (const reason of ['stop', 'tool_calls', 'function_call', 'length', 'content_filter', null, 'future']) {
    const exporter = capture();
    const value = { object: 'chat.completion', choices: [{ index: 0, finish_reason: reason,
      get message() { throw new Error('must not inspect'); } }], usage: { prompt_tokens: 8, completion_tokens: 2, total_tokens: 10 } };
    await openaiCall(exporter, metadata, () => value, { api: 'chat_completions' });
    const success = ['stop', 'tool_calls', 'function_call'].includes(reason);
    assert.equal(exporter.events[0].status, success ? 'success' : 'unknown');
    assert.equal(exporter.events[0].total_tokens, reason === null || reason === 'future' ? null : 10);
  }
});
test('malformed response lifecycle does not claim success', async () => {
  for (const [value, api] of [[{ ...response(), object: 'wrong' }, 'responses'],
    [{ object: 'chat.completion', choices: [], usage }, 'chat_completions'],
    [{ object: 'chat.completion', choices: [{ index: 0 }, { index: 1 }], usage }, 'chat_completions']]) {
    const exporter = capture(); assert.equal(await openaiCall(exporter, metadata, () => value, { api }), value);
    assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
  }
});
test('provider errors preserve identity and cancellation is unknown', async () => {
  const error = new Error('private-source-canary');
  for (const abort of [false, true]) {
    const exporter = capture(), controller = new AbortController(); if (abort) controller.abort();
    await assert.rejects(openaiCall(exporter, metadata, async () => { throw error; }, { signal: controller.signal }), (caught) => caught === error);
    assert.deepEqual(exporter.events, [{ status: abort ? 'unknown' : 'error', ...UNKNOWN }]);
  }
});
test('exporter failures cannot prevent calls or replace original provider error', async () => {
  const value = response(), failure = new Error('original');
  for (const exporter of [{ startCall() { throw new Error('instrumentation'); } }, { startCall() { return { finish() { throw new Error(); } }; } }]) {
    assert.equal(await openaiCall(exporter, metadata, () => value), value);
    await assert.rejects(openaiCall(exporter, metadata, () => { throw failure; }), (caught) => caught === failure);
    const items = [terminal()]; assert.deepEqual(await collect(openaiStream(exporter, metadata, () => items)), items);
  }
});
test('unconsumed stream is inert and awaited SDK stream is supported', async () => {
  const exporter = capture(); let operations = 0;
  const stream = openaiStream(exporter, metadata, async () => { operations++; return [terminal()]; });
  assert.equal(exporter.starts.length, 0); assert.equal(operations, 0);
  await collect(stream); assert.equal(operations, 1); assert.equal(exporter.events.length, 1);
});
test('terminal metadata is copied before yielding without modifying chunks', async () => {
  const exporter = capture(), value = terminal();
  const stream = openaiStream(exporter, metadata, () => [value]);
  assert.equal((await stream.next()).value, value);
  value.response.usage.total_tokens = 900; value.response.status = 'failed';
  assert.equal((await stream.next()).done, true);
  assert.deepEqual(exporter.events, [{ status: 'success', ...usage }]);
});
test('responses identical terminal duplicates do not add usage twice', async () => {
  const exporter = capture(); await collect(openaiStream(exporter, metadata, () => [terminal(), terminal()]));
  assert.deepEqual(exporter.events, [{ status: 'success', ...usage }]);
});
test('conflicting response IDs statuses or valid snapshots become unknown', async () => {
  for (const chunks of [[terminal(), terminal('completed', { id: 'resp_other' })], [terminal(), terminal('failed')],
    [terminal(), terminal('completed', { usage: { input_tokens: 9, output_tokens: 2, total_tokens: 11 } })]]) {
    const exporter = capture(); await collect(openaiStream(exporter, metadata, () => chunks));
    assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
  }
});
test('invalid numeric usage keeps valid completion while counters stay unknown', async () => {
  const exporter = capture(); await collect(openaiStream(exporter, metadata, () => [terminal('completed', { usage: { input_tokens: -1 } })]));
  assert.deepEqual(exporter.events, [{ status: 'success', ...UNKNOWN }]);
});
test('invalid usage cannot conceal contradictory valid snapshots', async () => {
  for (const finalInput of [8, 9]) {
    const exporter = capture();
    await collect(openaiStream(exporter, metadata, () => [terminal(),
      terminal('completed', { usage: { input_tokens: -1 } }),
      terminal('completed', { usage: { input_tokens: finalInput, output_tokens: 2, total_tokens: finalInput + 2 } })]));
    assert.deepEqual(exporter.events, [{ status: finalInput === 8 ? 'success' : 'unknown', ...UNKNOWN }]);
  }
});
test('responses failure and generic error events are observed without error body', async () => {
  for (const chunks of [[terminal('failed')], [{ type: 'error', get message() { throw new Error('private'); } }]]) {
    const exporter = capture(); await collect(openaiStream(exporter, metadata, () => chunks));
    assert.equal(exporter.events[0].status, 'error');
  }
});
test('chat waits for final usage-only chunk after finish reason', async () => {
  const exporter = capture(), chunks = [chunk(), chunk('stop'), usageChunk(), usageChunk()];
  const actual = await collect(openaiStream(exporter, metadata, () => chunks, { api: 'chat_completions' }));
  assert.ok(actual.every((value, index) => value === chunks[index]));
  assert.deepEqual(exporter.events, [{ status: 'success', ...usage }]);
});
test('chat final usage missing stays unknown; delta usage is not counted', async () => {
  const exporter = capture();
  await collect(openaiStream(exporter, metadata, () => [chunk(null, { usage: { prompt_tokens: 9, completion_tokens: 9, total_tokens: 18 } }), chunk('stop')], { api: 'chat_completions' }));
  assert.deepEqual(exporter.events, [{ status: 'success', ...UNKNOWN }]);
});
test('usage-only chunk before chat finish or extra choice is unknown', async () => {
  for (const chunks of [[usageChunk(), chunk('stop')], [chunk('stop', { choices: [{ index: 1, finish_reason: 'stop' }] }), usageChunk()]]) {
    const exporter = capture(); await collect(openaiStream(exporter, metadata, () => chunks, { api: 'chat_completions' }));
    assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
  }
});
test('plain stream exhaustion is not proof of provider completion', async () => {
  for (const [api, chunks] of [['responses', [{ type: 'response.output_text.delta', delta: 'private-source-canary' }]], ['chat_completions', [chunk()]]]) {
    const exporter = capture(); await collect(openaiStream(exporter, metadata, () => chunks, { api }));
    assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
  }
});
test('early close discards final usage and closes iterator once', async () => {
  const exporter = capture(); let closes = 0;
  async function* provider() { try { yield terminal(); yield terminal(); } finally { closes++; } }
  const stream = openaiStream(exporter, metadata, provider); await stream.next(); await stream.return();
  assert.equal(closes, 1); assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
});
test('consumer throw remains the consumer error and records unknown', async () => {
  const exporter = capture(), error = new Error('consumer'); let closed = false;
  async function* provider() { try { yield terminal(); } finally { closed = true; } }
  const stream = openaiStream(exporter, metadata, provider); await stream.next();
  await assert.rejects(stream.throw(error), (caught) => caught === error);
  assert.equal(closed, true); assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
});
test('stream provider failure preserves error when cleanup also throws', async () => {
  const exporter = capture(), error = new Error('provider');
  const provider = { [Symbol.asyncIterator]() { return this; }, async next() { throw error; }, async return() { throw new Error('cleanup'); } };
  await assert.rejects(collect(openaiStream(exporter, metadata, () => provider)), (caught) => caught === error);
  assert.deepEqual(exporter.events, [{ status: 'error', ...UNKNOWN }]);
});
test('abort after terminal snapshot still records cancellation as unknown', async () => {
  const exporter = capture(), controller = new AbortController();
  const stream = openaiStream(exporter, metadata, () => [terminal()], { signal: controller.signal });
  await stream.next(); controller.abort(); await stream.next();
  assert.deepEqual(exporter.events, [{ status: 'unknown', ...UNKNOWN }]);
});
