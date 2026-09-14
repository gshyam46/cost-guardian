'use strict';

const https = require('node:https');
const { httpsOrigin } = require('./contract.cjs');
const { json } = require('./http.cjs');

function probeReady(target, { timeoutMs = 3000, request = https.get } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let outgoing;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(new Error('workspace_unavailable')); else resolve(result);
    };
    const timer = setTimeout(() => {
      finish(true);
      outgoing?.destroy();
    }, timeoutMs);
    try {
      // Fixed operator target; Node HTTPS does not follow redirects or use HTTP_PROXY.
      outgoing = request(target, { method: 'GET', agent: false, headers: { Accept: 'application/json' } }, response => {
        let size = 0;
        let chunks = [];
        response.on('error', () => finish(true));
        response.on('aborted', () => finish(true));
        if (response.statusCode !== 200 || !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(response.headers['content-type'] || '')) {
          finish(true);
          response.destroy();
          return;
        }
        response.on('data', chunk => {
          if (settled) return;
          size += chunk.length;
          if (size > 4096) { chunks = []; finish(true); response.destroy(); return; }
          chunks.push(chunk);
        });
        response.on('end', () => {
          if (settled) return;
          try {
            const body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
            chunks = [];
            finish(null, !!body && !Array.isArray(body) && Object.keys(body).length === 2 && body.status === 'ready' && body.service === 'cost-guardian');
          } catch { finish(true); }
        });
      });
      outgoing.on('error', () => finish(true));
    } catch { finish(true); }
  });
}

function createAvailabilityHandler({ env = process.env, transport = probeReady, timeoutMs = 3000 } = {}) {
  return async (req, res) => {
    if (req.method !== 'GET') return json(res, 405, { error: 'method_not_allowed' }, { Allow: 'GET' });
    const value = env.SILLAGE_WORKSPACE_URL;
    if (value === undefined || value === '') return json(res, 200, { available: false, workspace_url: null, reason: 'coming_soon' });
    const origin = httpsOrigin(value);
    let available = false;
    if (origin) {
      let timer;
      try {
        // Also bound injected/custom transports. The native transport destroys its socket itself.
        available = await Promise.race([transport(`${origin}/api/ready`, { timeoutMs }),
          new Promise(resolve => { timer = setTimeout(() => resolve(false), timeoutMs); })]) === true;
      } catch { available = false; } finally { clearTimeout(timer); }
    }
    return json(res, 200, { available, workspace_url: available ? origin : null, reason: available ? 'ready' : 'unavailable' });
  };
}

module.exports = { createAvailabilityHandler, probeReady };
