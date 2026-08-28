// Indic-language nudge preview component for the Pay Portal.
//
// Shows a side-by-side preview of the recovery nudge in 6 Indian
// languages + the Hinglish default. The user picks a language
// (default Hinglish); the component calls /api/nudge/preview and
// renders the returned text. This is the visual proof for the
// track-3 demo that the engine has copy-reviewable, locale-aware
// templates.

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, Badge } from '../components/primitives';
import { api } from '../services/api';
import { Languages } from 'lucide-react';

const LANGUAGES: { code: string; label: string; greeting: string }[] = [
  { code: 'hinglish', label: 'Hinglish', greeting: 'default' },
  { code: 'hi', label: 'Hindi', greeting: 'Namaste' },
  { code: 'ta', label: 'Tamil', greeting: 'Vanakkam' },
  { code: 'te', label: 'Telugu', greeting: 'Namaskaram' },
  { code: 'bn', label: 'Bengali', greeting: 'Namaskar' },
  { code: 'mr', label: 'Marathi', greeting: 'Namaskar' },
  { code: 'gu', label: 'Gujarati', greeting: 'Namaskar' },
];

const DEMO_AMOUNT_MINOR = 49900;
const DEMO_LINK = 'https://pay.cadence.in/r/sub_demo_001';

export const NudgePreview: React.FC = () => {
  const [language, setLanguage] = useState<string>('hinglish');
  const [text, setText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPreview = useCallback(async (lang: string) => {
    try {
      setLoading(true);
      const data = await api.getNudgePreview(lang, DEMO_AMOUNT_MINOR, DEMO_LINK);
      setText(data.text);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? 'failed to load nudge preview');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPreview(language);
  }, [language, fetchPreview]);

  return (
    <Card className="p-5 space-y-4">
      <CardHeader
        title="Indic-language recovery nudge"
        subtitle="The same payment reminder, copy-reviewable in 6 Indian languages. The engine picks the customer's locale; the templates live in source so they can be reviewed without running the engine."
        action={
          <Badge tone="info">
            <Languages size={11} className="inline-block mr-1" />
            {LANGUAGES.find((l) => l.code === language)?.label ?? language}
          </Badge>
        }
      />
      <div className="flex flex-wrap gap-2">
        {LANGUAGES.map((lang) => (
          <button
            key={lang.code}
            type="button"
            onClick={() => setLanguage(lang.code)}
            className={
              'px-3 py-1.5 rounded-md text-[12px] font-semibold transition ' +
              (language === lang.code
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-surface-2)] text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-3)]')
            }
            title={lang.greeting}
          >
            {lang.label}
          </button>
        ))}
      </div>
      {error ? (
        <div className="text-[12px] text-[var(--color-ink-muted)] font-mono">
          {error}
        </div>
      ) : (
        <div className="bg-[var(--color-surface-2)] border border-[var(--color-line)] rounded-md p-4 text-[13px] text-[var(--color-ink)] font-mono leading-relaxed">
          {loading ? '...' : text}
        </div>
      )}
      <p className="text-[10.5px] text-[var(--color-ink-subtle)]">
        Demo amount: &#8377;499 (49900 minor). Demo link: {DEMO_LINK}. Sign-off:
        Cadence. Templates: <code className="font-mono">revive/policy/nudge_templates.py</code>.
      </p>
    </Card>
  );
};
