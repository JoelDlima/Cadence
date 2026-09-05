import React, { useState, useEffect } from 'react';
import { AppShell } from './layouts/AppShell';
import { PayPortalView } from './views/PayPortalView';
import TestLabView from './views/TestLabView';
import { DashboardView } from './views/DashboardView';
import { Metrics, Status, CloudStatus } from './types';
import { api } from './services/api';

const POLL_MS = 2500;

// Every hash the SPA answers to. `journeys`, `guardian`, `brain`, `overview`
// and `merchant` are retired tabs kept here only so old links resolve; they
// all land on the Dashboard, which absorbed their content (the journey drawer
// carries the reasoning panel and the audit chain).
const TAB_IDS = [
  'live', 'dashboard', 'testlab', 'b2b', 'mandate', 'checkout', 'pay',
  'predebit',
  'overview', 'merchant', 'agentcompare', 'testbench', 'journeys',
  'guardian', 'brain',
];

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [online, setOnline] = useState(true);

  // Sync with URL hash
  useEffect(() => {
    const readHash = () => {
      const h = window.location.hash.replace('#', '').replace('/', '');
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

  // Background poller: status + metrics + cloud mirror
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

  const isDashboard = ['dashboard', 'overview', 'merchant', 'journeys', 'guardian', 'brain']
    .includes(currentTab);
  const isTestLab = ['testlab', 'live', 'checkout', 'b2b', 'mandate', 'predebit', 'agentcompare', 'testbench']
    .includes(currentTab);

  return (
    <AppShell
      currentTab={isDashboard ? 'dashboard' : isTestLab ? 'testlab' : currentTab}
      onTabChange={handleTabChange}
      online={online}
      mode={status?.mode ?? null}
      cloud={cloud}
    >
      {isDashboard && <DashboardView />}

      {isTestLab && <TestLabView initialSection={currentTab} />}

      {currentTab === 'pay' && <PayPortalView />}
    </AppShell>
  );
};

export default App;
