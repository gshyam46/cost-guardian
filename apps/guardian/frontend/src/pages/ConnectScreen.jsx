import { useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';

const ConnectScreen = ({ authMode = 'api_key', onLogin, onConnect, checking = false, error = '' }) => {
  const [key, setKey] = useState('');

  const connect = (event) => {
    event.preventDefault();
    if (key.trim() && !checking) onConnect(key.trim());
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6">
      <Card className="w-full max-w-md">
        <CardContent className="pt-8 pb-6">
          <div className="flex items-center gap-3 mb-6">
            <ShieldAlert className="h-7 w-7 text-slate-900" />
            <div>
              <h1 className="text-lg font-semibold text-slate-900 leading-tight">Cost Guardian</h1>
              <p className="text-xs text-slate-500">AI reliability &amp; incident intelligence</p>
            </div>
          </div>

          <p className="text-sm text-slate-600 mb-5">Connect to inspect captured AI usage and incident evidence.
            Access does not start monitoring; source setup and application instrumentation are separate.</p>
          {authMode === 'oidc' ? <div>
            <p className="text-sm text-slate-600">Sign in with your organization account. Your Guardian operator manages project membership and permissions.</p>
            {error && <p role="alert" className="text-sm text-red-600 mt-3">{error}</p>}
            <Button className="w-full mt-5" onClick={onLogin}>Sign in with your organization</Button>
          </div> : <form onSubmit={connect}>
            <label className="text-sm text-slate-700 block mb-2" htmlFor="api-key">
              Guardian API key
            </label>
            <Input
              id="api-key"
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="gk_..."
              autoFocus
              disabled={checking}
              autoComplete="off"
            />
            <p className="text-xs text-slate-400 mt-2">
              Use the access key supplied by your Guardian operator. This is not a model-provider key or an ingestion token.
            </p>
            {error && <p role="alert" className="text-sm text-red-600 mt-3">{error}</p>}
            <Button type="submit" className="w-full mt-5" disabled={!key.trim() || checking}>
              {checking ? 'Connecting...' : 'Connect'}
            </Button>
          </form>}
        </CardContent>
      </Card>
    </div>
  );
};

export default ConnectScreen;
