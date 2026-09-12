// OpenAI usage adapters. Import is inert; the application owns its SDK and requests.
import { types } from 'node:util';

const MAX_TOKENS = Number.MAX_SAFE_INTEGER;
const UNKNOWN = () => ({ input_tokens: null, output_tokens: null, total_tokens: null });
const APIS = new Set(['responses', 'chat_completions']);
const SUCCESS = new Set(['stop', 'tool_calls', 'function_call']);
const TERMINAL = new Set([...SUCCESS, 'length', 'content_filter']);
const RESPONSE_TERMINAL = new Set(['completed', 'failed', 'incomplete']);

function record(value) {
  return value !== null && typeof value === 'object' && !types.isProxy(value)
    && !Array.isArray(value) && [null, Object.prototype].includes(Object.getPrototypeOf(value));
}
function field(value, name) {
  if (!record(value)) throw new Error('unsupported_usage');
  const descriptor = Object.getOwnPropertyDescriptor(value, name);
  if (!descriptor) return undefined;
  if (!Object.hasOwn(descriptor, 'value')) throw new Error('unsupported_usage');
  return descriptor.value;
}
function array(value, max = 1) {
  if (!Array.isArray(value) || types.isProxy(value)) throw new Error('unsupported_usage');
  const length = Object.getOwnPropertyDescriptor(value, 'length').value;
  if (length > max) throw new Error('unsupported_usage');
  const items = [];
  for (let index = 0; index < length; index += 1) {
    const item = Object.getOwnPropertyDescriptor(value, String(index));
    if (!item || !Object.hasOwn(item, 'value')) throw new Error('unsupported_usage');
    items.push(item.value);
  }
  return items;
}
function count(value) {
  if (value === undefined || value === null) return null;
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_TOKENS) throw new Error('unsupported_usage');
  return value;
}
function subset(usage, detailsName, names, parent, total) {
  const details = field(usage, detailsName);
  if (details === undefined || details === null) return;
  for (const name of names) {
    const value = count(field(details, name));
    if (value !== null && [parent, total].some((limit) => limit !== null && value > limit)) throw new Error('unsupported_usage');
  }
}
function usageSnapshot(response, api) {
  if (!APIS.has(api)) throw new Error('unsupported_api');
  const usage = field(response, 'usage');
  if (usage === undefined || usage === null) return UNKNOWN();
  const input = count(field(usage, api === 'responses' ? 'input_tokens' : 'prompt_tokens'));
  const output = count(field(usage, api === 'responses' ? 'output_tokens' : 'completion_tokens'));
  let total = count(field(usage, 'total_tokens'));
  if (input !== null && output !== null) {
    const sum = input + output;
    if (!Number.isSafeInteger(sum) || (total !== null && total !== sum)) throw new Error('unsupported_usage');
    total = sum;
  }
  if (total !== null && ((input !== null && input > total) || (output !== null && output > total))) throw new Error('unsupported_usage');
  subset(usage, api === 'responses' ? 'input_tokens_details' : 'prompt_tokens_details', ['cached_tokens', 'cache_write_tokens'], input, total);
  subset(usage, api === 'responses' ? 'output_tokens_details' : 'completion_tokens_details', ['reasoning_tokens'], output, total);
  return { input_tokens: input, output_tokens: output, total_tokens: total };
}

export function extractOpenAIUsage(response, api = 'responses') {
  try { return usageSnapshot(response, api); } catch { return UNKNOWN(); }
}

function completion(response, api) {
  try {
    if (api === 'responses') {
      if (field(response, 'object') !== 'response') return { status: 'unknown', usage: UNKNOWN() };
      const status = field(response, 'status');
      return { status: status === 'completed' ? 'success' : status === 'failed' ? 'error' : 'unknown',
        usage: RESPONSE_TERMINAL.has(status) ? extractOpenAIUsage(response, api) : UNKNOWN() };
    }
    if (api === 'chat_completions') {
      if (field(response, 'object') !== 'chat.completion') return { status: 'unknown', usage: UNKNOWN() };
      const choices = array(field(response, 'choices'));
      if (choices.length !== 1 || field(choices[0], 'index') !== 0) return { status: 'unknown', usage: UNKNOWN() };
      const reason = field(choices[0], 'finish_reason');
      return { status: SUCCESS.has(reason) ? 'success' : 'unknown',
        usage: TERMINAL.has(reason) ? extractOpenAIUsage(response, api) : UNKNOWN() };
    }
  } catch { /* Invalid instrumentation metadata must not change the provider result. */ }
  return { status: 'unknown', usage: UNKNOWN() };
}

function callHandle(exporter, metadata) {
  try { return exporter.startCall(metadata); } catch { return null; }
}
function finish(call, status, usage = UNKNOWN()) {
  try { call?.finish({ status, ...usage }); } catch { /* Telemetry cannot fail the application. */ }
}
function cancelled(signal) {
  try { return signal?.aborted === true; } catch { return false; }
}

