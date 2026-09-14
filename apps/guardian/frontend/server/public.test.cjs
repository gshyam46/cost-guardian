'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { PassThrough, Readable } = require('node:stream');
const { EventEmitter } = require('node:events');
const { createInterestHandler } = require('./interest.cjs');
const { createAvailabilityHandler, probeReady } = require('./availability.cjs');
const { validateInterest, normalizeEmail, rateBuckets, interestRecord, requestIp, publicOrigin, httpsOrigin, PublicError, CONSENT_TEXT } = require('./contract.cjs');
const { MongoInterestStore, bootstrap, COLLECTIONS, connectionConfig } = require('./mongo.cjs');
const admin = require('./interest-admin.cjs');

const NOW = new Date('2026-09-14T10:00:00Z');
const ENV = { SILLAGE_PUBLIC_ORIGIN: 'https://sillage.example', SILLAGE_INTEREST_HMAC_KEY: 'synthetic-test-hmac-key-32-characters-only' };
const BODY = { schema_version: 1, name: 'Founder', email: 'person@example.com', consent: true, source: 'signup' };

async function invoke(handler, { body = BODY, raw, method = 'POST', headers = {}, stream } = {}) {
  const bytes = raw === undefined ? Buffer.from(JSON.stringify(body)) : Buffer.from(raw);
  const req = stream || Readable.from([bytes]);
  req.method = method;
  req.headers = { 'content-type': 'application/json', origin: ENV.SILLAGE_PUBLIC_ORIGIN, ...headers };
  req.socket = { remoteAddress: '203.0.113.1' };
  const res = { statusCode: 200, headers: {}, setHeader(key, value) { this.headers[key.toLowerCase()] = value; },
    end(value) { this.body = JSON.parse(value); } };
  await handler(req, res);
  return res;
}

function handler(store, extra = {}) { return createInterestHandler({ env: ENV, store, now: () => NOW, ...extra }); }

test('registration only acknowledges a confirmed store result and sends no personal details back', async () => {
  let captured;
  const res = await invoke(handler({ register: async (record, buckets) => { captured = { record, buckets }; return { acknowledged: true }; } }),
    { body: { ...BODY, name: '  Jose\u0301  ', email: ' PERSON@EXAMPLE.COM ', company: ' Team ', use_case: 'RAG\nquality' } });
  assert.equal(res.statusCode, 202);
  assert.deepEqual(res.body, { registered: true, status: 'interest_recorded', schema_version: 1 });
  assert.equal(res.headers['cache-control'], 'no-store');
  assert.equal(captured.record.name, 'José');
  assert.equal(captured.record.email, 'person@example.com');
  assert.equal(captured.record.verified, false);
  assert.equal(captured.record.consent.text, CONSENT_TEXT);
  assert.equal(captured.record.expiresAt - NOW, 180 * 86400000);
  assert.ok(!JSON.stringify(captured).includes('203.0.113.1'));
});

test('missing, unacknowledged, and throwing storage never report success or leak errors', async () => {
  for (const register of [async () => undefined, async () => ({ acknowledged: false }), async () => { throw new Error('secret uri person@example.com'); }]) {
    const res = await invoke(handler({ register }));
    assert.equal(res.statusCode, 503);
    assert.deepEqual(res.body, { registered: false, error: 'registration_unavailable' });
    assert.equal(res.headers['retry-after'], '30');
  }
  assert.equal((await invoke(createInterestHandler({ env: ENV }))).statusCode, 503);
});

test('HTTP methods, origin and media type fail before persistence; no GET list or CORS', async () => {
  let writes = 0;
  const subject = handler({ register: async () => { writes++; return { acknowledged: true }; } });
  for (const method of ['GET', 'HEAD', 'OPTIONS', 'PUT']) assert.equal((await invoke(subject, { method })).statusCode, 405);
  for (const origin of [undefined, 'null', 'https://attacker.example', `${ENV.SILLAGE_PUBLIC_ORIGIN}/`, [ENV.SILLAGE_PUBLIC_ORIGIN]]) {
    assert.equal((await invoke(subject, { headers: { origin } })).statusCode, 403);
  }
  assert.equal((await invoke(subject, { headers: { 'sec-fetch-site': 'cross-site' } })).statusCode, 403);
  for (const headers of [{ 'content-type': 'text/plain' }, { 'content-type': 'application/json; charset=latin1' }, { 'content-encoding': 'gzip' }]) {
    assert.equal((await invoke(subject, { headers })).statusCode, 415);
  }
  assert.equal(writes, 0);
});

