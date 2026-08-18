"""
Braintrust evaluation for Research_company (research accuracy).

WHAT THIS CHECKS:
Does Research_company actually find the RIGHT company's website, or does
it sometimes latch onto an unrelated company's data (like the real "Zeevou"
bug we found and fixed earlier today)?

HOW IT WORKS (plain words):
1. "dataset"  = a list of real companies we already know the correct answer for
2. "task"     = calls your actual Research_company function on each one
3. "scorer"   = a small function that checks: does the returned company_website
                actually contain the target company's name? If Research_company
                ever returns a completely different company's website, this
                scorer catches it automatically - no human needs to notice by hand.

This file does NOT touch agent.py, main.py, or database.py - it only IMPORTS
and calls Research_company to test it from the outside, same as our pytest
tests do for the API endpoints.

HOW TO RUN:
    python3 eval_research.py
Then check the results at https://www.braintrust.dev
"""

import asyncio
import config  # loads .env, including BRAINTRUST_API_KEY
from braintrust import EvalAsync
from agent import Research_company


# Real companies with a KNOWN correct website, so we can check if the
# research step got confused and returned the wrong company's data instead.
dataset = [
    {"company_name": "Airbnb", "company_description": "an online marketplace for lodging and travel experiences", "expected_domain": "airbnb"},
    {"company_name": "Stripe", "company_description": "a payment infrastructure company", "expected_domain": "stripe"},
    {"company_name": "Slack", "company_description": "a business team communication and collaboration platform", "expected_domain": "slack"},
    {"company_name": "HubSpot", "company_description": "a CRM and marketing automation platform", "expected_domain": "hubspot"},
    {"company_name": "Zoom", "company_description": "a video conferencing and communication platform", "expected_domain": "zoom"},
]


async def task(input):
    """Runs the REAL Research_company node, exactly as it runs in production."""
    state = {
        "company_name": input["company_name"],
        "company_description": input["company_description"],
    }
    result = await Research_company(state)
    return result


def company_website_matches_scorer(input, output, expected):
    """
    Checks whether the researched company_website actually belongs to the
    target company - the exact check that would have caught the Zeevou bug.
    """
    target_domain = expected["expected_domain"].lower()
    website = (output.get("company_website") or "").lower()

    matched = target_domain in website
    return {
        "name": "company_website_matches",
        "score": 1.0 if matched else 0.0,
    }


async def main():
    await EvalAsync(
        "AI_lead_qualification",
        data=lambda: [
            {
                "input": row,
                "expected": row,
            }
            for row in dataset
        ],
        task=task,
        scores=[company_website_matches_scorer],
    )


if __name__ == "__main__":
    asyncio.run(main())
