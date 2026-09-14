'use strict';

const { PublicError, RETENTION_DAYS } = require('./contract.cjs');

const COLLECTIONS = Object.freeze({ contacts: 'interest_contacts', rates: 'interest_rate_limits', schema: 'interest_schema' });
const CLIENT_OPTIONS = Object.freeze({ maxPoolSize: 3, minPoolSize: 0, maxConnecting: 1, maxIdleTimeMS: 60000,
  connectTimeoutMS: 2000, serverSelectionTimeoutMS: 2000, socketTimeoutMS: 4000, waitQueueTimeoutMS: 1000,
  timeoutMS: 4000, retryWrites: true, readPreference: 'primary', readConcern: { level: 'majority' },
  writeConcern: { w: 'majority', journal: true } });
const POOL_KEY = Symbol.for('sillage.public-interest.pool.v1');

function unavailable() { return new PublicError('registration_unavailable', 503, 30); }

function databaseName(value) {
  if (typeof value !== 'string' || !/^[a-zA-Z][a-zA-Z0-9_-]{0,62}$/.test(value) || ['admin', 'config', 'local', 'test'].includes(value.toLowerCase())) throw unavailable();
  return value;
}

function connectionConfig(env) {
  const uri = env.SILLAGE_INTEREST_MONGO_URL;
  const dbName = databaseName(env.SILLAGE_INTEREST_DB);
  if (typeof uri !== 'string' || uri.length > 4096 || !/^mongodb(?:\+srv)?:\/\//.test(uri) || /[\r\n]/.test(uri)) throw unavailable();
  const query = new URLSearchParams(uri.split('?')[1] || '');
  let secure = uri.startsWith('mongodb+srv://');
  for (const [name, value] of query) {
    const key = name.toLowerCase();
    if ((key === 'tls' || key === 'ssl') && value !== 'true') throw unavailable();
    if ((key.includes('allowinvalid') || key === 'tlsinsecure') && value !== 'false') throw unavailable();
    if ((key === 'tls' || key === 'ssl') && value === 'true') secure = true;
  }
  if (!secure) throw unavailable();
  return { uri, dbName };
}

class MongoInterestStore {
  constructor(client, dbName) {
    this.client = client;
    this.db = client.db(databaseName(dbName));
  }

  async register(record, buckets) {
    const session = this.client.startSession();
    try {
      return await session.withTransaction(async () => {
        const options = { session };
        const schema = await this.db.collection(COLLECTIONS.schema).findOne({ _id: 'interest-v1' }, options);
        if (schema?.version !== 1 || schema?.retentionDays !== RETENTION_DAYS) throw unavailable();
        // The global reservations run first. A rejected transaction cannot create IP keys or contacts.
        for (const bucket of buckets) {
          const reserved = await this.db.collection(COLLECTIONS.rates).findOneAndUpdate({ _id: bucket.id },
            { $inc: { count: 1 }, $setOnInsert: { expiresAt: bucket.expiresAt } },
            { ...options, upsert: true, returnDocument: 'after', includeResultMetadata: false });
          if (!Number.isSafeInteger(reserved?.count) || reserved.count < 1) throw unavailable();
          if (reserved.count > bucket.limit) throw new PublicError('rate_limited', 429, bucket.retryAfter);
        }
        const contacts = this.db.collection(COLLECTIONS.contacts);
        const existing = await contacts.findOne({ _id: record._id }, options);
        if (!existing) {
          const result = await contacts.insertOne(record, options);
          if (result.acknowledged !== true) throw unavailable();
        } else if (existing.expiresAt instanceof Date && existing.expiresAt <= record.createdAt) {
          // A new consent after logical expiry starts a new retention period, even before TTL cleanup.
          const result = await contacts.replaceOne({ _id: record._id }, record, options);
          if (result.acknowledged !== true || result.matchedCount !== 1) throw unavailable();
        } else if (!(existing.expiresAt instanceof Date)) {
          throw unavailable();
        }
        // Existing, unexpired contacts keep their original details and consent unchanged.
        // Returning from this callback is not success until withTransaction acknowledges commit.
        return { acknowledged: true };
      }, { timeoutMS: 4000, readConcern: { level: 'snapshot' }, readPreference: 'primary',
        writeConcern: { w: 'majority', journal: true }, maxCommitTimeMS: 2000 });
    } finally { await session.endSession(); }
  }
}

function getStore(env = process.env) {
  const config = connectionConfig(env);
  let cached = globalThis[POOL_KEY];
  if (cached && (cached.uri !== config.uri || cached.dbName !== config.dbName)) throw unavailable();
  if (!cached) {
    const { MongoClient } = require('mongodb');
    const { attachDatabasePool } = require('@vercel/functions');
    const client = new MongoClient(config.uri, CLIENT_OPTIONS);
    attachDatabasePool(client);
    cached = { ...config, store: new MongoInterestStore(client, config.dbName) };
    globalThis[POOL_KEY] = cached;
  }
  return cached.store;
}

async function bootstrap(client, dbName) {
  const db = client.db(databaseName(dbName));
  const markers = db.collection(COLLECTIONS.schema);
  const supported = marker => marker?.version === 1 && marker?.retentionDays === RETENTION_DAYS;
  const existing = await markers.findOne({ _id: 'interest-v1' }, { timeoutMS: 4000 });
  if (existing && !supported(existing)) throw unavailable();
  const indexOptions = { name: 'interest_expiry_v1', expireAfterSeconds: 0, timeoutMS: 4000 };
  await db.collection(COLLECTIONS.contacts).createIndex({ expiresAt: 1 }, indexOptions);
  await db.collection(COLLECTIONS.rates).createIndex({ expiresAt: 1 }, indexOptions);
  await db.collection(COLLECTIONS.contacts).createIndex({ createdAt: 1, _id: 1 }, { name: 'interest_export_v1', timeoutMS: 4000 });
  const result = await markers.updateOne({ _id: 'interest-v1' },
    { $setOnInsert: { version: 1, retentionDays: RETENTION_DAYS } },
    { upsert: true, timeoutMS: 4000, writeConcern: { w: 'majority', journal: true } });
  if (result.acknowledged !== true) throw unavailable();
  // A concurrent operator may have created/upgraded the marker after the first read.
  // Never replace that marker or claim bootstrap succeeded for another schema.
  if (!supported(await markers.findOne({ _id: 'interest-v1' }, { timeoutMS: 4000 }))) throw unavailable();
  return { bootstrapped: true };
}

module.exports = { MongoInterestStore, getStore, bootstrap, connectionConfig, databaseName, CLIENT_OPTIONS, COLLECTIONS };
