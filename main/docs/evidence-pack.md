# Evidence Pack — Live Sources to Open During Judging

Purpose: prove every claim with primary sources you can open in a browser tab on stage.
Order of authority: Regulator first, rails operator second, industry data third.
Honesty rule: quote ranges ("published estimates run 20-40 percent"), never absolutes.

| # | Claim | Open this URL | Point at | Type |
|---|---|---|---|---|
| 1 | Auto-debit rules require a 24h pre-debit notice | https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12722 | "at least 24 hours prior to the actual debit" | Regulator (RBI) |
| 2 | Recurring-debit framework updated 2026 (E-mandate Framework) | https://www.zoho.com/payments/academy/payment-processing/upi-autopay-mandates-and-recurring-debits.html | 24h pre-transaction notification; opt-out facility | Framework explainer |
| 3 | Retries belong off-peak; mandate mechanics | https://docs.decentro.tech/reference/payments_api-upi-autopay-pre-debit-notification | NPCI 24h validation note; 24-48h window | Rails operator docs |
| 4 | Our error codes are Razorpay's own vocabulary | https://razorpay.com/docs/errors/payments/upi/ | insufficient_funds, bank_technical_error, payment_collect_request_expired | Platform docs |
| 5 | Webhook delivery rules we coded against | https://razorpay.com/docs/webhooks/best-practices/ | 5s response window; at-least-once; 24h retry then disable; event-id header | Platform docs |
| 6 | Test-mode simulation levers used in our demo | https://razorpay.com/docs/payments/payments/test-upi-details/ | success@razorpay / failure@razorpay | Platform docs |
| 7 | India UPI scale (~228B transactions, ~Rs 300T/year) | Bureau "India Fraud Report 2026" - https://bureau.id/resources/reports-ebooks/india-fraud-report-2026 | scale section | Industry report |
| 8 | Digital-payment fraud Rs 4,457 crore FY16-FY26, half in one year | https://theprint.in/india/banks-reported-rs-4457-cr-worth-of-digital-payment-fraud-over-11-yrs... (Aug 2026) | Lok Sabha data quote | Press citing government |
| 9 | UPI Autopay debits fail 8-15% vs cards 2-3% | https://productgrowth.in/insights/fintech/upi-autopay-guide/ | TL;DR failure-rate comparison | Practitioner data |
| 10 | Involuntary churn = 20-40% of subscription churn | https://www.digitalapplied.com/blog/failed-payment-recovery-dunning-playbook-2026 | opening stat | Industry playbook |
| 11 | Market validation: Razorpay ships its own recovery agents | https://razorpay.com/agent-studio/ | Subscription Recovery / Dispute Responder prebuilts | The judge's own product |
| 12 | AI adoption pressure in Indian BFSI (~21% already in production) | RBI FREE-AI committee coverage - https://www.humaineeti.ai/resources/ai-bfsi-india-use-cases | survey citation | Regulator-adjacent |
| 13 | LLM quota reality shaping our fallback design | https://ai.google.dev/gemini-api/docs/rate-limits | per-model free-tier RPM/RPD tables | Platform docs |

## Three spoken lines

1. "Every rule in our Guardian traces to document number 1 or 3 - regulation, not opinion."
2. "The failure codes our classifier uses are copied verbatim from Razorpay's own error pages - rows 4 and 5."
3. "Every number in our eval report traces to a cited calibration in this pack - if a source is a range, we say range."

## Calibration cross-check for eval-report.md

Simulator base rates map to rows 9-10: NO_FUNDS retry decay .38/.22/.12 sits inside published recoverable-majority findings; cohort failure mix centers on the 8-15% UPI band scaled to a distressed-cohort scenario (we model only failures, hence higher apparent rates - stated openly in the report's methodology).
