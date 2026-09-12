import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';
import { BackgroundExporter } from '../../examples/native-capture/guardian_exporter.mjs';
import { sendBatch, testBatch } from '../../examples/native-capture/guardian_capture.mjs';
import { runCall, streamCall, syntheticLifecycle } from '../../examples/native-capture/node_app.mjs';

const TOKEN = `cg_ingest_${'a'.repeat(32)}_${'b'.repeat(43)}`;
const configuration = { origin: 'https://guardian.invalid', token: TOKEN };
const originalFetch = globalThis.fetch;
const instances = [];
function exporter(options = {}) {
  const instance = new BackgroundExporter({ ...configuration, ...options });
  instances.push(instance);
  return instance;
}
function event(changes = {}) {
  const now = new Date().toISOString();
  return { observation_id: 'obs-1', trace_id: 'trace-1', agent_name: 'test-agent', model: 'test/model',
    started_at: now, ended_at: now, status: 'success', ...changes };
}
function receipt(body, changes = {}) {
  const batch = JSON.parse(body);
  return new Response(JSON.stringify({ batch_id: batch.batch_id, test_mode: batch.test_mode,
    processing: batch.test_mode ? 'test_only' : 'queued', received: batch.events.length,
    duplicate: 0, conflict_candidates: 0, replayed: false, ...changes }), { status: 202 });
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function until(predicate) {
  const deadline = performance.now() + 2000;
  while (!predicate()) {
    if (performance.now() > deadline) assert.fail('synchronization_timeout');
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
}
function reconciles(stats) {
  assert.equal(stats.enqueued_events, stats.confirmed_events + stats.unconfirmed_events + stats.pending_events);
  assert.equal(stats.pending_events, stats.queued_events + stats.in_flight_events);
  for (const value of Object.values(stats)) if (typeof value === 'number') assert.ok(value >= 0 && Number.isSafeInteger(value));
  assert.ok(!JSON.stringify(stats).includes(TOKEN));
}
afterEach(async () => {
  await Promise.all(instances.splice(0).map((instance) => instance.close(0)));
  globalThis.fetch = originalFetch;
});

test('constructor and synchronous admission do not perform I/O', async () => {
  let calls = 0;
  globalThis.fetch = async (_, request) => { calls += 1; return receipt(request.body); };
  const instance = exporter();
  assert.deepEqual(instance.emit(event()), { accepted: true, code: 'queued' });
  assert.equal(calls, 0);
  const result = await instance.flush(2000);
  assert.equal(calls, 1);
  assert.equal(result.confirmed, true);
  reconciles(result.stats);
});

test('constructor rejects unsafe options with a fixed error and no hooks', () => {
  let hooks = 0;
  const getter = { get origin() { hooks += 1; return configuration.origin; } };
  for (const options of [getter, { token: `${TOKEN}\n` }, { origin: 'http://example.com' }, { origin: 'https://user:secret@example.com' },
    { maxEvents: 1001 }, { maxBytes: 4194305 }, { maxAttempts: 6 }, { maxBatchAgeMs: 300001 },
    { maxBatchEvents: 101 }, { batchDelayMs: 1001 }, { testMode: 'true' }, { toJSON() { hooks += 1; } }]) {
    const supplied = options === getter ? options : { ...configuration, ...options };
    assert.throws(() => new BackgroundExporter(supplied), { message: 'invalid_exporter_configuration' });
  }
  assert.equal(hooks, 0);
});

test('invalid content, objects, proxies, getters and custom JSON never execute or enter storage', () => {
  const instance = exporter();
  let hooks = 0;
  const accessor = event();
  Object.defineProperty(accessor, 'model', { enumerable: true, get() { hooks += 1; return 'secret'; } });
  const proxy = new Proxy(event(), { ownKeys() { hooks += 1; throw new Error('private'); } });
  const values = [accessor, proxy, Object.assign(Object.create({ inherited: 'private' }), event()),
    event({ prompt: 'private' }), event({ output: 'private' }), event({ toJSON() { hooks += 1; return 'private'; } }),
    event({ model: { toString() { hooks += 1; return 'private'; } } }), event({ [Symbol('private')]: 'private' })];
  for (const value of values) assert.deepEqual(instance.emit(value), { accepted: false, code: 'invalid_event' });
  assert.equal(hooks, 0);
  assert.equal(instance.snapshot().pending_bytes, 0);
  assert.equal(instance.snapshot().rejected_events, values.length);
  assert.ok(!JSON.stringify(instance.snapshot()).includes('private'));
});

test('strict identifiers and numeric unknowns match the collector boundary', () => {
  const instance = exporter();
  const invalid = [{ observation_id: 'bad\n' }, { model: 'bad\n' }, { status: 'SUCCESS' },
    { input_tokens: true }, { input_tokens: '0' }, { output_tokens: -1 }, { total_tokens: 0.5 },
    { total_tokens: Number.MAX_SAFE_INTEGER + 1 }, { cost_usd: 0 }, { cost_usd: '0\n' },
    { cost_usd: '1e-3' }, { cost_usd: '1000000000' }, { cost_usd: '0.0000000000001' },
    { input_tokens: 2, output_tokens: 3, total_tokens: 4 }, { input_tokens: Number.MAX_SAFE_INTEGER, output_tokens: 1 },
    { total_tokens: undefined }, { cost_usd: NaN }, { parent_observation_id: {} }];
  for (const changes of invalid) assert.equal(instance.emit(event(changes)).code, 'invalid_event', JSON.stringify(changes));
  for (const changes of [{}, { cost_usd: null, total_tokens: null }, { cost_usd: '0', input_tokens: 0, output_tokens: 0 },
    { cost_usd: '999999999.999999999999', total_tokens: Number.MAX_SAFE_INTEGER }]) assert.equal(instance.emit(event(changes)).accepted, true);
});

test('timestamps reject rollover, missing zone and original submillisecond reversal', () => {
  const instance = exporter();
  const day = new Date().toISOString().slice(0, 10);
  const prefix = new Date().toISOString().slice(0, 19);
  const invalid = [{ started_at: `${day}T00:00:00`, ended_at: `${day}T00:00:00` },
    { started_at: `${prefix}.123900Z`, ended_at: `${prefix}.123100Z` },
    { started_at: '2026-02-30T00:00:00Z', ended_at: '2026-02-30T00:00:00Z' },
    { started_at: `${prefix}.1234567Z` }, { started_at: `${prefix}Z\n` },
    { started_at: new Date(Date.now() - 86401000).toISOString() },
    { ended_at: new Date(Date.now() + 301000).toISOString() }];
  for (const changes of invalid) assert.equal(instance.emit(event(changes)).code, 'invalid_event');
  assert.equal(instance.emit(event({ started_at: `${prefix}.123100Z`, ended_at: `${prefix}.123900Z` })).accepted, true);
  const stamp = new Date().toISOString().replace('Z', '+00:00');
  assert.equal(instance.emit(event({ started_at: stamp, ended_at: stamp })).accepted, true);
});

test('FIFO batches cap 100 rows, retain primitive snapshots and derive only known tokens', async () => {
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(request.body); return receipt(request.body); };
  const instance = exporter();
  for (let index = 0; index < 205; index += 1) {
    const caller = event({ observation_id: `obs-${index}`, input_tokens: index === 0 ? 0 : null, output_tokens: index === 0 ? 0 : null });
    assert.equal(instance.emit(caller).accepted, true);
    caller.observation_id = 'mutated'; caller.cost_usd = '42';
  }
  assert.equal((await instance.flush(2000)).confirmed, true);
  const batches = bodies.map(JSON.parse);
  assert.deepEqual(batches.map((batch) => batch.events.length), [100, 100, 5]);
  assert.equal(new Set(batches.map((batch) => batch.batch_id)).size, 3);
  assert.deepEqual(batches.flatMap((batch) => batch.events.map((row) => row.observation_id)), Array.from({ length: 205 }, (_, i) => `obs-${i}`));
  assert.equal(batches[0].events[0].total_tokens, 0);
  assert.equal(batches[0].events[1].total_tokens, null);
  assert.equal(batches[0].events[0].cost_usd, null);
  assert.ok(bodies.every((body) => Buffer.byteLength(body) <= 262144));
  reconciles(instance.snapshot());
});

test('event and byte limits include a batch retained in flight', async () => {
  const gate = deferred(); let request;
  globalThis.fetch = async (_, input) => { request = input; return gate.promise; };
  const instance = exporter({ maxEvents: 1 });
  instance.emit(event());
  const initialBytes = instance.snapshot().pending_bytes;
  const flushing = instance.flush(2000);
  await until(() => request);
  assert.equal(instance.snapshot().pending_bytes, initialBytes);
  assert.equal(instance.snapshot().in_flight_events, 1);
  assert.equal(instance.emit(event()).code, 'queue_full');
  reconciles(instance.snapshot());
  gate.resolve(receipt(request.body));
  assert.equal((await flushing).confirmed, true);
  const bytesLimited = exporter({ maxBytes: initialBytes });
  assert.equal(bytesLimited.emit(event()).accepted, true);
  assert.equal(bytesLimited.emit(event()).code, 'queue_full');
  assert.equal(exporter({ maxBytes: 1 }).emit(event()).code, 'queue_full');
});

test('retry owns one transport attempt, exact immutable body and a one-second floor', async () => {
  const bodies = [], times = [];
  globalThis.fetch = async (_, request) => {
    bodies.push(request.body); times.push(performance.now());
    return bodies.length === 1 ? new Response('private', { status: 500 }) : receipt(request.body);
  };
  const instance = exporter({ maxAttempts: 2 });
  const caller = event(); instance.emit(caller); caller.model = 'mutated';
  const result = await instance.flush(2500);
  assert.equal(result.confirmed, true);
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0], bodies[1]);
  assert.ok(times[1] - times[0] >= 990);
  assert.equal(result.stats.export_attempts, 2);
});

