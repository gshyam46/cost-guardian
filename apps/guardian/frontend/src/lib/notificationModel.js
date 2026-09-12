const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const integer = (value, min, max) => Number.isSafeInteger(value) && value >= min && value <= max;
const label = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= 512
  && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
const PROJECT = ['organization_id', 'project_id', 'environment', 'name'];
const STATES = ['queued', 'sending', 'retrying', 'accepted', 'failed', 'unconfirmed', 'cancelled'];
const safeCode = (value) => value === null || (typeof value === 'string' && /^[a-z][a-z0-9_]{0,63}(?![\s\S])/.test(value));
const incidentId = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}(?![\s\S])/.test(value);
const deliveryId = (value) => typeof value === 'string' && /^[a-f0-9]{64}(?![\s\S])/.test(value);
export const notificationTimestamp = (value, nullable = true) => {
  if (value === null) return nullable;
  if (typeof value !== 'string' || value.length > 40) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-](\d{2}):(\d{2}))(?![\s\S])/.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, offsetHour = '0', offsetMinute = '0'] = match;
  return +year > 0 && +month > 0 && +month <= 12 && +day > 0 && +day <= new Date(Date.UTC(+year, +month, 0)).getUTCDate()
    && +hour < 24 && +minute < 60 && +second < 60 && +offsetHour < 24 && +offsetMinute < 60
    && Number.isFinite(new Date(value).getTime());
};
const validAttempt = (attempt) => exact(attempt, ['number', 'started_at', 'finished_at', 'outcome'])
  && integer(attempt.number, 1, 15) && notificationTimestamp(attempt.started_at, false)
  && notificationTimestamp(attempt.finished_at) && safeCode(attempt.outcome)
  && (attempt.finished_at === null || new Date(attempt.finished_at) >= new Date(attempt.started_at));
export const validDelivery = (row) => exact(row, ['id', 'incident_id', 'kind', 'state', 'created_at', 'updated_at',
  'attempt_count', 'cycle', 'next_attempt_at', 'last_outcome', 'can_retry', 'attempts'])
  && deliveryId(row.id) && ['test', 'incident'].includes(row.kind)
  && (row.kind === 'test' ? row.incident_id === null : incidentId(row.incident_id))
  && STATES.includes(row.state) && notificationTimestamp(row.created_at, false) && notificationTimestamp(row.updated_at, false)
  && new Date(row.updated_at) >= new Date(row.created_at)
  && integer(row.attempt_count, 0, 15) && integer(row.cycle, 1, 3)
  && notificationTimestamp(row.next_attempt_at) && safeCode(row.last_outcome) && typeof row.can_retry === 'boolean'
  && (!row.can_retry || (['failed', 'unconfirmed'].includes(row.state) && row.cycle < 3))
  && Array.isArray(row.attempts) && row.attempts.length <= row.attempt_count && row.attempts.every(validAttempt)
  && new Set(row.attempts.map((attempt) => attempt.number)).size === row.attempts.length
  && row.attempts.every((attempt) => attempt.number <= row.attempt_count);
export const validNotifications = (body, access, selectedIncident = null) => {
  if (!exact(body, ['schema_version', 'revision', 'project', 'can_manage', 'updated_at', 'destination', 'worker', 'deliveries', 'has_more'])
      || body.schema_version !== 1 || !integer(body.revision, 0, 2147483647)
      || !['api_key', 'oidc'].includes(access?.auth_mode) || typeof body.can_manage !== 'boolean'
      || !notificationTimestamp(body.updated_at) || typeof body.has_more !== 'boolean') return false;
  if (access.auth_mode === 'oidc') {
    if (!exact(body.project, PROJECT) || !PROJECT.every((key) => label(body.project[key]) && body.project[key] === access.project?.[key])
        || !['owner', 'operator', 'viewer'].includes(access.actor?.role) || body.can_manage !== (access.actor.role === 'owner')) return false;
  } else if (body.project !== null || body.can_manage !== false) return false;
  const target = body.destination;
  if (!exact(target, ['channel', 'state', 'verified', 'enabled']) || target.channel !== 'slack'
      || !['not_configured', 'invalid', 'configured', 'changed'].includes(target.state)
      || typeof target.verified !== 'boolean' || typeof target.enabled !== 'boolean'
      || (target.state !== 'configured' && (target.verified || target.enabled)) || (target.enabled && !target.verified)) return false;
  if (!exact(body.worker, ['status', 'last_seen_at']) || !['unknown', 'healthy', 'stale', 'blocked'].includes(body.worker.status)
      || !notificationTimestamp(body.worker.last_seen_at) || (body.worker.status === 'healthy' && (body.worker.last_seen_at === null || target.state !== 'configured'))) return false;
  return Array.isArray(body.deliveries) && body.deliveries.length <= 50 && body.deliveries.every(validDelivery)
    && new Set(body.deliveries.map((row) => row.id)).size === body.deliveries.length
    && (selectedIncident === null || body.deliveries.every((row) => row.kind === 'incident' && row.incident_id === selectedIncident));
};
const OUTCOMES = {
  accepted: 'Slack accepted the message.', slack_accepted: 'Slack accepted the message.',
  rate_limited: 'Slack limited delivery requests.', rejected: 'Slack rejected the request.',
  http_rejected: 'Slack rejected the request.', temporarily_unavailable: 'Slack was temporarily unavailable.',
  unconfirmed: 'Slack acceptance could not be confirmed.', acceptance_unconfirmed: 'Slack acceptance could not be confirmed.',
  network_error: 'Slack acceptance could not be confirmed.', timeout: 'Slack acceptance could not be confirmed before the deadline.',
  destination_changed: 'The notification destination changed.', disabled: 'Incident notifications were disabled.',
  cycle_expired: 'The delivery retry window expired.', attempts_exhausted: 'The retry attempt limit was reached.',
  receiver_unavailable: 'Slack was temporarily unavailable.', receiver_rejected: 'Slack rejected the request.',
  invalid_response: 'Slack returned an unrecognized acknowledgement.', response_too_large: 'Slack acceptance could not be confirmed.',
  network_unconfirmed: 'Slack acceptance could not be confirmed.', timeout_unconfirmed: 'Slack acceptance could not be confirmed before the deadline.',
  worker_lost_unconfirmed: 'The worker stopped before acceptance was confirmed.', notifications_disabled: 'Incident notifications were disabled.',
  retry_requested: 'An owner requested another delivery attempt.', invalid_delivery: 'The delivery record needs operator review.',
};
export const outcomeText = (code) => code === null ? 'No outcome recorded.'
  : Object.hasOwn(OUTCOMES, code) ? OUTCOMES[code] : 'Delivery could not be confirmed.';
export const deliveryStateText = (state) => ({ queued: 'Queued', sending: 'Sending', retrying: 'Retry scheduled',
  accepted: 'Accepted by Slack', failed: 'Delivery failed', unconfirmed: 'Acceptance unconfirmed', cancelled: 'Cancelled' }[state]);
