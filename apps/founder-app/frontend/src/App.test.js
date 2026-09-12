import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import api, { reportsApi, profileApi } from '@/services/api';

jest.mock('@/services/api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
  reportsApi: { listReports: jest.fn(), getReport: jest.fn() },
  profileApi: { getProfile: jest.fn() },
  analysisApi: { runAnalysis: jest.fn() },
}));
jest.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

let container;
let root;

beforeEach(() => {
  jest.clearAllMocks();
  window.history.replaceState({}, '', '/');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockResolvedValue({ data: { user_id: 'user-42', name: 'Test Founder' } });
  reportsApi.listReports.mockResolvedValue({ data: [] });
  profileApi.getProfile.mockResolvedValue({ data: null });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

test('protected routes wait for the session before requesting customer data', async () => {
  api.get.mockReturnValue(new Promise(() => {}));
  window.history.replaceState({}, '', '/dashboard');
  await act(async () => root.render(<App />));

  expect(container.textContent).toContain('Loading...');
  expect(api.get).toHaveBeenCalledWith('/auth/me');
  expect(reportsApi.listReports).not.toHaveBeenCalled();
});

test('an unauthenticated dashboard deep link returns to the sign-in landing page', async () => {
  api.get.mockRejectedValue({ response: { status: 401 } });
  window.history.replaceState({}, '', '/dashboard');
  await act(async () => root.render(<App />));

  expect(window.location.pathname).toBe('/');
  expect(container.querySelector('[data-testid="nav-login-btn"]')).not.toBeNull();
  expect(reportsApi.listReports).not.toHaveBeenCalled();
});

test('an authenticated dashboard deep link loads the real dashboard', async () => {
  window.history.replaceState({}, '', '/dashboard');
  await act(async () => root.render(<App />));

  expect(window.location.pathname).toBe('/dashboard');
  expect(container.querySelector('[data-testid="dashboard-page"]')).not.toBeNull();
  expect(reportsApi.listReports).toHaveBeenCalledTimes(1);
  expect(profileApi.getProfile).toHaveBeenCalledTimes(1);
});

test('an authenticated report deep link requests the ID from the route', async () => {
  reportsApi.getReport.mockReturnValue(new Promise(() => {}));
  window.history.replaceState({}, '', '/results/report-42');
  await act(async () => root.render(<App />));

  expect(reportsApi.getReport).toHaveBeenCalledWith('report-42');
  expect(container.textContent).toContain('Loading report...');
  expect(window.location.pathname).toBe('/results/report-42');
});