test('flush and close never accelerate a Retry-After deadline', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response('', { status: 429, headers: { 'Retry-After': '2' } }); };
  const instance = exporter(); instance.emit(event());
  assert.equal((await instance.flush(40)).drained, false);
  assert.equal((await instance.flush(40)).drained, false);
  const closed = await instance.close(40);
  assert.equal(calls, 1);
  assert.equal(closed.confirmed, false);
  assert.equal(closed.stats.unconfirmed_events, 1);
});

test('Retry-After beyond age budget terminates without a further request', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response('', { status: 503, headers: { 'Retry-After': '3600' } }); };
  const instance = exporter(); instance.emit(event());
  const result = await instance.flush(1000);
  assert.equal(result.drained, true); assert.equal(result.confirmed, false);
  assert.equal(result.stats.last_error_code, 'batch_expired'); assert.equal(calls, 1);
});

test('elapsed monotonic batch budget prevents a retry even if wall time is unchanged', async (t) => {
  let monotonic = 1000;
  t.mock.method(performance, 'now', () => monotonic);
  globalThis.fetch = async () => { monotonic += 2000; return new Response('', { status: 500 }); };
  const instance = exporter({ maxBatchAgeMs: 1000 }); instance.emit(event());
  const result = await instance.flush(1000);
  assert.equal(result.stats.export_attempts, 1);
  assert.equal(result.stats.last_error_code, 'batch_expired');
});

