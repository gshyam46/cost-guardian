import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ArrowLeft, ExternalLink, CheckCircle2 } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import guardianApi from '@/services/guardianApi';
import { useGuardianAccess } from '@/contexts/GuardianAccess';
import { policyExplanation } from '@/lib/policyModel';
import IncidentDeliveries from './IncidentDeliveries';

const SEVERITY_STYLES = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-700',
};

const GuardianIncidentDetail = () => {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const canResolve = useGuardianAccess().permissions.includes('resolve_incidents');
  const [result, setResult] = useState({ id: null, incident: null, error: null, loading: true });
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState('');
  const read = useRef(null);
  const write = useRef(null);

  const load = useCallback(async () => {
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    const current = () => read.current === controller && !controller.signal.aborted;
    setResult({ id: incidentId, incident: null, error: null, loading: true });
    setResolveError('');
    try {
      const response = await guardianApi.getIncident(incidentId, { signal: controller.signal });
      if (!current()) return;
      if (!response.data || response.data.id !== incidentId) throw new Error('Invalid incident response');
      setResult({ id: incidentId, incident: response.data, error: null, loading: false });
    } catch (error) {
      if (current()) setResult({ id: incidentId, incident: null, error: error?.response?.status || 'unavailable', loading: false });
    }
  }, [incidentId]);

  useEffect(() => {
    load();
    setResolving(false);
    return () => {
      read.current?.abort();
      write.current?.abort();
    };
  }, [load]);

  const handleResolve = async () => {
    if (!canResolve) return;
    write.current?.abort();
    const controller = new AbortController();
    write.current = controller;
    const current = () => write.current === controller && !controller.signal.aborted;
    setResolving(true);
    setResolveError('');
    try {
      const response = await guardianApi.resolveIncident(incidentId, { signal: controller.signal });
      if (!current()) return;
      if (!response.data || response.data.id !== incidentId || response.data.status !== 'resolved') throw new Error('Invalid resolution response');
      setResult({ id: incidentId, incident: response.data, error: null, loading: false });
      toast.success('Incident resolved');
    } catch (error) {
      if (current()) setResolveError(error?.response?.status === 403
        ? 'Access to resolve this incident was denied.' : 'Could not confirm resolution. Retry when the service is available.');
    } finally {
      if (current()) setResolving(false);
    }
  };

  const currentResult = result.id === incidentId;
  const incident = currentResult ? result.incident : null;
  const explanation = policyExplanation(incident?.evidence);
  if (!currentResult || result.loading) {
    return (
      <GuardianLayout>
        <div role="status" className="animate-pulse text-slate-600">Loading incident...</div>
      </GuardianLayout>
    );
  }

  if (!incident) return <GuardianLayout>
    <Button variant="ghost" size="sm" onClick={() => navigate('/incidents')} className="mb-4">Back to incidents</Button>
    <Card><CardContent className="py-6">
      <h2 className="text-lg font-semibold mb-2">{result.error === 404 ? 'Incident not found' : result.error === 403 ? 'Access denied' : 'Could not load incident'}</h2>
      <p role="alert" className="text-sm text-slate-600">
        {result.error === 404 ? 'The requested incident was not found.'
          : result.error === 403 ? 'Access to this incident was denied. Check with your Sillage operator.'
          : result.error === 401 ? 'Access was rejected. Connect again to continue.'
          : 'Incident evidence is temporarily unavailable. Retry when the service is available.'}
      </p>
      {result.error !== 404 && result.error !== 401 && <Button className="mt-4" variant="outline" onClick={load}>Retry incident</Button>}
    </CardContent></Card>
  </GuardianLayout>;

  return (
    <GuardianLayout>
      <Button variant="ghost" size="sm" onClick={() => navigate('/incidents')} className="mb-4">
        <ArrowLeft className="h-4 w-4 mr-1" />
        Back to incidents
      </Button>
      {resolveError && <p role="alert" className="text-sm text-amber-900 mb-4">{resolveError}</p>}

      <div className="flex flex-col sm:flex-row items-start justify-between gap-3 mb-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <Badge className={SEVERITY_STYLES[incident.severity] || SEVERITY_STYLES.low}>
              {incident.severity}
            </Badge>
            <Badge variant="outline">{incident.detector}</Badge>
            <Badge variant="outline">{incident.status}</Badge>
          </div>
          <h2 className="text-xl font-semibold text-slate-900">{incident.title}</h2>
          <p className="text-sm text-slate-500 mt-1">{incident.summary}</p>
        </div>
        {incident.status === 'open' && canResolve && (
          <Button className="shrink-0" onClick={handleResolve} disabled={resolving}>
            <CheckCircle2 className="h-4 w-4 mr-1" />
            {resolving ? 'Resolving...' : 'Mark resolved'}
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Evidence</CardTitle>
          </CardHeader>
          <CardContent>
            {explanation && <div className="mb-4 rounded border border-slate-200 bg-slate-50 p-3" aria-label="Monitoring rule evidence">
              <p className="font-medium text-slate-900">{explanation}</p>
              <p className="mt-2 text-xs text-slate-600">Evaluated with saved policy revision {incident.evidence.policy_revision}. Later rule changes do not change this evidence.</p>
            </div>}
            <p className="text-xs text-slate-400 mb-2">
              The exact values that triggered this incident — check these against the raw
              trace, don't just trust the verdict.
            </p>
            <pre className="bg-slate-50 border rounded-md p-3 text-xs overflow-x-auto">
              {JSON.stringify(incident.evidence, null, 2)}
            </pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Agent</span>
              <span className="font-medium text-slate-900">{incident.agent_name || '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Created</span>
              <span className="font-medium text-slate-900">
                {new Date(incident.created_at).toLocaleString()}
              </span>
            </div>
            {incident.resolved_at && (
              <div className="flex justify-between">
                <span className="text-slate-500">Resolved</span>
                <span className="font-medium text-slate-900">
                  {new Date(incident.resolved_at).toLocaleString()}
                </span>
              </div>
            )}
            <div>
              <span className="text-slate-500 block mb-2">Trace</span>
              {incident.trace_urls && incident.trace_urls.length > 0 ? (
                <div className="space-y-1">
                  {incident.trace_urls.map((url) => (
                    <a
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-sm text-blue-600 hover:underline"
                    >
                      View in Langfuse <ExternalLink className="h-3 w-3" />
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-slate-500 space-y-2">
                  <p>No external trace link is available.</p>
                  {(incident.trace_ids || []).map((id) => <Link key={id} className="block underline break-all" to={`/runs/${encodeURIComponent(id)}`}>Inspect captured run {id}</Link>)}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
      <IncidentDeliveries incidentId={incidentId} />
    </GuardianLayout>
  );
};

export default GuardianIncidentDetail;
