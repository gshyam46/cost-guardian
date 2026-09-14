import { act } from 'react';
import { createRoot } from 'react-dom/client';
import EvidenceDemo from './components/EvidenceDemo';
import { SAMPLE_RUNS } from './components/sampleRuns';

let root;
let container;
let replayIntervals;
const button = name => [...container.querySelectorAll('button')].find(node => node.textContent.trim() === name || node.getAttribute('aria-label') === name);
const field = label => container.querySelector(`input[aria-label="${label}"]`);
const detail = () => container.querySelector('[aria-label="Sample trace detail"]');
const timeline = () => container.querySelector('[aria-label="Sample call timeline"]');
const click = async name => act(async () => button(name).click());
const changeRange = async (label, value) => act(async () => {
  const node = field(label);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(node, String(value));
  node.dispatchEvent(new Event('input', { bubbles: true }));
  node.dispatchEvent(new Event('change', { bubbles: true }));
});
const render = async props => act(async () => root.render(<EvidenceDemo {...props} />));

beforeEach(() => {
  jest.useFakeTimers();
  replayIntervals = new Set();
  // React act may queue unrelated timers. Track the replay's interval handles
  // and require its own cleanup paths to clear those exact handles.
  const scheduleInterval = window.setInterval.bind(window);
  const cancelInterval = window.clearInterval.bind(window);
  jest.spyOn(window, 'setInterval').mockImplementation((callback, delay, ...args) => {
    const handle = scheduleInterval(callback, delay, ...args);
    if (delay === 100) replayIntervals.add(handle);
    return handle;
  });
  jest.spyOn(window, 'clearInterval').mockImplementation(handle => {
    replayIntervals.delete(handle);
    return cancelInterval(handle);
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  container.remove();
  jest.restoreAllMocks();
  jest.useRealTimers();
});

test('opens with all sample evidence and never autoplays', async () => {
  await render();
  expect(detail().textContent).toContain('Draft answer');
  expect(field('Replay position').value).toBe('4110');
  expect(container.textContent).toContain('3 / 3 calls captured');
  expect(button('Replay sample')).toBeDefined();
  expect(replayIntervals.size).toBe(0);
  await act(async () => jest.advanceTimersByTime(10000));
  expect(detail().textContent).toContain('Draft answer');
  expect(field('Replay position').value).toBe('4110');
});

test('replay reveals completed samples, pause preserves position, and continuation stops at the end', async () => {
  await render();
  await click('Replay sample');
  expect(container.textContent).toContain('0 / 3 calls captured');
  expect(detail().textContent).toContain('Waiting for a captured call.');
  expect([...timeline().querySelectorAll('button')].every(node => node.disabled)).toBe(true);
  await act(async () => jest.advanceTimersByTime(300));
  expect(container.textContent).toContain('1 / 3 calls captured');
  expect(detail().textContent).toContain('Classify question');
  expect(timeline().querySelectorAll('button:disabled')).toHaveLength(2);
  await click('Pause replay');
  const paused = field('Replay position').value;
  expect(replayIntervals.size).toBe(0);
  await act(async () => jest.advanceTimersByTime(3000));
  expect(field('Replay position').value).toBe(paused);
  await click('Continue replay');
  await act(async () => jest.advanceTimersByTime(5000));
  expect(field('Replay position').value).toBe('4110');
  expect(container.textContent).toContain('3 / 3 calls captured');
  expect(detail().textContent).toContain('Check answer');
  expect(button('Replay sample')).toBeDefined();
  expect(replayIntervals.size).toBe(0);
});

test('scrubbing hides uncaptured measurements, selects the latest captured call, and clamps to native range bounds', async () => {
  await render();
  await changeRange('Replay position', 0);
  expect(detail().textContent).toContain('Waiting for a captured call.');
  expect(timeline().textContent).not.toContain('3.42 s');
  await changeRange('Replay position', 280);
  expect(detail().textContent).toContain('Classify question');
  expect(timeline().querySelectorAll('button:disabled')).toHaveLength(2);
  await changeRange('Replay position', 3700);
  expect(detail().textContent).toContain('Draft answer');
  expect(detail().textContent).toContain('3.42 s');
  await changeRange('Replay position', 99999);
  expect(field('Replay position').value).toBe('4110');
  expect(timeline().querySelectorAll('button:disabled')).toHaveLength(0);
  await changeRange('Replay position', -100);
  expect(field('Replay position').value).toBe('0');
  expect(timeline().querySelectorAll('button:disabled')).toHaveLength(3);
  expect(replayIntervals.size).toBe(0);
});

test('scrubbing during playback cancels its timer and restart returns to a paused empty recording', async () => {
  await render();
  await click('Replay sample');
  await act(async () => jest.advanceTimersByTime(500));
  await changeRange('Replay position', 3700);
  expect(replayIntervals.size).toBe(0);
  await act(async () => jest.advanceTimersByTime(2000));
  expect(field('Replay position').value).toBe('3700');
  await click('Restart replay');
  expect(field('Replay position').value).toBe('0');
  expect(detail().textContent).toContain('Waiting for a captured call.');
  expect(button('Replay sample')).toBeDefined();
  expect(replayIntervals.size).toBe(0);
});

test('selecting a captured call pauses replay so its detail remains inspectable', async () => {
  await render();
  await click('Replay sample');
  await act(async () => jest.advanceTimersByTime(3800));
  const first = timeline().querySelector('button');
  await act(async () => first.click());
  expect(detail().textContent).toContain('Classify question');
  expect(replayIntervals.size).toBe(0);
  await act(async () => jest.advanceTimersByTime(1000));
  expect(detail().textContent).toContain('Classify question');
});

test('a run switch clears playback and local changes and starts with the correct selected evidence', async () => {
  await render();
  await changeRange('Demo duration rule', 5000);
  await click('Inspect incident');
  await click('Mark demo incident resolved');
  await click('Replay sample');
  await act(async () => jest.advanceTimersByTime(300));
  await click('Document search');
  expect(field('Replay position').value).toBe('970');
  expect(detail().textContent).toContain('Rewrite question');
  expect(field('Demo duration rule').value).toBe('2000');
  expect(replayIntervals.size).toBe(0);
  await act(async () => jest.advanceTimersByTime(1000));
  expect(field('Replay position').value).toBe('970');
  await click('Support answer');
  await click('Inspect incident');
  expect(button('Mark demo incident resolved').disabled).toBe(false);
});

test('changing a run filter pauses replay and keeps the selected evidence consistent', async () => {
  await render();
  await click('Replay sample');
  await act(async () => jest.advanceTimersByTime(300));
  await click('Needs attention');
  expect(replayIntervals.size).toBe(0);
  expect(button('Document search')).toBeUndefined();
  expect(detail().textContent).toContain('Classify question');
  await click('All calls');
  await click('Document search');
  await click('Needs attention');
  expect(detail().textContent).toContain('Draft answer');
  expect(field('Replay position').value).toBe('4110');
});

test('unmounting during replay clears the interval', async () => {
  await render();
  await click('Replay sample');
  expect(replayIntervals.size).toBe(1);
  await act(async () => root.unmount());
  root = null;
  expect(replayIntervals.size).toBe(0);
});

test('measurement lenses compare the actual units and never turn unknown usage or prices into zero', async () => {
  await render();
  const first = () => timeline().querySelector('button');
  const initialWidth = first().querySelector('.sg-evidence-meter-fill').style.width;
  await click('Tokens');
  expect(first().textContent).toContain('272 tokens');
  expect(first().querySelector('.sg-evidence-meter-fill').style.width).not.toBe(initialWidth);
  expect(button('Tokens').getAttribute('aria-pressed')).toBe('true');
  await click('Cost');
  expect(first().textContent).toContain('$0.00015');
  await click('Agent handoff');
  await click('Cost');
  let unknown = [...timeline().querySelectorAll('button')].find(node => node.textContent.includes('Run specialist'));
  expect(unknown.textContent).toContain('Unknown');
  expect(unknown.querySelector('.sg-evidence-meter-fill')).toBeNull();
  expect(detail().textContent).toContain('Unknown');
  expect(container.textContent).toContain('Partial cost coverage');
  await click('Tokens');
  unknown = [...timeline().querySelectorAll('button')].find(node => node.textContent.includes('Run specialist'));
  expect(unknown.textContent).toContain('Unknown');
  expect(unknown.querySelector('.sg-evidence-meter-fill')).toBeNull();
  expect(unknown.textContent).not.toContain('0 tokens');
});

test('the adjustable rule is an isolated comparison and cannot alter the saved sample incident or measurements', async () => {
  const original = JSON.stringify(SAMPLE_RUNS);
  await render();
  const comparison = () => container.querySelector('[aria-label="Demo rule comparison"]').textContent;
  expect(comparison()).toBe('1 of 3 calls would exceed 2.00 s.');
  await changeRange('Demo duration rule', 5000);
  expect(comparison()).toBe('0 of 3 calls would exceed 5.00 s.');
  expect(detail().textContent).toContain('Slow call');
  expect(detail().textContent).toContain('3.42 s exceeds the sample rule of 2.00 s');
  await click('Inspect incident');
  expect(container.textContent).toContain('Draft answer exceeded its duration limit');
  await click('Mark demo incident resolved');
  await changeRange('Demo duration rule', 500);
  expect(comparison()).toBe('1 of 3 calls would exceed 500 ms.');
  expect(button('Resolved in this demo').disabled).toBe(true);
  await click('Reset demo rule');
  expect(field('Demo duration rule').value).toBe('2000');
  expect(button('Resolved in this demo').disabled).toBe(true);
  expect(JSON.stringify(SAMPLE_RUNS)).toBe(original);
});

test('compact mode keeps replay and comparison usable while respecting the public signup destination', async () => {
  await render({ compact: true, publicSite: true });
  expect(button('All calls')).toBeUndefined();
  expect(button('Replay sample')).toBeDefined();
  expect(field('Replay position')).not.toBeNull();
  expect(field('Demo duration rule')).not.toBeNull();
  expect(container.querySelector('a[href="/signup"]').textContent.trim()).toBe('Sign up');
  expect(container.querySelector('a[href="/setup"]')).toBeNull();
});

test('flow nodes share the selected evidence, reveal only captured calls, and pause playback for inspection', async () => {
  await render();
  const flow = () => container.querySelector('[aria-label="Sample call flow"]');
  const first = () => button('Inspect Classify question in flow');
  const draft = () => button('Inspect Draft answer in flow');
  expect(draft().getAttribute('aria-pressed')).toBe('true');
  await click('Inspect Classify question in flow');
  expect(detail().textContent).toContain('Classify question');
  expect(first().getAttribute('aria-pressed')).toBe('true');
  await click('Replay sample');
  expect([...flow().querySelectorAll('button')].every(node => node.disabled)).toBe(true);
  await act(async () => jest.advanceTimersByTime(300));
  expect(first().disabled).toBe(false);
  expect(draft().disabled).toBe(true);
  expect(replayIntervals.size).toBe(1);
  await click('Inspect Classify question in flow');
  expect(replayIntervals.size).toBe(0);
  const inspectedPosition = field('Replay position').value;
  await act(async () => jest.advanceTimersByTime(1000));
  expect(field('Replay position').value).toBe(inspectedPosition);
  await changeRange('Replay position', 3700);
  expect(draft().disabled).toBe(false);
  expect(draft().getAttribute('aria-pressed')).toBe('true');
  expect(button('Inspect Check answer in flow').disabled).toBe(true);
  expect(detail().textContent).toContain('Draft answer');
});