test('original event age is rechecked before first I/O', async (t) => {
  const wall = Date.now();
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error(); };
  const instance = exporter(); instance.emit(event({ started_at: new Date(wall - 23 * 3600000).toISOString() }));
  t.mock.method(Date, 'now', () => wall + 2 * 3600000);
  const result = await instance.flush(1000);
  assert.equal(calls, 0); assert.equal(result.stats.last_error_code, 'event_expired');
});

test('an expired unsent head does not discard newer events in either queue order', async (t) => {
  let wall = Date.now();
  t.mock.method(Date, 'now', () => wall);
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  for (const order of [['old', 'fresh'], ['fresh', 'old'], ['fresh', 'old', 'fresh']]) {
    const instance = exporter();
    for (let index = 0; index < order.length; index += 1) instance.emit(event({ observation_id: `${order[index]}-${index}`,
      started_at: new Date(wall - (order[index] === 'old' ? 86400000 - 1000 : 0)).toISOString(), ended_at: new Date(wall).toISOString() }));
    wall += 2000;
    const before = bodies.length;
    const result = await instance.flush(1000);
    assert.equal(result.drained, true); assert.equal(result.confirmed, false);
    assert.equal(result.stats.unconfirmed_events, 1);
    assert.equal(result.stats.confirmed_events, order.length - 1);
    assert.deepEqual(bodies.slice(before).flatMap((batch) => batch.events.map((row) => row.observation_id)),
      order.flatMap((kind, index) => kind === 'fresh' ? [`${kind}-${index}`] : []));
    reconciles(result.stats);
  }
});

