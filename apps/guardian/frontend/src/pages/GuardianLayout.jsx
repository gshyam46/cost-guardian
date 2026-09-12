import { Link, useLocation } from 'react-router-dom';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import { Button } from '@/components/ui/button';
import { ShieldAlert, LayoutDashboard, AlertTriangle, LogOut, Activity, Settings } from 'lucide-react';

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, exact: true },
  { to: '/live', label: 'Live activity', icon: Activity },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
  { to: '/setup', label: 'Setup', icon: Settings },
];

/** Receipt of an API response is distinct from source freshness or worker health. */
const ApiCheckIndicator = ({ refreshing, lastUpdated }) => {
  if (!lastUpdated) return null;
  return (
    <div className="flex items-center gap-2 whitespace-nowrap text-xs text-slate-500" title="Last dashboard API response; source freshness is shown with the data">
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${
          refreshing ? 'bg-slate-400 animate-pulse' : 'bg-slate-400'
        }`}
      />
      <span>
        API checked &middot;{' '}
        {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
      </span>
    </div>
  );
};

const GuardianLayout = ({ children, refreshing, lastUpdated }) => {
  const location = useLocation();
  const access = useGuardianAccess();

  const isActive = (item) =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="min-w-0 flex flex-1 items-center gap-3">
            <ShieldAlert className="h-6 w-6 shrink-0 text-slate-900" />
            <div>
              <h1 className="text-lg font-semibold text-slate-900 leading-tight">Cost Guardian</h1>
              <p className="text-xs text-slate-500">AI reliability &amp; incident intelligence</p>
            </div>
          </div>
          {lastUpdated && <div className="order-3 w-full sm:order-none sm:w-auto">
            <ApiCheckIndicator refreshing={refreshing} lastUpdated={lastUpdated} />
          </div>}
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={access.disconnect}
            title={access.auth_mode === 'oidc' ? 'Sign out of this Guardian session. Monitoring continues.' : 'Disconnect this browser. Monitoring continues; the server key is not revoked.'}
          >
            <LogOut className="h-4 w-4 mr-1" />
            {access.auth_mode === 'oidc' ? 'Sign out' : 'Disconnect'}
          </Button>
        </div>
        {access.auth_mode === 'oidc' && <div className="max-w-6xl mx-auto px-6 pb-3 text-xs text-slate-600 break-words">
          <p>{access.actor.name} · {access.actor.role}</p>
          <p>{access.project.name} · {access.project.environment} · Organization: {access.project.organization_id}</p>
        </div>}
        <nav className="max-w-6xl mx-auto px-6 flex flex-wrap gap-1" aria-label="Guardian">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-2 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
                  isActive(item)
                    ? 'border-slate-900 text-slate-900 font-medium'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
};

export default GuardianLayout;
