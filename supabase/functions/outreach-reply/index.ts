// CeliacMap — Outreach Agent Etapa 2: reply webhook.
//
// Receives Resend's `email.received` event when a business replies to an
// Etapa 1 confirmation email (see agents/outreach_agent.py). This function
// does webhook mechanics ONLY — signature verification, place_id matching,
// fetching the real email body, and persistence — and never calls an LLM
// itself. The actual re-evaluation against the Validator rubric happens in
// Python (agents/outreach_reply_handler.py), reusing RUBRIC and
// ValidatorAgent._normalize unmodified, triggered via a GitHub
// repository_dispatch event fired at the end of this handler. See
// CLAUDE.md's "Outreach reply webhook (Etapa 2) design decisions" for the
// full rationale (why this split, not a TypeScript port of the rubric).
//
// Response codes are deliberate, for correct Resend retry behavior:
//   401 - signature verification failed. No writes, no dispatch.
//   200 - verified but not actionable (wrong event type, no place_id match,
//         place not found, or place already resolved). Not retried.
//   500 - verified and actionable but a step failed. Retryable — Resend
//         redelivers the webhook on any non-2xx response.
//
// Required secrets (`supabase secrets set`, separate from .env / GitHub
// Actions secrets): RESEND_API_KEY, RESEND_WEBHOOK_SECRET (the Svix signing
// secret from the Resend dashboard, format "whsec_..."), GITHUB_DISPATCH_TOKEN
// (fine-grained PAT scoped to this repo only). SUPABASE_URL and
// SUPABASE_SERVICE_ROLE_KEY are auto-injected by the platform.

import { Resend } from "npm:resend@4";
import { createClient } from "npm:@supabase/supabase-js@2";

const GITHUB_REPO = "santisanchez4/CeliacMap";
const REPLY_TO_RE =
  /^outreach\+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})@/;

// Reject a webhook whose timestamp is further than this from "now", to
// block replay of a captured request (standard Svix guidance).
const MAX_TIMESTAMP_SKEW_SECONDS = 5 * 60;

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Manual Svix HMAC-SHA256 verification (see docs.svix.com/receiving/verifying-payloads/how-manual).
 * Implemented directly against Web Crypto rather than a library so the exact
 * algorithm is auditable here — this is the one security-critical check in
 * this function. */
async function verifySvixSignature(
  rawBody: string,
  headers: Headers,
  secret: string,
): Promise<boolean> {
  const svixId = headers.get("svix-id");
  const svixTimestamp = headers.get("svix-timestamp");
  const svixSignature = headers.get("svix-signature");
  if (!svixId || !svixTimestamp || !svixSignature) return false;

  const now = Math.floor(Date.now() / 1000);
  const ts = parseInt(svixTimestamp, 10);
  if (!Number.isFinite(ts) || Math.abs(now - ts) > MAX_TIMESTAMP_SKEW_SECONDS) {
    return false;
  }

  const secretBytes = base64ToBytes(secret.replace(/^whsec_/, ""));
  const key = await crypto.subtle.importKey(
    "raw",
    secretBytes.buffer.slice(secretBytes.byteOffset, secretBytes.byteOffset + secretBytes.byteLength) as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signedContent = `${svixId}.${svixTimestamp}.${rawBody}`;
  const sigBytes = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signedContent)),
  );
  const expected = bytesToBase64(sigBytes);

  // svix-signature can carry multiple space-separated "v1,<base64>" entries
  // (key rotation); any match is valid.
  return svixSignature
    .split(" ")
    .map((part) => part.replace(/^v1,/, ""))
    .some((candidate) => timingSafeEqual(candidate, expected));
}

export function extractPlaceId(toAddresses: string[]): string | null {
  for (const addr of toAddresses) {
    const match = REPLY_TO_RE.exec(addr.trim().toLowerCase());
    if (match) return match[1];
  }
  return null;
}

