'use strict';

const { createHmac } = require('node:crypto');
const { isIP } = require('node:net');

const MAX_BODY_BYTES = 4096;
const RETENTION_DAYS = 180;
const CONSENT_VERSION = 'early-access-v1';
const CONSENT_TEXT = 'I agree that Sillage may store these details for up to 180 days and contact me about early access.';
const SOURCES = new Set(['signup', 'signin', 'onboarding']);
const FIELDS = new Set(['schema_version', 'name', 'email', 'company', 'use_case', 'consent', 'source']);

class PublicError extends Error {
  constructor(code, status = 400, retryAfter = undefined) {
    super(code);
    this.code = code;
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

function textField(value, maximum, required = false, multiline = false) {
  if (value === undefined && !required) return '';
  if (typeof value !== 'string') throw new PublicError('invalid_request');
  const result = value.normalize('NFC').trim();
  const controls = multiline ? /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/ : /[\x00-\x1f\x7f]/;
  if (result.length > maximum || (required && !result) || controls.test(result) || /[\uD800-\uDFFF]/u.test(result)) {
    throw new PublicError('invalid_request');
  }
  return result;
}

function normalizeEmail(value) {
  if (typeof value !== 'string') throw new PublicError('invalid_request');
  const email = value.trim().toLowerCase();
  if (email.length > 254 || !/^[\x21-\x7e]+$/.test(email)) throw new PublicError('invalid_request');
  const parts = email.split('@');
  if (parts.length !== 2) throw new PublicError('invalid_request');
  const [local, domain] = parts;
  if (local.length > 64 || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local) || local.startsWith('.') || local.endsWith('.') || local.includes('..')) {
    throw new PublicError('invalid_request');
  }
  const labels = domain.split('.');
  if (labels.length < 2 || labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) || /^\d+$/.test(labels.at(-1))) {
    throw new PublicError('invalid_request');
  }
  return email;
}

function validateInterest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).some(key => !FIELDS.has(key)) ||
      body.schema_version !== 1 || body.consent !== true || !SOURCES.has(body.source)) throw new PublicError('invalid_request');
  return {
    schema_version: 1,
    name: textField(body.name, 100, true),
    email: normalizeEmail(body.email),
    company: textField(body.company, 120),
    use_case: textField(body.use_case, 1200, false, true),
    source: body.source,
  };
}

function httpsOrigin(value) {
  if (typeof value !== 'string' || value.length > 512 || value !== value.trim()) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.replace(/\.$/, '');
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
        /[\\\s]/.test(value) || !host || host === 'localhost' || host.endsWith('.localhost') ||
        isIP(host.replace(/^\[|\]$/g, ''))) return null;
    return url.origin;
  } catch { return null; }
}

function publicOrigin(env) {
  if (env.SILLAGE_PUBLIC_ORIGIN !== undefined) return httpsOrigin(env.SILLAGE_PUBLIC_ORIGIN);
  if (env.VERCEL === '1' && env.VERCEL_ENV === 'preview' && typeof env.VERCEL_URL === 'string' && /^[a-z0-9][a-z0-9.-]*\.vercel\.app$/i.test(env.VERCEL_URL)) {
    return httpsOrigin(`https://${env.VERCEL_URL}`);
  }
  return null;
}

function requireOrigin(req, env) {
  const allowed = publicOrigin(env);
  if (!allowed) throw new PublicError('registration_unavailable', 503, 30);
  // Origin is a browser cross-site boundary, not authentication or bot protection.
  if (req.headers.origin !== allowed || (req.headers['sec-fetch-site'] && req.headers['sec-fetch-site'] !== 'same-origin')) {
    throw new PublicError('origin_not_allowed', 403);
  }
}

function requestIp(req, env) {
  // Vercel overwrites this header. Outside Vercel, never trust forwarded headers.
  let value = env.VERCEL === '1' ? req.headers['x-vercel-forwarded-for'] : req.socket?.remoteAddress;
  if (typeof value !== 'string' || value.length > 64 || !isIP(value)) throw new PublicError('registration_unavailable', 503, 30);
  if (value.startsWith('::ffff:') && isIP(value.slice(7)) === 4) value = value.slice(7);
  // URL serialisation canonicalises equivalent IPv6 spellings before hashing.
  return isIP(value) === 6 ? new URL(`http://[${value}]/`).hostname : value;
}

function rateBuckets(ip, key, now) {
  if (typeof key !== 'string' || Buffer.byteLength(key) < 32 || Buffer.byteLength(key) > 512) throw new PublicError('registration_unavailable', 503, 30);
  const timestamp = now.getTime();
  const specs = [ ['global-minute', 60000, 60], ['global-day', 86400000, 1000], ['ip', 900000, 5] ];
  return specs.map(([scope, windowMs, limit]) => {
    const window = Math.floor(timestamp / windowMs);
    const identity = scope === 'ip' ? createHmac('sha256', key).update(`interest-ip-v1:${window}:${ip}`).digest('hex') : scope;
    return {
      id: `${scope}:${window}:${identity}`,
      limit,
      retryAfter: Math.max(1, Math.ceil(((window + 1) * windowMs - timestamp) / 1000)),
      expiresAt: new Date((window + 1) * windowMs + 86400000),
    };
  });
}

function interestRecord(input, now) {
  return { _id: input.email, ...input, verified: false, createdAt: now,
    expiresAt: new Date(now.getTime() + RETENTION_DAYS * 86400000),
    consent: { accepted: true, version: CONSENT_VERSION, text: CONSENT_TEXT, acceptedAt: now } };
}

module.exports = { MAX_BODY_BYTES, RETENTION_DAYS, CONSENT_VERSION, CONSENT_TEXT, PublicError, validateInterest,
  normalizeEmail, httpsOrigin, publicOrigin, requireOrigin, requestIp, rateBuckets, interestRecord };
