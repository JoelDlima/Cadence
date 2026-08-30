import React, { useState, useEffect, type ReactNode } from 'react';
import { BarChart3, FileClock, ShieldCheck, FlaskConical, CreditCard, Power, Menu, X, ShieldAlert, Server, Activity, ShoppingCart, Briefcase, GitBranch, Play, Database, ChevronDown } from 'lucide-react';
import { Badge, Button, cn } from '../components/primitives';
import { api } from '../services/api';
import { CloudStatus } from '../types';

interface NavItem {
  id: string;
  label: string;
  icon: typeof BarChart3;
  group?: 'primary' | 'more';
}

const navItems: NavItem[] = [
  // === TOP 4 — primary pitch surfaces ===
  { id: 'live',         label: 'Live Recovery',       icon: Play,         group: 'primary' },
  { id: 'dashboard',    label: 'Dashboard',           icon: BarChart3,    group: 'primary' },
  { id: 'testlab',      label: 'Test Lab',            icon: FlaskConical, group: 'primary' },
  { id: 'journeys',     label: 'Journeys & Audit',    icon: FileClock,    group: 'primary' },
  // === MORE — depth, not breadth ===
  { id: 'b2b',          label: 'B2B Receivables',     icon: Briefcase,    group: 'more' },
  { id: 'mandate',      label: 'Mandate Sequencer',   icon: GitBranch,    group: 'more' },
  { id: 'checkout',     label: 'Checkout Recovery',   icon: ShoppingCart, group: 'more' },
  { id: 'pay',          label: 'Payment Portal',      icon: CreditCard,   group: 'more' },
];