test('expiry crossing during first batch construction preserves fresh FIFO neighbors', async (t) => {
  const wall = Date.now();
  let armed = false, clockReads = 0;
  t.mock.method(Date, 'now', () => armed && ++clockReads > 1 ? wall + 2 : wall);
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  for (const order of [['old', 'fresh'], ['fresh', 'old'], ['fresh', 'old', 'fresh']]) {
    armed = false; clockReads = 0;
    const instance = exporter();
    for (let index = 0; index < order.length; index += 1) {
      assert.equal(instance.emit(event({ observation_id: `${order[index]}-${index}`,
        started_at: new Date(wall - (order[index] === 'old' ? 86400000 - 1 : 0)).toISOString(),
        ended_at: new Date(wall).toISOString() })).accepted, true);
    }
    // makeBatch sees the still-valid timestamp; pump's next wall-clock read sees
    // it expired. No sleeps or timing-dependent scheduling are needed.
    armed = true;
    const before = bodies.length;
    const result = await instance.flush(1000);
    assert.equal(result.drained, true); assert.equal(result.confirmed, false);
    assert.equal(result.stats.unconfirmed_events, 1);
    assert.equal(result.stats.confirmed_events, order.length - 1);
    assert.equal(result.stats.pending_bytes, 0);
    assert.deepEqual(bodies.slice(before).flatMap((batch) => batch.events.map((row) => row.observation_id)),
      order.flatMap((kind, index) => kind === 'fresh' ? [`${kind}-${index}`] : []));
    assert.equal(result.stats.export_attempts, order.length === 3 ? 2 : 1);
    reconciles(result.stats);
  }
});

test('default attempts have exponential 1, 2, 4, 8 second floors and stop at five', async (t) => {
  let monotonic = 0, calls = 0;
  t.mock.method(performance, 'now', () => monotonic);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  globalThis.fetch = async () => { calls += 1; return new Response('', { status: 500 }); };
  const instance = exporter(); instance.emit(event());
  const flushing = instance.flush(30000);
  t.mock.timers.tick(0);
  await new Promise(setImmediate);
  assert.equal(calls, 1);
  for (const floor of [1000, 2000, 4000, 8000]) {
    const before = calls;
    monotonic += floor - 1; t.mock.timers.tick(floor - 1);
    await new Promise(setImmediate);
    assert.equal(calls, before);
    monotonic += 1; t.mock.timers.tick(1);
    await new Promise(setImmediate);
    assert.equal(calls, before + 1);
  }
  const result = await flushing;
  assert.equal(result.confirmed, false); assert.equal(result.stats.export_attempts, 5);
  assert.equal(result.stats.unconfirmed_events, 1);
  await instance.close(0);
});

test('normal batching waits one second from the first event without later-event starvation', async (t) => {
  let monotonic = 0, calls = 0;
  t.mock.method(performance, 'now', () => monotonic);
  t.mock.timers.enable({ apis: ['setTimeout'] });
  globalThis.fetch = async (_, request) => { calls += 1; return receipt(request.body); };
  const instance = exporter(); instance.emit(event());
  monotonic = 900; t.mock.timers.tick(900); await new Promise(setImmediate);
  assert.equal(calls, 0); instance.emit(event());
  monotonic = 1000; t.mock.timers.tick(100); await new Promise(setImmediate);
  assert.equal(calls, 1); assert.equal(instance.snapshot().confirmed_events, 2);
  await instance.close(0);
});

