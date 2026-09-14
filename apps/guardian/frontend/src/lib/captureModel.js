const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const count = (value) => value === null || (Number.isSafeInteger(value) && value >= 0);
export const captureTimestamp = (value) => value === null || (typeof value === 'string'
  && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(new Date(value).getTime()));
const text = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max
  && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
const PROJECT = ['organization_id', 'project_id', 'environment', 'name'];
const STATUS = ['last_test_received_at', 'last_received_at', 'received_events', 'pending_events', 'processed_events', 'last_processed_at', 'conflicted_events', 'worker_status'];
export const validCapture = (body, project) => {
  if (!exact(body, ['mode', 'enabled', 'schema_version', 'collector_path', 'can_manage_keys', 'project', 'limits', 'status'])
      || !['langfuse', 'direct'].includes(body.mode) || typeof body.enabled !== 'boolean' || typeof body.can_manage_keys !== 'boolean'
      || body.schema_version !== 1 || body.collector_path !== '/api/guardian/ingest/events'
      || !exact(body.limits, ['max_batch_events', 'max_body_bytes', 'max_active_keys', 'max_keys'])
      || body.limits.max_batch_events !== 100 || body.limits.max_body_bytes !== 262144
      || body.limits.max_active_keys !== 10 || body.limits.max_keys !== 100) return false;
  if (body.project !== null && (!exact(body.project, PROJECT) || !PROJECT.every((key) => text(body.project[key], 512)))) return false;
  if (project && (!body.project || PROJECT.some((key) => project[key] !== body.project[key]))) return false;
  if (body.mode === 'langfuse') return body.enabled === false && body.can_manage_keys === false && body.status === null;
  return body.enabled === true && body.project !== null && exact(body.status, STATUS)
    && ['last_test_received_at', 'last_received_at', 'last_processed_at'].every((key) => captureTimestamp(body.status[key]))
    && ['received_events', 'pending_events', 'processed_events', 'conflicted_events'].every((key) => count(body.status[key]))
    && ['not_started', 'current', 'stale'].includes(body.status.worker_status);
};

export const validCredential = (value) => exact(value, ['id', 'label', 'prefix', 'status', 'created_at', 'expires_at', 'revoked_at', 'last_used_at'])
  && typeof value.id === 'string' && /^[a-f0-9]{32}$/.test(value.id) && text(value.label, 80)
  && value.prefix === `cg_ingest_${value.id.slice(0, 8)}` && ['active', 'expired', 'revoked'].includes(value.status)
  && typeof value.created_at === 'string' && typeof value.expires_at === 'string'
  && ['created_at', 'expires_at', 'revoked_at', 'last_used_at'].every((key) => captureTimestamp(value[key]))
  && (value.status === 'revoked' ? value.revoked_at !== null : value.revoked_at === null)
  && new Date(value.expires_at).getTime() > new Date(value.created_at).getTime();

export const validCreatedCredential = (body) => exact(body, ['credential', 'token']) && validCredential(body.credential)
  && body.credential.status === 'active' && typeof body.token === 'string'
  && new RegExp(`^cg_ingest_${body.credential.id}_[A-Za-z0-9_-]{43}$`).test(body.token);

export const credentialList = (body) => {
  if (!exact(body, ['credentials']) || !Array.isArray(body.credentials) || body.credentials.length > 100
      || !body.credentials.every(validCredential) || new Set(body.credentials.map((item) => item.id)).size !== body.credentials.length) {
    throw new Error('credential_metadata_unavailable');
  }
  return body.credentials;
};
