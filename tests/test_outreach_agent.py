"""Unit tests for the Outreach agent (offline, all external calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.outreach_agent import OutreachAgent


def make_place(
    id="place-1",
    name="Cafe X",
    category="cafe",
    city="Montevideo",
    phone="099123456",
    website=None,
):
    return {
        "id": id,
        "name": name,
        "category": category,
        "city": city,
        "phone": phone,
        "website": website,
    }


def make_agent(max_per_run=20, test_recipient="dev@example.com"):
    db = MagicMock()
    db.fetch_needs_review_for_outreach.return_value = [make_place()]
    db.insert_outreach_message.return_value = {"id": "msg-1"}
    llm = MagicMock()
    llm.complete_json.return_value = {
        "subject": "Confirmacion sin TACC - Cafe X",
        "body": "Hola, somos el equipo de CeliacMap...",
    }
    resend_client = MagicMock()
    resend_client.send.return_value = "email-1"
    agent = OutreachAgent(
        db,
        llm,
        resend_client,
        test_recipient=test_recipient,
        max_per_run=max_per_run,
    )
    return agent, db, llm, resend_client


# --- Selection filter -------------------------------------------------------


def test_select_candidates_keeps_phone_or_website():
    agent, db, _, _ = make_agent()
    db.fetch_needs_review_for_outreach.return_value = [
        make_place(id="p1", phone="099", website=None),
        make_place(id="p2", phone=None, website="https://x.com"),
        make_place(id="p3", phone=None, website=None),
    ]
    selected = agent._select_candidates()
    assert [p["id"] for p in selected] == ["p1", "p2"]


def test_select_candidates_respects_cap():
    agent, db, _, _ = make_agent(max_per_run=1)
    db.fetch_needs_review_for_outreach.return_value = [
        make_place(id="p1"),
        make_place(id="p2"),
    ]
    selected = agent._select_candidates()
    assert len(selected) == 1


# --- Drafting ----------------------------------------------------------------


def test_draft_returns_none_on_llm_error():
    agent, _, llm, _ = make_agent()
    llm.complete_json.side_effect = RuntimeError("boom")
    assert agent._draft(make_place()) is None


def test_draft_returns_none_on_empty_subject_or_body():
    agent, _, llm, _ = make_agent()
    llm.complete_json.return_value = {"subject": "", "body": "algo"}
    assert agent._draft(make_place()) is None
    llm.complete_json.return_value = {"subject": "algo", "body": ""}
    assert agent._draft(make_place()) is None


# --- Happy path ----------------------------------------------------------------


def test_successful_draft_and_send():
    agent, db, llm, resend_client = make_agent()

    summary = agent.run()

    assert summary["candidates_seen"] == 1
    assert summary["drafted"] == 1
    assert summary["sent"] == 1
    assert summary["errors"] == 0

    resend_client.send.assert_called_once_with(
        to="dev@example.com",
        subject="Confirmacion sin TACC - Cafe X",
        text="Hola, somos el equipo de CeliacMap...",
    )
    db.insert_outreach_message.assert_called_once()
    call = db.insert_outreach_message.call_args
    assert call.args[0] == "place-1"
    assert call.kwargs["direction"] == "sent"
    assert call.kwargs["channel"] == "email"

    db.update_place.assert_called_once_with(
        "place-1", {"outreach_status": "sent", "outreach_channel": "email"}
    )


# --- Error handling ------------------------------------------------------------


def test_candidate_without_contact_is_skipped():
    agent, db, llm, resend_client = make_agent()
    db.fetch_needs_review_for_outreach.return_value = [
        make_place(phone=None, website=None)
    ]

    summary = agent.run()

    assert summary["candidates_seen"] == 0
    assert summary["drafted"] == 0
    llm.complete_json.assert_not_called()
    resend_client.send.assert_not_called()


def test_draft_failure_is_counted_and_no_send_attempted():
    agent, db, llm, resend_client = make_agent()
    llm.complete_json.side_effect = RuntimeError("boom")

    summary = agent.run()

    assert summary["errors"] == 1
    assert summary["drafted"] == 0
    assert summary["sent"] == 0
    resend_client.send.assert_not_called()
    db.insert_outreach_message.assert_not_called()


def test_send_failure_leaves_no_db_writes():
    agent, db, llm, resend_client = make_agent()
    resend_client.send.side_effect = RuntimeError("resend down")

    summary = agent.run()

    assert summary["errors"] == 1
    assert summary["drafted"] == 1
    assert summary["sent"] == 0
    db.insert_outreach_message.assert_not_called()
    db.update_place.assert_not_called()


# --- Budget / cap ---------------------------------------------------------------


def test_zero_cap_does_nothing():
    agent, db, llm, resend_client = make_agent(max_per_run=0)

    summary = agent.run()

    assert summary == {
        "candidates_seen": 0,
        "drafted": 0,
        "sent": 0,
        "errors": 0,
    }
    llm.complete_json.assert_not_called()
    resend_client.send.assert_not_called()
