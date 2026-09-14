import { useState } from 'react';
import { ArrowLeft, ArrowRight, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GuardianWordmark } from '@/pages/GuardianWelcome';

export default function ConnectScreen({ authMode = 'api_key', onLogin, onConnect, checking = false, error = '' }) {
  const [key, setKey] = useState('');
  const connect = event => { event.preventDefault(); if (key.trim() && !checking) onConnect(key.trim()); };
  return <main className="cg-signin">
    <section className="cg-signin-story"><a href="/welcome" aria-label="Product home"><GuardianWordmark /></a><div><span className="cg-eyebrow">A CLEARER VIEW OF YOUR AI</span><h1>Pick up where you left off.</h1><p>Open your workspace to follow recent calls, review incidents and check your connections.</p><ul><li><Check size={16} />See calls across models</li><li><Check size={16} />Investigate slow and failed requests</li><li><Check size={16} />Keep missing costs visible</li></ul><a href="/demo">Explore the sample workspace <ArrowRight size={17} /></a></div><small>Numeric telemetry. No model-provider key required.</small></section>
    <section className="cg-signin-form"><div><a className="cg-back-link" href="/welcome"><ArrowLeft size={14} /> Product home</a><span className="cg-eyebrow">WORKSPACE ACCESS</span><h2>Welcome to your workspace.</h2><p>{authMode === 'oidc' ? 'Sign in first. Then connect your app and verify its first real call in Connections.' : 'Open your configured workspace to inspect its application activity and connection status.'}</p>
      {authMode === 'oidc' ? <div><Button className="w-full mt-7" onClick={onLogin}>Sign in with your organization</Button>{error && <p role="alert" className="text-sm text-danger-700 mt-3">{error}</p>}<div className="cg-access-note"><strong>Joining for the first time?</strong><p>Ask your workspace owner to add your organization account. Workspace access is currently managed by the owner; public account registration is not available yet.</p></div></div> : <form onSubmit={connect}>
        <label className="text-sm font-medium block mt-6 mb-2" htmlFor="api-key">Workspace access key</label><Input id="api-key" type="password" value={key} onChange={event => setKey(event.target.value)} placeholder="Workspace access key" autoFocus disabled={checking} autoComplete="off" /><p className="text-xs text-ink-500 mt-2">Use the access key supplied with this deployment. It opens the dashboard for its configured Langfuse source. This is not a model-provider key.</p>{error && <p role="alert" className="text-sm text-danger-700 mt-3">{error}</p>}<Button type="submit" className="w-full mt-5" disabled={!key.trim() || checking}>{checking ? 'Connecting...' : 'Connect'}</Button><div className="cg-access-note"><strong>Local deployment access</strong><p>Direct application capture requires an isolated workspace with organization sign-in. Ask your workspace owner to configure that deployment.</p></div>
      </form>}<p className="cg-signin-footnote">Just looking around? <a href="/demo">Try the interactive demo</a> without an account.</p></div></section>
  </main>;
}
