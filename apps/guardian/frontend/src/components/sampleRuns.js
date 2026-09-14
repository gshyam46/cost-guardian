export const SAMPLE_RUNS = Object.freeze([
  { id: 'support', name: 'Support answer', state: 'Slow call', outcome: 'An answer took longer than the saved rule allows.', calls: [
    { name: 'Classify question', model: 'gpt-4.1-mini', ms: 280, input: 240, output: 32, cost: 0.0001472, state: 'Completed' },
    { name: 'Draft answer', model: 'gpt-4.1', ms: 3420, input: 1840, output: 386, cost: 0.006768, state: 'Slow call' },
    { name: 'Check answer', model: 'gpt-4.1-mini', ms: 410, input: 580, output: 46, cost: 0.0003056, state: 'Completed' },
  ] },
  { id: 'search', name: 'Document search', state: 'Completed', outcome: 'Both captured model calls completed. Retrieval contents are not captured.', calls: [
    { name: 'Rewrite question', model: 'gpt-4.1-mini', ms: 190, input: 160, output: 40, cost: 0.000128, state: 'Completed' },
    { name: 'Compose answer', model: 'gpt-4.1-mini', ms: 780, input: 1280, output: 210, cost: 0.000848, state: 'Completed' },
  ] },
  { id: 'handoff', name: 'Agent handoff', state: 'Reported error', outcome: 'The application reported an error. Missing usage and cost stay unknown.', calls: [
    { name: 'Route request', model: 'gpt-4.1-mini', ms: 240, input: 360, output: 28, cost: 0.0001888, state: 'Completed' },
    { name: 'Run specialist', model: 'gpt-4.1', ms: 1240, input: null, output: null, cost: null, state: 'Reported error' },
  ] },
]);
