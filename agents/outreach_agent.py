"""Outreach agent — Etapa 1 (``outreach_send``) of the Outreach Agent.

Closes the gap where places sit indefinitely in ``needs_review`` (the
Validator's evidence floor, ADR-001) by contacting the business directly to
ask for confirmation. Per
``docs/architecture/ADR-002-outreach-evidence-not-autoapproval.md``, this
agent never approves anything itself — it only gathers a new piece of
evidence (the business's reply, handled by a separate, not-yet-built
``outreach_reply_handler``) for the Validator to re-weigh later.

Approach, per candidate:

1. Select the oldest ``needs_review`` places that still have
   ``outreach_status='not_sent'`` and a ``phone`` or ``website`` on file (a
   place with neither is unlikely to be reachable at all).
2. Draft a short confirmation email with ``claude-haiku-4-5`` (same
   fixed-rubric + JSON-contract pattern as the Social agent's ``PARSE_RUBRIC``).
3. Send it via Resend. **Sandbox note:** without a verified sending domain,
   every email currently goes to a fixed ``test_recipient`` regardless of the
   place's own contact info — Google Places has no email field, and Resend's
   shared sandbox sender can only deliver to the account's own verified
   address anyway (see CLAUDE.md's Outreach agent design decisions).
4. On success, record the sent message in ``outreach_messages`` and flip
   ``places.outreach_status`` to ``'sent'`` (channel ``'email'``) so the place
   isn't re-contacted every run. On failure, nothing is written — the place
   stays ``'not_sent'`` and is naturally retried on a later run.

Every outcome and a final run summary are written to ``agent_log``.
"""

from __future__ import annotations

import logging

from agents.base import BaseAgent
from agents.clients.llm import LLMClient
from agents.clients.resend_client import ResendClient
from agents.clients.supabase_client import SupabaseClient

logger = logging.getLogger("celiacmap.agent")

# Oldest-first batch fetched before the phone/website filter is applied in
# Python (no precedent for an OR-filter query string in supabase_client.py;
# needs_review volume has historically been small — tens, not thousands).
CANDIDATE_FETCH_LIMIT = 200

# Haiku rubric: draft a short, respectful sin-TACC confirmation email.
OUTREACH_RUBRIC = """\
Redactás un email breve y respetuoso en nombre de CeliacMap, un proyecto \
comunitario que mapea lugares gluten free / sin TACC en Uruguay y Argentina, \
dirigido a un comercio que aparece como candidato en el mapa pero todavía no \
tiene evidencia suficiente confirmada.

Se te da el nombre del comercio, su categoría y su ciudad. El email debe:
- Presentar brevemente a CeliacMap (un mapa comunitario, no una entidad oficial).
- Pedir amablemente que confirmen si ofrecen opciones sin TACC y, si es \
posible, que describan su protocolo de contaminación cruzada.
- Ser breve (2-3 párrafos cortos), cordial, sin sonar a spam ni a exigencia.
- Firmarse como "Equipo de CeliacMap".

Respondé ÚNICAMENTE con un objeto JSON válido, sin texto adicional, exactamente \
con esta forma:
{"subject": "<asunto breve>", "body": "<cuerpo del email en texto plano>"}
"""


class OutreachAgent(BaseAgent):
    name = "outreach"

    def __init__(
        self,
        db: SupabaseClient,
        llm: LLMClient,
        resend_client: ResendClient,
        *,
        test_recipient: str,
        haiku_model: str | None = None,
        max_per_run: int = 20,
    ):
        super().__init__(db)
        self.llm = llm
        self.resend = resend_client
        self.test_recipient = test_recipient
        self.haiku_model = haiku_model
        self.max_per_run = max_per_run

    def _select_candidates(self) -> list[dict]:
        candidates = self.db.fetch_needs_review_for_outreach(CANDIDATE_FETCH_LIMIT)
        reachable = [p for p in candidates if p.get("phone") or p.get("website")]
        return reachable[: self.max_per_run]

    def _draft(self, place: dict) -> dict | None:
        """Use Haiku to draft {subject, body}. Returns None if invalid."""
        user = (
            f"place_name: {place.get('name')}\n"
            f"category: {place.get('category')}\n"
            f"city: {place.get('city') or ''}"
        )
        try:
            draft = self.llm.complete_json(
                OUTREACH_RUBRIC, user, model=self.haiku_model, max_tokens=400
            )
        except Exception:  # noqa: BLE001
            logger.exception("Haiku draft failed for %r", place.get("name"))
            return None

        subject = (draft.get("subject") or "").strip()
        body = (draft.get("body") or "").strip()
        if not subject or not body:
            return None
        return {"subject": subject, "body": body}

    def run(self) -> dict:
        candidates = self._select_candidates()

        candidates_seen = len(candidates)
        drafted = 0
        sent = 0
        errors = 0

        for place in candidates:
            place_id = place.get("id")

            draft = self._draft(place)
            if not draft:
                errors += 1
                self.log(
                    "outreach_draft_failed",
                    {"place_id": place_id, "name": place.get("name")},
                    status="error",
                    place_id=place_id,
                )
                continue
            drafted += 1

            try:
                self.resend.send(
                    to=self.test_recipient,
                    subject=draft["subject"],
                    text=draft["body"],
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.exception("Resend send failed for place %s", place_id)
                self.log(
                    "outreach_send_failed",
                    {"place_id": place_id, "name": place.get("name"), "error": str(exc)},
                    status="error",
                    place_id=place_id,
                )
                continue

            try:
                self.db.insert_outreach_message(
                    place_id,
                    direction="sent",
                    channel="email",
                    content=f"{draft['subject']}\n\n{draft['body']}",
                )
                self.db.update_place(
                    place_id, {"outreach_status": "sent", "outreach_channel": "email"}
                )
            except Exception:  # noqa: BLE001
                errors += 1
                logger.exception("failed to persist outreach result for %s", place_id)
                self.log(
                    "outreach_persist_failed",
                    {"place_id": place_id, "name": place.get("name")},
                    status="error",
                    place_id=place_id,
                )
                continue

            sent += 1
            self.log(
                "outreach_sent",
                {"place_id": place_id, "name": place.get("name")},
                status="success",
                place_id=place_id,
            )

        summary = {
            "candidates_seen": candidates_seen,
            "drafted": drafted,
            "sent": sent,
            "errors": errors,
        }
        self.log(
            "outreach_run_complete",
            summary,
            status="error" if errors else "success",
        )
        return summary


def main() -> int:
    """Run the Outreach agent standalone (manual pipeline validation)."""
    from config.settings import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = get_settings()
    settings.require(
        "supabase_url",
        "supabase_service_role_key",
        "anthropic_api_key",
        "resend_api_key",
        "outreach_test_recipient",
    )

    db = SupabaseClient(settings.supabase_url, settings.supabase_service_role_key)
    llm = LLMClient(settings.anthropic_api_key, settings.haiku_model)
    resend_client = ResendClient(settings.resend_api_key)
    agent = OutreachAgent(
        db,
        llm,
        resend_client,
        test_recipient=settings.outreach_test_recipient,
        haiku_model=settings.haiku_model,
        max_per_run=settings.outreach_monthly_limit,
    )

    summary = agent.run()
    print("Outreach run complete:", summary)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
