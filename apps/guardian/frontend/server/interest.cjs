'use strict';

const { PublicError, requireOrigin, validateInterest, requestIp, rateBuckets, interestRecord } = require('./contract.cjs');
const { readJson, json } = require('./http.cjs');

function createInterestHandler({ env = process.env, store, now = () => new Date(), clientIp = requestIp,
  bodyTimeoutMs = 2000, originCheck = requireOrigin } = {}) {
  return async (req, res) => {
    if (req.method !== 'POST') return json(res, 405, { registered: false, error: 'method_not_allowed' }, { Allow: 'POST' });
    try {
      originCheck(req, env);
      const input = validateInterest(await readJson(req, bodyTimeoutMs));
      const at = now();
      const buckets = rateBuckets(clientIp(req, env), env.SILLAGE_INTEREST_HMAC_KEY, at);
      const storage = store || require('./mongo.cjs').getStore(env);
      const result = await storage.register(interestRecord(input, at), buckets);
      if (result?.acknowledged !== true) throw new PublicError('registration_unavailable', 503, 30);
      return json(res, 202, { registered: true, status: 'interest_recorded', schema_version: 1 });
    } catch (error) {
      const safe = error instanceof PublicError ? error : new PublicError('registration_unavailable', 503, 30);
      return json(res, safe.status, { registered: false, error: safe.code }, safe.retryAfter ? { 'Retry-After': String(safe.retryAfter) } : {});
    }
  };
}

module.exports = { createInterestHandler };
