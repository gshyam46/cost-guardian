// Run in a background telemetry job. This module never invokes a model/provider.
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export function target(origin, allowLocal = false) {
  const url = new URL(origin);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash
      || /[\\?#\s]/.test(origin) || (url.protocol !== 'https:' && !(allowLocal && local && url.protocol === 'http:'))) {
    throw new Error('invalid_target');
  }
  return `${url.origin}/api/guardian/ingest/events`;
}

function validReceipt(receipt, batchId, testMode, eventCount) {
  const fields = ['batch_id', 'test_mode', 'processing', 'received', 'duplicate', 'conflict_candidates', 'replayed'];
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)
      || Object.keys(receipt).length !== fields.length || !fields.every((key) => Object.hasOwn(receipt, key))
      || receipt.batch_id !== batchId || receipt.test_mode !== testMode
      || receipt.processing !== (testMode ? 'test_only' : 'queued') || typeof receipt.replayed !== 'boolean'
      || !['received', 'duplicate', 'conflict_candidates'].every((key) => Number.isSafeInteger(receipt[key]) && receipt[key] >= 0)
      || receipt.received + receipt.duplicate !== eventCount || receipt.conflict_candidates > receipt.received) return false;
  return !testMode || (receipt.received === eventCount && receipt.duplicate === 0 && receipt.conflict_candidates === 0);
}

export async function sendBatch(batch, { origin = process.env.GUARDIAN_URL, token = process.env.GUARDIAN_INGEST_KEY,
  allowLocal = false, maxAttempts = 3, externalAbortSignal, includeHttpStatus = false } = {}) {
  try {
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 3
        || typeof includeHttpStatus !== 'boolean'
        || (externalAbortSignal !== undefined && !(externalAbortSignal instanceof AbortSignal))) {
      throw new Error('invalid_configuration');
    }
    if (externalAbortSignal?.aborted) return { ok: false, code: 'cancelled' };
    const url = target(origin, allowLocal);
    if (typeof token !== 'string' || !/^cg_ingest_[!-~]+$/.test(token) || typeof batch?.batch_id !== 'string'
        || typeof batch.test_mode !== 'boolean' || !Array.isArray(batch.events) || batch.events.length < 1 || batch.events.length > 100) {
      throw new Error('invalid_configuration');
    }
    const batchId = batch.batch_id, testMode = batch.test_mode, eventCount = batch.events.length;
    const body = JSON.stringify(batch, (_, value) => {
      if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('invalid_number');
      return value;
    });
    if (Buffer.byteLength(body) > 262144) throw new Error('batch_too_large');
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (externalAbortSignal?.aborted) return { ok: false, code: 'cancelled' };
      let retry = false;
      const controller = new AbortController();
      const abort = () => controller.abort();
      externalAbortSignal?.addEventListener('abort', abort, { once: true });
      const timer = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(url, {
          method: 'POST', redirect: 'error', credentials: 'omit', signal: controller.signal,
          headers: { 'Content-Type': 'application/json', 'X-Guardian-Ingest-Key': token }, body,
        });
        if (controller.signal.aborted) return { ok: false, code: 'cancelled' };
        if (response.status !== 202) {
          try { await response.body?.cancel(); } catch { /* The HTTP rejection itself is still known. */ }
          const hint = response.headers.get('Retry-After') || '';
          const dateDelay = Date.parse(hint);
          const delay = /^[0-9]{1,6}$/.test(hint) ? Math.min(3600, Math.max(1, Number(hint)))
            : (Number.isFinite(dateDelay) ? Math.min(3600, Math.max(1, Math.ceil((dateDelay - Date.now()) / 1000))) : null);
          if (response.status === 429 || ([500, 502, 503, 504].includes(response.status) && delay !== null)) {
            return { ok: false, code: response.status === 429 ? 'rate_limited' : 'temporarily_unavailable', retry_after_seconds: delay || 60 };
          }
          retry = [429, 500, 502, 503, 504].includes(response.status);
          if (!retry) return { ok: false, code: 'rejected', ...(includeHttpStatus ? { http_status: response.status } : {}) };
        } else {
          const reader = response.body.getReader();
          const chunks = [];
          let length = 0;
          for (;;) {
            if (controller.signal.aborted) return { ok: false, code: 'cancelled' };
            const { done, value } = await reader.read();
            if (done) break;
            length += value.byteLength;
            if (length > 16384) { await reader.cancel(); return { ok: false, code: 'receipt_unconfirmed' }; }
            chunks.push(Buffer.from(value));
          }
          const receipt = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          if (!validReceipt(receipt, batchId, testMode, eventCount)) {
            return { ok: false, code: 'receipt_unconfirmed' };
          }
          return { ok: true, code: testMode ? 'test_received' : 'received' };
        }
      } catch { retry = true; }
      finally {
        clearTimeout(timer);
        externalAbortSignal?.removeEventListener('abort', abort);
      }
      if (externalAbortSignal?.aborted) return { ok: false, code: 'cancelled' };
      if (retry && attempt < maxAttempts - 1) await new Promise((resolve) => {
        const complete = () => {
          clearTimeout(wait);
          externalAbortSignal?.removeEventListener('abort', complete);
          resolve();
        };
        const wait = setTimeout(complete, 100 * (attempt + 1));
        externalAbortSignal?.addEventListener('abort', complete, { once: true });
        if (externalAbortSignal?.aborted) complete();
      });
    }
    return { ok: false, code: 'receipt_unconfirmed' };
  } catch { return { ok: false, code: 'invalid_configuration_or_batch' }; }
}

export function testBatch() {
  const now = new Date().toISOString();
  return { schema_version: 1, batch_id: randomUUID(), test_mode: true, events: [{
    observation_id: randomUUID(), trace_id: randomUUID(), agent_name: 'capture-test', model: 'test-model',
    started_at: now, ended_at: now, status: 'unknown', cost_usd: null,
  }] };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!process.argv.slice(2).includes('--send-test')) {
    console.log('Set GUARDIAN_URL and GUARDIAN_INGEST_KEY, then run --send-test [--allow-local-http].');
  } else {
    const result = await sendBatch(testBatch(), { allowLocal: process.argv.includes('--allow-local-http') });
    console.log(JSON.stringify(result));
    process.exitCode = result.ok ? 0 : 1;
  }
}