test('credential rejection stops all queued work and future admissions', async () => {
  for (const status of [401, 403]) {
    let calls = 0;
    globalThis.fetch = async () => { calls += 1; return new Response('private', { status }); };
    const instance = exporter({ maxBatchEvents: 1 }); instance.emit(event()); instance.emit(event());
    const result = await instance.flush(1000);
    assert.equal(calls, 1); assert.equal(result.drained, true); assert.equal(result.confirmed, false);
    assert.equal(result.stats.unconfirmed_events, 2);
    assert.equal(instance.emit(event()).code, 'exporter_unavailable');
    assert.equal(instance.snapshot().last_error_code, 'credential_rejected');
    reconciles(instance.snapshot());
  }
});

test('permanent batch rejection is terminal while later batches may continue', async () => {
  let calls = 0;
  globalThis.fetch = async (_, request) => ++calls === 1 ? new Response('private', { status: 400 }) : receipt(request.body);
  const instance = exporter({ maxBatchEvents: 1 }); instance.emit(event()); instance.emit(event());
  const result = await instance.flush(1000);
  assert.equal(calls, 2); assert.equal(result.drained, true); assert.equal(result.confirmed, false);
  assert.equal(result.stats.confirmed_events, 1); assert.equal(result.stats.unconfirmed_events, 1);
});

test('unverified receipt reaches attempt limit without fabricated confirmation', async () => {
  let calls = 0;
  globalThis.fetch = async (_, request) => { calls += 1; return receipt(request.body, { received: 0 }); };
  const instance = exporter({ maxAttempts: 1 }); instance.emit(event());
  const result = await instance.flush(1000);
  assert.equal(calls, 1); assert.equal(result.confirmed, false);
  assert.equal(result.stats.last_error_code, 'receipt_unconfirmed');
});

test('flush covers its admission prefix without waiting for later producers', async () => {
  const gates = [], requests = [];
  globalThis.fetch = async (_, request) => { const gate = deferred(); gates.push(gate); requests.push(request); return gate.promise; };
  const instance = exporter({ maxBatchEvents: 1 }); instance.emit(event());
  const first = instance.flush(1000);
  await until(() => gates.length === 1);
  instance.emit(event({ observation_id: 'later' }));
  gates[0].resolve(receipt(requests[0].body));
  const result = await first;
  assert.equal(result.confirmed, true); assert.equal(result.stats.pending_events, 1);
  await instance.close(0);
  for (let i = 1; i < gates.length; i += 1) gates[i].resolve(receipt(requests[i].body));
});

test('flush timeout preserves work and later acknowledgement can confirm it', async () => {
  const gate = deferred(); let request;
  globalThis.fetch = async (_, input) => { request = input; return gate.promise; };
  const instance = exporter(); instance.emit(event());
  assert.equal((await instance.flush(30)).drained, false);
  assert.equal(instance.snapshot().pending_events, 1);
  gate.resolve(receipt(request.body));
  assert.equal((await instance.flush(1000)).confirmed, true);
});

test('forced close aborts transport, fences late success, and stops admission idempotently', async () => {
  const gate = deferred(); let request;
  globalThis.fetch = async (_, input) => { request = input; return gate.promise; };
  const instance = exporter(); instance.emit(event());
  const flushing = instance.flush(1000);
  await until(() => request);
  const closing = instance.close(0);
  assert.equal(instance.close(1000), closing);
  const result = await closing;
  assert.equal(request.signal.aborted, true);
  assert.equal(result.drained, true); assert.equal(result.confirmed, false);
  assert.equal((await flushing).confirmed, false);
  assert.equal(instance.emit(event()).code, 'closed');
  gate.resolve(receipt(request.body));
  await until(() => !instance.snapshot().transport_active);
  assert.equal(instance.snapshot().confirmed_events, 0);
  assert.equal(instance.snapshot().unconfirmed_events, 1);
  reconciles(instance.snapshot());
});

