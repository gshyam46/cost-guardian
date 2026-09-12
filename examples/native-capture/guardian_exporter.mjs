// A process-local queue for terminal measurements. No configuration or I/O on import.
import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { types } from 'node:util';
import { sendBatch, target } from './guardian_capture.mjs';

const REQUIRED = ['observation_id', 'trace_id', 'agent_name', 'model', 'started_at', 'ended_at', 'status'];
const OPTIONAL = ['parent_observation_id', 'cost_usd', 'input_tokens', 'output_tokens', 'total_tokens'];
const TOKENS = ['input_tokens', 'output_tokens', 'total_tokens'];
const ID = /^[A-Za-z0-9_.:-]{1,128}(?![\s\S])/;
const LABEL = /^[A-Za-z0-9_.:/-]{1,120}(?![\s\S])/;
const COST = /^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?(?![\s\S])/;
const DAY_US = 86400000000n;
const FUTURE_US = 300000000n;
const MAX_BODY = 262144;
const FAILURE_CODES = new Set(['rejected', 'receipt_unconfirmed', 'rate_limited', 'temporarily_unavailable',
  'invalid_configuration_or_batch', 'cancelled']);

// Inspect descriptors rather than reading caller properties: no getters, JSON hooks,
// proxies, inherited fields, symbols, SDK objects or nested values enter the queue.
function flat(value, allowed, required = []) {
  if (!value || typeof value !== 'object' || types.isProxy(value)
      || ![null, Object.prototype].includes(Object.getPrototypeOf(value))) throw new Error();
  const keys = Reflect.ownKeys(value);
  if (keys.some((key) => typeof key !== 'string' || !allowed.includes(key))
      || required.some((key) => !keys.includes(key))) throw new Error();
  const copy = Object.create(null);
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!Object.hasOwn(descriptor, 'value') || !descriptor.enumerable
        || !['string', 'number', 'boolean'].includes(typeof descriptor.value) && descriptor.value !== null) throw new Error();
    copy[key] = descriptor.value;
  }
  return copy;
}

function stamp(value) {
  if (typeof value !== 'string' || value.length > 40) throw new Error();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})(?![\s\S])/.exec(value);
  if (!match) throw new Error();
  const [, year, month, day, hour, minute, second, fraction = '', zone] = match;
  if (+year < 1 || +month < 1 || +month > 12 || +day < 1 || +hour > 23 || +minute > 59 || +second > 59) throw new Error();
  const date = new Date(0);
  date.setUTCFullYear(+year, +month - 1, +day);
  date.setUTCHours(+hour, +minute, +second, 0);
  if (date.getUTCFullYear() !== +year || date.getUTCMonth() !== +month - 1 || date.getUTCDate() !== +day) throw new Error();
  let offset = 0;
  if (zone !== 'Z') {
    const hours = +zone.slice(1, 3), minutes = +zone.slice(4, 6);
    if (hours > 23 || minutes > 59) throw new Error();
    offset = (hours * 60 + minutes) * (zone[0] === '+' ? 1 : -1);
  }
  return BigInt(date.getTime() - offset * 60000) * 1000n + BigInt(fraction.padEnd(6, '0'));
}

function normalize(value) {
  const row = flat(value, [...REQUIRED, ...OPTIONAL], REQUIRED);
  for (const key of ['observation_id', 'trace_id']) if (typeof row[key] !== 'string' || !ID.test(row[key])) throw new Error();
  if (row.parent_observation_id != null && (typeof row.parent_observation_id !== 'string' || !ID.test(row.parent_observation_id))) throw new Error();
  for (const key of ['agent_name', 'model']) if (typeof row[key] !== 'string' || !LABEL.test(row[key])) throw new Error();
  if (!['success', 'error', 'unknown'].includes(row.status)) throw new Error();
  const start = stamp(row.started_at), end = stamp(row.ended_at), now = BigInt(Date.now()) * 1000n;
  if (start < now - DAY_US || end < start || start > now + FUTURE_US || end > now + FUTURE_US) throw new Error();
  if (row.cost_usd != null && (typeof row.cost_usd !== 'string' || !COST.test(row.cost_usd))) throw new Error();
  for (const key of TOKENS) if (row[key] != null && (!Number.isSafeInteger(row[key]) || row[key] < 0)) throw new Error();
  if (row.input_tokens != null && row.output_tokens != null) {
    const total = row.input_tokens + row.output_tokens;
    if (!Number.isSafeInteger(total) || (row.total_tokens != null && row.total_tokens !== total)) throw new Error();
    row.total_tokens = total;
  }
  // Canonical key order and explicit unknowns produce immutable, reproducible bytes.
  const event = Object.create(null);
  for (const key of [...REQUIRED, ...OPTIONAL]) event[key] = row[key] ?? null;
  Object.freeze(event);
  return { event, start, bytes: Buffer.byteLength(JSON.stringify(event)) };
}

