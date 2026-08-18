"""
Braintrust evaluation for Qualify (scoring sensibility).

WHAT THIS CHECKS:
Does Qualify give sensible scores? An obviously good-fit company should
score high (7+), and an obviously bad-fit company should score low (below 7).

HOW IT WORKS:
1. "dataset" = fake but clear-cut company examples, with a known expected
               direction (high or low), so we're testing the JUDGMENT LOGIC,
               not memorizing real companies.
2. "task"    = calls your actual Qualify function on each one.
3. "scorer"  = checks if the real score's direction matches what we expected.

HOW TO RUN:
    python3 eval_qualify.py
Then check results at https://www.braintrust.dev
"""

import asyncio
import config
from braintrust import EvalAsync
from agent import Qualify

PRODUCT_DESCRIPTION = "We build custom AI agents, LangGraph-based workflows, and AI-powered automation systems for businesses that want to save time, reduce manual work, and integrate LLMs into their operations."


dataset = [
    {
        "company_name": "TechCorp AI",
        "company_info": "A fast-growing SaaS startup struggling to build reliable AI agent workflows in-house.",
        "company_website": "techcorp.ai",
        "company_problem": "Needs help building production-grade AI agents but lacks in-house LangGraph expertise.",
        "company_size": 50,
        "expected_range": "high"
    },
    {
        "company_name": "Joe's Bakery",
        "company_info": "A small local bakery selling bread and pastries.",
        "company_website": "joesbakery.com",
        "company_problem": "Needs more foot traffic and better ingredient sourcing.",
        "company_size": 5,
        "expected_range": "low"
    },
]


async def task(input):
    """Runs the REAL Qualify node, exactly as it runs in production."""
    state = {
        "company_name": input["company_name"],
        "company_info": input["company_info"],
        "company_website": input["company_website"],
        "company_problem": input["company_problem"],
        "company_size": input["company_size"],
        "product_description": PRODUCT_DESCRIPTION,
    }
    result = await Qualify(state)
    return result


def qualify_score_sensible_scorer(input, output, expected):
    """Checks whether Qualify's score direction matches expectation."""
    score = output.get("qualify_score", 0)
    expected_range = expected["expected_range"]

    if expected_range == "high":
        matched = score >= 7
    else:
        matched = score < 7

    return {
        "name": "qualify_score_sensible",
        "score": 1.0 if matched else 0.0,
    }


async def main():
    await EvalAsync(
        "AI_lead_qualification",
        data=lambda: [
            {"input": row, "expected": row}
            for row in dataset
        ],
        task=task,
        scores=[qualify_score_sensible_scorer],
    )


if __name__ == "__main__":
    asyncio.run(main())
    