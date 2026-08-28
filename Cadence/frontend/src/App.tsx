import React, { useState, useEffect } from 'react';
import { AppShell } from './layouts/AppShell';
import { OverviewView } from './views/OverviewView';
import { JourneysView } from './views/JourneysView';
import { GuardianView } from './views/GuardianView';
import { TestbenchView } from './views/TestbenchView';
import { PayPortalView } from './views/PayPortalView';
import { RecoveryBrainView } from './views/RecoveryBrainView';
import { CheckoutView } from './views/CheckoutView';
import { B2BView } from './views/B2BView';
import { MandateView } from './views/MandateView';
import { Journey, Metrics, Status, CloudStatus } from './types';
import { api } from './services/api';

const POLL_MS = 2500;

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState('overview');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [online, setOnline] = useState(true);

  // Sync with URL hash
  useEffect(() => {
    const readHash = () => {
      const h = window.location.hash.replace('#', '');
      if (h && ['overview', 'journeys', 'guardian', 'testbench', 'pay', 'brain', 'checkout', 'b2b', 'mandate'].includes(h)) {
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
      {currentTab === 'overview' && (
        <OverviewView
          metrics={metrics}
          journeys={journeys}
          onSelectTab={handleTabChange}
        />
      )}

      {currentTab === 'journeys' && (
        <JourneysView
          journeys={journeys}
        />
      )}

      {currentTab === 'guardian' && (
        <GuardianView />
      )}

      {currentTab === 'testbench' && (
        <TestbenchView />
      )}

      {currentTab === 'pay' && (
        <PayPortalView />
      )}

      {currentTab === 'brain' && (
        <RecoveryBrainView />
      )}

      {currentTab === 'checkout' && (
        <CheckoutView />
      )}

      {currentTab === 'b2b' && (
        <B2BView />
      )}

      {currentTab === 'mandate' && (
        <MandateView />
      )}
    </AppShell>
  );
};

export default App;