function integer(value, minimum, maximum) {
  return Number.isInteger(value) && value >= minimum && value <= maximum;
}

export class BackgroundExporter {
  #options; #queue = []; #active = null; #timer = null; #timerAt = null; #controller = null;
  #transportActive = false; #generation = 0; #unavailable = false; #closed = false;
  #enqueued = 0; #confirmed = 0; #unconfirmed = 0; #rejected = 0; #bytes = 0;
  #attempts = 0; #completed = 0; #firstUnconfirmed = null; #lastError = null;
  #waiters = new Set(); #closePromise = null;

  constructor(options = {}) {
    try {
      const supplied = flat(options, ['origin', 'token', 'allowLocal', 'testMode', 'maxEvents', 'maxBytes',
        'batchDelayMs', 'maxBatchEvents', 'maxAttempts', 'maxBatchAgeMs']);
      const values = { allowLocal: false, testMode: false, maxEvents: 1000, maxBytes: 4 * 1024 * 1024,
        batchDelayMs: 1000, maxBatchEvents: 100, maxAttempts: 5, maxBatchAgeMs: 300000, ...supplied };
      if (typeof values.origin !== 'string' || typeof values.token !== 'string'
          || !/^cg_ingest_[a-f0-9]{32}_[A-Za-z0-9_-]{43}(?![\s\S])/.test(values.token)
          || typeof values.allowLocal !== 'boolean' || typeof values.testMode !== 'boolean'
          || !integer(values.maxEvents, 1, 1000) || !integer(values.maxBytes, 1, 4194304)
          || !integer(values.batchDelayMs, 0, 1000) || !integer(values.maxBatchEvents, 1, 100)
          || !integer(values.maxAttempts, 1, 5) || !integer(values.maxBatchAgeMs, 1, 300000)) throw new Error();
      target(values.origin, values.allowLocal);
      this.#options = Object.freeze(values);
    } catch { throw new Error('invalid_exporter_configuration'); }
  }

  #reject(code) {
    this.#rejected += 1;
    if (!this.#unavailable) this.#lastError = code;
    return { accepted: false, code };
  }

