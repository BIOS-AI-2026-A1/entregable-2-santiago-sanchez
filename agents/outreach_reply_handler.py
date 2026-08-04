"""Outreach agent — Etapa 2 (``outreach_reply_handler``).

Triggered by a GitHub ``repository_dispatch`` event fired from the Supabase
Edge Function (``supabase/functions/outreach-reply/``) when a business
replies to an Etapa 1 confirmation email — never by the monthly cron.

Re-evaluates a single ``needs_review`` place after a reply arrives,
combining the original evidence with the reply through the *same* Validator
rubric (``RUBRIC``, ``ValidatorAgent._normalize``) — zero duplicated
rubric/gate logic. Per
``docs/architecture/ADR-002-outreach-evidence-not-autoapproval.md``, a
high-confidence combined verdict lands in ``'outreach_confirmed'``, never
directly ``'approved'``; ``'discarded'`` and ``'needs_review'`` pass through
unchanged, since a genuinely disqualifying reply should still be able to
discard a place (ADR-001's own conservative gate), not just bounce it back.
"""

from __future__ import annotations

import argparse
import logging

from agents.base import BaseAgent
from agents.clients.llm import LLMClient
from agents.clients.supabase_client import SupabaseClient
from agents.validator_agent import RUBRIC, ValidatorAgent

logger = logging.getLogger("celiacmap.agent")

# Statuses a reply is still allowed to act on: a place already resolved
# (approved/discarded) or already confirmed by an earlier reply must not be
# re-evaluated by a duplicate/late/redelivered webhook.
ACTIONABLE_STATUSES = ("needs_review", "outreach_confirmed")


def _build_reply_prompt(place: dict, reviews: list[dict], reply_text: str) -> str:
    base = ValidatorAgent._build_user_prompt(place, reviews)
    return (
        f"{base}\n\n"
        "Respuesta directa del comercio (auto-reportada vía email; el comercio "
        "tiene incentivo económico en confirmar — pesar con la misma cautela que "
        "cualquier fuente con sesgo, nunca como confirmación automática):\n"
        f"{reply_text}"
    )


class OutreachReplyHandler(BaseAgent):
    name = "outreach_reply"

    def __init__(self, db: SupabaseClient, llm: LLMClient):
        super().__init__(db)
        self.llm = llm
        self.validator = ValidatorAgent(db, llm)  # reused only for ._normalize()

    def handle(self, place_id: str) -> dict:
        place = self.db.fetch_place_by_id(place_id)
        if not place:
            self.log(
                "outreach_reply_unknown_place",
                {"place_id": place_id},
                status="error",
            )
            return {"skipped": "place not found"}

        if place.get("status") not in ACTIONABLE_STATUSES:
            self.log(
                "outreach_reply_skipped_wrong_status",
                {"place_id": place_id, "status": place.get("status")},
                status="success",
                place_id=place_id,
            )
            return {"skipped": f"status={place.get('status')}"}

        message = self.db.fetch_latest_received_message(place_id)
        reply_text = (message.get("content") or "").strip() if message else ""
        if not reply_text:
            self.log(
                "outreach_reply_no_content",
                {"place_id": place_id},
                status="error",
                place_id=place_id,
            )
            return {"skipped": "no reply content"}

        try:
            reviews = self.db.fetch_reviews_for_place(place_id)
        except Exception:  # noqa: BLE001 - review context is best-effort
            logger.exception("fetching review context failed for %s", place_id)
            reviews = []

        prompt = _build_reply_prompt(place, reviews, reply_text)

        try:
            raw_verdict = self.llm.complete_json(RUBRIC, prompt)
            v = self.validator._normalize(raw_verdict, place)
        except Exception as exc:  # noqa: BLE001
            logger.exception("reply re-evaluation failed for %s", place_id)
            self.log(
                "outreach_reply_evaluate_failed",
                {"place_id": place_id, "error": str(exc)},
                status="error",
                place_id=place_id,
            )
            return {"skipped": "evaluation failed"}

        # Never directly 'approved' from a business's own reply (ADR-002);
        # 'needs_review' and 'discarded' pass through unchanged.
        db_status = "outreach_confirmed" if v["status"] == "approved" else v["status"]

        try:
            self.db.update_place_validation(
                place_id,
                status=db_status,
                confidence=v["confidence"],
                notes=v["reason"],
                category=v["category"],
                safety_level=v["safety_level"],
                flags=v["flags"],
                recommendation=v["recommendation"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("persisting reply verdict failed for %s", place_id)
            self.log(
                "outreach_reply_persist_failed",
                {"place_id": place_id, "error": str(exc)},
                status="error",
                place_id=place_id,
            )
            return {"skipped": "persist failed"}

        self.log(
            "outreach_reply_evaluated",
            {"place_id": place_id, "verdict": v["verdict"], "status": db_status},
            status="success",
            place_id=place_id,
        )
        return {"place_id": place_id, "status": db_status}


def main() -> int:
    """Run the reply handler for one place (invoked by the GitHub Actions
    workflow triggered from the Supabase Edge Function)."""
    from config.settings import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--place-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    settings.require("supabase_url", "supabase_service_role_key", "anthropic_api_key")
    db = SupabaseClient(settings.supabase_url, settings.supabase_service_role_key)
    llm = LLMClient(settings.anthropic_api_key, settings.validator_model)

    result = OutreachReplyHandler(db, llm).handle(args.place_id)
    print("Outreach reply handled:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
