import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ChevronRight, ShieldCheck } from 'lucide-react';
import GuardianLayout from './GuardianLayout';
import guardianApi from '@/services/guardianApi';
import useLiveData from '@/hooks/useLiveData';

const SEVERITY_STYLES = {
  high: 'bg-danger-100 text-danger-700',
  medium: 'bg-ochre-100 text-ochre-700',
  low: 'bg-ink-100 text-ink-700',
};

const FILTERS = [
  { key: 'open', label: 'Open' },
  { key: 'resolved', label: 'Resolved' },
  { key: null, label: 'All' },
];

const GuardianIncidents = () => {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('open');

  const fetchIncidents = useCallback(
    async ({ signal } = {}) => {
      const response = await guardianApi.listIncidents(filter, { signal });
      if (!Array.isArray(response.data)) throw new Error('Invalid incident response');
      return { filter, incidents: response.data };
    },
    [filter],
  );

  const { data, loading, refreshing, error, lastUpdated, reload } = useLiveData(fetchIncidents, {
    refetchKey: filter,
  });

  const hasCurrentData = data?.filter === filter && Array.isArray(data?.incidents);
  const incidents = hasCurrentData ? data.incidents : [];
  const isLoading = loading || (!hasCurrentData && !error);

  return (
    <GuardianLayout refreshing={refreshing} lastUpdated={hasCurrentData ? lastUpdated : null}>
      <div className="flex items-center justify-between mb-4">
        <h2 className="cg-page-title text-xl font-semibold text-ink-900">Incidents</h2>
        <div className="flex gap-1">
          {FILTERS.map((option) => (
            <Button
              key={option.label}
              size="sm"
              variant={filter === option.key ? 'default' : 'outline'}
              aria-pressed={filter === option.key}
              onClick={() => setFilter(option.key)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading && <div role="status" className="animate-pulse text-ink-600">Loading incidents...</div>}

      {!isLoading && error && <Card className="mb-4 border-ochre-200 bg-ochre-50">
        <CardContent className="py-4">
          <div role="alert" className="text-sm text-ochre-900">
            <p className="font-medium">{hasCurrentData ? 'Could not refresh incidents.' : 'Could not load incidents.'}</p>
            {hasCurrentData
              ? <p className="mt-1">Showing the last successful response for this filter from {lastUpdated.toLocaleString()}.
                {incidents.length === 0 && ' That response contained no matching incidents; current results are unknown.'}</p>
              : <p className="mt-1">Incident results for this filter are unavailable. Try again to check the current state.</p>}
          </div>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => reload()} disabled={refreshing}>
            {refreshing ? 'Retrying incidents...' : 'Retry incidents'}
          </Button>
        </CardContent>
      </Card>}

      {!isLoading && !error && hasCurrentData && incidents.length === 0 && (
        <Card>
          <CardContent className="pt-6 flex flex-col items-center text-center py-12">
            <ShieldCheck className="h-8 w-8 text-ink-300 mb-3" />
            <p className="text-ink-700 font-medium">{filter ? `No ${filter} incidents` : 'No incidents'}</p>
            <p className="text-sm text-ink-500 mt-1">
              Sillage raises an incident when a detector finds a cost, reliability, or PII
              anomaly in your captured observations.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {incidents.map((incident) => (
          <Card
            key={incident.id}
            className="cursor-pointer hover:border-ink-300 transition-colors"
            onClick={() => navigate(`/incidents/${incident.id}`)}
          >
            <CardContent className="py-4 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge className={SEVERITY_STYLES[incident.severity] || SEVERITY_STYLES.low}>
                    {incident.severity}
                  </Badge>
                  <Badge variant="outline">{incident.detector}</Badge>
                  {incident.status === 'resolved' && (
                    <Badge variant="outline" className="text-ink-400">
                      resolved
                    </Badge>
                  )}
                </div>
                <p className="font-medium text-ink-900 mt-2 truncate">{incident.title}</p>
                <p className="text-sm text-ink-500 truncate">{incident.summary}</p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs text-ink-400">
                  {new Date(incident.created_at).toLocaleString()}
                </span>
                <ChevronRight className="h-4 w-4 text-ink-400" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </GuardianLayout>
  );
};

export default GuardianIncidents;