test('single-attempt transport keeps default manual responses and honors external abort', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response('', { status: 401 }); };
  assert.deepEqual(await sendBatch(testBatch(), configuration), { ok: false, code: 'rejected' });
  assert.deepEqual(await sendBatch(testBatch(), { ...configuration, maxAttempts: 1, includeHttpStatus: true }),
    { ok: false, code: 'rejected', http_status: 401 });
  const controller = new AbortController(); controller.abort();
  assert.deepEqual(await sendBatch(testBatch(), { ...configuration, externalAbortSignal: controller.signal }), { ok: false, code: 'cancelled' });
  assert.equal(calls, 2);
  const requestSeen = deferred();
  globalThis.fetch = async (_, request) => {
    requestSeen.resolve();
    return new Promise((_, reject) => request.signal.addEventListener('abort', () => reject(new Error('private')), { once: true }));
  };
  const active = new AbortController();
  const pending = sendBatch(testBatch(), { ...configuration, externalAbortSignal: active.signal });
  await requestSeen.promise; active.abort();
  assert.equal((await pending).code, 'cancelled');
});

test('known credential denial survives body cancellation failure and date retry hints stay bounded', async () => {
  globalThis.fetch = async () => ({ status: 403, body: { cancel: async () => { throw new Error('private'); } }, headers: new Headers() });
  assert.equal((await sendBatch(testBatch(), { ...configuration, maxAttempts: 1, includeHttpStatus: true })).http_status, 403);
  globalThis.fetch = async () => new Response('', { status: 503, headers: { 'Retry-After': new Date(Date.now() + 86400000).toUTCString() } });
  assert.equal((await sendBatch(testBatch(), configuration)).retry_after_seconds, 3600);
  for (const status of [500, 502, 503, 504]) {
    globalThis.fetch = async () => new Response('', { status, headers: { 'Retry-After': '2' } });
    assert.deepEqual(await sendBatch(testBatch(), { ...configuration, maxAttempts: 1 }),
      { ok: false, code: 'temporarily_unavailable', retry_after_seconds: 2 });
  }
});

test('handles capture only identity and seal on the first finish, even rejection', async () => {
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  const instance = exporter();
  const metadata = { agent_name: 'technical', model: 'model', trace_id: 'shared', parent_observation_id: 'parent' };
  const first = instance.startCall(metadata), retry = instance.startCall(metadata);
  metadata.model = 'mutated';
  assert.notEqual(first.observation_id, retry.observation_id);
  assert.equal(first.trace_id, retry.trace_id);
  assert.equal(first.finish({ status: 'success', cost_usd: '0' }).accepted, true);
  assert.equal(first.finish({ status: 'error' }).code, 'already_finished');
  assert.equal(retry.finish({ status: 'unknown', cost_usd: 0 }).code, 'invalid_event');
  assert.equal(retry.finish({ status: 'success' }).code, 'already_finished');
  const inert = instance.startCall({ agent_name: 'technical', model: { private: true } });
  assert.equal(inert.observation_id, null);
  assert.equal(inert.finish({ status: 'success' }).code, 'invalid_event');
  assert.equal(inert.finish({ status: 'success' }).code, 'already_finished');
  assert.equal(instance.snapshot().rejected_events, 2);
  await instance.flush(1000);
  assert.equal(bodies[0].events[0].model, 'model');
  assert.equal(bodies[0].events[0].cost_usd, '0');
  assert.equal(bodies[0].events[0].total_tokens, null);
});

test('synthetic helpers preserve return, stream chunks, original exceptions and cancellation', async () => {
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  const instance = exporter(), metadata = { agent_name: 'technical', model: 'model' };
  const value = {}, failure = new Error('private');
  assert.equal(await runCall(instance, metadata, async () => value), value);
  await assert.rejects(runCall(instance, metadata, async () => { throw failure; }), (error) => error === failure);
  async function* provider() { yield value; yield value; }
  const chunks = [];
  for await (const chunk of streamCall(instance, metadata, provider)) chunks.push(chunk);
  assert.deepEqual(chunks, [value, value]); assert.equal(chunks[0], value);
  for await (const chunk of streamCall(instance, metadata, provider)) { assert.equal(chunk, value); break; }
  const controller = new AbortController();
  await assert.rejects(runCall(instance, metadata, async () => { controller.abort(); throw failure; }, {}, { signal: controller.signal }), (error) => error === failure);
  await instance.flush(1000);
  assert.deepEqual(bodies[0].events.map((row) => row.status), ['success', 'error', 'success', 'unknown', 'unknown']);
  assert.ok(bodies[0].events.every((row) => row.cost_usd === null && row.total_tokens === null));
});