  emit(event) {
    if (this.#closed) return this.#reject('closed');
    if (this.#unavailable) return this.#reject('exporter_unavailable');
    try {
      const item = normalize(event);
      if (this.#enqueued - this.#confirmed - this.#unconfirmed >= this.#options.maxEvents
          || this.#bytes + item.bytes > this.#options.maxBytes) return this.#reject('queue_full');
      item.sequence = ++this.#enqueued;
      item.admittedAt = performance.now();
      this.#bytes += item.bytes;
      this.#queue.push(item);
      this.#schedule();
      return { accepted: true, code: 'queued' };
    } catch { return this.#reject('invalid_event'); }
  }

  startCall(metadata) {
    let identity, event;
    try {
      identity = flat(metadata, ['agent_name', 'model', 'trace_id', 'parent_observation_id'], ['agent_name', 'model']);
      if (typeof identity.agent_name !== 'string' || !LABEL.test(identity.agent_name)
          || typeof identity.model !== 'string' || !LABEL.test(identity.model)
          || (identity.trace_id != null && (typeof identity.trace_id !== 'string' || !ID.test(identity.trace_id)))
          || (identity.parent_observation_id != null && (typeof identity.parent_observation_id !== 'string' || !ID.test(identity.parent_observation_id)))) throw new Error();
      event = { ...identity, trace_id: identity.trace_id ?? randomUUID(), observation_id: randomUUID(),
        started_at: new Date().toISOString(), parent_observation_id: identity.parent_observation_id ?? null };
    } catch {
      this.#reject('invalid_event');
      let finished = false;
      return Object.freeze({ observation_id: null, trace_id: null, parent_observation_id: null,
        finish: () => { const code = finished ? 'already_finished' : 'invalid_event'; finished = true; return { accepted: false, code }; } });
    }
    let finished = false;
    return Object.freeze({ observation_id: event.observation_id, trace_id: event.trace_id,
      parent_observation_id: event.parent_observation_id,
      finish: (measurements) => {
        if (finished) return { accepted: false, code: 'already_finished' };
        finished = true;
        try {
          const values = flat(measurements, ['status', 'cost_usd', ...TOKENS], ['status']);
          return this.emit({ ...event, ...values, ended_at: new Date().toISOString() });
        } catch { return this.#reject('invalid_event'); }
      } });
  }

  snapshot() {
    return { enqueued_events: this.#enqueued, confirmed_events: this.#confirmed,
      unconfirmed_events: this.#unconfirmed, rejected_events: this.#rejected,
      pending_events: this.#enqueued - this.#confirmed - this.#unconfirmed,
      queued_events: this.#queue.length, in_flight_events: this.#active?.items.length ?? 0,
      pending_bytes: this.#bytes, export_attempts: this.#attempts, closed: this.#closed,
      transport_active: this.#transportActive, last_error_code: this.#lastError };
  }

  #schedule() {
    if (this.#unavailable || this.#transportActive || (!this.#active && !this.#queue.length)) return;
    const now = performance.now();
    const urgent = [...this.#waiters].some((waiter) => waiter.target > this.#completed);
    const due = this.#active ? this.#active.nextAt
      : (urgent ? now : this.#queue[0].admittedAt + this.#options.batchDelayMs);
    if (this.#timer && this.#timerAt <= due) return;
    clearTimeout(this.#timer);
    this.#timerAt = due;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      this.#timerAt = null;
      void this.#pump();
    }, Math.max(0, Math.ceil(due - now)));
    // A best-effort background queue must not hold an otherwise idle process open.
    // Explicit flush/close has its own referenced deadline timer.
    this.#timer.unref();
  }

  #makeBatch() {
    const batch = Object.assign(Object.create(null), {
      schema_version: 1, batch_id: randomUUID(), test_mode: this.#options.testMode, events: [],
    });
    const items = [];
    const oldestAllowed = BigInt(Date.now()) * 1000n - DAY_US;
    while (this.#queue.length && items.length < this.#options.maxBatchEvents) {
      const item = this.#queue[0];
      // Never mix a known-expired, unattempted event with its fresh neighbors.
      // Its own terminal disposition still advances the FIFO prefix in order.
      if (items.length && item.start < oldestAllowed) break;
      batch.events.push(item.event);
      if (Buffer.byteLength(JSON.stringify(batch)) > MAX_BODY) { batch.events.pop(); break; }
      items.push(this.#queue.shift());
      if (item.start < oldestAllowed) break;
    }
    Object.freeze(batch.events);
    Object.freeze(batch);
    const now = performance.now();
    this.#active = { items, batch, createdAt: now, nextAt: now, attempts: 0 };
  }

  #terminal(confirmed, code = null) {
    const items = this.#active.items;
    if (confirmed) {
      this.#confirmed += items.length;
      this.#lastError = null;
    }
    else {
      this.#unconfirmed += items.length;
      this.#firstUnconfirmed ??= items[0].sequence;
      this.#lastError = code;
    }
    this.#bytes -= items.reduce((sum, item) => sum + item.bytes, 0);
    this.#completed = items.at(-1).sequence;
    this.#active = null;
    this.#notify();
  }

  #stop(code) {
    this.#generation += 1;
    clearTimeout(this.#timer);
    this.#timer = null;
    this.#timerAt = null;
    this.#controller?.abort();
    const pending = this.#enqueued - this.#confirmed - this.#unconfirmed;
    if (pending) {
      this.#firstUnconfirmed ??= this.#completed + 1;
      this.#unconfirmed += pending;
      this.#completed = this.#enqueued;
    }
    this.#queue = [];
    this.#active = null;
    this.#bytes = 0;
    this.#lastError = code;
    this.#notify();
  }

  async #pump() {
    if (this.#unavailable || this.#transportActive || (!this.#active && !this.#queue.length)) return;
    try {
      if (!this.#active) this.#makeBatch();
      const active = this.#active, now = performance.now();
      if (now < active.nextAt) { this.#schedule(); return; }
      if (now - active.createdAt >= this.#options.maxBatchAgeMs) {
        this.#terminal(false, 'batch_expired'); this.#schedule(); return;
      }
      const oldestAllowed = BigInt(Date.now()) * 1000n - DAY_US;
      if (active.items.some((item) => item.start < oldestAllowed)) {
        if (active.attempts === 0 && active.items.length > 1) {
          // Wall time can cross the acceptance boundary during batch construction.
          // Nothing was sent yet: restore FIFO order so batching can isolate the
          // expired entry without discarding its fresh neighbors. Keep capacity.
          this.#queue = [...active.items, ...this.#queue];
          this.#active = null;
        } else this.#terminal(false, 'event_expired');
        this.#schedule(); return;
      }
      const generation = this.#generation;
      active.attempts += 1;
      this.#attempts += 1;
      this.#transportActive = true;
      this.#controller = new AbortController();
      let result;
      try {
        result = await sendBatch(active.batch, { origin: this.#options.origin, token: this.#options.token,
          allowLocal: this.#options.allowLocal, maxAttempts: 1, includeHttpStatus: true,
          externalAbortSignal: this.#controller.signal });
      } catch { result = { ok: false, code: 'receipt_unconfirmed' }; }
      finally { this.#transportActive = false; this.#controller = null; }
      if (generation !== this.#generation) return;
      if (result.ok) this.#terminal(true);
      else if ([401, 403].includes(result.http_status)) {
        this.#unavailable = true;
        this.#stop('credential_rejected');
      } else {
        const code = FAILURE_CODES.has(result.code) ? result.code : 'receipt_unconfirmed';
        this.#lastError = code;
        if (['rejected', 'invalid_configuration_or_batch'].includes(code)
            || active.attempts >= this.#options.maxAttempts) this.#terminal(false, code);
        else {
          const floor = Math.min(8000, 1000 * 2 ** (active.attempts - 1));
          const serverFloor = Number.isFinite(result.retry_after_seconds) && result.retry_after_seconds > 0
            ? result.retry_after_seconds * 1000 : 0;
          active.nextAt = performance.now() + Math.max(floor, serverFloor);
          if (active.nextAt >= active.createdAt + this.#options.maxBatchAgeMs) this.#terminal(false, 'batch_expired');
        }
      }
      this.#schedule();
    } catch {
      this.#unavailable = true;
      this.#stop('exporter_unavailable');
    }
  }

  #result(target) {
    const drained = this.#completed >= target;
    return { drained, confirmed: drained && (this.#firstUnconfirmed === null || this.#firstUnconfirmed > target), stats: this.snapshot() };
  }

  #notify() {
    for (const waiter of this.#waiters) if (this.#completed >= waiter.target) waiter.finish();
  }

  #wait(target, timeoutMs) {
    if (this.#completed >= target || timeoutMs === 0) return Promise.resolve(this.#result(target));
    return new Promise((resolve) => {
      const waiter = { target, finish: () => {
        clearTimeout(waiter.timer);
        this.#waiters.delete(waiter);
        resolve(this.#result(target));
      } };
      waiter.timer = setTimeout(waiter.finish, timeoutMs);
      this.#waiters.add(waiter);
      this.#schedule();
    });
  }

  flush(timeoutMs = 5000) {
    if (!integer(timeoutMs, 0, 300000)) return Promise.resolve({ ...this.#result(this.#enqueued), drained: false, confirmed: false });
    return this.#wait(this.#enqueued, timeoutMs);
  }

  close(timeoutMs = 5000) {
    if (this.#closePromise) return this.#closePromise;
    this.#closed = true;
    const targetSequence = this.#enqueued;
    const boundedTimeout = integer(timeoutMs, 0, 300000) ? timeoutMs : 0;
    this.#closePromise = this.#wait(targetSequence, boundedTimeout).then((result) => {
      if (!result.drained) {
        this.#stop('close_timeout');
        return { ...this.#result(targetSequence), confirmed: false };
      }
      return result;
    });
    return this.#closePromise;
  }
}
