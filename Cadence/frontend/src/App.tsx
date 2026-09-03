import React, { useState, useEffect } from 'react';
import { AppShell } from './layouts/AppShell';
import { LiveRecoveryView } from './views/LiveRecoveryView';
import { PayPortalView } from './views/PayPortalView';
import { AgentCompareView } from './views/AgentCompareView';
import { DashboardView } from './views/DashboardView';
import { CheckoutView } from './views/CheckoutView';
import { B2BView } from './views/B2BView';
import { MandateView } from './views/MandateView';
import { Metrics, Status, CloudStatus } from './types';
import { api } from './services/api';

const POLL_MS = 2500;

// Every hash the SPA answers to. `journeys`, `guardian`, `brain`, `overview`
// and `merchant` are retired tabs kept here only so old links resolve; they
// all land on the Dashboard, which absorbed their content (the journey drawer
// carries the reasoning panel and the audit chain).
const TAB_IDS = [
  'live', 'dashboard', 'testlab', 'b2b', 'mandate', 'checkout', 'pay',
  'overview', 'merchant', 'agentcompare', 'testbench', 'journeys',
  'guardian', 'brain',
];

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState('live');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [online, setOnline] = useState(true);

  // Sync with URL hash
  useEffect(() => {
    const readHash = () => {
      const h = window.location.hash.replace('#', '');
      if (h && TAB_IDS.includes(h)) {
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

  // Background poller: status + metrics + cloud mirror. Journey rows are no
  // longer fetched here — the Dashboard owns its own polling now.
  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [s, m, c] = await Promise.all([
          api.getStatus().catch(() => null),
          api.getMetrics(),
          api.getCloudStatus().catch(() => null),
        ]);
        setStatus(s);
        setMetrics(m);
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

  // Retired tab ids all resolve to the Dashboard.
  const isDashboard = ['dashboard', 'overview', 'merchant', 'journeys', 'guardian', 'brain']
    .includes(currentTab);
  const isTestLab = ['testlab', 'agentcompare', 'testbench'].includes(currentTab);

  return (
    <AppShell
      currentTab={currentTab}
      onTabChange={handleTabChange}
      online={online}
      mode={status?.mode ?? null}
      cloud={cloud}
    >
      {currentTab === 'live' && <LiveRecoveryView />}

      {isDashboard && <DashboardView />}

      {isTestLab && <AgentCompareView />}

      {currentTab === 'b2b' && <B2BView />}

      {currentTab === 'mandate' && <MandateView />}

      {currentTab === 'checkout' && <CheckoutView />}

      {currentTab === 'pay' && <PayPortalView />}
    </AppShell>
  );
};

export default App;
