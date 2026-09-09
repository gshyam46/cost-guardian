import { useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import guardianApi, { setApiKey } from '@/services/guardianApi';

/**
 * Guardian's own sign-in. It is a standalone service, so it can't reuse a monitored
 * application's session -- the operator supplies Guardian's API key directly. The key
 * is validated against the API before being stored, so a wrong key fails here rather
 * than turning into confusing 401s on every page.
 */
const ConnectScreen = ({ onConnected }) => {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  const connect = async (event) => {
    event.preventDefault();
    setChecking(true);
    setError('');
    setApiKey(key.trim());
    try {
      await guardianApi.getOverview();
      onConnected();
    } catch (err) {
      const status = err?.response?.status;
      setError(
        status === 401
          ? 'That key was rejected by the Guardian API.'
          : status === 503
          ? 'Guardian has no API key configured yet — set GUARDIAN_API_KEY in apps/guardian/backend/.env'
          : 'Could not reach the Guardian API. Is it running on port 8001?'
      );
    } finally {
      setChecking(false);
    }
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

          <form onSubmit={connect}>
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
            />
            <p className="text-xs text-slate-400 mt-2">
              Found in <code>apps/guardian/backend/.env</code> as <code>GUARDIAN_API_KEY</code>.
            </p>
            {error && <p className="text-sm text-red-600 mt-3">{error}</p>}
            <Button type="submit" className="w-full mt-5" disabled={!key.trim() || checking}>
              {checking ? 'Connecting...' : 'Connect'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

export default ConnectScreen;
