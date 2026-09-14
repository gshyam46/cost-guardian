import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import GuardianWelcome, { SAMPLE_RUNS } from '@/pages/GuardianWelcome';
import guardianApi from '@/services/guardianApi';

jest.mock('@/services/guardianApi', () => ({
  ...jest.requireActual('@/services/guardianApi'),
  __esModule: true,
  default: { getAuthConfig: jest.fn(), getAccess: jest.fn(), getLive: jest.fn(), getSummary: jest.fn(), getMonitoring: jest.fn(), getMetrics: jest.fn() },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));

let root;
let container;
const button = text => [...container.querySelectorAll('button')].find(node => node.textContent.trim() === text);
beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, '', '/demo');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); window.history.replaceState({}, '', '/'); });

test.each(['/welcome', '/demo'])('public %s works without auth or private API requests and preserves browser credentials', async path => {
  window.history.replaceState({}, '', path);
  localStorage.setItem('guardian_api_key', 'existing-browser-key');
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain('Sample workspace');
  expect(container.textContent).toContain('DEMO DATA');
  expect(container.textContent).toContain('No customer data');
  Object.values(guardianApi).forEach(method => expect(method).not.toHaveBeenCalled());
  expect(localStorage.getItem('guardian_api_key')).toBe('existing-browser-key');
  expect(sessionStorage.length).toBe(0);
  expect(container.querySelector('a[href="/setup"]')).not.toBeNull();
  expect(container.querySelector('a[href="/signin"]')).not.toBeNull();
  expect(container.querySelector('a[href="#main-content"]').textContent).toBe('Skip to content');
  expect(container.querySelectorAll('h1')).toHaveLength(1);
});

test.each([false, true])('public-site landing/demo %s routes every tracking CTA to registration', async demo => {
  await act(async () => root.render(<GuardianWelcome publicSite demo={demo} />));
  expect(container.querySelector('h1').textContent).toBe(demo
    ? 'Follow a call.Find the cause.' : 'See the callsbehind the answer.');
  const signups = [...container.querySelectorAll('a[href="/signup"]')];
  expect(signups.length).toBeGreaterThanOrEqual(3);
  signups.forEach(link => expect(link.textContent.trim()).toBe('Sign up'));
  expect(container.querySelector('a[href="/setup"]')).toBeNull();
  expect(container.querySelector('a[href="/signin"]')).not.toBeNull();
  expect(container.querySelector('a[href="/privacy"]')).not.toBeNull();
  expect(container.textContent).not.toMatch(/early access|request access|join early/i);
  expect(container.textContent).toContain('Unknown values stay unknown');
  expect(container.textContent).toContain('does not collect raw prompts');
  Object.values(guardianApi).forEach(method => expect(method).not.toHaveBeenCalled());
});

test('self-hosted landing keeps its workspace CTA and explains the supported integration choices', async () => {
  await act(async () => root.render(<GuardianWelcome />));
  const tracking = [...container.querySelectorAll('a[href="/setup"]')];
  expect(tracking).toHaveLength(4);
  tracking.forEach(link => expect(link.textContent.trim()).toBe('Start tracking'));
  expect(container.querySelector('a[href="/signup"]')).toBeNull();
  expect(container.textContent).toContain('sillage-run');
  expect(container.textContent).toContain('existing OpenTelemetry');
  expect(container.textContent).toContain('Langfuse source');
  expect(container.textContent).toContain('manual Node integration');
  expect(container.textContent).toContain('Check receipt and processing');
});

test('selecting a sample call changes actual evidence and selected-button state', async () => {
  await act(async () => root.render(<GuardianWelcome />));
  const rows = [...container.querySelectorAll('[aria-label="Sample call timeline"] button')];
  const first = rows.find(row => row.textContent.includes(SAMPLE_RUNS[0].calls[0].name));
  const slow = rows.find(row => row.textContent.includes('Draft answer'));
  first.focus();
  expect(document.activeElement).toBe(first);
  await act(async () => first.click());
  expect(first.getAttribute('aria-pressed')).toBe('true');
  expect(slow.getAttribute('aria-pressed')).toBe('false');
  const detail = container.querySelector('[aria-label="Sample trace detail"]');
  expect(detail.textContent).toContain('Classify question');
  expect(detail.textContent).toContain('280 ms');
  expect(detail.textContent).toContain('240 / 32');
  expect(detail.textContent).toContain('Completed');
  expect(button('Inspect incident')).toBeUndefined();
  await act(async () => slow.click());
  expect(detail.textContent).toContain('3.42 s exceeds the sample rule of 2.00 s');
  expect(button('Inspect incident')).toBeDefined();
  Object.values(guardianApi).forEach(method => expect(method).not.toHaveBeenCalled());
});

test('sample investigation preserves unknown values and records only a temporary demo resolution', async () => {
  await act(async () => root.render(<App />));
  await act(async () => button('Agent handoff').click());
  expect(button('Agent handoff').getAttribute('aria-pressed')).toBe('true');
  expect(container.textContent).toContain('A failed handoff, explained.');
  expect(container.textContent).toContain('03 / 03');
  const detail = container.querySelector('[aria-label="Sample trace detail"]');
  expect(detail.textContent).toContain('Run specialist');
  expect(detail.textContent).toContain('1.24 s');
  expect(detail.textContent).toContain('Unknown');
  expect(container.textContent).toContain('Partial cost coverage');
  await act(async () => button('Inspect incident').click());
  await act(async () => button('Mark demo incident resolved').click());
  expect(container.textContent).toContain('Sample incident resolved');
  expect(button('Resolved in this demo').disabled).toBe(true);
  await act(async () => button('Back to trace').click());
  expect(container.querySelector('[aria-label="Sample trace detail"]').textContent).toContain('Run specialist');
  await act(async () => button('Support answer').click());
  await act(async () => button('Agent handoff').click());
  await act(async () => button('Inspect incident').click());
  expect(button('Mark demo incident resolved').disabled).toBe(false);
  Object.values(guardianApi).forEach(method => expect(method).not.toHaveBeenCalled());
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

test('filtering to runs needing attention changes a completed selection and keeps the detail consistent', async () => {
  await act(async () => root.render(<App />));
  await act(async () => button('Document search').click());
  expect(container.querySelector('[aria-label="Sample trace detail"]').textContent).toContain('Rewrite question');
  expect(container.textContent).toContain('A search, step by step.');
  expect(container.textContent).toContain('02 / 03');
  expect(button('Inspect incident')).toBeUndefined();
  await act(async () => button('Needs attention').click());
  expect(button('Document search')).toBeUndefined();
  expect(button('Support answer').getAttribute('aria-pressed')).toBe('true');
  expect(container.querySelector('[aria-label="Sample trace detail"]').textContent).toContain('Draft answer');
  await act(async () => button('All calls').click());
  expect(button('Document search')).toBeDefined();
});

test('a sign-in route uses the existing verified access gate', async () => {
  window.history.replaceState({}, '', '/signin');
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'oidc', login_path: '/api/guardian/auth/login' } });
  guardianApi.getAccess.mockRejectedValue({ response: { status: 401 } });
  await act(async () => root.render(<App />));
  expect(guardianApi.getAccess).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain('Sign in with your organization');
  expect(container.textContent).toContain('public account registration is not available yet');
  expect(guardianApi.getLive).not.toHaveBeenCalled();
  expect(guardianApi.getSummary).not.toHaveBeenCalled();
});
