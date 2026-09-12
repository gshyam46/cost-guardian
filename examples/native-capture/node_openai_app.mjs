// Explicit synthetic smoke only; no provider client/key is imported or constructed.
import { pathToFileURL } from 'node:url';
import { BackgroundExporter } from './guardian_exporter.mjs';
import { openaiCall, openaiStream } from './guardian_openai.mjs';

export async function syntheticOpenAIUsage(exporter) {
  const identity = { agent_name: 'synthetic-openai', model: 'synthetic/openai' };
  const value = { id: 'resp_synthetic', object: 'response', status: 'completed',
    usage: { input_tokens: 8, output_tokens: 2, total_tokens: 10 }, output: 'Local synthetic output' };
  if (await openaiCall(exporter, identity, () => value) !== value) throw new Error('example_failed');
  async function* responseStream() {
    yield { type: 'response.output_text.delta', delta: 'Local synthetic chunk' };
    yield { type: 'response.completed', response: value };
  }
  for await (const _ of openaiStream(exporter, identity, responseStream)) { /* Application consumes its own chunks. */ }
  const chat = { id: 'chatcmpl-synthetic', object: 'chat.completion',
    choices: [{ index: 0, finish_reason: 'stop', message: { content: 'Local synthetic output' } }],
    usage: { prompt_tokens: 8, completion_tokens: 2, total_tokens: 10 } };
  await openaiCall(exporter, identity, () => chat, { api: 'chat_completions' });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const options = process.argv.slice(2);
  if (!options.includes('--send-test')) {
    console.log('Synthetic OpenAI usage recipe. Set GUARDIAN_URL and GUARDIAN_INGEST_KEY, then use --send-test [--allow-local-http]. No provider calls.');
  } else if (options.some((value) => !['--send-test', '--allow-local-http'].includes(value))) {
    console.log(JSON.stringify({ ok: false, code: 'invalid_arguments' })); process.exitCode = 1;
  } else {
    let exporter;
    try {
      exporter = new BackgroundExporter({ origin: process.env.GUARDIAN_URL, token: process.env.GUARDIAN_INGEST_KEY,
        allowLocal: options.includes('--allow-local-http'), testMode: true });
      await syntheticOpenAIUsage(exporter);
      const result = await exporter.close(5000);
      console.log(JSON.stringify(result)); process.exitCode = result.confirmed ? 0 : 1;
    } catch {
      console.log(JSON.stringify({ ok: false, code: 'example_failed' })); process.exitCode = 1;
    } finally { await exporter?.close(5000); }
  }
}
