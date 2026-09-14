import { Link, useLocation } from 'react-router-dom';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import { Button } from '@/components/ui/button';
import { LayoutDashboard, AlertTriangle, LogOut, Activity, Cable, ArrowUpRight } from 'lucide-react';
import { GuardianWordmark } from '@/pages/GuardianWelcome';

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, exact: true },
  { to: '/live', label: 'Live activity', icon: Activity },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
  { to: '/setup', label: 'Connections', icon: Cable },
];

/** An API response is distinct from source freshness or worker health. */
const ApiCheckIndicator = ({ refreshing, lastUpdated }) => !lastUpdated ? null : (
  <div className="flex items-center gap-2 text-xs text-ink-500" title="Last dashboard API response; source freshness is shown with the data">
    <span className={`h-1.5 w-1.5 shrink-0 rounded-full bg-ink-400 ${refreshing ? 'animate-pulse' : ''}`} />
    <span>API checked &middot; {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
  </div>
);

export default function GuardianLayout({ children, refreshing, lastUpdated }) {
  const location = useLocation();
  const access = useGuardianAccess();
  const isActive = item => item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to);
  const page = NAV.find(isActive)?.label || 'Investigation';
  return <div className="cg-product">
    <aside className="cg-sidebar">
      <a href="/welcome" className="cg-sidebar-brand" aria-label="Product home"><GuardianWordmark /></a>
      <div className="cg-mobile-brand"><a href="/welcome"><GuardianWordmark /></a></div>
      <div className="cg-workspace"><span className="cg-eyebrow">WORKSPACE</span><strong>{access.project?.name || 'Your workspace'}</strong><span>{access.project?.environment || 'Application monitoring'}</span>{access.project && <small>Organization: {access.project.organization_id}</small>}</div>
      <nav aria-label="Sillage">{NAV.map(item => { const Icon = item.icon; return <Link key={item.to} to={item.to} aria-current={isActive(item) ? 'page' : undefined} className={isActive(item) ? 'active' : ''}><Icon size={17} />{item.label}</Link>; })}</nav>
      <div className="cg-sidebar-footer"><a href="/demo"><span>Explore sample workspace</span><ArrowUpRight size={15} /></a><p>Get familiar with a trace before connecting your app.</p>{access.actor && <div className="cg-account"><span className="cg-avatar" aria-hidden="true">{access.actor.name?.slice(0, 1) || 'W'}</span><span><strong>{access.actor.name}</strong><small>{access.actor.role}</small></span></div>}</div>
    </aside>
    <div className="cg-main-column">
      {access.auth_mode === 'oidc' && <div className="cg-mobile-context"><strong>{access.project.name} · {access.project.environment}</strong><span>{access.actor.name} · {access.actor.role}</span></div>}
      <header className="cg-app-topbar"><div className="cg-breadcrumb">Workspace <span>/</span> <strong>{page}</strong></div><div className="flex flex-wrap items-center gap-3"><ApiCheckIndicator refreshing={refreshing} lastUpdated={lastUpdated} /><Button variant="ghost" size="sm" onClick={() => access.disconnect()} title={access.auth_mode === 'oidc' ? 'Sign out of this workspace. Monitoring continues.' : 'Disconnect this browser. Monitoring continues; the server key is not revoked.'}><LogOut className="h-3.5 w-3.5 mr-1" />{access.auth_mode === 'oidc' ? 'Sign out' : 'Disconnect'}</Button></div></header>
      <main className="cg-content">{children}</main>
    </div>
  </div>;
}
