import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import GuardianOverview from "@/pages/GuardianOverview";
import GuardianLive from "@/pages/GuardianLive";
import GuardianRunDetail from "@/pages/GuardianRunDetail";
import GuardianIncidents from "@/pages/GuardianIncidents";
import GuardianIncidentDetail from "@/pages/GuardianIncidentDetail";
import ConnectScreen from "@/pages/ConnectScreen";
import GuardianSetup from "@/pages/GuardianSetup";
import { Button } from "@/components/ui/button";
import guardianApi, { announceLogout, clearApiKey, clearSessionAccess, configureAuth, getApiKey, getLoginUrl, LOGOUT_NOTICE, setApiKey, setSessionAccess } from "@/services/guardianApi";
import { beginLogin, restoreLoginPath, validAccess, validAuthConfig } from '@/services/guardianIdentity';
import { GuardianAccessContext } from '@/contexts/GuardianAccess';

export { validAccess } from '@/services/guardianIdentity';

function App() {
  const [access, setAccess] = useState({ phase: 'checking', message: '' });
  const pending = useRef(null);
  const generation = useRef(0);
  const mode = useRef(null);
  const callbackComplete = useRef(false);
  const callbackFailed = useRef(false);
  const logoutIntent = useRef(false);

  const reset = useCallback((phase, message = '') => {
    generation.current += 1;
    pending.current?.abort();
    pending.current = null;
    setAccess({ phase, message });
  }, []);

  const check = useCallback(async (candidate, persist = false) => {
    const currentGeneration = ++generation.current;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const current = () => generation.current === currentGeneration && !controller.signal.aborted;
    setAccess({ phase: persist ? 'connecting' : 'checking', message: '' });
    try {
      const oidc = mode.current === 'oidc';
      const before = oidc ? null : getApiKey();
      const response = await guardianApi.getAccess(candidate, { signal: controller.signal });
      if (!current()) return;
      if (!validAccess(response.data, mode.current)) throw new Error('Invalid access response');
      // A storage event can be queued behind the network response. Do not save
      // an old candidate or mount content after another tab replaced the key.
      if (!oidc && getApiKey() !== before) {
        reset('unavailable', 'Browser access changed. Retry to verify the current key.');
        return;
      }
      if (oidc) {
        setSessionAccess(response.data);
        if (callbackComplete.current) { restoreLoginPath(); callbackComplete.current = false; }
      } else if (persist) setApiKey(candidate, { notify: false });
      const { csrf_token, ...identity } = response.data;
      setAccess({ phase: 'connected', message: '', identity });
    } catch (error) {
      if (!current()) return;
      if (error?.code === 'browser_storage_unavailable') {
        reset('storage_error', 'Browser storage is unavailable. Allow site storage, then retry.');
      } else if (error?.response?.status === 401) {
        if (mode.current === 'oidc') {
          clearSessionAccess();
          reset('disconnected', 'Sign in to continue to Guardian.');
          return;
        }
        try {
          if (!persist && getApiKey() === candidate) clearApiKey({ notify: false });
          reset('disconnected', 'That key was rejected by the Guardian API.');
        } catch {
          reset('storage_error', 'Browser storage is unavailable. Allow site storage, then retry.');
        }
      } else {
        setAccess({ phase: persist ? 'disconnected' : 'unavailable',
          message: 'Could not verify Guardian access. Retry when the service is available.' });
      }
    } finally {
      if (current()) pending.current = null;
    }
  }, [reset]);

  const restore = useCallback(() => {
    if (mode.current === 'oidc') { check(undefined); return; }
    try {
      const key = getApiKey();
      if (key) check(key);
      else reset('disconnected');
    } catch {
      reset('storage_error', 'Browser storage is unavailable. Allow site storage, then retry.');
    }
  }, [check, reset]);

  const disconnect = useCallback(async ({ revalidate = false } = {}) => {
    if (mode.current === 'oidc') {
      logoutIntent.current = true;
      reset('logging_out');
      const currentGeneration = generation.current;
      const controller = new AbortController();
      pending.current = controller;
      const current = () => generation.current === currentGeneration && !controller.signal.aborted;
      try {
        if (revalidate) {
          const response = await guardianApi.getAccess(undefined, { signal: controller.signal });
          if (!current()) return;
          if (!validAccess(response.data, 'oidc')) throw new Error('Session verification was not confirmed.');
          setSessionAccess(response.data);
        }
        const response = await guardianApi.logout({ signal: controller.signal });
        if (!current()) return;
        if (response.status !== 204) throw new Error('Logout was not confirmed.');
        clearSessionAccess();
        announceLogout();
        logoutIntent.current = false;
        reset('disconnected', 'Signed out of Guardian.');
      } catch (error) {
        if (!current()) return;
        if (error?.response?.status === 401) {
          clearSessionAccess();
          announceLogout();
          logoutIntent.current = false;
          reset('disconnected', 'The Guardian session has ended.');
        } else {
          setAccess({ phase: 'logout_failed', message: 'Could not confirm server sign-out. Your Guardian session may still be active. Retry sign-out.' });
        }
      }
      return;
    }
    try { clearApiKey(); }
    catch { reset('storage_error', 'Browser storage is unavailable. Allow site storage, then retry.'); }
  }, [reset]);

  const bootstrap = useCallback(async () => {
    reset('checking');
    mode.current = null;
    logoutIntent.current = false;
    const currentGeneration = generation.current;
    const controller = new AbortController();
    pending.current = controller;
    try {
      const response = await guardianApi.getAuthConfig({ signal: controller.signal });
      if (generation.current !== currentGeneration || controller.signal.aborted) return;
      if (!validAuthConfig(response.data)) throw new Error('Invalid authentication configuration.');
      configureAuth(response.data);
      mode.current = response.data.auth_mode;
      if (mode.current === 'oidc') {
        const marker = new URLSearchParams(window.location.search).get('guardian_login');
        if (marker === 'complete' || marker === 'failed') {
          window.history.replaceState({}, '', window.location.pathname);
          callbackComplete.current = marker === 'complete';
          callbackFailed.current = marker === 'failed';
          if (marker === 'failed') { reset('disconnected', 'Sign-in could not be completed. Try signing in again.'); return; }
        }
      }
      restore();
    } catch {
      if (generation.current === currentGeneration && !controller.signal.aborted) {
        reset('configuration_failed', 'Could not load Guardian sign-in configuration. Retry when the service is available.');
      }
    }
  }, [reset, restore]);

  useEffect(() => {
    const changed = (event) => {
      if (mode.current === 'oidc') {
        if (event.detail?.reason === 'session_rejected') reset('disconnected', 'Your Guardian session has ended. Sign in again to continue.');
        return;
      }
      if (!mode.current) return;
      if (event.detail?.reason === 'storage_error') reset('storage_error', 'Browser storage is unavailable. Allow site storage, then retry.');
      else if (event.detail?.reason === 'rejected') reset('disconnected', 'Access was rejected. Connect again to continue.');
      else if (event.detail?.reason === 'disconnected') reset('disconnected');
      else restore();
    };
    const storage = (event) => {
      if (mode.current === 'oidc') {
        if (event.key === LOGOUT_NOTICE && event.newValue) sessionChanged();
      } else if (mode.current === 'api_key' && (event.key === 'guardian_api_key' || event.key === null)) restore();
    };
    const sessionChanged = () => {
      if (mode.current !== 'oidc') return;
      clearSessionAccess();
      if (logoutIntent.current) reset('logout_failed', 'Browser session state changed. Retry sign-out to verify and end the current Guardian session.');
      else if (!callbackFailed.current) restore();
    };
    let channel;
    try {
      channel = new BroadcastChannel('guardian-session');
      channel.onmessage = (event) => { if (event.data?.type === 'logout') sessionChanged(); };
    } catch { /* Storage notification and focus remain available. */ }
    // Focus also covers browsers where cross-tab storage and BroadcastChannel are blocked.
    const focus = () => { if (mode.current === 'oidc' && !pending.current && !logoutIntent.current && !callbackFailed.current) restore(); };
    window.addEventListener('guardian-access-changed', changed);
    window.addEventListener('storage', storage);
    window.addEventListener('focus', focus);
    bootstrap();
    return () => {
      generation.current += 1;
      pending.current?.abort();
      window.removeEventListener('guardian-access-changed', changed);
      window.removeEventListener('storage', storage);
      window.removeEventListener('focus', focus);
      channel?.close();
    };
  }, [bootstrap, reset, restore]);

  if (['checking', 'unavailable', 'storage_error', 'configuration_failed', 'logging_out', 'logout_failed'].includes(access.phase)) {
    return <main className="min-h-screen bg-slate-50 flex items-center justify-center px-6">
      <div className="max-w-md rounded-lg border bg-white p-6">
        <h1 className="text-lg font-semibold mb-3">Cost Guardian</h1>
        {access.phase === 'checking' || access.phase === 'logging_out' ? <p role="status">{access.phase === 'logging_out' ? 'Signing out of Guardian...' : 'Checking Guardian access...'}</p> : <>
          <p role="alert" className="text-sm text-amber-900">{access.message}</p>
          <div className="flex gap-2 mt-4">
            {access.phase === 'logout_failed' ? <Button onClick={() => disconnect({ revalidate: true })}>Retry sign-out</Button>
              : <Button onClick={access.phase === 'configuration_failed' ? bootstrap : restore}>Retry access</Button>}
            {mode.current === 'api_key' && access.phase !== 'storage_error' && <Button variant="outline" onClick={disconnect}>Use a different key</Button>}
          </div>
        </>}
      </div>
    </main>;
  }

  if (access.phase !== 'connected') {
    return (
      <>
        <ConnectScreen authMode={mode.current} onLogin={() => beginLogin(getLoginUrl(), { preserveReturn: callbackComplete.current || callbackFailed.current })} onConnect={(candidate) => check(candidate, true)} checking={access.phase === 'connecting'} error={access.message} />
        <Toaster position="top-right" richColors />
      </>
    );
  }

  return (
    <GuardianAccessContext.Provider value={{ ...access.identity, disconnect }}><BrowserRouter>
      <Routes>
        <Route path="/" element={<GuardianOverview />} />
        <Route path="/live" element={<GuardianLive />} />
        <Route path="/runs/:traceId" element={<GuardianRunDetail />} />
        <Route path="/incidents" element={<GuardianIncidents />} />
        <Route path="/incidents/:incidentId" element={<GuardianIncidentDetail />} />
        <Route path="/setup" element={<GuardianSetup />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster position="top-right" richColors />
    </BrowserRouter></GuardianAccessContext.Provider>
  );
}

export default App;
