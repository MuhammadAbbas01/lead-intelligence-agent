"""
Automated tests for the Lead Intelligence Agent API.

This file does NOT touch main.py, agent.py, or database.py.
It simply sends real requests to your ALREADY RUNNING server
(same as we've been doing by hand with curl all day) and checks
the responses automatically, instead of a human reading them.

HOW TO RUN:
    1. Make sure your server is running:  uvicorn main:app
    2. In another terminal, run:          pytest test_main.py -v

Since this system calls a real AI model and a real database, results
like the exact qualify_score will vary each run - so these tests check
STRUCTURE (status codes, expected fields present, correct types) rather
than exact values. That's the normal way to test an AI-backed system.
"""

import requests
import pytest
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("APP_API_KEY")
HEADERS = {"X-API-KEY": API_KEY}

BASE_URL = "http://localhost:8000"
PRODUCT_DESCRIPTION = "We build custom AI agents, LangGraph-based workflows, and AI-powered automation systems for businesses that want to save time, reduce manual work, and integrate LLMs into their operations."


def test_qualify_returns_valid_response():
    """/qualify should always return a 200 with a lead_id and a valid status."""
    response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "Slack",
        "company_description": "a business team communication and collaboration platform",
        "product_description": PRODUCT_DESCRIPTION
    }, headers=HEADERS)

    assert response.status_code == 200

    data = response.json()
    assert "lead_id" in data
    assert data["lead_id"].startswith("LEAD-")
    assert data["status"] in ["pending_review", "not_qualified"]
    assert "qualify_score" in data


def test_qualify_pending_review_has_email():
    """If a lead qualifies, it must come back with a real email subject and body."""
    response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "Stripe",
        "company_description": "a payment infrastructure company",
        "product_description": PRODUCT_DESCRIPTION
    }, headers=HEADERS)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    if data["status"] == "pending_review":
        assert data.get("email_subject")
        assert data.get("email_body")
        assert len(data["email_body"]) > 10


def test_review_approve_flow():
    """A full cycle: qualify a lead, then approve it, and check the response is correct."""
    qualify_response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "HubSpot",
        "company_description": "a CRM and marketing automation platform",
        "product_description": PRODUCT_DESCRIPTION
    }, headers=HEADERS)
    assert qualify_response.status_code == 200, f"Expected 200, got {qualify_response.status_code}: {qualify_response.text}"
    qualify_data = qualify_response.json()

    if qualify_data["status"] != "pending_review":
        pytest.skip("Lead did not qualify this run, cannot test review flow")

    lead_id = qualify_data["lead_id"]

    review_response = requests.post(f"{BASE_URL}/review", json={
        "lead_id": lead_id,
        "company_name": "HubSpot",
        "is_approved": True,
        "human_feedback": ""
    }, headers=HEADERS)

    assert review_response.status_code == 200
    review_data = review_response.json()
    assert review_data["status"] == "approved"
    assert review_data["is_approved"] is True


def test_pending_escalations_returns_list():
    """/pending-escalations should always return a list (even if empty)."""
    response = requests.get(f"{BASE_URL}/pending-escalations", headers=HEADERS)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_qualify_missing_fields_is_rejected():
    """Sending an incomplete request should fail validation, not crash the server."""
    response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "IncompleteCo"
        # missing company_description on purpose
    }, headers=HEADERS)
    assert response.status_code == 422


def test_escalation_after_three_rejections():
    """A lead rejected 3 times in a row must escalate to a human, then be
    resolvable via the manual-email route - the full unhappy path, not just
    the happy path the other tests cover."""
    qualify_response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "Zendesk",
        "company_description": "a customer service and support ticketing platform",
        "product_description": PRODUCT_DESCRIPTION
    }, headers=HEADERS)
    assert qualify_response.status_code == 200, f"Expected 200, got {qualify_response.status_code}: {qualify_response.text}"
    qualify_data = qualify_response.json()

    if qualify_data["status"] != "pending_review":
        pytest.skip("Lead did not qualify this run, cannot test escalation flow")

    lead_id = qualify_data["lead_id"]

    # Reject the same lead 3 times - max_attempts is 3, so the 3rd rejection
    # should trigger escalation instead of another rewrite.
    last_response = None
    for attempt in range(3):
        last_response = requests.post(f"{BASE_URL}/review", json={
            "lead_id": lead_id,
            "company_name": "Zendesk",
            "is_approved": False,
            "human_feedback": "still not good enough, try again"
        }, headers=HEADERS)
        assert last_response.status_code == 200, f"Rejection {attempt + 1} failed: {last_response.status_code}: {last_response.text}"

    final_data = last_response.json()
    assert final_data["status"] == "escalated"
    assert final_data.get("escalation_summary")

    # It should now show up in the human-escalation queue.
    pending_response = requests.get(f"{BASE_URL}/pending-escalations", headers=HEADERS)
    assert pending_response.status_code == 200
    pending_ids = [lead.get("lead_id") for lead in pending_response.json()]
    assert lead_id in pending_ids

    # A human resolves it manually - this should always succeed regardless
    # of what the LLM did, since it bypasses the agent entirely.
    resolve_response = requests.post(f"{BASE_URL}/submit-manual-email", json={
        "lead_id": lead_id,
        "email_subject": "Manually written follow-up",
        "email_body": "Writing this one by hand since the automated drafts didn't land."
    }, headers=HEADERS)
    assert resolve_response.status_code == 200
    resolve_data = resolve_response.json()
    assert resolve_data["status"] == "resolved"
