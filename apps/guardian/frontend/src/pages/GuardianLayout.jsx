import { Link, useLocation } from 'react-router-dom';
import { clearApiKey } from '@/services/guardianApi';
import { Button } from '@/components/ui/button';
import { ShieldAlert, LayoutDashboard, AlertTriangle, LogOut } from 'lucide-react';

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, exact: true },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
];

/** Small "data is moving" affordance for the header.
 *
 * Worth the pixels because a dashboard that is quietly polling looks identical to one
 * that has silently stopped -- and on an incident dashboard, "no incidents" and "not
 * updating" must never look the same. */
const LiveIndicator = ({ refreshing, lastUpdated }) => {
  if (!lastUpdated) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500" title="Auto-refreshing">
      <span
        className={`h-2 w-2 rounded-full ${
          refreshing ? 'bg-emerald-500 animate-pulse' : 'bg-emerald-500'
        }`}
      />
      <span>
        Live &middot; updated{' '}
        {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
      </span>
    </div>
  );
};

const GuardianLayout = ({ children, refreshing, lastUpdated }) => {
  const location = useLocation();

  const isActive = (item) =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert className="h-6 w-6 text-slate-900" />
            <div>
              <h1 className="text-lg font-semibold text-slate-900 leading-tight">Cost Guardian</h1>
              <p className="text-xs text-slate-500">AI reliability &amp; incident intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <LiveIndicator refreshing={refreshing} lastUpdated={lastUpdated} />
            {/* Guardian is standalone -- there is no "parent" app to go back to.
                Disconnecting just clears the stored API key. */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                clearApiKey();
                window.location.reload();
              }}
            >
              <LogOut className="h-4 w-4 mr-1" />
              Disconnect
            </Button>
          </div>
        </div>
        <nav className="max-w-6xl mx-auto px-6 flex gap-1">
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
