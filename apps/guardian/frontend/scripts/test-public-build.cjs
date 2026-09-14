'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { buildPublic, publicEnvironment } = require('./build-public.cjs');

test('public build strips ambient credentials and application settings; only validated contact survives', () => {
  const environment = publicEnvironment({ PATH: process.env.PATH,
    SILLAGE_INTEREST_MONGO_URL: 'synthetic-private-canary',
    REACT_APP_PROVIDER_KEY: 'synthetic-browser-canary', NODE_OPTIONS: '--inspect',
    REACT_APP_GUARDIAN_URL: 'https://wrong.example', REACT_APP_PUBLIC_SITE: 'false',
    GENERATE_SOURCEMAP: 'true', REACT_APP_ENABLE_VISUAL_EDITS: 'true',
    REACT_APP_PRIVACY_CONTACT_EMAIL: 'privacy@example.test' }, '/fixture/build');
  assert.equal(environment.REACT_APP_PUBLIC_SITE, 'true');
  assert.equal(environment.REACT_APP_GUARDIAN_URL, '/');
  assert.equal(environment.GENERATE_SOURCEMAP, 'false');
  assert.equal(environment.REACT_APP_ENABLE_VISUAL_EDITS, 'false');
  assert.equal(environment.REACT_APP_PRIVACY_CONTACT_EMAIL, 'privacy@example.test');
  assert.equal(environment.BUILD_PATH, '/fixture/build');
  for (const key of ['SILLAGE_INTEREST_MONGO_URL', 'REACT_APP_PROVIDER_KEY', 'NODE_OPTIONS']) {
    assert.equal(Object.hasOwn(environment, key), false);
  }
});

test('invalid public contact fails before compiling and does not appear in the error', () => {
  for (const value of ['mailto:privacy@example.test', 'person@example.test\n', '<private-value>', 'x'.repeat(255)]) {
    assert.throws(() => publicEnvironment({ REACT_APP_PRIVACY_CONTACT_EMAIL: value }, '/fixture/build'),
      { message: 'invalid_public_privacy_contact' });
  }
});

test('Vercel routes only public pages to HTML and preserves independent function routes', () => {
  const root = path.resolve(__dirname, '..');
  const config = JSON.parse(fs.readFileSync(path.join(root, 'vercel.json'), 'utf8'));
  assert.equal(config.buildCommand, 'npm run build:public');
  assert.equal(config.outputDirectory, 'build');
  assert.deepEqual(config.rewrites.map((rule) => rule.source),
    ['/', '/welcome', '/demo', '/signup', '/privacy', '/signin', '/setup']);
  assert.ok(config.rewrites.every((rule) => rule.destination === '/index.html'));
  assert.deepEqual(Object.keys(config.functions).sort(), ['api/availability.js', 'api/interest.js']);
  assert.equal(config.headers[0].source, '/api/:path*');
  assert.ok(config.headers[0].headers.some((header) => header.key === 'Cache-Control' && header.value === 'no-store'));
  const scripts = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).scripts;
  assert.equal(scripts.build, 'craco build');
  assert.equal(scripts['build:public'], 'node scripts/build-public.cjs');
});

test('deployment ignore rules omit local secrets and generated files while retaining function/build inputs', () => {
  const ignore = require('ignore')().add(fs.readFileSync(path.resolve(__dirname, '../.vercelignore'), 'utf8'));
  for (const name of ['.env', '.env.production', 'src/.env.local', '.cache/private.json',
    '.vercel/project.json', 'node_modules/mongodb/lib/index.js', 'build/static/js/main.js',
    'coverage/report.json', 'operator.pem']) assert.equal(ignore.ignores(name), true, name);
  for (const name of ['vercel.json', 'package-lock.json', 'scripts/build-public.cjs',
    'api/interest.js', 'api/availability.js', 'server/contract.cjs', 'src/App.js', 'public/index.html']) {
    assert.equal(ignore.ignores(name), false, name);
  }
});

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sillage-public-build-test-'));
  t.after(() => {
    assert.equal(path.dirname(root), os.tmpdir());
    assert.ok(path.basename(root).startsWith('sillage-public-build-test-'));
    fs.rmSync(root, { recursive: true, force: true });
  });
  for (const name of ['src', 'public', 'api', 'node_modules/@craco/craco/dist/bin']) {
    fs.mkdirSync(path.join(root, name), { recursive: true });
  }
  for (const name of ['package.json', 'package-lock.json', 'craco.config.js',
    'tailwind.config.js', 'postcss.config.js', 'jsconfig.json']) fs.writeFileSync(path.join(root, name), '{}');
  fs.writeFileSync(path.join(root, 'src/index.js'), 'window.example = true;');
  fs.writeFileSync(path.join(root, 'public/index.html'), '<main>Public fixture</main>');
  fs.writeFileSync(path.join(root, '.env'), 'REACT_APP_PROVIDER_KEY=synthetic-dotenv-canary');
  fs.writeFileSync(path.join(root, 'src/.env.local'), 'synthetic-nested-canary');
  fs.writeFileSync(path.join(root, 'api/interest.js'), 'synthetic-server-canary');
  fs.writeFileSync(path.join(root, 'node_modules/@craco/craco/package.json'), JSON.stringify({
    name: '@craco/craco', bin: { craco: './dist/bin/craco.js' },
  }));
  fs.writeFileSync(path.join(root, 'node_modules/@craco/craco/dist/bin/craco.js'), `
    const fs = require('node:fs'); const path = require('node:path');
    if (fs.existsSync('.env') || fs.existsSync('src/.env.local') || fs.existsSync('api')) process.exit(2);
    if (process.env.REACT_APP_PROVIDER_KEY || process.env.SILLAGE_INTEREST_MONGO_URL) process.exit(3);
    fs.mkdirSync('node_modules/.cache', {recursive: true});
    fs.writeFileSync('node_modules/.cache/build-only.txt', 'synthetic-cache');
    fs.mkdirSync(process.env.BUILD_PATH, {recursive: true});
    fs.writeFileSync(path.join(process.env.BUILD_PATH, 'index.html'), process.env.REACT_APP_PUBLIC_SITE);
  `);
  return root;
}

test('real child build receives clean staged sources and leaves dependency directory unchanged', (t) => {
  const root = fixture(t);
  const output = buildPublic(root, { PATH: process.env.PATH,
    SILLAGE_INTEREST_MONGO_URL: 'synthetic-private-canary',
    REACT_APP_PROVIDER_KEY: 'synthetic-browser-canary' });
  assert.equal(output, path.join(root, 'build'));
  assert.equal(fs.readFileSync(path.join(output, 'index.html'), 'utf8'), 'true');
  assert.equal(fs.existsSync(path.join(root, 'node_modules/.cache')), false);
  assert.equal(fs.existsSync(path.join(root, '.env')), true);
  assert.equal(fs.existsSync(path.join(root, 'api/interest.js')), true);
});

test('a linked output is refused before the compiler can clear or write its target', (t) => {
  const root = fixture(t);
  const target = path.join(root, 'keep');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'sentinel.txt'), 'keep');
  const link = path.join(root, 'build');
  fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir');
  try {
    assert.throws(() => buildPublic(root, {}), { message: 'unsupported_public_build_path' });
    assert.equal(fs.readFileSync(path.join(target, 'sentinel.txt'), 'utf8'), 'keep');
  } finally { fs.unlinkSync(link); }
});
