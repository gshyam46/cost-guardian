import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { NotificationFeedback, NotificationHistory, useNotificationData } from './NotificationSetup';

export default function IncidentDeliveries({ incidentId }) {
  const state = useNotificationData(incidentId);
  return <Card className="mt-6" aria-labelledby="incident-delivery-title"><CardHeader><h2 id="incident-delivery-title" className="font-semibold text-lg">Notification history</h2></CardHeader>
    <CardContent className="space-y-4 text-sm text-ink-600">
      <NotificationFeedback state={state} />
      <NotificationHistory state={state} incident />
      <p className="text-xs">Delivery status is separate from incident resolution. Resolving an incident does not recall a message already sent to Slack.</p>
    </CardContent>
  </Card>;
}
