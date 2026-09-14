import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
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
