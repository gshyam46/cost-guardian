// Static application templates only. Never interpolate a dashboard or ingestion key.
export const providerModules = (language) => ['guardian_capture', 'guardian_exporter', 'guardian_openai']
  .map((name) => `${name}.${language === 'node' ? 'mjs' : 'py'}`);

export function providerRecipe(language = 'python', api = 'responses', streaming = false) {
  const chat = api === 'chat_completions';
  const endpoint = chat ? 'chat.completions' : 'responses';
  const selectedApi = chat ? 'chat_completions' : 'responses';
  if (language === 'node') {
    const helper = streaming ? 'openaiStream' : 'openaiCall';
    const request = `      ...requestArgs, model${chat ? ', n: 1' : ''}${streaming ? ', stream: true' : ', stream: false'}${chat && streaming ? ',\n      stream_options: { ...requestArgs.stream_options, include_usage: true }' : ''}`;
    return `import { BackgroundExporter } from './guardian_exporter.mjs';
import { ${helper} } from './guardian_openai.mjs';

// Once at application startup, with server-side environment values.
const exporter = new BackgroundExporter({
  origin: process.env.GUARDIAN_URL,
  token: process.env.GUARDIAN_INGEST_KEY,
  testMode: false,
});
const model = process.env.OPENAI_MODEL; // Your application's model setting.

// At your existing call site: reuse client and requestArgs.
// requestArgs stays in your app; Sillage does not capture its content.
// Reuse the same AbortSignal as your existing provider request, if any.
const requestOptions = {}; // Reuse your existing request options here, including signal if used.
const signal = requestOptions.signal;
${streaming ? 'for await (const chunk of ' : 'const result = await '}${helper}(
  exporter,
  { agent_name: 'answer-generator', model },
  () => client.${endpoint}.create({
${request}
    }, { ...requestOptions, signal }),
  { api: '${selectedApi}', signal },
)${streaming ? `) {
  await consumeChunk(chunk); // Your existing stream consumer receives the original chunk.
}` : '; // result is the original SDK result.'}

// Only during application shutdown, outside the response path:
// await exporter.close(5000);
// Inspect exporter.snapshot() through your application's diagnostics.`;
  }
  const helper = streaming ? 'openai_stream' : 'openai_call';
  return `${streaming ? 'from contextlib import closing\n' : ''}import os
from guardian_exporter import BackgroundExporter
from guardian_openai import ${helper}

# Once at application startup, with server-side environment values.
exporter = BackgroundExporter(
    origin=os.environ["GUARDIAN_URL"],
    token=os.environ["GUARDIAN_INGEST_KEY"],
    test_mode=False,
)
model = os.environ["OPENAI_MODEL"]  # Your application's model setting.

# At your existing call site: reuse client and request_args.
# request_args stays in your app; Sillage does not capture its content.
observed_args = {**request_args, "model": model, "stream": ${streaming ? 'True' : 'False'}${chat ? ', "n": 1' : ''}}
${chat && streaming ? `observed_args["stream_options"] = {
    **(request_args.get("stream_options") or {}), "include_usage": True
}
` : ''}${streaming ? 'with closing(' : 'result = '}${helper}(
    exporter,
    lambda: client.${endpoint}.create(**observed_args),
    api="${selectedApi}", agent_name="answer-generator", model=model,
)${streaming ? `) as stream:
    for chunk in stream:
        consume_chunk(chunk)  # Your existing consumer receives the original chunk.
# closing also handles an early break without claiming successful completion.` : '  # result is the original SDK result.'}

# Only during application shutdown, outside the response path:
# exporter.close(timeout=5)
# Inspect exporter.snapshot() through your application's diagnostics.`;
}
