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

BASE_URL = "http://localhost:8000"
PRODUCT_DESCRIPTION = "We build custom AI agents, LangGraph-based workflows, and AI-powered automation systems for businesses that want to save time, reduce manual work, and integrate LLMs into their operations."


def test_qualify_returns_valid_response():
    """/qualify should always return a 200 with a lead_id and a valid status."""
    response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "Slack",
        "company_description": "a business team communication and collaboration platform",
        "product_description": PRODUCT_DESCRIPTION
    })

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
    })
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
    })
    qualify_data = qualify_response.json()

    if qualify_data["status"] != "pending_review":
        pytest.skip("Lead did not qualify this run, cannot test review flow")

    lead_id = qualify_data["lead_id"]

    review_response = requests.post(f"{BASE_URL}/review", json={
        "lead_id": lead_id,
        "company_name": "HubSpot",
        "is_approved": True,
        "human_feedback": ""
    })

    assert review_response.status_code == 200
    review_data = review_response.json()
    assert review_data["status"] == "approved"
    assert review_data["is_approved"] is True


def test_pending_escalations_returns_list():
    """/pending-escalations should always return a list (even if empty)."""
    response = requests.get(f"{BASE_URL}/pending-escalations")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_qualify_missing_fields_is_rejected():
    """Sending an incomplete request should fail validation, not crash the server."""
    response = requests.post(f"{BASE_URL}/qualify", json={
        "company_name": "IncompleteCo"
        # missing company_description on purpose
    })
    assert response.status_code == 422
