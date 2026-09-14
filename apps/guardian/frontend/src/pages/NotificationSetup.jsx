import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import guardianApi from '@/services/guardianApi';
import { deliveryStateText, outcomeText, validNotifications } from '@/lib/notificationModel';

const initial = (scope) => ({ scope, data: null, loading: true, action: null, mustRead: false, error: '', notice: '' });
export const NotificationTime = ({ value }) => value === null ? <>Not recorded</> : <time dateTime={value}>
  {new Date(value).toISOString().replace('T', ' ').replace('Z', ' UTC')}</time>;

export function useNotificationData(incidentId = null) {
  const access = useGuardianAccess();
  const scope = JSON.stringify([access.auth_mode, access.actor?.id, access.actor?.role, access.project, incidentId]);
  const [state, setState] = useState(() => initial(scope));
  const read = useRef(null), write = useRef(null), sequence = useRef(0), authority = useRef(access);
  authority.current = access;
  const load = useCallback(async () => {
    if (write.current) return;
    read.current?.abort();
    const controller = new AbortController(), request = ++sequence.current;
    read.current = controller;
    const current = () => sequence.current === request && !controller.signal.aborted;
    setState((previous) => ({ ...previous, loading: true, error: '', notice: '' }));
    try {
      const response = await guardianApi.getNotifications(incidentId, { signal: controller.signal });
      if (!current()) return;
      if (!validNotifications(response?.data, authority.current, incidentId)) throw new Error('notifications_unavailable');
      setState((previous) => previous.data && response.data.revision < previous.data.revision
        ? { ...previous, loading: false, mustRead: true, error: 'Current notification settings could not be confirmed. Refresh before another action.' }
        : { ...previous, data: response.data, loading: false, mustRead: false, error: '' });
    } catch (error) {
      if (current()) setState((previous) => ({ ...previous, loading: false, mustRead: true,
        error: error?.response?.status === 403 ? 'Access to notification status was denied.'
          : incidentId ? 'Notification history is unavailable. Refresh to check delivery status.' : 'Notification status is unavailable. Refresh to check the current settings.' }));
    } finally { if (read.current === controller) read.current = null; }
  }, [incidentId]);
  useEffect(() => {
    setState(initial(scope)); load();
    return () => { sequence.current += 1; read.current?.abort(); write.current?.abort(); read.current = null; write.current = null; };
  }, [load, scope]);
  const currentScope = state.scope === scope;
  const data = currentScope ? state.data : null;
  const canManage = access.auth_mode === 'oidc' && access.actor?.role === 'owner' && data?.can_manage === true
    && validNotifications(data, access, incidentId);
  const canAct = canManage && !state.loading && !state.action && !state.mustRead && data.revision < 2147483647;
  const perform = async (action, deliveryId) => {
    if (!canAct || write.current || !['test', 'enable', 'disable', 'retry'].includes(action)) return;
    const destination = data.destination;
    if (action === 'test' && (!['configured', 'changed'].includes(destination.state)
      || (destination.state === 'configured' && data.deliveries.some((row) => row.kind === 'test' && ['queued', 'sending', 'retrying'].includes(row.state))))) return;
    if (action === 'enable' && (destination.state !== 'configured' || !destination.verified || destination.enabled)) return;
    if (action === 'retry' && (destination.state !== 'configured' || !data.deliveries.some((row) => row.id === deliveryId && row.can_retry))) return;
    let requestId;
    try { requestId = globalThis.crypto.randomUUID(); } catch {
      setState((previous) => ({ ...previous, error: 'A secure notification request could not be created. Refresh before trying again.', mustRead: true })); return;
    }
    read.current?.abort(); read.current = null;
    const controller = new AbortController(), request = ++sequence.current;
    write.current = controller;
    const current = () => sequence.current === request && !controller.signal.aborted;
    setState((previous) => ({ ...previous, action, error: '', notice: '' }));
    let acknowledged = false;
    try {
      const response = await guardianApi.notificationAction({ expected_revision: data.revision, request_id: requestId,
        action, ...(action === 'retry' ? { delivery_id: deliveryId } : {}) }, { signal: controller.signal });
      if (!current()) return;
      if (response?.status !== 200 || !validNotifications(response.data, authority.current)
          || response.data.revision <= data.revision) throw new Error('notification_action_unconfirmed');
      acknowledged = true;
      let next = response.data;
      if (incidentId !== null) {
        const history = await guardianApi.getNotifications(incidentId, { signal: controller.signal });
        if (!current()) return;
        if (!validNotifications(history?.data, authority.current, incidentId) || history.data.revision < response.data.revision) throw new Error('notification_history_unavailable');
        next = history.data;
      }
      setState((previous) => ({ ...previous, data: next, action: null, mustRead: false, error: '',
        notice: action === 'test' ? 'Test request queued. Refresh notification status to check whether Slack accepted it.'
          : action === 'retry' ? 'Retry request accepted. Refresh notification status to check the delivery result.'
            : 'Notification settings updated. Review the current delivery status below.' }));
    } catch (error) {
      if (current()) setState((previous) => ({ ...previous, action: null, mustRead: true,
        error: acknowledged ? 'The action was accepted, but delivery history could not be refreshed. Refresh before another action.'
          : error?.response?.status === 409 ? 'Notification settings or delivery state changed. Refresh before trying again.'
            : error?.response?.status === 403 ? 'Only the project owner can change notifications. Refresh to check your access.'
              : 'The notification action was not confirmed. It may have reached Sillage. Refresh before trying again.' }));
    } finally { if (write.current === controller) write.current = null; }
  };
  return { ...state, data, error: currentScope ? state.error : '', notice: currentScope ? state.notice : '',
    loading: !currentScope || state.loading, access, canManage, canAct, load, perform };
}

