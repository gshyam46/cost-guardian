#!/usr/bin/env node
'use strict';

const { normalizeEmail } = require('./contract.cjs');
const { connectionConfig, CLIENT_OPTIONS, COLLECTIONS, bootstrap } = require('./mongo.cjs');

const HELP = `Sillage early-access record administration (no workspace accounts).
Server-only environment: SILLAGE_INTEREST_MONGO_URL and SILLAGE_INTEREST_DB.
Use a dedicated interest database and restricted operator credential; TLS is required.
MongoDB Atlas or a replica set is required for public registration transactions.

node server/interest-admin.cjs --help
node server/interest-admin.cjs bootstrap --confirm-bootstrap
node server/interest-admin.cjs export --output <new-private-file.csv>
node server/interest-admin.cjs delete --email <single-email> --confirm-delete

Bootstrap creates TTL/index metadata; it does not provision a hosted database.
Export contains personal data, excludes expired records, and refuses to overwrite files.
Delete removes exactly one normalized email. No wildcard or bulk deletion exists.
`;

function parseArgs(argv) {
  if (argv.length === 0 || (argv.length === 1 && ['--help', '-h'].includes(argv[0]))) return { command: 'help' };
  if (argv.length === 2 && argv[0] === 'bootstrap' && argv[1] === '--confirm-bootstrap') return { command: 'bootstrap' };
  if (argv.length === 3 && argv[0] === 'export' && argv[1] === '--output' && argv[2] && !argv[2].startsWith('-')) {
    return { command: 'export', output: argv[2] };
  }
  if (argv.length === 4 && argv[0] === 'delete' && argv[1] === '--email' && argv[3] === '--confirm-delete') {
    return { command: 'delete', email: normalizeEmail(argv[2]) };
  }
  throw new Error('invalid_arguments');
}

function csvCell(value) {
  let text = value instanceof Date ? value.toISOString() : String(value ?? '');
  if (/^[\s\uFEFF]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

async function exportContacts(db, output, now = new Date(), fs = require('node:fs/promises')) {
  const columns = ['name', 'email', 'company', 'use_case', 'source', 'verified', 'createdAt', 'expiresAt', 'consent_version', 'consent_acceptedAt'];
  const file = await fs.open(output, 'wx', 0o600);
  let cursor;
  let count = 0;
  try {
    await file.writeFile(`${columns.map(csvCell).join(',')}\r\n`);
    cursor = db.collection(COLLECTIONS.contacts).find({ expiresAt: { $gt: now } }, { timeoutMS: 4000, timeoutMode: 'iteration' })
      .sort({ createdAt: 1, _id: 1 }).batchSize(100);
    for await (const row of cursor) {
      const values = columns.map(column => column === 'consent_version' ? row.consent?.version :
        column === 'consent_acceptedAt' ? row.consent?.acceptedAt : row[column]);
      await file.writeFile(`${values.map(csvCell).join(',')}\r\n`);
      count += 1;
    }
    return { exported: count };
  } finally {
    await cursor?.close();
    await file.close();
  }
}

async function run(argv, { env = process.env, createClient, fs, now } = {}) {
  const args = parseArgs(argv);
  if (args.command === 'help') return { help: HELP };
  const config = connectionConfig(env);
  const client = createClient ? createClient(config.uri, CLIENT_OPTIONS) : new (require('mongodb').MongoClient)(config.uri, CLIENT_OPTIONS);
  try {
    if (args.command === 'bootstrap') return await bootstrap(client, config.dbName);
    const db = client.db(config.dbName);
    if (args.command === 'export') return await exportContacts(db, args.output, now?.() || new Date(), fs);
    const result = await db.collection(COLLECTIONS.contacts).deleteOne({ _id: args.email }, { timeoutMS: 4000, writeConcern: { w: 'majority', journal: true } });
    if (result.acknowledged !== true || ![0, 1].includes(result.deletedCount)) throw new Error('operation_failed');
    return { deleted: result.deletedCount };
  } finally { await client.close(); }
}

if (require.main === module) {
  run(process.argv.slice(2)).then(result => {
    process.stdout.write(result.help || `${JSON.stringify(result)}\n`);
  }).catch(() => {
    process.stderr.write('Interest administration failed. Check arguments, database access and configuration.\n');
    process.exitCode = 1;
  });
}

module.exports = { HELP, parseArgs, csvCell, exportContacts, run };