test('strict schema rejects passwords, honeypots, unknown fields and unsafe scalar values', async () => {
  const malformed = [null, [], 'text', { ...BODY, password: 'not-a-password' }, { ...BODY, website: 'bot' },
    { ...BODY, consent: false }, { ...BODY, consent: 'true' }, { ...BODY, schema_version: '1' }, { ...BODY, source: 'landing' },
    { ...BODY, name: '' }, { ...BODY, name: 'a'.repeat(101) }, { ...BODY, name: 'Name\nOther' }, { ...BODY, name: '\uD800' },
    { ...BODY, company: [] }, { ...BODY, use_case: 'a'.repeat(1201) }, { ...BODY, email: { $ne: '' } }];
  for (const body of malformed) {
    assert.equal((await invoke(handler({ register: () => assert.fail('must not store') }), { body })).statusCode, 400);
  }
  for (const source of ['signup', 'signin', 'onboarding']) assert.equal(validateInterest({ ...BODY, source }).source, source);
  assert.equal(validateInterest({ ...BODY, name: 'Founder 🌊' }).name, 'Founder 🌊');
});

test('email normalization is deterministic and rejects unsupported email forms', () => {
  assert.equal(normalizeEmail(' A+B@EXAMPLE.COM '), 'a+b@example.com');
  for (const email of ['a..b@example.com', '.a@example.com', 'a.@example.com', 'a@localhost', 'a@example.123',
    'a@-example.com', 'a@ex ample.com', 'a@例子.com', 'a@example.com\nExtra', 'a'.repeat(65) + '@example.com']) assert.throws(() => normalizeEmail(email));
});

test('raw request limit counts escaped JSON bytes, chunks, invalid UTF8 and claimed Content-Length', async () => {
  const subject = handler({ register: () => assert.fail('must not store') });
  const large = JSON.stringify({ ...BODY, use_case: '\\u0061'.repeat(700) });
  assert.equal((await invoke(subject, { raw: large })).statusCode, 413);
  assert.equal((await invoke(subject, { raw: '{}', headers: { 'content-length': '4097' } })).statusCode, 413);
  assert.equal((await invoke(subject, { raw: '{}', headers: { 'content-length': '1' } })).statusCode, 400);
  assert.equal((await invoke(subject, { raw: '{}', headers: { 'content-length': 'x' } })).statusCode, 400);
  assert.equal((await invoke(subject, { raw: '{' })).statusCode, 400);
  assert.equal((await invoke(subject, { raw: Buffer.from([0xc3, 0x28]) })).statusCode, 400);
  assert.equal((await invoke(subject, { stream: Readable.from([Buffer.alloc(3000, 32), Buffer.alloc(1100, 32)]) })).statusCode, 413);
});

test('body read timeout and cancellation fail promptly without storing', async () => {
  const subject = handler({ register: () => assert.fail('must not store') }, { bodyTimeoutMs: 10 });
  const stalled = new PassThrough();
  assert.equal((await invoke(subject, { stream: stalled })).statusCode, 400);
  stalled.destroy();
  const aborted = new PassThrough();
  const pending = invoke(subject, { stream: aborted });
  aborted.emit('aborted');
  assert.equal((await pending).statusCode, 400);
  aborted.destroy();
});

test('raw intake never accesses the Vercel parsed-body getter', async () => {
  const stream = Readable.from([Buffer.from(JSON.stringify(BODY))]);
  Object.defineProperty(stream, 'body', { get() { assert.fail('parsed body was accessed'); } });
  assert.equal((await invoke(handler({ register: async () => ({ acknowledged: true }) }), { stream })).statusCode, 202);
});

