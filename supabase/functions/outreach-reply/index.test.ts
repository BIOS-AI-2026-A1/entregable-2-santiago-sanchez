// Unit tests for the pure/testable logic in index.ts (place_id extraction).
// Run with: deno test supabase/functions/outreach-reply/
//
// Does NOT exercise Deno.serve, signature verification, or any network call
// (Resend/Supabase/GitHub) — those require a real deployed environment and
// are covered by live verification instead (see CLAUDE.md's Etapa 2 build
// status entry).

import { assertEquals } from "jsr:@std/assert@1";
import { extractPlaceId } from "./index.ts";

const PLACE_ID = "7707c9e1-9837-4410-8c45-57f94fec8bb4";

Deno.test("extractPlaceId finds a matching outreach+<uuid>@ address", () => {
  const result = extractPlaceId([`outreach+${PLACE_ID}@abc123.resend.app`]);
  assertEquals(result, PLACE_ID);
});

Deno.test("extractPlaceId is case-insensitive on the uuid and domain", () => {
  const result = extractPlaceId([`Outreach+${PLACE_ID.toUpperCase()}@ABC123.RESEND.APP`]);
  assertEquals(result, PLACE_ID.toLowerCase());
});

Deno.test("extractPlaceId picks the matching address out of several recipients", () => {
  const result = extractPlaceId([
    "someone-else@example.com",
    `outreach+${PLACE_ID}@abc123.resend.app`,
  ]);
  assertEquals(result, PLACE_ID);
});

Deno.test("extractPlaceId returns null when no address matches the pattern", () => {
  const result = extractPlaceId(["hola@cafex.com", "info@cafex.com"]);
  assertEquals(result, null);
});

Deno.test("extractPlaceId returns null for a malformed / non-uuid suffix", () => {
  const result = extractPlaceId(["outreach+not-a-uuid@abc123.resend.app"]);
  assertEquals(result, null);
});

Deno.test("extractPlaceId returns null for an empty recipient list", () => {
  const result = extractPlaceId([]);
  assertEquals(result, null);
});
