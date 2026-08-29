// Cadence Supabase Edge Function: webhook-collector
//
// Deploy: supabase functions deploy webhook-collector --project-ref vzrasadomyrycafbzdwg
//        supabase secrets set RAZORPAY_WEBHOOK_SECRET=... --project-ref vzrasadomyrycafbzdwg
//
// When Razorpay fires a webhook (payment_link.paid, payment.captured, etc.)
// and the merchant's Razorpay is on a NAT/edge that the engine cannot reach,
// Supabase (which is publicly reachable) takes the hit and POSTs the
// canonicalized event to the engine. The engine's HMAC is re-verified
// server-side.
//
// PHASE 9: this is the relay that lets a real Razorpay test-mode webhook
// reach a developer's laptop-engine without the laptop needing a
// public ingress.

// Deno runtime. Supabase Edge Functions are Deno + Web Standards.
// (No npm, no Python.)
// @ts-nocheck

// @ts-ignore  Deno serves this URL on the edge
const ENGINE_URL = Deno.env.get("CADENCE_ENGINE_URL") ?? "http://host.docker.internal:8000";
const ENGINE_WEBHOOK_TOKEN = Deno.env.get("CADENCE_ENGINE_TOKEN") ?? "";
const RAZORPAY_WEBHOOK_SECRET = Deno.env.get("RAZORPAY_WEBHOOK_SECRET") ?? "";

interface RazorpayWebhookPayload {
  entity?: string;
  account_id?: string;
  event?: string;
  contains?: string[];
  payload?: Record<string, unknown>;
  created_at?: number;
}

interface ForwardedEvent {
  id: string;
  event: string;
  received_at: string;
  payload: RazorpayWebhookPayload;
  forwarded_to: string;
  status: "ok" | "skipped" | "error";
  error?: string;
}

Deno.serve(async (req: Request): Promise<Response> => {
  const url = new URL(req.url);
  if (req.method !== "POST" || !url.pathname.startsWith("/webhooks/")) {
    return new Response("not found", { status: 404 });
  }

  // 1) Pull raw body
  const raw = new Uint8Array(await req.arrayBuffer());

  // 2) Verify Razorpay signature
  const sig = req.headers.get("x-razorpay-signature") ?? "";
  // Razorpay signs the body with HMAC-SHA256, hex; the secret is shared.
  // Deno Web Crypto API is the standard for HMAC in edge functions.
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(RAZORPAY_WEBHOOK_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false, ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, raw);
  const expected = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (RAZORPAY_WEBHOOK_SECRET && expected !== sig) {
    return new Response(JSON.stringify({ error: "invalid signature" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  // 3) Parse, then forward to the engine
  let parsed: RazorpayWebhookPayload;
  try {
    parsed = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return new Response(JSON.stringify({ error: "invalid json" }), {
      status: 400, headers: { "content-type": "application/json" },
    });
  }

  const eventName = parsed.event ?? "unknown";
  const eventId = parsed.entity ?? crypto.randomUUID();

  // 4) Append to a Supabase audit table so the operator can see
  //    traffic even if the engine is down.
  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (supabaseUrl && serviceKey) {
    try {
      await fetch(`${supabaseUrl}/rest/v1/cadence_edge_log`, {
        method: "POST",
        headers: {
          "apikey": serviceKey,
          "Authorization": `Bearer ${serviceKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          event_id: eventId,
          event_name: eventName,
          received_at: new Date().toISOString(),
          payload: parsed,
        }),
      });
    } catch (_e) { /* audit is best-effort, never block the webhook */ }
  }

  // 5) Forward to the engine. We send the exact raw body back so the
  //    engine's HMAC verification re-checks against the same secret.
  if (!ENGINE_URL || !ENGINE_WEBHOOK_TOKEN) {
    return new Response(JSON.stringify({
      ok: true, event: eventName, status: "skipped",
      reason: "no engine credentials configured",
    } as ForwardedEvent), { status: 200, headers: { "content-type": "application/json" } });
  }
  const forwardHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Edge-Forwarded": "1",
  };
  if (ENGINE_WEBHOOK_TOKEN) {
    forwardHeaders["Authorization"] = `Bearer ${ENGINE_WEBHOOK_TOKEN}`;
  }
  const fwd = await fetch(`${ENGINE_URL}/webhooks/razorpay`, {
    method: "POST",
    headers: forwardHeaders,
    body: raw,
  });
  if (!fwd.ok) {
    const errBody = await fwd.text();
    return new Response(JSON.stringify({
      ok: false, event: eventName, status: "error",
      forwarded_to: ENGINE_URL,
      error: `engine returned ${fwd.status}: ${errBody.slice(0, 200)}`,
    } as ForwardedEvent), {
      status: 502, headers: { "content-type": "application/json" },
    });
  }
  return new Response(JSON.stringify({
    ok: true, event: eventName, status: "ok", forwarded_to: ENGINE_URL,
  } as ForwardedEvent), { status: 200, headers: { "content-type": "application/json" } });
});
