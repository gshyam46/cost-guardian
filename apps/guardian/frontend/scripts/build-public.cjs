'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const CONFIG_FILES = ['package.json', 'package-lock.json', 'craco.config.js',
  'tailwind.config.js', 'postcss.config.js', 'jsconfig.json'];
const SOURCE_EXTENSIONS = new Set(['.js', '.jsx', '.css', '.html', '.json', '.svg',
  '.png', '.ico', '.webp', '.woff', '.woff2', '.ttf', '.txt']);
const SYSTEM_KEYS = new Set(['PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC',
  'PATHEXT', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL']);

function publicEnvironment(environment, output) {
  const result = Object.fromEntries(Object.entries(environment)
    .filter(([key]) => SYSTEM_KEYS.has(key.toUpperCase())));
  const contact = environment.REACT_APP_PRIVACY_CONTACT_EMAIL;
  if (contact !== undefined && contact !== '') {
    if (typeof contact !== 'string' || contact.length > 254
        || !/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$/.test(contact)) {
      throw new Error('invalid_public_privacy_contact');
    }
    result.REACT_APP_PRIVACY_CONTACT_EMAIL = contact;
  }
  return Object.assign(result, { CI: 'true', NODE_ENV: 'production',
    REACT_APP_PUBLIC_SITE: 'true', REACT_APP_GUARDIAN_URL: '/',
    GENERATE_SOURCEMAP: 'false', DISABLE_HOT_RELOAD: 'true',
    REACT_APP_ENABLE_VISUAL_EDITS: 'false', ENABLE_HEALTH_CHECK: 'false',
    BUILD_PATH: output });
}

function regularTree(filename) {
  const info = fs.lstatSync(filename);
  if (info.isSymbolicLink() || (!info.isFile() && !info.isDirectory())) {
    throw new Error('unsupported_public_build_path');
  }
  if (info.isDirectory()) {
    for (const name of fs.readdirSync(filename)) regularTree(path.join(filename, name));
  }
}

function copyInput(source, destination) {
  const info = fs.lstatSync(source);
  if (info.isSymbolicLink()) throw new Error('unsupported_public_build_input');
  if (info.isDirectory()) {
    fs.mkdirSync(destination, { recursive: true });
    for (const name of fs.readdirSync(source)) {
      // Hidden/local configuration is never read, including nested .env files.
      if (name.startsWith('.') || name === 'node_modules' || name === 'build') continue;
      copyInput(path.join(source, name), path.join(destination, name));
    }
  } else {
    if (!info.isFile() || !SOURCE_EXTENSIONS.has(path.extname(source).toLowerCase())) {
      throw new Error('unsupported_public_build_input');
    }
    fs.copyFileSync(source, destination);
  }
}

function buildPublic(root, environment = process.env) {
  const project = fs.realpathSync(root);
  const output = path.join(project, 'build');
  const env = publicEnvironment(environment, output);
  // CRA clears this exact output directory. Never follow a linked output tree.
  try { regularTree(output); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const temporaryRoot = fs.realpathSync(os.tmpdir());
  const stage = fs.mkdtempSync(path.join(temporaryRoot, 'sillage-public-build-'));
  try {
    for (const name of CONFIG_FILES) copyInput(path.join(project, name), path.join(stage, name));
    for (const name of ['src', 'public']) copyInput(path.join(project, name), path.join(stage, name));
    // Link packages individually: a real staging node_modules keeps CRA's
    // Webpack/ESLint caches away from the installed dependency directory.
    const dependencies = path.join(project, 'node_modules');
    const stageDependencies = path.join(stage, 'node_modules');
    fs.mkdirSync(stageDependencies);
    for (const entry of fs.readdirSync(dependencies, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      if (!entry.isDirectory()) throw new Error('unsupported_public_build_dependency');
      fs.symlinkSync(path.join(dependencies, entry.name), path.join(stageDependencies, entry.name),
        process.platform === 'win32' ? 'junction' : 'dir');
    }
    const craco = require.resolve('@craco/craco/package.json', { paths: [project] });
    const metadata = JSON.parse(fs.readFileSync(craco, 'utf8'));
    const executable = path.resolve(path.dirname(craco), metadata.bin.craco);
    const result = spawnSync(process.execPath, [executable, 'build'],
      { cwd: stage, env, stdio: 'inherit', timeout: 180000, windowsHide: true });
    if (result.error || result.status !== 0) throw new Error('public_build_failed');
    if (!fs.existsSync(path.join(output, 'index.html'))) throw new Error('public_build_output_missing');
    return output;
  } finally {
    // This directory is generated above, never supplied by a caller. unlink the
    // dependency links before deleting the staging tree on Windows.
    if (path.dirname(stage) !== temporaryRoot || !path.basename(stage).startsWith('sillage-public-build-')) {
      throw new Error('invalid_public_build_cleanup');
    }
    const links = path.join(stage, 'node_modules');
    if (fs.existsSync(links)) {
      for (const entry of fs.readdirSync(links, { withFileTypes: true })) {
        const candidate = path.join(links, entry.name);
        if (fs.lstatSync(candidate).isSymbolicLink()) fs.unlinkSync(candidate);
      }
    }
    const resolvedStage = fs.realpathSync(stage);
    if (resolvedStage !== stage || path.dirname(resolvedStage) !== temporaryRoot) {
      throw new Error('invalid_public_build_cleanup');
    }
    fs.rmSync(resolvedStage, { recursive: true, force: true });
  }
}

if (require.main === module) {
  try {
    buildPublic(path.resolve(__dirname, '..'));
    process.stdout.write('Sillage public frontend built in build/.\n');
  } catch (error) {
    const codes = new Set(['invalid_public_privacy_contact', 'unsupported_public_build_path',
      'unsupported_public_build_input', 'unsupported_public_build_dependency',
      'public_build_failed', 'public_build_output_missing', 'invalid_public_build_cleanup']);
    process.stderr.write((codes.has(error.message) ? error.message : 'public_build_failed') + '\n');
    process.exitCode = 1;
  }
}

module.exports = { buildPublic, publicEnvironment };