test('configured origin cannot be replaced by host, forwarded headers or arbitrary preview hosts', () => {
  assert.equal(publicOrigin({ VERCEL: '1', VERCEL_ENV: 'preview', VERCEL_URL: 'sillage-preview-123.vercel.app' }), 'https://sillage-preview-123.vercel.app');
  assert.equal(publicOrigin({ VERCEL_URL: 'sillage-preview-123.vercel.app' }), null);
  assert.equal(publicOrigin({ VERCEL: '1', VERCEL_ENV: 'production', VERCEL_URL: 'sillage-preview-123.vercel.app' }), null);
  assert.equal(publicOrigin({ VERCEL: '1', VERCEL_URL: 'evil.example' }), null);
  assert.equal(publicOrigin({ ...ENV, VERCEL: '1', VERCEL_URL: 'sillage.vercel.app' }), ENV.SILLAGE_PUBLIC_ORIGIN);
  for (const value of ['http://sillage.example', 'https://u:p@sillage.example', 'https://sillage.example/path', 'https://sillage.example?x=1',
    'https://sillage.example/#x', 'https://localhost', 'https://localhost.', 'https://127.0.0.1', 'https://[::1]',
    'https://169.254.169.254', 'https://0x7f000001', 'https://sillage.example\\@evil.example', ' https://sillage.example']) assert.equal(httpsOrigin(value), null);
});

test('IP identity trusts Vercel only in its environment, canonicalizes IPv6 and stores windowed HMAC keys', () => {
  const req = { headers: { 'x-vercel-forwarded-for': '203.0.113.10', 'x-forwarded-for': '192.0.2.3' }, socket: { remoteAddress: '127.0.0.1' } };
  assert.equal(requestIp(req, {}), '127.0.0.1');
  assert.equal(requestIp(req, { VERCEL: '1' }), '203.0.113.10');
  assert.equal(requestIp({ headers: {}, socket: { remoteAddress: '::ffff:127.0.0.1' } }, {}), '127.0.0.1');
  const canonical = address => requestIp({ headers: {}, socket: { remoteAddress: address } }, {});
  assert.equal(canonical('2001:db8::1'), canonical('2001:0db8:0:0:0:0:0:1'));
  assert.throws(() => requestIp({ headers: { 'x-vercel-forwarded-for': '192.0.2.1, 192.0.2.2' } }, { VERCEL: '1' }));
  const first = rateBuckets('203.0.113.1', ENV.SILLAGE_INTEREST_HMAC_KEY, NOW);
  const next = rateBuckets('203.0.113.1', ENV.SILLAGE_INTEREST_HMAC_KEY, new Date(+NOW + 900000));
  assert.notEqual(first[2].id, next[2].id);
  assert.equal(first[2].limit, 5);
  assert.ok(first.every(bucket => !bucket.id.includes('203.0.113.1') && bucket.expiresAt > NOW));
  assert.throws(() => rateBuckets('203.0.113.1', 'short', NOW));
});

function fakeMongo({ commitError = false } = {}) {
  let state = { contacts: new Map(), rates: new Map(), schema: new Map([['interest-v1', { version: 1, retentionDays: 180 }]]) };
  const seen = { transactionOptions: undefined, closed: 0, ended: 0, indices: [] };
  const names = Object.fromEntries(Object.entries(COLLECTIONS).map(([key, value]) => [value, key]));
  const db = { collection(name) {
    const key = names[name];
    return {
      async findOne(query) { return state[key].get(query._id) || null; },
      async findOneAndUpdate(query, change) {
        const row = state[key].get(query._id) || { _id: query._id, count: 0, ...change.$setOnInsert };
        row.count += change.$inc.count;
        state[key].set(query._id, row);
        return row;
      },
      async insertOne(row) { state[key].set(row._id, row); return { acknowledged: true }; },
      async replaceOne(query, row) { state[key].set(query._id, row); return { acknowledged: true, matchedCount: 1 }; },
      async createIndex(spec, options) { seen.indices.push({ name, spec, options }); },
      async updateOne(query, update) {
        if (!state[key].has(query._id)) state[key].set(query._id, { ...update.$setOnInsert });
        if (update.$set) Object.assign(state[key].get(query._id), update.$set);
        return { acknowledged: true };
      },
    };
  } };
  const client = { db: () => db, close: async () => { seen.closed++; }, startSession() {
    return { async withTransaction(callback, options) {
      seen.transactionOptions = options;
      const backup = structuredClone(state);
      try { const value = await callback(); if (commitError) throw new Error('private commit failure'); return value; }
      catch (error) { state = backup; throw error; }
    }, endSession: async () => { seen.ended++; } };
  } };
  return { client, db, seen, state: () => state };
}

