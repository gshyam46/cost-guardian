const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const text = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= 512
  && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
const PROJECT = ['organization_id', 'project_id', 'environment', 'name'];
export const validCostLimit = (value) => typeof value === 'string'
  && /^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?(?![\s\S])/.test(value);
export const validPolicyRules = (rules) => exact(rules, ['max_call_cost_usd', 'max_call_latency_ms', 'alert_on_errors'])
  && (rules.max_call_cost_usd === null || validCostLimit(rules.max_call_cost_usd))
  && (rules.max_call_latency_ms === null || (Number.isSafeInteger(rules.max_call_latency_ms)
    && rules.max_call_latency_ms >= 0 && rules.max_call_latency_ms <= 86400000))
  && typeof rules.alert_on_errors === 'boolean';
const timestamp = (value) => {
  if (typeof value !== 'string' || value.length > 40) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-](\d{2}):(\d{2}))(?![\s\S])/.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, offsetHour = '0', offsetMinute = '0'] = match;
  return +year > 0 && +month > 0 && +month <= 12 && +day > 0 && +day <= new Date(Date.UTC(+year, +month, 0)).getUTCDate()
    && +hour < 24 && +minute < 60 && +second < 60 && +offsetHour < 24 && +offsetMinute < 60
    && Number.isFinite(new Date(value).getTime());
};
export const validMonitoringPolicy = (body, access) => {
  if (!exact(body, ['schema_version', 'revision', 'updated_at', 'updated_by', 'rules', 'can_manage', 'project'])
      || !['api_key', 'oidc'].includes(access?.auth_mode)
      || body.schema_version !== 1 || !Number.isSafeInteger(body.revision) || body.revision < 0 || body.revision > 2147483647
      || typeof body.can_manage !== 'boolean' || !validPolicyRules(body.rules)) return false;
  if (body.revision === 0) {
    if (body.updated_at !== null || body.updated_by !== null || body.rules.max_call_cost_usd !== null
        || body.rules.max_call_latency_ms !== null || body.rules.alert_on_errors !== true) return false;
  } else if (!timestamp(body.updated_at) || !exact(body.updated_by, ['id', 'name', 'role'])
      || !text(body.updated_by.id) || !text(body.updated_by.name)
      || body.updated_by.role !== 'owner') return false;
  if (access?.auth_mode === 'oidc') {
    if (!exact(body.project, PROJECT) || !PROJECT.every((key) => text(body.project[key]) && body.project[key] === access.project?.[key])) return false;
    if (!['owner', 'operator', 'viewer'].includes(access.actor?.role) || body.can_manage !== (access.actor.role === 'owner')) return false;
  } else if (body.project !== null || body.can_manage !== false) return false;
  return true;
};
export const policyDraft = (rules) => ({ cost: rules.max_call_cost_usd ?? '',
  latency: rules.max_call_latency_ms === null ? '' : String(rules.max_call_latency_ms), errors: rules.alert_on_errors });
export const draftRules = (draft) => {
  if (!draft || (draft.cost !== '' && !validCostLimit(draft.cost))
      || (draft.latency !== '' && !/^(?:0|[1-9][0-9]{0,7})(?![\s\S])/.test(draft.latency))) return null;
  const rules = { max_call_cost_usd: draft.cost === '' ? null : draft.cost,
    max_call_latency_ms: draft.latency === '' ? null : Number(draft.latency), alert_on_errors: draft.errors };
  return validPolicyRules(rules) ? rules : null;
};
const canonicalCost = (value) => value === null ? null : value.includes('.') ? value.replace(/0+$/, '').replace(/\.$/, '') : value;
export const samePolicyRules = (left, right) => validPolicyRules(left) && validPolicyRules(right)
  && canonicalCost(left.max_call_cost_usd) === canonicalCost(right.max_call_cost_usd)
  && left.max_call_latency_ms === right.max_call_latency_ms && left.alert_on_errors === right.alert_on_errors;
export const samePolicyDraft = (left, right) => left && right && left.cost === right.cost && left.latency === right.latency && left.errors === right.errors;
const costUnits = (value) => { const [whole, fraction = ''] = value.split('.'); return BigInt(whole + fraction.padEnd(12, '0')); };

// Only known evidence contracts become an explanation; legacy/unknown evidence
// remains available in the existing raw view without an invented conclusion.
export const policyExplanation = (evidence) => {
  if (!evidence || !Number.isSafeInteger(evidence.policy_revision) || evidence.policy_revision < 0) return null;
  if (evidence.policy_kind === 'absolute' && evidence.comparison === 'gt') {
    if (evidence.metric === 'cost_usd' && evidence.reason === 'cost_limit_exceeded'
        && validCostLimit(evidence.observed_value) && validCostLimit(evidence.threshold_value)
        && costUnits(evidence.observed_value) > costUnits(evidence.threshold_value)) {
      return `Observed call cost $${evidence.observed_value} exceeded the saved $${evidence.threshold_value} limit.`;
    }
    if (evidence.metric === 'latency_ms' && evidence.reason === 'latency_limit_exceeded'
        && typeof evidence.observed_value === 'number' && Number.isFinite(evidence.observed_value) && evidence.observed_value >= 0
        && Number.isSafeInteger(evidence.threshold_value) && evidence.threshold_value >= 0 && evidence.threshold_value <= 86400000
        && evidence.observed_value > evidence.threshold_value) {
      return `Observed call duration ${evidence.observed_value.toLocaleString('en-US')} ms exceeded the saved ${evidence.threshold_value.toLocaleString('en-US')} ms limit.`;
    }
  }
  if (evidence.policy_kind === 'reported_error' && evidence.metric === 'status' && evidence.comparison === 'eq'
      && evidence.reason === 'reported_call_error' && evidence.observed_value === 'error' && evidence.threshold_value === 'error') {
    return 'The call reported an error while call-error alerts were enabled. This does not establish that the whole workflow failed.';
  }
  return null;
};
