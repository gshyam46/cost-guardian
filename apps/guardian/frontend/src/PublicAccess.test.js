import { act } from 'react';
import { createRoot } from 'react-dom/client';
import PublicAccess, { PrivacyNotice } from './pages/PublicAccess';

let root;
let container;
let originalFetch;
const acknowledgment = { registered: true, status: 'interest_recorded', schema_version: 1 };
const ready = { available: true, workspace_url: 'https://workspace.example.test', reason: 'ready' };
const response = (body, status = 200) => ({ status, json: async () => body });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const button = label => [...container.querySelectorAll('button')].find(node => node.textContent.trim().startsWith(label));
const render = async intent => act(async () => root.render(<PublicAccess intent={intent} />));
const fill = async (name, value) => {
  const element = container.querySelector(`[name="${name}"]`);
  await act(async () => {
    if (element.type === 'checkbox') {
      if (element.checked !== value) element.click();
    } else {
      const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
};
const completeForm = async () => {
  await fill('name', '  Test Founder  ');
  await fill('email', 'founder@example.test');
  await fill('consent', true);
};
const submit = async () => act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
beforeEach(() => {
  originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue(response({ available: false, workspace_url: null, reason: 'coming_soon' }));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  global.fetch = originalFetch;
  jest.useRealTimers();
  jest.restoreAllMocks();
  delete process.env.REACT_APP_PRIVACY_CONTACT_EMAIL;
});

test('signup opens the independent interest form without fetching auth or availability', async () => {
  localStorage.setItem('guardian_api_key', 'existing-key');
  await render('signup');
  expect(global.fetch).not.toHaveBeenCalled();
  expect(container.textContent).toContain('Get early access to Sillage');
  expect(container.querySelector('[name="name"]').required).toBe(true);
  expect(container.querySelector('[name="email"]').type).toBe('email');
  expect(container.querySelector('[name="consent"]').checked).toBe(false);
  expect(container.querySelector('[type="password"]')).toBeNull();
  expect(localStorage.getItem('guardian_api_key')).toBe('existing-key');
  expect(sessionStorage.length).toBe(0);
  expect(container.textContent).toContain('does not create a workspace or sign you in');
  expect(container.querySelector('a[href="/privacy"]')).not.toBeNull();
});

test.each([['signin', '/signin'], ['onboarding', '/setup']])('healthy %s offers the validated workspace link without redirecting', async (intent, route) => {
  global.fetch.mockResolvedValue(response(ready));
  const prior = window.location.href;
  await render(intent);
  expect(container.textContent).toContain('Your workspace is ready');
  expect(container.querySelector(`a[href="https://workspace.example.test${route}"]`)).not.toBeNull();
  expect(window.location.href).toBe(prior);
  const [url, options] = global.fetch.mock.calls[0];
  expect(url).toBe('/api/availability');
  expect(options.credentials).toBe('omit');
  expect(options.mode).toBe('same-origin');
  expect(options.cache).toBe('no-store');
  expect(options.headers).toEqual({ Accept: 'application/json' });
});

test.each([
  { available: false, workspace_url: null, reason: 'unavailable' },
  { available: 'true', workspace_url: 'https://workspace.example.test', reason: 'ready' },
  { available: true, workspace_url: 'javascript:alert(1)', reason: 'ready' },
  { available: true, workspace_url: 'http://workspace.example.test', reason: 'ready' },
  { available: true, workspace_url: 'https://private:secret@workspace.example.test', reason: 'ready' },
  { available: true, workspace_url: 'https://workspace.example.test/other', reason: 'ready' },
  { available: true, workspace_url: 'https://workspace.example.test?token=private', reason: 'ready' },
  { available: true, workspace_url: 'https://workspace.example.test/#secret', reason: 'ready' },
  { available: false, workspace_url: 'https://workspace.example.test', reason: 'coming_soon' },
  { ...ready, unexpected: true },
])('unavailable or malformed availability %j leaves a useful independent form', async value => {
  global.fetch.mockResolvedValue(response(value));
  await render('signin');
  expect(container.textContent).toContain('Currently unavailable');
  expect(container.querySelector('form')).not.toBeNull();
  expect(button('Retry access')).toBeDefined();
  expect(container.querySelector('a[href^="https:"]')).toBeNull();
  expect(container.textContent).not.toContain('secret');
});

test('coming soon invites registration and retry recovery keeps entered details', async () => {
  await render('onboarding');
  expect(container.textContent).toContain('Early access is coming soon');
  await fill('name', 'Retained Founder');
  global.fetch.mockResolvedValue(response(ready));
  await act(async () => button('Retry access').click());
  expect(container.querySelector('[name="name"]').value).toBe('Retained Founder');
  expect(container.querySelector('a[href="https://workspace.example.test/setup"]')).not.toBeNull();
});

test('availability network and JSON errors never expose provider exception content', async () => {
  global.fetch.mockRejectedValue(new Error('private-operator-configuration'));
  await render('signin');
  expect(container.textContent).toContain('Currently unavailable');
  expect(container.textContent).not.toContain('private-operator');
  global.fetch.mockResolvedValue({ status: 200, json: async () => { throw new Error('private-json-body'); } });
  await act(async () => button('Retry access').click());
  expect(container.textContent).not.toContain('private-json');
  expect(container.querySelector('form')).not.toBeNull();
});

test('a hanging availability request times out and its late response cannot replace recovery', async () => {
  jest.useFakeTimers();
  const waiting = deferred();
  global.fetch.mockReturnValueOnce(waiting.promise);
  await render('signin');
  expect(container.textContent).toContain('Checking workspace access');
  const oldSignal = global.fetch.mock.calls[0][1].signal;
  await act(async () => jest.advanceTimersByTime(5000));
  expect(oldSignal.aborted).toBe(true);
  expect(container.textContent).toContain('Currently unavailable');
  global.fetch.mockResolvedValue(response(ready));
  await act(async () => button('Retry access').click());
  await act(async () => waiting.resolve(response({ available: false, workspace_url: null, reason: 'coming_soon' })));
  expect(container.textContent).toContain('Your workspace is ready');
});

test.each(['signup', 'signin', 'onboarding'])('registration from %s saves only after the explicit acknowledgment', async intent => {
  await render(intent);
  global.fetch.mockClear();
  global.fetch.mockResolvedValue(response(acknowledgment, 202));
  await completeForm();
  await fill('company', ' Example Team ');
  await fill('use_case', ' A support assistant. ');
  await submit();
  expect(global.fetch).toHaveBeenCalledTimes(1);
  const [url, options] = global.fetch.mock.calls[0];
  expect(url).toBe('/api/interest');
  expect(options.credentials).toBe('omit');
  expect(options.headers).toEqual({ 'Content-Type': 'application/json', Accept: 'application/json' });
  expect(JSON.parse(options.body)).toEqual({ schema_version: 1, name: 'Test Founder', email: 'founder@example.test',
    company: 'Example Team', use_case: 'A support assistant.', consent: true, source: intent });
  expect(container.textContent).toContain('Interest registered');
  expect(container.textContent).toContain('This does not create an account');
  expect(container.querySelector('form')).toBeNull();
  expect(container.textContent).not.toContain('founder@example.test');
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(window.location.href).not.toContain('founder');
});

test('required fields and affirmative consent are checked before sending any request', async () => {
  await render('signup');
  await submit();
  expect(container.textContent).toContain('Enter your name');
  expect(document.activeElement.name).toBe('name');
  await fill('name', 'Founder');
  await fill('email', 'invalid');
  await submit();
  expect(container.textContent).toContain('Enter a valid email');
  await fill('email', 'founder@example.test');
  await submit();
  expect(container.textContent).toContain('Please agree');
  expect(global.fetch).not.toHaveBeenCalled();
});

test.each(['founder..name@example.test', '.founder@example.test', 'founder.@example.test',
  `${'a'.repeat(65)}@example.test`, `founder@${'a'.repeat(64)}.test`, 'founder@example.123',
  'founder@example..test', 'founder@-example.test', 'founder@example-.test', 'founder@exämple.test'])
  ('email %j rejected by the server is rejected before submission with a useful correction', async email => {
    await render('signup');
    await completeForm();
    await fill('email', email);
    await submit();
    expect(global.fetch).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Enter a valid email address');
    expect(document.activeElement.name).toBe('email');
    expect(container.querySelector('[name="email"]').value).toBe(email);
  });

test.each(['Founder+team@EXAMPLE.TEST', `${'a'.repeat(64)}@${'b'.repeat(63)}.test`, 'founder@sub-team.example.test'])
  ('supported email %j remains accepted', async email => {
    await render('signup');
    await completeForm();
    await fill('email', email);
    global.fetch.mockResolvedValue(response(acknowledgment, 202));
    await submit();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(global.fetch.mock.calls[0][1].body).email).toBe(email);
    expect(container.textContent).toContain('Interest registered');
  });

test('multibyte input cannot exceed the bounded request even within individual character limits', async () => {
  await render('signup');
  await completeForm();
  await fill('name', '漢'.repeat(100));
  await fill('company', '漢'.repeat(120));
  await fill('use_case', '漢'.repeat(1200));
  await submit();
  expect(global.fetch).not.toHaveBeenCalled();
  expect(container.textContent).toContain('Please shorten your description');
});

test.each([
  [200, acknowledgment], [202, { registered: true }], [202, { ...acknowledgment, schema_version: 2 }],
  [202, { ...acknowledgment, registered: 'true' }], [202, { ...acknowledgment, status: 'account_created' }],
  [202, { ...acknowledgment, extra: 'unexpected' }], [503, { error: 'private-storage-error' }],
])('unconfirmed response HTTP %i %j preserves entered details without claiming a save', async (status, value) => {
  await render('signup');
  global.fetch.mockResolvedValue(response(value, status));
  await completeForm();
  await submit();
  expect(container.textContent).toContain('could not confirm');
  expect(container.textContent).not.toContain('Interest registered');
  expect(container.textContent).not.toContain('private-storage');
  expect(container.querySelector('[name="name"]').value).toBe('  Test Founder  ');
  expect(container.querySelector('[name="email"]').value).toBe('founder@example.test');
  expect(container.querySelector('[name="consent"]').checked).toBe(true);
  expect(button('Register interest').disabled).toBe(false);
});

test('duplicate clicks make one pending request and rate limits retain a retryable form', async () => {
  const waiting = deferred();
  await render('signup');
  global.fetch.mockReturnValue(waiting.promise);
  await completeForm();
  await act(async () => {
    const form = container.querySelector('form');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  expect(global.fetch).toHaveBeenCalledTimes(1);
  expect(container.querySelector('fieldset').disabled).toBe(true);
  await act(async () => waiting.resolve(response({ registered: false, error: 'rate_limited' }, 429)));
  expect(container.textContent).toContain('Please wait a moment');
  expect(container.querySelector('[name="email"]').value).toBe('founder@example.test');
  expect(container.querySelector('fieldset').disabled).toBe(false);
});

test.each([[400, 'Please check your name, email and other details'], [413, 'Please shorten your description or company name']])
  ('HTTP %i shows a correction instead of a transient-save message and retains input', async (status, message) => {
    await render('signup');
    await completeForm();
    await fill('use_case', 'Retain this project description.');
    global.fetch.mockResolvedValue(response({ error: 'private-server-diagnostic' }, status));
    await submit();
    expect(container.textContent).toContain(message);
    expect(container.textContent).not.toContain('could not confirm');
    expect(container.textContent).not.toContain('private-server-diagnostic');
    expect(container.textContent).not.toContain('Interest registered');
    expect(container.querySelector('[name="email"]').value).toBe('founder@example.test');
    expect(container.querySelector('[name="use_case"]').value).toBe('Retain this project description.');
    expect(container.querySelector('[name="consent"]').checked).toBe(true);
    expect(container.querySelector('fieldset').disabled).toBe(false);
  });

test('late submit success after timeout cannot claim registration and explicit retry can save', async () => {
  jest.useFakeTimers();
  const waiting = deferred();
  await render('signup');
  global.fetch.mockReturnValueOnce(waiting.promise);
  await completeForm();
  await submit();
  const signal = global.fetch.mock.calls[0][1].signal;
  await act(async () => jest.advanceTimersByTime(5000));
  expect(signal.aborted).toBe(true);
  expect(container.textContent).toContain('could not confirm');
  await act(async () => waiting.resolve(response(acknowledgment, 202)));
  expect(container.textContent).not.toContain('Interest registered');
  global.fetch.mockResolvedValue(response(acknowledgment, 202));
  await submit();
  expect(container.textContent).toContain('Interest registered');
});

test('intent change cancels pending registration and does not apply its late acknowledgment', async () => {
  const waiting = deferred();
  await render('signup');
  global.fetch.mockReturnValueOnce(waiting.promise);
  await completeForm();
  await submit();
  const signal = global.fetch.mock.calls[0][1].signal;
  await render('signin');
  expect(signal.aborted).toBe(true);
  await act(async () => waiting.resolve(response(acknowledgment, 202)));
  expect(container.textContent).not.toContain('Interest registered');
  expect(container.querySelector('[name="email"]').value).toBe('');
});

test('unmount aborts availability and independent registration without saving browser details', async () => {
  const availability = deferred();
  const interest = deferred();
  global.fetch.mockImplementation(url => url === '/api/availability' ? availability.promise : interest.promise);
  await render('signin');
  await completeForm();
  await submit();
  const signals = global.fetch.mock.calls.map(([, options]) => options.signal);
  await act(async () => root.unmount());
  root = createRoot(container);
  expect(signals.every(signal => signal.aborted)).toBe(true);
  await act(async () => { availability.resolve(response(ready)); interest.resolve(response(acknowledgment, 202)); });
  expect(container.textContent).toBe('');
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

test('privacy notice states the actual period and does not invent a contact address', async () => {
  await act(async () => root.render(<PrivacyNotice />));
  expect(global.fetch).not.toHaveBeenCalled();
  expect(container.textContent).toContain('180 days after its first registration');
  expect(container.textContent).toContain('Repeated submissions while it is active keep that original expiry');
  expect(container.textContent).toContain('your new consent starts a new 180-day period');
  expect(container.textContent).toContain('Deletion may not happen at the exact expiry time');
  expect(container.textContent).toContain('clears them after a confirmed registration');
  expect(container.textContent).toContain('Your browser may remember fields through its own autofill settings');
  expect(container.textContent).toContain('does not send an automated email');
  expect(container.textContent).toContain('Vercel');
  expect(container.textContent).toContain('MongoDB');
  expect(container.textContent).toContain('channel where you received this invitation');
  expect(container.querySelector('a[href^="mailto:"]')).toBeNull();
});

test.each([['privacy@example.test', true], ['private@example.test\n', false], ['javascript:alert(1)', false]])(
  'privacy contact %j is only linked if it is a valid address', async (contact, valid) => {
    process.env.REACT_APP_PRIVACY_CONTACT_EMAIL = contact;
    await act(async () => root.render(<PrivacyNotice />));
    expect(Boolean(container.querySelector('a[href^="mailto:"]'))).toBe(valid);
  },
);

test('valid email punctuation cannot become mail-link headers or query parameters', async () => {
  process.env.REACT_APP_PRIVACY_CONTACT_EMAIL = 'privacy?subject=unexpected@example.test';
  await act(async () => root.render(<PrivacyNotice />));
  const link = container.querySelector('a[href^="mailto:"]');
  expect(link.textContent).toBe('privacy?subject=unexpected@example.test');
  expect(new URL(link.href).search).toBe('');
  expect(link.getAttribute('href')).toBe('mailto:privacy%3Fsubject%3Dunexpected%40example.test');
});