async function fetchReplyText(resend: Resend, emailId: string): Promise<string> {
  // resend@4.8.0's typed SDK has no emails.receiving namespace yet (confirmed
  // via `deno check` against the actual installed package — an earlier
  // assumption based on Resend's docs alone was wrong). Resend.get<T>() is
  // the SDK's own public low-level method (every typed resource, e.g.
  // Emails.get, is implemented as a thin wrapper over it), so this calls the
  // documented REST endpoint (GET /emails/receiving/{id}) directly through it.
  const { data, error } = await resend.get<{ text?: string; html?: string }>(
    `/emails/receiving/${emailId}`,
  );
  if (error || !data) {
    throw new Error(`Resend GET /emails/receiving/${emailId} failed: ${error?.message}`);
  }
  const text = data.text;
  if (text && text.trim()) return text.trim();
  const html = data.html;
  return (html ?? "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

async function triggerRevalidation(placeId: string, token: string): Promise<void> {
  const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      event_type: "outreach_reply_received",
      client_payload: { place_id: placeId },
    }),
  });
  if (!res.ok) {
    throw new Error(`GitHub dispatch failed: ${res.status} ${await res.text()}`);
  }
}

export async function handleRequest(req: Request): Promise<Response> {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  // Raw body text is required for signature verification — parsing to JSON
  // and re-stringifying would produce different bytes and break the check.
  const rawBody = await req.text();

  const webhookSecret = Deno.env.get("RESEND_WEBHOOK_SECRET") ?? "";
  const verified = webhookSecret
    ? await verifySvixSignature(rawBody, req.headers, webhookSecret)
    : false;
  if (!verified) {
    return new Response("Invalid signature", { status: 401 });
  }

  let payload: {
    type?: string;
    data?: { email_id?: string; to?: string[] };
  };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response("Bad payload", { status: 200 }); // not actionable, not retryable
  }

  if (payload.type !== "email.received") {
    return new Response("Ignored event type", { status: 200 });
  }

  const emailId = payload.data?.email_id;
  const toAddresses = payload.data?.to ?? [];
  const placeId = emailId ? extractPlaceId(toAddresses) : null;
  if (!emailId || !placeId) {
    return new Response("No matching place_id in reply-to", { status: 200 });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const supabase = createClient(supabaseUrl, supabaseKey);

  const { data: place, error: placeError } = await supabase
    .from("places")
    .select("id, status")
    .eq("id", placeId)
    .maybeSingle();

  if (placeError) {
    return new Response(`Supabase read failed: ${placeError.message}`, { status: 500 });
  }
  if (!place) {
    return new Response("Unknown place_id", { status: 200 });
  }
  if (!["needs_review", "outreach_confirmed"].includes(place.status)) {
    // Already resolved (approved/discarded) — a duplicate/late reply must
    // not re-trigger a stale re-evaluation.
    return new Response(`Place already resolved (status=${place.status})`, { status: 200 });
  }

  const resend = new Resend(Deno.env.get("RESEND_API_KEY") ?? "");

  let replyText: string;
  try {
    replyText = await fetchReplyText(resend, emailId);
  } catch (err) {
    return new Response(`Content fetch failed: ${err}`, { status: 500 });
  }

  const { error: insertError } = await supabase.from("outreach_messages").insert({
    place_id: placeId,
    direction: "received",
    channel: "email",
    content: replyText,
    external_id: emailId,
  });
  // Unique violation on (place_id, external_id) means this exact reply was
  // already recorded (a Resend redelivery) — treat as success, not an error.
  if (insertError && insertError.code !== "23505") {
    return new Response(`Persisting reply failed: ${insertError.message}`, { status: 500 });
  }

  const { error: updateError } = await supabase
    .from("places")
    .update({ outreach_status: "replied" })
    .eq("id", placeId);
  if (updateError) {
    return new Response(`Updating outreach_status failed: ${updateError.message}`, {
      status: 500,
    });
  }

  const githubToken = Deno.env.get("GITHUB_DISPATCH_TOKEN") ?? "";
  try {
    await triggerRevalidation(placeId, githubToken);
  } catch (err) {
    return new Response(`Dispatch failed: ${err}`, { status: 500 });
  }

  return new Response("OK", { status: 200 });
}

// Only start the HTTP server when this file is run directly (the real Edge
// Function entrypoint) — not when it's imported, e.g. by index.test.ts,
// which would otherwise try to bind a port under the test runner's sandbox.
if (import.meta.main) {
  Deno.serve(handleRequest);
}
