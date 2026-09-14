import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import guardianApi from '@/services/guardianApi';
import { draftRules, policyDraft, samePolicyDraft, samePolicyRules, validMonitoringPolicy } from '@/lib/policyModel';

const initial = () => ({ policy: null, draft: null, loading: true, saving: false, error: '', notice: '', mustRead: false });
export default function MonitoringPolicySetup() {
  const access = useGuardianAccess();
  const scope = JSON.stringify([access.auth_mode, access.actor?.id, access.actor?.role, access.project]);
  const [state, setState] = useState(() => ({ ...initial(), scope }));
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
      const response = await guardianApi.getMonitoringPolicy({ signal: controller.signal });
      if (!current()) return;
      if (!validMonitoringPolicy(response?.data, authority.current)) throw new Error('policy_unavailable');
      setState((previous) => {
        if (previous.policy && response.data.revision < previous.policy.revision) {
          return { ...previous, loading: false, mustRead: true, error: 'The saved rules could not be confirmed. Reload the rules before saving.' };
        }
        const dirty = previous.policy && !samePolicyDraft(previous.draft, policyDraft(previous.policy.rules));
        return { ...previous, policy: response.data, draft: dirty ? previous.draft : policyDraft(response.data.rules),
          loading: false, mustRead: false, error: '',
          notice: dirty ? `${response.data.revision === 0 ? 'Default monitoring rules' : 'Latest saved rules'} loaded. Your unsaved edits are preserved; compare them with the current values before saving.` : '' };
      });
    } catch (error) {
      if (current()) setState((previous) => ({ ...previous, loading: false, mustRead: true,
        error: error?.response?.status === 403 ? 'Access to monitoring rules was denied.' : 'Monitoring rules are unavailable. Reload the rules to check the current settings.' }));
    } finally { if (read.current === controller) read.current = null; }
  }, []);

  useEffect(() => {
    setState({ ...initial(), scope });
    load();
    return () => {
      sequence.current += 1;
      read.current?.abort(); write.current?.abort();
      read.current = null; write.current = null;
    };
  }, [load, scope]);

  const owner = access.auth_mode === 'oidc' && access.actor?.role === 'owner';
  const currentScope = state.scope === scope;
  const canManage = currentScope && owner && state.policy?.can_manage === true && validMonitoringPolicy(state.policy, access);
  const rules = draftRules(state.draft);
  const dirty = state.policy && !samePolicyDraft(state.draft, policyDraft(state.policy.rules));
  const save = async (event) => {
    event.preventDefault();
    if (!canManage || state.loading || state.saving || state.mustRead || !rules || !dirty || write.current) return;
    read.current?.abort(); read.current = null;
    const controller = new AbortController(), request = ++sequence.current;
    write.current = controller;
    const expected = state.policy.revision;
    const current = () => sequence.current === request && !controller.signal.aborted;
    setState((previous) => ({ ...previous, saving: true, error: '', notice: '' }));
    try {
      const response = await guardianApi.updateMonitoringPolicy({ expected_revision: expected, rules }, { signal: controller.signal });
      if (!current()) return;
      if (response?.status !== 200 || !validMonitoringPolicy(response.data, authority.current)
          || response.data.revision !== expected + 1 || !samePolicyRules(response.data.rules, rules)) throw new Error('policy_save_unconfirmed');
      setState((previous) => ({ ...previous, policy: response.data, draft: policyDraft(response.data.rules),
        saving: false, mustRead: false, notice: `Monitoring rules saved as revision ${response.data.revision}.`, error: '' }));
    } catch (error) {
      if (current()) {
        const status = error?.response?.status;
        setState((previous) => ({ ...previous, saving: false, mustRead: status !== 400 && status !== 422,
          error: status === 409 ? 'Another save changed the rules. Reload the saved rules before saving your edits.'
            : status === 403 ? 'Only the project owner can save monitoring rules. Reload to check your access.'
              : status === 400 || status === 422 ? 'These rules were rejected. Check the limits and try again.'
                : 'The save was not confirmed. It may have reached Sillage. Reload the saved rules before trying again.' }));
      }
    } finally { if (write.current === controller) write.current = null; }
  };
  const change = (field, value) => setState((previous) => ({ ...previous, draft: { ...previous.draft, [field]: value }, notice: '' }));

  return <Card className="mt-6" aria-labelledby="monitoring-policy-title">
    <CardHeader><h2 id="monitoring-policy-title" className="font-semibold text-lg">Monitoring rules</h2></CardHeader>
    <CardContent className="space-y-4 text-sm text-slate-600">
      <p>Set limits that create incidents for expensive or slow calls, and choose whether reported call errors create incidents.</p>
      {(!currentScope || state.loading) && <p role="status">{currentScope && state.policy ? 'Refreshing saved rules...' : 'Loading monitoring rules...'}</p>}
      {currentScope && state.error && <div role="alert" className="rounded border border-amber-200 bg-amber-50 p-3 text-amber-950">
        <p>{state.error}</p>{state.policy && <p className="mt-1">Showing previously fetched rules; current settings are unconfirmed.</p>}
      </div>}
      {currentScope && state.notice && <p role="status" className="text-slate-800">{state.notice}</p>}
      <Button variant="outline" onClick={load} disabled={state.loading || state.saving}>Reload saved rules</Button>
      {currentScope && state.policy && <>
        <section aria-label="Current monitoring rules" className="rounded border bg-slate-50 p-3">
          <p className="font-medium text-slate-900">{state.policy.revision === 0 ? 'Default monitoring rules' : `Saved revision ${state.policy.revision}`}</p>
          <dl className="mt-2 space-y-2">
            <div><dt>Cost per call</dt><dd className="font-medium text-slate-800">{state.policy.rules.max_call_cost_usd === null ? 'Absolute cost limit disabled' : `Above $${state.policy.rules.max_call_cost_usd} USD`}</dd></div>
            <div><dt>Duration per call</dt><dd className="font-medium text-slate-800">{state.policy.rules.max_call_latency_ms === null ? 'Absolute duration limit disabled' : `Above ${state.policy.rules.max_call_latency_ms.toLocaleString('en-US')} ms`}</dd></div>
            <div><dt>Reported call errors</dt><dd className="font-medium text-slate-800">{state.policy.rules.alert_on_errors ? 'Create incidents' : 'Error alerts disabled'}</dd></div>
          </dl>
          {state.policy.updated_at && <p className="mt-3 text-xs">Updated {new Date(state.policy.updated_at).toISOString().replace('T', ' ').replace('Z', ' UTC')} by {state.policy.updated_by.name}.</p>}
        </section>
        {canManage ? <form onSubmit={save} className="space-y-4" aria-label="Edit monitoring rules">
          <div><label htmlFor="policy-cost" className="block font-medium text-slate-800">Maximum cost per call (USD)</label>
            <input id="policy-cost" type="text" inputMode="decimal" autoComplete="off" maxLength={22}
              value={state.draft.cost} disabled={state.saving} onChange={(event) => change('cost', event.target.value)}
              aria-describedby="policy-cost-help" className="mt-1 w-full max-w-sm rounded border px-3 py-2 text-slate-900" />
            <p id="policy-cost-help" className="mt-1 text-xs">Leave blank to disable. Zero is valid. A known cost must be strictly greater than this limit; missing prices cannot trigger it.</p>
          </div>
          <div><label htmlFor="policy-latency" className="block font-medium text-slate-800">Maximum duration per call (milliseconds)</label>
            <input id="policy-latency" type="text" inputMode="numeric" autoComplete="off" maxLength={8}
              value={state.draft.latency} disabled={state.saving} onChange={(event) => change('latency', event.target.value)}
              aria-describedby="policy-latency-help" className="mt-1 w-full max-w-sm rounded border px-3 py-2 text-slate-900" />
            <p id="policy-latency-help" className="mt-1 text-xs">Leave blank to disable. Use a whole number from 0 to 86,400,000; equality does not trigger an incident.</p>
          </div>
          <label className="flex items-start gap-2 text-slate-800"><input id="policy-errors" type="checkbox" checked={state.draft.errors}
            disabled={state.saving} onChange={(event) => change('errors', event.target.checked)} className="mt-1" />Create incidents for reported call errors</label>
          {!rules && <p role="alert" className="text-amber-900">Use a nonnegative USD decimal with up to 12 decimal places and a whole-number duration within the allowed range.</p>}
          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={state.loading || state.saving || state.mustRead || !rules || !dirty}>{state.saving ? 'Saving rules...' : 'Save monitoring rules'}</Button>
            <Button type="button" variant="outline" disabled={state.saving || !dirty}
              onClick={() => setState((previous) => ({ ...previous, draft: policyDraft(previous.policy.rules), notice: '' }))}>Discard edits</Button>
          </div>
        </form> : <p>{access.auth_mode === 'api_key' ? 'Local shared-key access shows monitoring rules read-only.' : 'Only the project owner can edit monitoring rules.'}</p>}
      </>}
      <div className="space-y-2 text-xs">
        <p>Existing relative cost and latency checks remain active. These limits apply to calls whose evaluation has not started; saved changes do not rescore historical incidents.</p>
        <p>Saving rules does not establish capture or worker health. These rules create incidents; notification delivery is configured separately, and spending limits are not enforced.</p>
        <Link to="/incidents" className="inline-block underline text-slate-800">Review incidents</Link>
      </div>
    </CardContent>
  </Card>;
}