test('Mongo storage keeps first consent/details on retry and renews only after logical expiry', async () => {
  const mongo = fakeMongo();
  const store = new MongoInterestStore(mongo.client, 'sillage_interest_fixture');
  const buckets = rateBuckets('203.0.113.1', ENV.SILLAGE_INTEREST_HMAC_KEY, NOW);
  const first = interestRecord(validateInterest(BODY), NOW);
  await store.register(first, buckets);
  await store.register({ ...first, name: 'Other person', source: 'signin' }, buckets);
  assert.equal(mongo.state().contacts.size, 1);
  assert.equal(mongo.state().contacts.get(first._id).name, 'Founder');
  assert.equal(mongo.state().contacts.get(first._id).source, 'signup');
  const future = new Date(+first.expiresAt + 1);
  const renewed = interestRecord(validateInterest({ ...BODY, name: 'Renewed' }), future);
  await store.register(renewed, rateBuckets('203.0.113.1', ENV.SILLAGE_INTEREST_HMAC_KEY, future));
  assert.equal(mongo.state().contacts.get(first._id).name, 'Renewed');
  assert.equal(mongo.state().contacts.get(first._id).expiresAt - future, 180 * 86400000);
  assert.equal(mongo.seen.transactionOptions.timeoutMS, 4000);
  assert.deepEqual(mongo.seen.transactionOptions.writeConcern, { w: 'majority', journal: true });
  assert.equal(mongo.seen.ended, 3);
});

test('Mongo rate rejection rolls back all reservations and does not persist extra contact/IP rows', async () => {
  const mongo = fakeMongo();
  const store = new MongoInterestStore(mongo.client, 'sillage_interest_fixture');
  const buckets = rateBuckets('203.0.113.1', ENV.SILLAGE_INTEREST_HMAC_KEY, NOW);
  for (let index = 0; index < 5; index++) await store.register(interestRecord(validateInterest(BODY), NOW), buckets);
  const result = await invoke(handler(store), { body: { ...BODY, email: 'other@example.com' } });
  assert.equal(result.statusCode, 429);
  assert.equal(result.body.error, 'rate_limited');
  assert.equal(mongo.state().contacts.size, 1);
  assert.ok([...mongo.state().rates.values()].every(row => row.count === 5));
  const global = buckets.map(bucket => ({ ...bucket, limit: 5 }));
  global[2] = { ...global[2], id: 'ip:new-hmac' };
  await assert.rejects(store.register(interestRecord(validateInterest(BODY), NOW), global), error => error instanceof PublicError && error.status === 429);
  assert.equal(mongo.state().rates.size, 3);
});

test('unbootstrapped database and failed commit return retryable failure with no record', async () => {
  for (const mode of ['schema', 'commit']) {
    const mongo = fakeMongo({ commitError: mode === 'commit' });
    if (mode === 'schema') mongo.state().schema.clear();
    const res = await invoke(handler(new MongoInterestStore(mongo.client, 'sillage_interest_fixture')));
    assert.equal(res.statusCode, 503);
    assert.equal(mongo.state().contacts.size, 0);
    assert.equal(mongo.seen.ended, 1);
  }
});

test('bootstrap creates both absolute-expiry TTL indexes before publishing schema readiness', async () => {
  const mongo = fakeMongo();
  mongo.state().schema.clear();
  assert.deepEqual(await bootstrap(mongo.client, 'sillage_interest_fixture'), { bootstrapped: true });
  const ttl = mongo.seen.indices.filter(index => index.options.expireAfterSeconds === 0);
  assert.deepEqual(ttl.map(index => index.name), [COLLECTIONS.contacts, COLLECTIONS.rates]);
  assert.ok(ttl.every(index => index.spec.expiresAt === 1));
  assert.equal(mongo.state().schema.get('interest-v1').retentionDays, 180);
});

