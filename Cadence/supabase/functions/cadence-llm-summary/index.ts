// Cadence Supabase Edge Function: cadence-llm-summary
//
// Deploy: supabase functions deploy cadence-llm-summary --project-ref vzrasadomyrycafbzdwg
//        supabase secrets set GROQ_API_KEY=... --project-ref vzrasadomyrycafbzdwg
//
// Background job that periodically reads the latest journeys from
// journeys_mirror, asks the LLM for a one-line merchant-facing
// summary, and writes it back. In a real product this would be a
// cron / Supabase scheduled function. In demo mode this
// runs on demand via a curl to the function URL.
//
// @ts-nocheck

const GROQ_API_KEY = Deno.env.get("GROQ_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const GROQ_MODEL = Deno.env.get("GROQ_MODEL") ?? "openai/gpt-oss-120b";
const CADENCE_ENGINE_TOKEN = Deno.env.get("CADENCE_ENGINE_TOKEN") ?? "";
const JOURNEYS_TABLE = "journeys_mirror";
const SUMMARY_TABLE = "journey_summaries";

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method !== "POST") {
    return new Response("use POST", { status: 405 });
  }
  // S5: require a bearer token. Anyone with the function URL could
  // otherwise burn the Groq quota and write into journey_summaries.
  // The local engine sends `Authorization: Bearer <CADENCE_ENGINE_TOKEN>`.
  if (!CADENCE_ENGINE_TOKEN) {
    return new Response(JSON.stringify({
      error: "CADENCE_ENGINE_TOKEN not configured",
      fix: "supabase secrets set CADENCE_ENGINE_TOKEN=... --project-ref <ref>",
    }), { status: 501, headers: { "content-type": "application/json" } });
  }
  const auth = req.headers.get("Authorization") ?? "";
  if (auth !== `Bearer ${CADENCE_ENGINE_TOKEN}`) {
    return new Response(JSON.stringify({ error: "unauthorized" }),
                        { status: 401, headers: { "content-type": "application/json" } });
  }
  if (!GROQ_API_KEY) {
    return new Response(JSON.stringify({ error: "GROQ_API_KEY not set" }), {
      status: 503, headers: { "content-type": "application/json" },
    });
  }
  if (!SUPABASE_URL || !SERVICE_KEY) {
    return new Response(JSON.stringify({ error: "SUPABASE_URL or SERVICE_KEY not set" }), {
      status: 503, headers: { "content-type": "application/json" },
    });
  }
  // Read the latest journeys (most recent first, up to 20)
  const j = await fetch(
    `${SUPABASE_URL}/rest/v1/${JOURNEYS_TABLE}?select=journey_id,subscription_id,customer_id,amount_minor,state,root_cause,updated_at&order=updated_at.desc&limit=20`,
    { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
  );
  if (!j.ok) {
    return new Response(JSON.stringify({ error: `journeys read failed: ${j.status}` }), {
      status: 502, headers: { "content-type": "application/json" },
    });
  }
  const journeys: any[] = await j.json();
  const summaries: { id: string; ok: boolean; summary?: string; err?: string }[] = [];
  for (const jn of journeys) {
    const prompt = `Summarize this Cadence recovery journey in one sentence for a merchant support team. Journey ${jn.journey_id} is in state ${jn.state}, root cause ${jn.root_cause ?? "unknown"}, amount ${(jn.amount_minor / 100).toFixed(2)} INR.`;
    const g = await fetch(
      "https://api.groq.com/openai/v1/chat/completions",
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${GROQ_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: GROQ_MODEL,
          messages: [
            {
              role: "system",
              content: "You write a single concise plain-English sentence for a merchant support team. Be specific (include the state, the root cause, the amount).",
            },
            { role: "user", content: prompt },
          ],
          max_tokens: 120,
          response_format: { type: "json_object" },
        }),
      },
    );
    if (!g.ok) {
      summaries.push({ id: jn.journey_id, ok: false, err: `groq ${g.status}` });
      continue;
    }
    const gj = await g.json();
    const txt = gj?.choices?.[0]?.message?.content ?? "{}";
    let summary = txt;
    try {
      const obj = JSON.parse(txt);
      summary = obj.summary ?? txt;
    } catch { /* keep raw */ }
    // Upsert into the summary table
    await fetch(
      `${SUPABASE_URL}/rest/v1/${SUMMARY_TABLE}?on_conflict=journey_id`,
      {
        method: "POST",
        headers: {
          apikey: SERVICE_KEY,
          Authorization: `Bearer ${SERVICE_KEY}`,
          "Content-Type": "application/json",
          "Prefer": "resolution=merge-duplicates",
        },
        body: JSON.stringify({
          journey_id: jn.journey_id,
          summary,
          generated_at: new Date().toISOString(),
          model: GROQ_MODEL,
        }),
      },
    );
    summaries.push({ id: jn.journey_id, ok: true, summary });
  }
  return new Response(JSON.stringify({ ok: true, generated: summaries.length, summaries }), {
    status: 200, headers: { "content-type": "application/json" },
  });
});
