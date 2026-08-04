"""Thin wrapper around the Resend API for the Outreach agent.

Sends the confirmation email drafted by the Outreach agent to a business in
``needs_review``. The ``resend`` SDK is process-global (``resend.api_key = ...``)
rather than a per-instance client like ``googlemaps.Client`` / ``TavilyClient`` /
``anthropic.Anthropic`` — this wrapper still presents the same per-instance shape
at the call site, on the assumption that only one instance is ever live per
process (true today: the orchestrator builds exactly one).

Sandbox note: without a verified sending domain, ``onboarding@resend.dev`` can
only deliver to the email address that owns the Resend account — not to
arbitrary businesses. The Outreach agent currently sends every message to a
fixed test recipient for this reason (see CLAUDE.md's Outreach agent design
decisions).
"""

from __future__ import annotations

import resend

# Resend's shared sandbox sender — usable without verifying a custom domain,
# but restricted to delivering only to the account's own verified email.
SANDBOX_FROM = "onboarding@resend.dev"


class ResendClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ResendClient requires a Resend API key.")
        resend.api_key = api_key

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        from_address: str = SANDBOX_FROM,
        reply_to: str | None = None,
    ) -> str:
        """Send one email. Returns the Resend message id.

        reply_to (Outreach Etapa 2): a unique outreach+<place_id>@<inbound
        domain>.resend.app address so a business's reply can be matched back
        to its place by the reply webhook. Omitted from the payload entirely
        when not set, rather than passed as a literal None.

        Raises RuntimeError on any transport/API error so the caller can log
        and continue, matching TavilySearchClient.search's contract.
        """
        payload = {
            "from": from_address,
            "to": [to],
            "subject": subject,
            "text": text,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        try:
            result = resend.Emails.send(payload)
        except Exception as exc:  # noqa: BLE001 - normalize any SDK/transport error
            raise RuntimeError(f"Resend send failed for {to!r}: {exc}") from exc
        return result["id"]