test('bootstrap preserves compatible metadata and rejects existing or concurrently created incompatible markers', async () => {
  const repeat = fakeMongo();
  repeat.state().schema.get('interest-v1').operatorNote = 'keep-existing-metadata';
  const before = structuredClone(repeat.state().schema);
  await bootstrap(repeat.client, 'sillage_interest_fixture');
  await bootstrap(repeat.client, 'sillage_interest_fixture');
  assert.deepEqual(repeat.state().schema, before);

  for (const marker of [{ version: 2, retentionDays: 180 }, { version: 1, retentionDays: 90 }, {}]) {
    const incompatible = fakeMongo();
    incompatible.state().schema.set('interest-v1', marker);
    await assert.rejects(bootstrap(incompatible.client, 'sillage_interest_fixture'), /registration_unavailable/);
    assert.equal(incompatible.seen.indices.length, 0);
    assert.deepEqual(incompatible.state().schema.get('interest-v1'), marker);
  }

  const concurrent = fakeMongo();
  concurrent.state().schema.clear();
  const collection = concurrent.db.collection;
  concurrent.db.collection = name => {
    const result = collection(name);
    if (name === COLLECTIONS.contacts) {
      const create = result.createIndex;
      result.createIndex = async (...args) => {
        concurrent.state().schema.set('interest-v1', { version: 2, retentionDays: 180 });
        return create(...args);
      };
    }
    return result;
  };
  await assert.rejects(bootstrap(concurrent.client, 'sillage_interest_fixture'), /registration_unavailable/);
  assert.equal(concurrent.state().schema.get('interest-v1').version, 2);
});

test('storage production config requires explicit dedicated database and certificate-valid TLS', () => {
  const base = { SILLAGE_INTEREST_DB: 'sillage_interest', SILLAGE_INTEREST_MONGO_URL: 'mongodb+srv://db.example/interest' };
  assert.equal(connectionConfig(base).dbName, 'sillage_interest');
  for (const uri of ['mongodb://db.example', 'mongodb+srv://db.example/?tls=false', 'mongodb+srv://db.example/?tlsAllowInvalidCertificates=true']) {
    assert.throws(() => connectionConfig({ ...base, SILLAGE_INTEREST_MONGO_URL: uri }));
  }
  for (const dbName of ['', 'admin', 'local', 'config', 'test', 'bad/name']) assert.throws(() => connectionConfig({ ...base, SILLAGE_INTEREST_DB: dbName }));
  assert.throws(() => connectionConfig({ SILLAGE_INTEREST_DB: 'sillage_interest' }));
});

test('availability accepts only exact successful ready result from fixed operator origin', async () => {
  let target;
  const subject = createAvailabilityHandler({ env: { SILLAGE_WORKSPACE_URL: 'https://workspace.example/' }, transport: async value => { target = value; return true; } });
  const response = await invoke(subject, { method: 'GET', headers: { origin: undefined, authorization: 'must-not-forward', cookie: 'must-not-forward' } });
  assert.equal(target, 'https://workspace.example/api/ready');
  assert.deepEqual(response.body, { available: true, workspace_url: 'https://workspace.example', reason: 'ready' });
  assert.equal(response.headers['cache-control'], 'no-store');
  assert.equal((await invoke(subject)).statusCode, 405);
});

test('availability is helpful with missing config and bounded for failed or hanging workspaces', async () => {
  assert.deepEqual((await invoke(createAvailabilityHandler({ env: {} }), { method: 'GET' })).body,
    { available: false, workspace_url: null, reason: 'coming_soon' });
  for (const transport of [async () => false, async () => ({ status: 'ready' }), async () => { throw new Error('secret endpoint'); }, () => new Promise(() => {})]) {
    const res = await invoke(createAvailabilityHandler({ env: { SILLAGE_WORKSPACE_URL: 'https://workspace.example' }, transport, timeoutMs: 10 }), { method: 'GET' });
    assert.deepEqual(res.body, { available: false, workspace_url: null, reason: 'unavailable' });
  }
  for (const origin of ['http://127.0.0.1:8001', 'https://u:p@workspace.example', 'https://workspace.example/path', 'https://workspace.example?target=elsewhere']) {
    const res = await invoke(createAvailabilityHandler({ env: { SILLAGE_WORKSPACE_URL: origin }, transport: () => assert.fail('must not call') }), { method: 'GET' });
    assert.equal(res.body.available, false);
  }
});

function requestFixture({ statusCode = 200, body = { status: 'ready', service: 'cost-guardian' }, contentType = 'application/json', hang = false } = {}) {
  let destroyed = false;
  let seen;
  const request = (target, options, callback) => {
    seen = { target, options };
    const outgoing = new EventEmitter();
    outgoing.destroy = () => { destroyed = true; };
    if (!hang) queueMicrotask(() => {
      const response = Readable.from([Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))]);
      response.statusCode = statusCode;
      response.headers = { 'content-type': contentType };
      callback(response);
    });
    return outgoing;
  };
  return { request, seen: () => seen, destroyed: () => destroyed };
}

