import React, { useState, useEffect } from 'react';
import { AppShell } from './layouts/AppShell';
import { LiveRecoveryView } from './views/LiveRecoveryView';
import { JourneysView } from './views/JourneysView';
import { PayPortalView } from './views/PayPortalView';
import { AgentCompareView } from './views/AgentCompareView';
import { MerchantDashboard } from './views/MerchantDashboard';
import { CheckoutView } from './views/CheckoutView';
import { B2BView } from './views/B2BView';
import { MandateView } from './views/MandateView';
import { Journey, Metrics, Status, CloudStatus } from './types';
import { api } from './services/api';

const POLL_MS = 2500;

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState('live');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [online, setOnline] = useState(true);

  // Sync with URL hash
  useEffect(() => {
    const readHash = () => {
      const h = window.location.hash.replace('#', '');
      if (h && ['live', 'dashboard', 'testlab', 'journeys', 'b2b', 'mandate', 'checkout', 'pay',
                'overview', 'merchant', 'agentcompare', 'testbench', 'guardian', 'brain'].includes(h)) {
        setCurrentTab(h);
      }
    };
    readHash();
    window.addEventListener('hashchange', readHash);
    return () => window.removeEventListener('hashchange', readHash);
  }, []);

  const handleTabChange = (tab: string) => {
    setCurrentTab(tab);
    window.location.hash = tab;
  };

  // Background poller: status + metrics + journeys + cloud mirror
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [s, m, j, c] = await Promise.all([
          api.getStatus().catch(() => null),
          api.getMetrics(),
          api.getJourneys(),
          api.getCloudStatus().catch(() => null),
        ]);
        setStatus(s);
        setMetrics(m);
        setJourneys(j);
        setCloud(c);
        setOnline(true);
      } catch {
        setOnline(false);
      }
    };
    fetchAll();
    const interval = setInterval(fetchAll, POLL_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <AppShell
      currentTab={currentTab}
      onTabChange={handleTabChange}
      online={online}
      mode={status?.mode ?? null}
      cloud={cloud}
    >
      {currentTab === 'live' && (
        <LiveRecoveryView />
      )}

      {currentTab === 'dashboard' && (
        <MerchantDashboard />
      )}

      {currentTab === 'testlab' && (
        <AgentCompareView />
      )}

      {currentTab === 'journeys' && (
        <JourneysView
          journeys={journeys}
        />
      )}

      {currentTab === 'b2b' && (
        <B2BView />
      )}

      {currentTab === 'mandate' && (
        <MandateView />
      )}

      {currentTab === 'checkout' && (
        <CheckoutView />
      )}

      {currentTab === 'pay' && (
        <PayPortalView />
      )}

      {/* === Legacy id fallbacks so old URLs / hashes still resolve === */}
      {currentTab === 'overview' && (
        <MerchantDashboard />
      )}

      {currentTab === 'merchant' && (
        <MerchantDashboard />
      )}

      {currentTab === 'agentcompare' && (
        <AgentCompareView />
      )}

      {currentTab === 'testbench' && (
        <AgentCompareView />
      )}

      {currentTab === 'guardian' && (
        <JourneysView journeys={journeys} />
      )}

      {currentTab === 'brain' && (
        <JourneysView journeys={journeys} />
      )}
    </AppShell>
  );
};

export default App;
