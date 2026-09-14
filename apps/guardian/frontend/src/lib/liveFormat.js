export const isKnown = (value) => typeof value === 'number' && Number.isFinite(value);
export const money = (value) => isKnown(value) ? `$${value.toFixed(value < 0.01 ? 5 : 4)}` : 'Unknown';
export const duration = (value) => !isKnown(value) ? 'Unknown'
  : value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${Math.round(value)}ms`;
export const count = (value) => !isKnown(value) ? 'Unknown'
  : Number.isInteger(value) && !Number.isSafeInteger(value) ? 'Out of display range' : value.toLocaleString();
export const observedCost = (total, known, knownCount) => isKnown(total) ? money(total)
  : knownCount > 0 && isKnown(known) ? `${money(known)} known` : 'Unknown';