test('HTTPS transport validates exact ready JSON, rejects redirects/oversized responses and forwards no credentials', async () => {
  const fixture = requestFixture();
  assert.equal(await probeReady('https://workspace.example/api/ready', fixture), true);
  assert.deepEqual(fixture.seen().options, { method: 'GET', agent: false, headers: { Accept: 'application/json' } });
  for (const options of [{ body: { status: 'not_ready', service: 'cost-guardian' } }, { body: { status: 'ready', service: 'other' } },
    { body: { status: 'ready', service: 'cost-guardian', extra: 'unexpected' } }, { body: [] }]) {
    assert.equal(await probeReady('https://workspace.example/api/ready', requestFixture(options)), false);
  }
  for (const options of [{ statusCode: 302 }, { statusCode: 503 }, { contentType: 'text/html' }, { body: '{bad' }, { body: ' '.repeat(4097) }]) {
    await assert.rejects(probeReady('https://workspace.example/api/ready', requestFixture(options)), /workspace_unavailable/);
  }
  const hanging = requestFixture({ hang: true });
  await assert.rejects(probeReady('https://workspace.example/api/ready', { ...hanging, timeoutMs: 10 }));
  assert.equal(hanging.destroyed(), true);
});

test('administration is inert by default and requires explicit single-email deletion confirmation', async () => {
  const result = await admin.run([], { env: {}, createClient: () => assert.fail('help must not connect') });
  assert.match(result.help, /--confirm-delete/);
  assert.deepEqual(admin.parseArgs(['delete', '--email', ' PERSON@EXAMPLE.COM ', '--confirm-delete']), { command: 'delete', email: BODY.email });
  for (const args of [['delete'], ['delete', '--email', BODY.email], ['delete', '--email', '*', '--confirm-delete'],
    ['delete', '--email', BODY.email, '--confirm-delete', '--all'], ['bootstrap'], ['export']]) assert.throws(() => admin.parseArgs(args));
});

test('CSV neutralizes formula cells and quotes untrusted separators/newlines', () => {
  for (const value of ['=CMD()', '+SUM(1,1)', '-10+1', '@SUM(A1)', '  =FORMULA()', '\tvalue', '\nvalue']) {
    assert.ok(admin.csvCell(value).startsWith('"\''));
  }
  assert.equal(admin.csvCell('team,"name"\nnext'), '"team,""name""\nnext"');
});

test('operator export excludes expired records and writes private new file; deletion is narrowly filtered', async () => {
  const writes = [];
  let query;
  let closed = false;
  const rows = [{ ...interestRecord(validateInterest(BODY), NOW), name: '=DANGEROUS()' }];
  const cursor = { sort() { return this; }, batchSize() { return this; }, async *[Symbol.asyncIterator]() { yield* rows; }, close: async () => {} };
  const db = { collection: () => ({ find(filter) { query = filter; return cursor; } }) };
  const fs = { open: async (path, flags, mode) => {
    assert.equal(path, 'private.csv'); assert.equal(flags, 'wx'); assert.equal(mode, 0o600);
    return { writeFile: async text => writes.push(text), close: async () => { closed = true; } };
  } };
  assert.deepEqual(await admin.exportContacts(db, 'private.csv', NOW, fs), { exported: 1 });
  assert.deepEqual(query, { expiresAt: { $gt: NOW } });
  assert.ok(writes[1].startsWith('"\'=DANGEROUS()"'));
  assert.equal(closed, true);
  const env = { SILLAGE_INTEREST_DB: 'sillage_interest_fixture', SILLAGE_INTEREST_MONGO_URL: 'mongodb+srv://synthetic.example/db' };
  let filter;
  let clientClosed = false;
  const createClient = () => ({ db: () => ({ collection: () => ({ deleteOne: async value => { filter = value; return { acknowledged: true, deletedCount: 1 }; } }) }),
    close: async () => { clientClosed = true; } });
  assert.deepEqual(await admin.run(['delete', '--email', BODY.email, '--confirm-delete'], { env, createClient }), { deleted: 1 });
  assert.deepEqual(filter, { _id: BODY.email });
  assert.equal(clientClosed, true);
});

test('deployable API entrypoints are callable without database configuration or installed database imports', () => {
  assert.equal(typeof require('../api/interest.js'), 'function');
  assert.equal(typeof require('../api/availability.js'), 'function');
});
