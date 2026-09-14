import { act } from 'react';
import { createRoot } from 'react-dom/client';
import PythonLauncherSetup, { launcherCommands, PYTHON_WHEEL } from './PythonLauncherSetup';
import { getGuardianApiOrigin } from '@/services/guardianApi';

jest.mock('@/services/guardianApi', () => ({ getGuardianApiOrigin: jest.fn() }));
let container, root;
beforeEach(() => {
  getGuardianApiOrigin.mockReturnValue('http://localhost:8001');
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); jest.restoreAllMocks(); });
const render = async () => act(async () => root.render(<PythonLauncherSetup />));
const change = async (index, value) => act(async () => {
  const select = container.querySelectorAll('select')[index];
  select.value = value; select.dispatchEvent(new Event('change', { bubbles: true }));
});
const clipboard = fn => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: fn } });
const copy = async name => act(async () => container.querySelector(`[aria-label="Copy ${name} commands"]`).click());

test('default flow installs the fixed wheel and launches the original app using the configured collector', async () => {
  await render();
  expect(container.querySelector('a[download]').getAttribute('download')).toBe(PYTHON_WHEEL);
  expect(container.querySelector('a[download]').getAttribute('href')).toBe('http://localhost:8001/api/guardian/integrations/python.whl');
  expect(container.querySelector('[aria-label="Install Sillage"]').textContent).toBe(`python -m pip install './${PYTHON_WHEEL}[openinference]'`);
  expect(container.querySelector('[aria-label="Sillage server configuration"]').textContent).toContain("$env:SILLAGE_URL = 'http://localhost:8001'");
  expect(container.querySelector('[aria-label="Start your app with Sillage"]').textContent).toBe('sillage-run --instrumentation openinference --instrumentors auto -- python -m uvicorn server:app');
  expect(container.textContent).toContain('It does not contact the collector');
  expect(container.textContent).toContain('LiteLLM streaming');
  expect(container.querySelector('label[for="launcher-shell"]').textContent).toBe('Terminal');
  expect(container.querySelector('label[for="launcher-target"]').textContent).toBe('How you start your app');
});

test('Bash and script choices copy usable commands without including credentials', async () => {
  const write = jest.fn().mockResolvedValue(); clipboard(write);
  await render(); await change(0, 'bash'); await change(1, 'script');
  await copy('configure');
  expect(write).toHaveBeenLastCalledWith("export SILLAGE_URL='http://localhost:8001'\nexport SILLAGE_INGEST_KEY='<your application key>'\nexport SILLAGE_SERVICE_NAME='my-ai-app'\nexport SILLAGE_ALLOW_LOCAL='true'");
  await copy('run');
  expect(write).toHaveBeenLastCalledWith('sillage-run --instrumentation openinference --instrumentors auto -- python app.py');
  expect(container.querySelector('[role="status"]').textContent).toBe('Launch command copied.');
  await copy('check');
  expect(write).toHaveBeenLastCalledWith('sillage-run --instrumentation openinference --instrumentors auto --check');
});

test('one selected instrumentor owns capture and native compatibility remains available', async () => {
  const write = jest.fn().mockResolvedValue(); clipboard(write);
  await render(); await change(3, 'litellm'); await copy('run');
  expect(write).toHaveBeenLastCalledWith('sillage-run --instrumentation openinference --instrumentors litellm -- python -m uvicorn server:app');
  await change(2, 'native');
  expect(container.querySelector('#launcher-layer')).toBeNull();
  expect(container.querySelector('[aria-label="Install Sillage"]').textContent).toBe(`python -m pip install ./${PYTHON_WHEEL}`);
  await copy('check'); expect(write).toHaveBeenLastCalledWith('sillage-run --check');
  await copy('run'); expect(write).toHaveBeenLastCalledWith('sillage-run -- python -m uvicorn server:app');
  await change(2, 'openinference');
  expect(container.querySelector('#launcher-layer').value).toBe('litellm');
});

test('existing OTel instructions preserve the provider and explain missing agent/context coverage', async () => {
  await render();
  expect(container.querySelector('[aria-label="Existing OpenTelemetry integration"]').textContent).toContain('provider.add_span_processor(');
  expect(container.textContent).toContain('Agent names require supplied context');
  expect(container.textContent).toContain('not stored as LLM calls');
  expect(container.textContent).toContain('not an OTLP receiver');
  expect(container.querySelector('[aria-label="Existing OpenTelemetry integration"]').textContent).not.toContain('set_tracer_provider');
});

test('a pending copied command cannot report success after changing capture method', async () => {
  let finish; clipboard(jest.fn(() => new Promise(resolve => { finish = resolve; })));
  await render(); await copy('run'); await change(2, 'native');
  await act(async () => finish());
  expect(container.querySelector('[role="status"]')).toBeNull();
});

test('production configuration keeps HTTPS and does not opt into local HTTP', () => {
  const commands = launcherCommands('https://sillage.example', 'bash');
  expect(commands.configure).toContain("export SILLAGE_URL='https://sillage.example'");
  expect(commands.configure).not.toContain('ALLOW_LOCAL');
});

test('shell templates preserve literal values rather than executing substitutions', () => {
  const literal = "https://example.test/quote'$(literal)`value";
  expect(launcherCommands(literal).configure.split('\n')[0]).toBe("$env:SILLAGE_URL = 'https://example.test/quote''$(literal)`value'");
  expect(launcherCommands(literal, 'bash').configure.split('\n')[0]).toBe("export SILLAGE_URL='https://example.test/quote'\\''$(literal)`value'");
});

test('an unavailable collector never falls back to the page origin for downloading', async () => {
  getGuardianApiOrigin.mockReturnValue(null); await render();
  expect(container.querySelector('a[download]')).toBeNull();
  expect(container.textContent).toContain('The capture address is unavailable');
  expect(container.querySelector('[aria-label="Sillage server configuration"]').textContent).toContain('<your Sillage address>');
});

test('clipboard failure is readable without echoing an error or configuration', async () => {
  clipboard(jest.fn().mockRejectedValue(new Error('secret clipboard detail')));
  await render(); await copy('configure');
  expect(container.querySelector('[role="status"]').textContent).toBe('Clipboard access failed. Select and copy the displayed commands.');
  expect(container.textContent).not.toContain('secret clipboard detail');
});

test('a pending clipboard completion cannot report success for a new selection', async () => {
  let finish; clipboard(jest.fn(() => new Promise(resolve => { finish = resolve; })));
  await render(); await copy('run'); await change(1, 'script');
  await act(async () => finish());
  expect(container.querySelector('[role="status"]')).toBeNull();
});