export async function openaiCall(exporter, metadata, operation, { api = 'responses', signal } = {}) {
  const call = callHandle(exporter, metadata);
  try {
    const response = await operation();
    const result = cancelled(signal) ? { status: 'unknown', usage: UNKNOWN() } : completion(response, api);
    finish(call, result.status, result.usage);
    return response;
  } catch (error) {
    finish(call, cancelled(signal) ? 'unknown' : 'error');
    throw error;
  }
}

class StreamState {
  constructor(api) {
    this.api = api;
    this.id = null;
    this.terminal = null;
    this.usage = null;
    this.badUsage = false;
    this.invalid = !APIS.has(api);
    this.error = false;
  }
  bind(value) {
    const id = field(value, 'id');
    if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}(?![\s\S])/.test(id)) throw new Error('invalid_stream');
    if (this.id !== null && this.id !== id) throw new Error('invalid_stream');
    this.id = id;
  }
  mark(value) {
    if (this.terminal !== null && this.terminal !== value) throw new Error('invalid_stream');
    this.terminal = value;
  }
  snapshot(value) {
    // Retain only the freshly copied numeric values, before the caller sees a chunk.
    let next;
    try { next = usageSnapshot(value, this.api); }
    catch { this.badUsage = true; return; }
    if (this.usage !== null && Object.keys(next).some((key) => next[key] !== this.usage[key])) throw new Error('invalid_stream');
    this.usage = next;
  }
  observe(chunk) {
    if (this.invalid) return;
    try {
      if (this.api === 'responses') {
        const type = field(chunk, 'type');
        if (type === 'error') { this.error = true; return; }
        if (['response.created', 'response.in_progress'].includes(type)) {
          this.bind(field(chunk, 'response'));
          return;
        }
        if (!['response.completed', 'response.failed', 'response.incomplete'].includes(type)) return;
        const response = field(chunk, 'response');
        this.bind(response);
        const status = field(response, 'status');
        if (field(response, 'object') !== 'response' || type !== 'response.' + status) throw new Error('invalid_stream');
        this.mark(status);
        this.snapshot(response);
      } else {
        if (field(chunk, 'object') !== 'chat.completion.chunk') throw new Error('invalid_stream');
        this.bind(chunk);
        const choices = array(field(chunk, 'choices'));
        if (choices.length) {
          if (field(choices[0], 'index') !== 0) throw new Error('invalid_stream');
          const reason = field(choices[0], 'finish_reason');
          if (reason !== undefined && reason !== null) {
            if (!TERMINAL.has(reason)) throw new Error('invalid_stream');
            this.mark(reason);
          }
          // Usage attached to non-final delta chunks is not a completion snapshot.
        } else if (field(chunk, 'usage') !== undefined && field(chunk, 'usage') !== null) {
          if (this.terminal === null) throw new Error('invalid_stream');
          this.snapshot(chunk);
        }
      }
    } catch { this.invalid = true; this.usage = null; }
  }
  result() {
    if (this.invalid || (this.error && this.terminal !== null && this.terminal !== 'failed')) return { status: 'unknown', usage: UNKNOWN() };
    if (this.error) return { status: 'error', usage: this.badUsage ? UNKNOWN() : this.usage ?? UNKNOWN() };
    const status = this.api === 'responses'
      ? this.terminal === 'completed' ? 'success' : this.terminal === 'failed' ? 'error' : 'unknown'
      : SUCCESS.has(this.terminal) ? 'success' : 'unknown';
    return { status, usage: this.terminal === null || this.badUsage ? UNKNOWN() : this.usage ?? UNKNOWN() };
  }
}

export async function* openaiStream(exporter, metadata, operation, { api = 'responses', signal } = {}) {
  const call = callHandle(exporter, metadata);
  const state = new StreamState(api);
  let stream, iterator, complete = false, settled = false, yielding = false;
  try {
    stream = await operation();
    iterator = stream[Symbol.asyncIterator]?.() ?? stream[Symbol.iterator]();
    while (true) {
      const next = await iterator.next();
      if (next.done) break;
      state.observe(next.value);
      yielding = true;
      yield next.value;
      yielding = false;
    }
    complete = true;
    const result = cancelled(signal) ? { status: 'unknown', usage: UNKNOWN() } : state.result();
    settled = true;
    finish(call, result.status, result.usage);
  } catch (error) {
    settled = true;
    finish(call, yielding || cancelled(signal) ? 'unknown' : 'error');
    throw error;
  } finally {
    if (!settled) finish(call, 'unknown');
    // Early return/throw does not automatically close a manually-driven iterator.
    if (!complete) {
      try { await iterator?.return?.(); } catch { /* Preserve the original outcome. */ }
      try { stream?.controller?.abort?.(); } catch { /* OpenAI Stream exposes its request controller. */ }
    }
  }
}
