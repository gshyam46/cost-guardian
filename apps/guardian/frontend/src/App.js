import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import GuardianOverview from "@/pages/GuardianOverview";
import GuardianIncidents from "@/pages/GuardianIncidents";
import GuardianIncidentDetail from "@/pages/GuardianIncidentDetail";
import ConnectScreen from "@/pages/ConnectScreen";
import { getApiKey } from "@/services/guardianApi";

function App() {
  const [connected, setConnected] = useState(Boolean(getApiKey()));

  if (!connected) {
    return (
      <>
        <ConnectScreen onConnected={() => setConnected(true)} />
        <Toaster position="top-right" richColors />
      </>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<GuardianOverview />} />
        <Route path="/incidents" element={<GuardianIncidents />} />
        <Route path="/incidents/:incidentId" element={<GuardianIncidentDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster position="top-right" richColors />
    </BrowserRouter>
  );
}

export default App;