test('helper measurements cannot override status or invoke a getter on the serving path', async () => {
  const instance = exporter(); const value = {};
  let hooks = 0;
  for (const measurements of [{ status: 'error' }, { get cost_usd() { hooks += 1; throw new Error('private'); } },
    new Proxy({}, { ownKeys() { hooks += 1; throw new Error('private'); } })]) {
    assert.equal(await runCall(instance, { agent_name: 'technical', model: 'model' }, async () => value, measurements), value);
  }
  assert.equal(hooks, 0);
  assert.equal(instance.snapshot().enqueued_events, 0);
  assert.equal(instance.snapshot().rejected_events, 3);
});

test('stream errors preserve original exceptions and signalled early return stays unknown', async () => {
  const bodies = [], instance = exporter(), metadata = { agent_name: 'technical', model: 'model' };
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  const failure = new Error('private'), controller = new AbortController();
  async function* broken() { yield 1; throw failure; }
  await assert.rejects(async () => { for await (const _chunk of streamCall(instance, metadata, broken)) { /* exhaust */ } }, (error) => error === failure);
  async function* cancelled() { yield 1; controller.abort(); throw failure; }
  await assert.rejects(async () => { for await (const _chunk of streamCall(instance, metadata, cancelled, {}, { signal: controller.signal })) { /* exhaust */ } }, (error) => error === failure);
  await instance.flush(1000);
  assert.deepEqual(bodies[0].events.map((row) => row.status), ['error', 'unknown']);
});

test('test-mode lifecycle batches cannot become production telemetry', async () => {
  const bodies = [];
  globalThis.fetch = async (_, request) => { bodies.push(JSON.parse(request.body)); return receipt(request.body); };
  const options = { testMode: true };
  const instance = exporter(options); options.testMode = false;
  await syntheticLifecycle(instance);
  assert.equal((await instance.close(1000)).confirmed, true);
  assert.equal(bodies[0].test_mode, true);
  assert.deepEqual(bodies[0].events.map((row) => row.status), ['success', 'success', 'unknown', 'error']);
});

test('import, no-argument recipe and idle batching do not keep a child process alive', () => {
  const module = new URL('../../examples/native-capture/guardian_exporter.mjs', import.meta.url).href;
  const script = `import {BackgroundExporter} from ${JSON.stringify(module)};
    globalThis.fetch=()=>{throw new Error('unexpected_network')};
    const exporter=new BackgroundExporter(${JSON.stringify(configuration)});
    exporter.emit(${JSON.stringify(event())});`;
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8', timeout: 2000 });
  assert.equal(child.status, 0, child.stderr); assert.equal(child.stdout, '');
  const recipe = spawnSync(process.execPath, [fileURLToPath(new URL('../../examples/native-capture/node_app.mjs', import.meta.url))], { encoding: 'utf8', timeout: 2000 });
  assert.equal(recipe.status, 0, recipe.stderr); assert.match(recipe.stdout, /--send-test/);
});

test('an explicit flush keeps required work alive in an otherwise idle child', () => {
  const module = new URL('../../examples/native-capture/guardian_exporter.mjs', import.meta.url).href;
  const script = `import {BackgroundExporter} from ${JSON.stringify(module)};
    globalThis.fetch=async(_,r)=>{const b=JSON.parse(r.body); return new Response(JSON.stringify({batch_id:b.batch_id,test_mode:false,processing:'queued',received:1,duplicate:0,conflict_candidates:0,replayed:false}),{status:202})};
    const exporter=new BackgroundExporter(${JSON.stringify(configuration)});
    exporter.emit(${JSON.stringify(event())});
    console.log(JSON.stringify(await exporter.flush(1000)));`;
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8', timeout: 2500 });
  assert.equal(child.status, 0, child.stderr); assert.equal(JSON.parse(child.stdout).confirmed, true);
});