export function AppShell({
  currentTab,
  onTabChange,
  online,
  mode,
  cloud,
  children,
}: {
  currentTab: string;
  onTabChange: (tab: string) => void;
  online: boolean;
  mode: 'DEMO' | 'LIVE' | null;
  cloud: CloudStatus | null;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [timeStr, setTimeStr] = useState('');
  const [killArmed, setKillArmed] = useState(false);
  const [showKillModal, setShowKillModal] = useState(false);
  const [killLoading, setKillLoading] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  // Live IST Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST');
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  // Poll kill switch state every 2 seconds so multiple SPA tabs/windows
  // all flip in sync, and so a kill from the API is reflected within 2s.
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      api.getKillSwitch().then((res) => setKillArmed(res)).catch(() => {});
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const handleToggleKill = async () => {
    setKillLoading(true);
    try {
      const res = await api.setKillSwitch(!killArmed);
      setKillArmed(res);
      setShowKillModal(false);
    } catch (err) {
      console.error(err);
    } finally {
      setKillLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-paper)] text-[var(--color-ink)] flex flex-col lg:flex-row">
      {/* Mobile Top Navigation */}
      <header className="flex items-center justify-between border-b border-[var(--color-line)] bg-[var(--color-surface)] px-4 py-3 lg:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
          className="rounded-md p-1.5 text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)]"
        >
          <Menu size={20} />
        </button>
        <div className="flex items-center gap-2">
          <span className="display text-2xl tracking-tight">Cadence</span>
          {mode && (
            <Badge
              tone={mode === 'LIVE' ? 'approved' : 'pending'}
              className="text-[10px]"
            >
              {mode === 'LIVE' ? 'LIVE MODE' : 'DEMO MODE'}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", online ? "bg-[var(--color-approved)]" : "bg-[var(--color-rejected)]")} />
        </div>
      </header>

      {/* Mobile Sidebar Sheet */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <nav className="absolute inset-y-0 left-0 w-72 bg-[var(--color-surface)] p-5 shadow-[var(--shadow-raised)] flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-5 border-b border-[var(--color-line)]">
                <div>
                  <span className="display text-3xl text-[var(--color-ink)]">Cadence</span>
                  <p className="text-[11px] text-[var(--color-ink-subtle)] uppercase tracking-wider mt-0.5">
                    Revenue Recovery
                  </p>
                </div>
                <button
                  onClick={() => setMobileOpen(false)}
                  aria-label="Close navigation"
                  className="rounded-md p-1.5 text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)]"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="mt-4 space-y-1">
                {navItems.filter((i) => (i.group ?? 'primary') === 'primary').map((item) => {
                  const Icon = item.icon;
                  const active = currentTab === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => { onTabChange(item.id); setMobileOpen(false); }}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-[13.5px] font-medium transition-colors",
                        active
                          ? "bg-[var(--color-surface-subtle)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)]"
                          : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
                      )}
                    >
                      <Icon size={16} className={active ? "text-[var(--color-ink)]" : "text-[var(--color-ink-subtle)]"} />
                      {item.label}
                    </button>
                  );
                })}

                <button
                  onClick={() => setMoreOpen((o) => !o)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-[11px] uppercase tracking-wider text-[var(--color-ink-subtle)] hover:bg-[var(--color-surface-subtle)] mt-2"
                  type="button"
                >
                  <ChevronDown size={12} className={cn("transition-transform", moreOpen ? "rotate-0" : "-rotate-90")} />
                  More
                </button>
                {moreOpen && navItems.filter((i) => i.group === 'more').map((item) => {
                  const Icon = item.icon;
                  const active = currentTab === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => { onTabChange(item.id); setMobileOpen(false); }}
                      className={cn(
                        "w-full flex items-center gap-3 px-3 py-2 rounded-md text-[13px] transition-colors",
                        active
                          ? "bg-[var(--color-surface-subtle)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)]"
                          : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
                      )}
                    >
                      <Icon size={14} className={active ? "text-[var(--color-ink)]" : "text-[var(--color-ink-subtle)]"} />
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="pt-4 border-t border-[var(--color-line)] text-xs text-[var(--color-ink-subtle)]">
              <p className="numeric">{timeStr}</p>
            </div>
          </nav>
        </div>
      )}

      {/* Desktop Left Sidebar Rail (240px wide, pure white against cream canvas) */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-[var(--color-line)] bg-[var(--color-surface)] px-3.5 py-5 lg:flex">
        {/* Brand Header */}
        <div className="px-2 pb-5 border-b border-[var(--color-line)]">
          <div className="flex items-center justify-between gap-2">
            <span className="display text-3xl text-[var(--color-ink)] tracking-tight">Cadence</span>
            {mode && (
              <Badge
                tone={mode === 'LIVE' ? 'approved' : 'pending'}
                className="text-[10px]"
              >
                {mode === 'LIVE' ? 'LIVE' : 'DEMO'}
              </Badge>
            )}
          </div>
          <p className="text-[11px] uppercase tracking-wider text-[var(--color-ink-subtle)] mt-1">
            Autonomous Revenue Defense
          </p>
        </div>

        {/* Navigation Items */}
        <nav className="mt-4 flex-1 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = currentTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onTabChange(item.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2 rounded-md text-[13px] font-medium transition-colors text-left cursor-pointer",
                  active 
                    ? "bg-[var(--color-surface-subtle)] text-[var(--color-ink)] font-semibold border border-[var(--color-line)] shadow-xs" 
                    : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
                )}
              >
                <Icon size={15} className={active ? "text-[var(--color-ink)]" : "text-[var(--color-ink-subtle)]"} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Sidebar Footer: System Telemetry & Kill Switch */}
        <div className="mt-auto space-y-3 border-t border-[var(--color-line)] pt-4 px-1.5">
          <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)]">
            <span className="flex items-center gap-1.5">
              <span className={cn("h-2 w-2 rounded-full", online ? "bg-[var(--color-approved)]" : "bg-[var(--color-rejected)]")} />
              <span>Core Engine</span>
            </span>
            <span className="numeric">{timeStr}</span>
          </div>

          {cloud && (
            <div>
              <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-muted)] bg-[var(--color-surface-subtle)] px-2.5 py-1.5 rounded border border-[var(--color-line)]">
                <span className="flex items-center gap-1.5">
                  <span className={cn(
                    "h-2 w-2 rounded-full",
                    cloud.sync_state === 'online' ? "bg-[var(--color-approved)]" :
                    cloud.sync_state === 'error' ? "bg-[var(--color-rejected)]" :
                    "bg-[var(--color-ink-subtle)]"
                  )} />
                  <span>Cloud Mirror</span>
                </span>
                <span className="text-[10px] font-mono font-medium uppercase">
                  {cloud.sync_state === 'offline' && 'OFFLINE (keyless)'}
                  {cloud.sync_state === 'online' && 'ONLINE'}
                  {cloud.sync_state === 'error' && 'ERROR'}
                </span>
              </div>
              <a
                href="https://vzrasadomyrycafbzdwg.supabase.co/project/default/editor"
                target="_blank"
                rel="noreferrer"
                className="mt-2 flex items-center gap-1.5 text-[11px] text-[var(--color-accent)] underline hover:no-underline"
              >
                <Database size={11} /> Open in Supabase
              </a>
            </div>
          )}

          <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-muted)] bg-[var(--color-surface-subtle)] px-2.5 py-1.5 rounded border border-[var(--color-line)]">
            <span className="flex items-center gap-1.5">
              <Server size={12} className="text-[var(--color-ink-subtle)]" />
              <span>Port :8000</span>
            </span>
            <span className="text-[10px] text-[var(--color-approved)] font-mono font-medium">200 OK</span>
          </div>

          <button
            onClick={() => setShowKillModal(true)}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-1.5 px-3 rounded text-[12px] font-medium border transition-colors cursor-pointer",
              killArmed
                ? "border-[var(--color-rejected)] text-[var(--color-rejected)] bg-[var(--color-rejected-wash)] hover:bg-[var(--color-rejected)] hover:text-white"
                : "border-[var(--color-line-strong)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-subtle)]"
            )}
          >
            <Power size={13} />
            <span>{killArmed ? "KILL SWITCH: ARMED" : "Emergency Kill Switch"}</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="min-w-0 flex-1 flex flex-col">
        {/* Top Header Bar with Apple/Vercel frosted glass */}
        <header className="hidden lg:flex items-center justify-between border-b border-[var(--color-line)] glass-surface px-8 py-3 sticky top-0 z-30">
          <div className="flex items-center gap-3">
            <span className="text-[12px] text-[var(--color-ink-subtle)] uppercase tracking-wider font-semibold">
              Workspace:
            </span>
            <Badge tone="neutral" className="text-[11px] font-mono">
              Razorpay UPI AutoPay · Track 3
            </Badge>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono text-[var(--color-ink-muted)]">
            {/* PHASE 4: prominent kill-switch indicator in the top header.
               Clicking it opens the same confirmation modal as the sidebar
               button. The two are kept in sync by the 2s polling above. */}
            <button
              onClick={() => setShowKillModal(true)}
              aria-pressed={killArmed}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded border text-[12px] font-mono font-medium transition-colors cursor-pointer",
                killArmed
                  ? "border-[var(--color-rejected)] bg-[var(--color-rejected)] text-white hover:bg-[var(--color-rejected)]"
                  : "border-[var(--color-line-strong)] text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink)]"
              )}
            >
              <Power size={13} />
              {killArmed ? "ENGINE STOPPED" : "STOP"}
            </button>
            <span className="text-[var(--color-line-strong)]">|</span>
            <span className="flex items-center gap-1 text-[var(--color-approved)]">
              <ShieldCheck size={14} />
              <span>Deterministic Spine</span>
            </span>
            <span className="text-[var(--color-line-strong)]">|</span>
            <span className="flex items-center gap-1 text-[var(--color-info)]">
              <Activity size={14} />
              <span>SHA-256 Audit Trail</span>
            </span>
          </div>
        </header>

        {/* PHASE 4: full-width red banner under the header when kill is
           armed. Sticky below the header so it scrolls with the user. */}
        {killArmed && (
          <div
            role="alert"
            data-testid="kill-banner"
            className="sticky top-[57px] z-20 bg-[var(--color-rejected)] text-white text-[13px] font-medium px-8 py-2 shadow-sm"
          >
            <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <ShieldAlert size={15} />
                <span>
                  <strong>Compliance stop engaged</strong> &mdash; no outreach, no
                  retries, no payment links. All Guardian vetoes now include
                  <code className="bg-white/20 px-1.5 py-0.5 rounded text-[11px] mx-1">kill_switch</code>
                  in the reason.
                </span>
              </div>
              <button
                onClick={() => setShowKillModal(true)}
                className="text-white/90 hover:text-white text-[12px] underline"
              >
                disarm
              </button>
            </div>
          </div>
        )}

        {/* Dynamic Page Content */}
        <main className="flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto">
          {children}
        </main>
      </div>

      {/* Global Kill Switch Confirmation Modal */}
      {showKillModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="glass-modal max-w-md w-full rounded-lg p-6 space-y-4 border border-[var(--color-line-strong)]">
            <div className="flex items-center gap-3 text-[var(--color-rejected)]">
              <ShieldAlert size={24} />
              <h3 className="text-base font-semibold">
                {killArmed ? "Disarm Emergency Kill Switch?" : "Arm Emergency Kill Switch?"}
              </h3>
            </div>

            <p className="text-[13.5px] text-[var(--color-ink-muted)] leading-relaxed">
              {killArmed
                ? "Disarming the kill switch will allow the recovery worker thread to resume executing customer contacts and payment links."
                : "Engaging the kill switch immediately suspends all automated customer outreaches, retries, and Payment Link generation across all active journeys."}
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowKillModal(false)}
                disabled={killLoading}
              >
                Cancel
              </Button>
              <Button
                variant={killArmed ? "primary" : "danger"}
                size="sm"
                loading={killLoading}
                onClick={handleToggleKill}
              >
                {killArmed ? "Disarm Kill Switch" : "Confirm Emergency Kill"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
