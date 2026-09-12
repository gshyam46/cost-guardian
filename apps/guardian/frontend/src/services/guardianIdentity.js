const objectWith = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const label = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= 512
  && !/[\u0000-\u001f\u007f]/.test(value);

export const validAuthConfig = (body) => objectWith(body, ['auth_mode', 'login_path'])
  && ((body.auth_mode === 'api_key' && body.login_path === null)
    || (body.auth_mode === 'oidc' && body.login_path === '/api/guardian/auth/login'));

export const validSessionOrigin = (apiUrl, uiUrl) => {
  try {
    const ui = new URL(uiUrl);
    const api = new URL(apiUrl, ui);
    const loopback = (url) => ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && ['http:', 'https:'].includes(url.protocol);
    return !api.username && !api.password && api.pathname === '/' && !api.search && !api.hash
      && ((loopback(api) && loopback(ui)) || (api.origin === ui.origin && api.protocol === 'https:'));
  } catch { return false; }
};

export const validAccess = (body, mode = 'api_key') => {
  const keys = ['authenticated', 'auth_mode', 'deployment_mode', 'permissions'];
  if (mode === 'oidc') keys.push('actor', 'project', 'csrf_token');
  if (!objectWith(body, keys) || body.authenticated !== true || body.auth_mode !== mode
      || body.deployment_mode !== 'single_project' || !Array.isArray(body.permissions)) return false;
  let expected = ['read', 'resolve_incidents'];
  if (mode === 'oidc') {
    if (!objectWith(body.actor, ['id', 'name', 'role']) || !label(body.actor.id) || !label(body.actor.name)
        || !['owner', 'operator', 'viewer'].includes(body.actor.role)
        || !objectWith(body.project, ['organization_id', 'project_id', 'environment', 'name'])
        || !Object.values(body.project).every(label)
        || typeof body.csrf_token !== 'string' || !/^[A-Za-z0-9_-]{32,256}$/.test(body.csrf_token)) return false;
    if (body.actor.role === 'viewer') expected = ['read'];
  }
  return body.permissions.length === expected.length && body.permissions.every((permission, index) => permission === expected[index]);
};

// A return target is only a known application pathname, never a URL or query.
export const safeReturnPath = (value) => {
  if (typeof value !== 'string' || value.length > 2048 || /[\\?#\u0000-\u0020\u007f]/.test(value)) return '/';
  let decoded;
  try { decoded = decodeURIComponent(value); } catch { return '/'; }
  if (/[\\%?#\u0000-\u0020\u007f]/.test(decoded) || decoded.includes('//')) return '/';
  return /^(\/|\/live|\/setup|\/incidents|\/incidents\/[^/.][^/]*|\/runs\/[^/.][^/]*)$/.test(decoded) ? value : '/';
};

const RETURN_PATH = 'guardian_login_return';
export const beginLogin = (url, { preserveReturn = false } = {}) => {
  try {
    const path = preserveReturn ? safeReturnPath(sessionStorage.getItem(RETURN_PATH)) : safeReturnPath(window.location.pathname);
    sessionStorage.setItem(RETURN_PATH, path);
  } catch { /* Root remains a safe fallback. */ }
  window.location.assign(url);
};
export const restoreLoginPath = () => {
  let path = '/';
  try { path = safeReturnPath(sessionStorage.getItem(RETURN_PATH)); sessionStorage.removeItem(RETURN_PATH); } catch { /* No session secret is stored here. */ }
  window.history.replaceState({}, '', path);
};
