'use strict';

const { MAX_BODY_BYTES, PublicError } = require('./contract.cjs');

function json(res, status, body, headers = {}) {
  res.statusCode = status;
  for (const [name, value] of Object.entries({ 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', Pragma: 'no-cache', 'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer', ...headers })) res.setHeader(name, value);
  res.end(JSON.stringify(body));
}

function readJson(req, timeoutMs = 2000) {
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(req.headers['content-type'] || '') || req.headers['content-encoding']) {
    throw new PublicError('unsupported_media_type', 415);
  }
  const length = req.headers['content-length'];
  if (length !== undefined && (typeof length !== 'string' || !/^\d+$/.test(length))) throw new PublicError('invalid_request');
  if (length !== undefined && Number(length) > MAX_BODY_BYTES) throw new PublicError('payload_too_large', 413);
  // Do not touch Vercel's req.body getter: count the restored raw stream, including JSON escapes.
  return new Promise((resolve, reject) => {
    let size = 0;
    let chunks = [];
    let done = false;
    const finish = (error, value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      chunks = [];
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => finish(new PublicError('invalid_request')), timeoutMs);
    req.on('error', () => finish(new PublicError('invalid_request')));
    req.on('aborted', () => finish(new PublicError('invalid_request')));
    req.on('data', chunk => {
      if (done) return;
      const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += data.length;
      if (size > MAX_BODY_BYTES) return finish(new PublicError('payload_too_large', 413));
      chunks.push(data);
    });
    req.on('end', () => {
      if (done) return;
      if (length !== undefined && Number(length) !== size) return finish(new PublicError('invalid_request'));
      try {
        const raw = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
        finish(null, JSON.parse(raw));
      } catch { finish(new PublicError('invalid_request')); }
    });
    if (req.aborted || req.readableEnded) finish(new PublicError('invalid_request'));
  });
}

module.exports = { json, readJson };
