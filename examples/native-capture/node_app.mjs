// Local synthetic providers only. Import and invocation without arguments are offline.
import { pathToFileURL } from 'node:url';
import { types } from 'node:util';
import { BackgroundExporter } from './guardian_exporter.mjs';

function finish(call, status, measurements = {}) {
  try {
    if (!measurements || typeof measurements !== 'object' || types.isProxy(measurements)
        || ![null, Object.prototype].includes(Object.getPrototypeOf(measurements))) throw new Error();
    const keys = Reflect.ownKeys(measurements);
    if (keys.some((key) => !['cost_usd', 'input_tokens', 'output_tokens', 'total_tokens'].includes(key))) throw new Error();
    const values = { status };
    for (const key of keys) {
      const descriptor = Object.getOwnPropertyDescriptor(measurements, key);
      if (!Object.hasOwn(descriptor, 'value')) throw new Error();
      values[key] = descriptor.value;
    }
    call.finish(values);
  } catch {
    // Reject instrumentation locally without turning a provider success into an error.
    call.finish({ status, invalid_measurements: true });
  }
}

// Pass explicit technical identity and measurements; provider objects are never inspected.
export async function runCall(exporter, metadata, provider, measurements = {}, { signal } = {}) {
  const call = exporter.startCall(metadata);
  try {
    const result = await provider();
    finish(call, signal?.aborted ? 'unknown' : 'success', measurements);
    return result;
  } catch (error) {
    call.finish({ status: signal?.aborted ? 'unknown' : 'error' });
    throw error;
  } finally {
    call.finish({ status: 'unknown' });
  }
}

export async function* streamCall(exporter, metadata, provider, measurements = {}, { signal } = {}) {
  const call = exporter.startCall(metadata);
  try {
    for await (const chunk of provider()) yield chunk;
    finish(call, signal?.aborted ? 'unknown' : 'success', measurements);
  } catch (error) {
    call.finish({ status: signal?.aborted ? 'unknown' : 'error' });
    throw error;
  } finally {
    // Early consumer return/cancellation reaches this block without exhaustion.
    call.finish({ status: 'unknown' });
  }
}

export async function syntheticLifecycle(exporter) {
  const identity = { agent_name: 'synthetic-recipe', model: 'synthetic/local' };
  const value = Object.freeze({ local: true });
  if (await runCall(exporter, identity, async () => value) !== value) throw new Error('recipe_failed');
  async function* provider() { yield value; yield value; }
  for await (const chunk of streamCall(exporter, identity, provider)) {
    if (chunk !== value) throw new Error('recipe_failed');
  }
  for await (const _chunk of streamCall(exporter, identity, provider)) break;
  const failure = new Error('synthetic_provider_failure');
  try {
    await runCall(exporter, identity, async () => { throw failure; });
    throw new Error('recipe_failed');
  } catch (error) { if (error !== failure) throw error; }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!process.argv.includes('--send-test')) {
    console.log('Local synthetic lifecycle recipe. Set GUARDIAN_URL and GUARDIAN_INGEST_KEY, then use --send-test [--allow-local-http].');
  } else {
    let exporter;
    try {
      exporter = new BackgroundExporter({ origin: process.env.GUARDIAN_URL, token: process.env.GUARDIAN_INGEST_KEY,
        allowLocal: process.argv.includes('--allow-local-http'), testMode: true });
      await syntheticLifecycle(exporter);
      const result = await exporter.close(5000);
      console.log(JSON.stringify(result));
      process.exitCode = result.confirmed ? 0 : 1;
    } catch {
      await exporter?.close(0);
      console.log(JSON.stringify({ ok: false, code: 'recipe_failed' }));
      process.exitCode = 1;
    }
  }
}
