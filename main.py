from config import DATABASE_URL
import agent
import json
import uvicorn
from pydantic import BaseModel
import time
from fastapi import FastAPI
from database import DatabaseManager
from braintrust import init_logger, traced, current_span
from langchain_core.messages import HumanMessage, SystemMessage

init_logger(project="AI_lead_qualification")


class EmailQualityCheck(BaseModel):
    mentions_product: bool
    professional_tone: bool
    is_personalized: bool

async def score_email_quality(email_subject, email_body, product_description):
    """A small AI 'judge' that silently checks the real email's quality
    and logs a score to Braintrust - doesn't change anything the user sees."""
    judge_instruction = SystemMessage(content="""You are a strict, honest grader reviewing an outreach email for quality.
    Check honestly: does it mention the actual product being offered, is the tone professional, does it feel personalized (not generic)?""")

    judge_content = HumanMessage(content=f"""Product being offered: {product_description}
    Email Subject: {email_subject}
    Email Body: {email_body}""")

    structured = agent.llm.with_structured_output(EmailQualityCheck)
    result = await structured.ainvoke([judge_instruction, judge_content])

    checks_passed = sum([result.mentions_product, result.professional_tone, result.is_personalized])
    return checks_passed / 3


db = DatabaseManager(DATABASE_URL)


class LeadRequest(BaseModel):
    company_name: str
    company_description: str
    product_description: str

class ReviewRequest(BaseModel):
    lead_id: str
    company_name: str
    is_approved: bool
    human_feedback: str = ""

class ManualEmailRequest(BaseModel):
    lead_id: str
    email_body: str = ""
    email_subject: str = ""


app_graph = None

app =  FastAPI(title="AI Support Agent")

@app.on_event("startup")
async def startup_event():
    global app_graph
    await db.open_pool()
    app_graph = await agent.build_graph()

@app.on_event("shutdown")
async def shutdown_event():
    await db.close_pool()

@app.post("/qualify")
@traced
async def qualify_lead(request: LeadRequest):
    lead_id = await db.create_lead(request.company_name, request.company_description)
    thread = {"configurable": {"thread_id": lead_id}}
    formatted_data = {"company_name": request.company_name, "company_description":
         request.company_description,
         "product_description": request.product_description,
         "attempt_count": 0,
         "max_attempts": 3}

    try:
        async for event in app_graph.astream(formatted_data, thread, stream_mode="values"):
            final_event = event
    except Exception as e:
        await db.update_lead(lead_id, status="failed")
        raise

    final_state = await app_graph.aget_state(thread)

    if final_state.next == ():
        await db.update_lead(lead_id, 
        company_name = request.company_name,
        status = "not_qualified", 
        qualify_reason = final_event.get("qualify_reason", ""),
        company_info = final_event.get("company_info", ""),
        company_website = final_event.get("company_website", ""),
        company_problem = final_event.get("company_problem", ""),
        company_size = final_event.get("company_size", 0),
        qualify_score = final_event.get("qualify_score", 0), )

        return {
            "lead_id": lead_id,
            "company_name": request.company_name,
            "status": "not_qualified",
            "qualify_score": final_event.get("qualify_score", 0),
            "qualify_reason": final_event.get("qualify_reason", ""),

        }
        
    else:
        email_score = await score_email_quality(final_event.get("email_subject", ""), final_event.get("email_body", ""), request.product_description)

        rewrite_attempts = 0
        while email_score < 0.5 and rewrite_attempts < 2:
            rewritten = await agent.WriteEmail(final_event)
            final_event["email_subject"] = rewritten["email_subject"]
            final_event["email_body"] = rewritten["email_body"]
            email_score = await score_email_quality(final_event["email_subject"], final_event["email_body"], request.product_description)
            rewrite_attempts += 1

        current_span().log(scores={"email_quality": email_score})

        await db.update_lead(lead_id,
        company_name = request.company_name,
        status = "pending_review", 
        qualify_score = final_event.get("qualify_score", 0),
        qualify_reason = final_event.get("qualify_reason", ""),
        company_info = final_event.get("company_info", ""),
        company_website = final_event.get("company_website", ""),
        company_problem = final_event.get("company_problem", ""),
        company_size = final_event.get("company_size", 0),
        email_subject = final_event.get("email_subject", ""), 
        email_body = final_event.get("email_body", "") )


        await db.save_draft(
        lead_id=lead_id,
        attempt_number=1,
        email_subject=final_event.get("email_subject", ""),
        email_body=final_event.get("email_body", ""),
        is_approved=None,
        human_feedback=""
        )

        return {
            "lead_id": lead_id,
            "company_name": request.company_name,
            "status": "pending_review",
            "qualify_score": final_event.get("qualify_score", 0),
            "email_subject": final_event.get("email_subject", ""),
            "email_body": final_event.get("email_body", "")
            
        }    

@app.post("/review")
async def review_email(request: ReviewRequest):
    thread = {"configurable": {"thread_id": request.lead_id}}


    await app_graph.aupdate_state(thread, {"human_feedback": request.human_feedback, "is_approved": request.is_approved}, as_node="Wait_for_human") 

    try:
        async for event in app_graph.astream(None, thread, stream_mode="values"):
            final_event = event
    except Exception as e:
        await db.update_lead(request.lead_id, status="failed")
        raise

    final_state = await app_graph.aget_state(thread)    


    if final_event.get("escalation_summary"):
        await db.update_lead(request.lead_id, 
        status = "escalated",
         company_name = request.company_name,
        escalation_summary=json.dumps(final_event.get("escalation_summary", "")) )

        return {
            "status": "escalated",
            "escalation_summary": final_event.get("escalation_summary", ""),
            "company_name": request.company_name,
        
        }
    
    elif final_state.next == ():
        await db.update_lead(request.lead_id, 
        status = "approved",
         company_name = request.company_name,
        is_approved = final_event.get("is_approved", None) )

        return {
            "status": "approved",
            "is_approved": final_event.get("is_approved", None),
            "company_name": request.company_name,
            
        }    

    else:
        await db.update_lead(request.lead_id, 
        status = "pending_review",
        company_name = request.company_name,
        human_feedback = request.human_feedback,
        email_subject = final_event.get("email_subject", ""),
        email_body = final_event.get("email_body", ""))

        await db.save_draft(
        lead_id=request.lead_id,
        attempt_number=final_event.get("attempt_count", 0) + 1,
        email_subject=final_event.get("email_subject", ""),
        email_body=final_event.get("email_body", ""),
        is_approved=False,
        human_feedback=request.human_feedback
        )

        return {
            "status": "pending_review",
            "company_name": request.company_name,
            "email_subject": final_event.get("email_subject", ""),
            "email_body": final_event.get("email_body", ""),
            
        } 

@app.get("/pending-escalations")
async def pending_escalations():
    return await db.get_pending_escalations()


@app.post("/submit-manual-email")
async def submit_manual_email(request: ManualEmailRequest):
    await db.update_lead(
        request.lead_id, 
        status = "resolved",
        email_body = request.email_body,
        email_subject = request.email_subject,
        is_approved = True
    )

    return {
        "status": "resolved",
        "email_body": request.email_body,
        "email_subject":  request.email_subject
    }



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
