// DemoSeedBadge.tsx
// A small badge that says "Demo seed data" on tabs whose data is generated
// locally (not synced from live Razorpay). Helps judges tell at a glance
// which tabs are "real Razorpay" vs "simulated / seeded".
import React from 'react';
import { Badge } from './primitives';

export const DemoSeedBadge: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <Badge tone="info">
    {children ?? 'Demo seed data'}
  </Badge>
);
