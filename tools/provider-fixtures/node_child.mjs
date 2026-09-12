// Actual SDK parsing with an explicit loopback fixture, never a provider account.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
if (process.argv.slice(2).join(' ') !== '--run-fixture') {
  console.log('Usage: node node_child.mjs --run-fixture < synthetic-config.json');
  process.exit(0);
}
let phase = 'configuration', exporter;
try {
  const config = JSON.parse(fs.readFileSync(0, 'utf8'));
  for (const field of ['origin', 'provider_origin']) {
    const address = new URL(config[field]);
    if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' || !address.port
        || config[field] !== 'http://127.0.0.1:' + address.port) throw Error();
  }
  const {default: OpenAI} = await import('openai');
  const {BackgroundExporter} = await import(pathToFileURL(config.module_dir + '/guardian_exporter.mjs'));
  const {openaiCall, openaiStream} = await import(pathToFileURL(config.module_dir + '/guardian_openai.mjs'));
  const provider = new URL(config.provider_origin);
  if (provider.protocol !== 'http:' || provider.hostname !== '127.0.0.1' || !provider.port) throw Error();
  const guardedFetch = (input, init) => {
    const target = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    if (target.origin !== provider.origin) throw Error();
    return fetch(input, {...init, redirect: 'error'});
  };
  const client = new OpenAI({apiKey:'synthetic-provider-key', organization:'synthetic', project:'synthetic',
    webhookSecret:'synthetic', baseURL:config.provider_origin + '/v1', maxRetries:0, timeout:3000, fetch:guardedFetch});
  exporter = new BackgroundExporter({origin:config.origin, token:config.token, allowLocal:true, testMode:config.test_mode});
  const trace = 'sdk-node-' + randomUUID(), api = config.api;
  const modes = config.test_mode ? ['known'] : ['known', 'stream', 'missing', 'early', 'failure', 'inconsistent'];
  let chunks = 0;
  for (const mode of modes) {
    phase = mode;
    const metadata = {agent_name:'sdk-' + mode, model:'synthetic/model', trace_id:trace};
    const seen = {};
    const operation = async () => {
      try {
        const result = api === 'responses'
          ? await client.responses.create({model:'fixture-' + mode, input:config.canary, stream:['stream','early'].includes(mode)})
          : await client.chat.completions.create({model:'fixture-' + mode, messages:[{role:'user',content:config.canary}],
            ...(['stream','early'].includes(mode) ? {stream:true,stream_options:{include_usage:true}} : {})});
        seen.result = result;
        return result;
      } catch(error) { seen.error = error; throw error; }
    };
    if (['stream', 'early'].includes(mode)) {
      for await (const item of openaiStream(exporter, metadata, operation, {api})) {
        chunks += 1;
        if (mode === 'early') break;
        const usage = api === 'responses' ? item.response?.usage : item.usage;
        if (usage) {
          if (api === 'responses') usage.input_tokens = 9999;
          else usage.prompt_tokens = 9999;
        }
      }
    } else {
      try {
        const result = await openaiCall(exporter, metadata, operation, {api});
        if (result !== seen.result) throw Error();
      } catch(error) {
        if (mode !== 'failure' || api !== 'chat_completions' || error !== seen.error) throw Error();
      }
    }
  }
  phase = 'flush';
  if (!(await exporter.flush(10000)).drained) throw Error();
  phase = 'close';
  if (!(await exporter.close(10000)).drained) throw Error();
  const sdk = JSON.parse(fs.readFileSync(new URL('./node_modules/openai/package.json', import.meta.url), 'utf8'));
  console.log(JSON.stringify({status:'passed',trace_id:trace,sdk_version:sdk.version,runtime_version:process.versions.node,
    stats:exporter.snapshot(),sdk_chunks:chunks}));
} catch {
  try { await exporter?.close(1000); } catch {}
  console.log(JSON.stringify({status:'failed',phase})); process.exitCode = 1;
}
