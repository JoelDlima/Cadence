// Cadence public webhook ingress (Deno Edge Function).
// Razorpay cannot reach a laptop behind NAT, so signed webhooks hit this
// function, which verifies the HMAC-SHA256 over the raw body and stages the
// payload in the `webhook_inbox` table. The local FastAPI app's
// SupabaseInboxPoller drains the inbox every 2s through the same gateway
// code the direct webhook uses.
//
// The function is server-side only; the service role key is read from
// the project's Edge Function secrets. No client-side keys are ever
// involved.
//
// This is one of the two ways Razorpay webhooks reach the engine. The
// other — direct POST to the FastAPI /webhooks/razorpay endpoint —
// works when the dev machine has a public address; the Edge Function
// is the path for laptop-behind-NAT development.
//
// Schema for webhook_inbox is in main/supabase/schema.sql. Apply it
// once in Supabase Studio -> SQL Editor before deploying this function.

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method !== "POST") {
    return Response.json({ ok: false, error: "POST only" }, { status: 405 });
  }

  const secret = Deno.env.get("RAZORPAY_WEBHOOK_SECRET") ?? "";
  const raw = await req.text();
  const sigHeader = req.headers.get("x-razorpay-signature") ?? "";

  // HMAC-SHA256 over the raw body using crypto.subtle.
  const encoder = new TextEncoder();
  const key = await globalThis.crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await globalThis.crypto.subtle.sign("HMAC", key, encoder.encode(raw));
  const expected = Array.from(new Uint8Array(mac))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  if (sigHeader !== expected) {
    console.error("revive-ingest: signature mismatch");
    return Response.json({ ok: false }, { status: 401 });
  }

  // Parse and stage. Always ack 200 — Razorpay retries non-2xx for 24h
  // before disabling the webhook, and a malformed body is not worth
  // burning that budget. The local poller will skip rows it can't
  // process.
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch (_err) {
    console.error("revive-ingest: valid signature but malformed json; dropping");
    return Response.json({ ok: true });
  }

  try {
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const res = await fetch(
      `${Deno.env.get("SUPABASE_URL")}/rest/v1/webhook_inbox`,
      {
        method: "POST",
        headers: {
          apikey: serviceKey,
          Authorization: `Bearer ${serviceKey}`,
          "Content-Type": "application/json",
          Prefer: "return=minimal",
        },
        body: JSON.stringify({
          payload,
          signature: sigHeader,
          processed: false,
        }),
      },
    );
    if (!res.ok) {
      console.error(`revive-ingest: inbox insert failed HTTP ${res.status}`);
    }
  } catch (err) {
    console.error("revive-ingest: inbox insert threw", err);
  }

  return Response.json({ ok: true });
});
