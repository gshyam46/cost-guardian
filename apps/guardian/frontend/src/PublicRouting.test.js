import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import guardianApi from '@/services/guardianApi';

jest.mock('@/pages/PublicAccess', () => ({
  __esModule: true,
  default: ({ intent }) => <main data-public-intent={intent}>Public registration boundary</main>,
  PrivacyNotice: () => <main data-public-privacy>Registration privacy</main>,
}));
jest.mock('@/services/guardianApi', () => ({
  ...jest.requireActual('@/services/guardianApi'),
  __esModule: true,
  default: { getAuthConfig: jest.fn(), getAccess: jest.fn(), getLive: jest.fn() },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));

const originalMode = process.env.REACT_APP_PUBLIC_SITE;
let container, root;
beforeEach(() => {
  process.env.REACT_APP_PUBLIC_SITE = 'true';
  jest.clearAllMocks();
  localStorage.clear(); sessionStorage.clear();
  localStorage.setItem('guardian_api_key', 'existing-workspace-key');
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  if (originalMode === undefined) delete process.env.REACT_APP_PUBLIC_SITE;
  else process.env.REACT_APP_PUBLIC_SITE = originalMode;
  localStorage.clear(); sessionStorage.clear(); window.history.replaceState({}, '', '/');
});
const renderAt = async path => {
  window.history.replaceState({}, '', path);
  await act(async () => root.render(<App />));
};
const privateStateUntouched = () => {
  Object.values(guardianApi).forEach(method => expect(method).not.toHaveBeenCalled());
  expect(localStorage.getItem('guardian_api_key')).toBe('existing-workspace-key');
  expect(sessionStorage.length).toBe(0);
};

test.each(['/', '/welcome', '/demo'])('public site %s remains accessible without workspace configuration', async path => {
  await renderAt(path);
  expect(container.textContent).toContain('Sample workspace');
  expect(container.querySelector('a[href="/signup"]')).not.toBeNull();
  privateStateUntouched();
});

test.each([['/signup', 'signup'], ['/signin', 'signin'], ['/setup', 'onboarding']])(
  '%s enters independent public flow without consulting stored workspace credentials', async (path, intent) => {
    await renderAt(path);
    expect(container.querySelector('[data-public-intent]').getAttribute('data-public-intent')).toBe(intent);
    privateStateUntouched();
  });

test('public privacy notice is available before consent and authentication', async () => {
  await renderAt('/privacy');
  expect(container.querySelector('[data-public-privacy]')).not.toBeNull();
  privateStateUntouched();
});

test('unknown public routes do not accidentally mount a private dashboard', async () => {
  await renderAt('/runs/private-trace');
  expect(container.textContent).toContain('This page is not available');
  expect(container.querySelector('a[href="/welcome"]')).not.toBeNull();
  privateStateUntouched();
});

test.each([undefined, 'false', 'TRUE'])('public mode is opt-in; %p preserves the existing workspace gate', async setting => {
  if (setting === undefined) delete process.env.REACT_APP_PUBLIC_SITE;
  else process.env.REACT_APP_PUBLIC_SITE = setting;
  localStorage.clear();
  guardianApi.getAuthConfig.mockResolvedValue({ data: { auth_mode: 'api_key', login_path: null } });
  await renderAt('/');
  expect(guardianApi.getAuthConfig).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[data-public-intent]')).toBeNull();
  expect(container.textContent).toContain('Workspace access key');
});