export function NotificationHistory({ state, incident = false }) {
  if (!state.data) return null;
  const rows = state.data.deliveries;
  return <section aria-label="Recent notification deliveries" className="space-y-3">
    <h3 className="font-medium text-ink-900">Recent deliveries</h3>
    <p className="text-xs">Showing {rows.length} recent delivery records{state.data.has_more ? '; older records are omitted' : ''}. Slack acceptance does not establish that someone read the message.</p>
    {!rows.length && <p>{incident ? 'No recent delivery records are shown for this incident. Older incidents are not backfilled when notifications are enabled.' : 'No recent delivery records are shown.'}</p>}
    {rows.map((row) => <article key={row.id} className="rounded border p-3 space-y-2" aria-label={`Delivery ${row.id}`}>
      <div className="flex flex-wrap justify-between gap-2"><h4 className="font-medium text-ink-900">{row.kind === 'test' ? 'Test notification' : 'Incident notification'}</h4>
        <span className="font-medium text-ink-800">{deliveryStateText(row.state)}</span></div>
      {!incident && row.incident_id && <Link className="underline break-all" to={`/incidents/${encodeURIComponent(row.incident_id)}`}>View incident</Link>}
      <dl className="space-y-1 text-xs"><div><dt className="inline">Created: </dt><dd className="inline"><NotificationTime value={row.created_at} /></dd></div>
        <div><dt className="inline">Last update: </dt><dd className="inline"><NotificationTime value={row.updated_at} /></dd></div>
        <div><dt className="inline">Attempts: </dt><dd className="inline">{row.attempt_count} of 15; cycle {row.cycle} of 3</dd></div>
        {row.next_attempt_at && <div><dt className="inline">Next attempt: </dt><dd className="inline"><NotificationTime value={row.next_attempt_at} /></dd></div>}</dl>
      <p>{outcomeText(row.last_outcome)}</p>
      {row.state === 'unconfirmed' && <p className="text-ochre-900">An unconfirmed attempt may already have reached Slack.</p>}
      {row.attempts.length > 0 && <details><summary className="cursor-pointer text-xs">Recorded attempts ({row.attempts.length} of {row.attempt_count})</summary>
        <ol className="mt-2 space-y-2 text-xs">{row.attempts.map((attempt) => <li key={attempt.number}>Attempt {attempt.number} started: <NotificationTime value={attempt.started_at} />
          {attempt.finished_at !== null && <p>Finished: <NotificationTime value={attempt.finished_at} /></p>}
          <p>{attempt.finished_at === null ? 'Awaiting outcome.' : outcomeText(attempt.outcome)}</p></li>)}</ol>
      </details>}
      {state.canManage && row.can_retry && <div className="space-y-2"><p className="text-xs text-ochre-900">Retrying can send another copy. An unconfirmed attempt may already have reached Slack.</p>
        <Button variant="outline" size="sm" disabled={!state.canAct || state.data.destination.state !== 'configured'} onClick={() => state.perform('retry', row.id)}>Retry notification</Button></div>}
    </article>)}
  </section>;
}

