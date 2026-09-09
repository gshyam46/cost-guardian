import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ArrowLeft, ExternalLink, CheckCircle2 } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import guardianApi from '@/services/guardianApi';

const SEVERITY_STYLES = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-700',
};

const GuardianIncidentDetail = () => {
  const { incidentId } = useParams();
  const navigate = useNavigate();
  const [incident, setIncident] = useState(null);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState(false);

  const load = async () => {
    try {
      const response = await guardianApi.getIncident(incidentId);
      setIncident(response.data);
    } catch (error) {
      toast.error('Incident not found');
      navigate('/incidents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [incidentId]);

  const handleResolve = async () => {
    setResolving(true);
    try {
      await guardianApi.resolveIncident(incidentId);
      toast.success('Incident resolved');
      await load();
    } catch (error) {
      toast.error('Could not resolve incident');
    } finally {
      setResolving(false);
    }
  };

  if (loading) {
    return (
      <GuardianLayout>
        <div className="animate-pulse text-slate-600">Loading incident...</div>
      </GuardianLayout>
    );
  }

  if (!incident) return null;

  return (
    <GuardianLayout>
      <Button variant="ghost" size="sm" onClick={() => navigate('/incidents')} className="mb-4">
        <ArrowLeft className="h-4 w-4 mr-1" />
        Back to incidents
      </Button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Badge className={SEVERITY_STYLES[incident.severity] || SEVERITY_STYLES.low}>
              {incident.severity}
            </Badge>
            <Badge variant="outline">{incident.detector}</Badge>
            <Badge variant="outline">{incident.status}</Badge>
          </div>
          <h2 className="text-xl font-semibold text-slate-900">{incident.title}</h2>
          <p className="text-sm text-slate-500 mt-1">{incident.summary}</p>
        </div>
        {incident.status === 'open' && (
          <Button onClick={handleResolve} disabled={resolving}>
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
                <p className="text-xs text-slate-400">
                  No trace link available (Langfuse not connected yet). Raw trace id
                  {incident.trace_ids.length > 1 ? 's' : ''}:{' '}
                  {incident.trace_ids.join(', ') || '—'}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </GuardianLayout>
  );
};

export default GuardianIncidentDetail;