export function NotificationFeedback({ state }) {
  return <>
    {state.loading && <p role="status">{state.data ? 'Refreshing notification status...' : 'Loading notification status...'}</p>}
    {state.error && <div role="alert" className="rounded border border-ochre-200 bg-ochre-50 p-3 text-ochre-950"><p>{state.error}</p>
      {state.data && <p className="mt-1">Showing previously fetched notification status; the current state is unconfirmed.</p>}</div>}
    {state.notice && <p role="status" className="text-ink-800">{state.notice}</p>}
    {state.action && <p role="status">Submitting notification action...</p>}
    <Button variant="outline" onClick={state.load} disabled={state.loading || !!state.action}>Refresh notification status</Button>
  </>;
}

export default function NotificationSetup() {
  const state = useNotificationData();
  const target = state.data?.destination;
  const pendingTest = target?.state === 'configured' && state.data?.deliveries.some((row) => row.kind === 'test' && ['queued', 'sending', 'retrying'].includes(row.state));
  return <Card className="mt-6" aria-labelledby="notification-setup-title"><CardHeader><h2 id="notification-setup-title" className="font-semibold text-lg">Notifications</h2></CardHeader>
    <CardContent className="space-y-4 text-sm text-ink-600">
      <p>Send new incident notifications to the deployment's Slack destination. Its webhook secret stays on the server.</p>
      <NotificationFeedback state={state} />
      {state.data && <>
        <section className="rounded border bg-ink-50 p-3 space-y-2" aria-label="Slack destination status">
          <p className="font-medium text-ink-900">{({ not_configured: 'Slack destination not configured', invalid: 'Slack destination configuration is invalid',
            configured: 'Slack destination configured', changed: 'Slack destination changed' })[target.state]}</p>
          {target.state === 'configured' ? <p>{target.verified ? 'Slack accepted a test for the current destination.' : 'A successful test is required before enabling incident notifications.'}</p>
            : <p>{target.state === 'changed' ? 'Previous verification and activation no longer apply. Send a new test after the operator confirms the destination.' : 'Ask your deployment operator to configure the Slack incoming webhook.'}</p>}
          <p className="font-medium text-ink-800">{target.enabled ? 'New incident notifications enabled' : 'New incident notifications disabled'}</p>
          <p>{({ unknown: 'Delivery worker status unknown', healthy: 'Recent delivery worker heartbeat', stale: 'Delivery worker heartbeat is stale', blocked: 'Delivery worker is blocked' })[state.data.worker.status]}</p>
          <p className="text-xs">Last delivery worker heartbeat: <NotificationTime value={state.data.worker.last_seen_at} /></p>
          {state.data.updated_at && <p className="text-xs">Settings updated: <NotificationTime value={state.data.updated_at} /></p>}
        </section>
        {state.canManage ? <div className="flex flex-wrap gap-3">
          <Button variant="outline" disabled={!state.canAct || !['configured', 'changed'].includes(target.state) || pendingTest} onClick={() => state.perform('test')}>Send test notification</Button>
          <Button disabled={!state.canAct || target.state !== 'configured' || !target.verified || target.enabled} onClick={() => state.perform('enable')}>Enable notifications</Button>
          <Button variant="outline" disabled={!state.canAct} onClick={() => state.perform('disable')}>Disable notifications</Button>
        </div> : <p>{state.access.auth_mode === 'api_key' ? 'Local shared-key access shows notifications read-only.' : 'Only the project owner can test, change or retry notifications.'}</p>}
        {pendingTest && <p role="status">A test is pending. Refresh notification status to check its result.</p>}
        <NotificationHistory state={state} />
      </>}
      <div className="space-y-2 text-xs"><p>A test request queues a labelled message; it does not enable notifications. Refresh status to check Slack acceptance. Enabled settings and worker health are separate facts.</p>
        <p>Enabling applies to new incidents only. Disabling cancels queued incident notifications; an attempt already admitted may still finish. Test messages can run while incident notifications are disabled.</p>
        <p>Messages contain a fixed category and severity, opaque identifiers and a Sillage link. They exclude prompts, outputs and incident evidence.</p></div>
    </CardContent>
  </Card>;
}
