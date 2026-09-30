import json
import os
import config
import time
import asyncio
from typing import Annotated, Optional, TypedDict, Union
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from langchain_core.messages import SystemMessage, HumanMessage
from tools import tavily_tool
from pydantic import BaseModel, Field, field_validator
from langchain_groq import ChatGroq

# LLM setup
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=config.GROQ_API_KEY
)

async def invoke_with_retry(structured_llm, messages, max_retries=3):
    """Calls structured_llm.ainvoke(messages). If Groq glitches (bad/malformed response),
    waits a moment and tries again, up to max_retries times, instead of crashing right away."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await structured_llm.ainvoke(messages)
        except Exception as e:
            last_error = e
            print(f"Model call failed (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(1)
    raise last_error


# ── SearchQuery ──────────────────────────────────────────
class SearchQuery(BaseModel):
    search_query: str = Field(None, description="Search query for retrieval")

# ── COMPANY INFO THE SYSYTEM NEED TO RETRIVE THIS SPECIFIC DATA FROMTAVILY SEARCH TOOL. ──────────────────────────────────────────
class companyinfo(BaseModel):
    company_info: Optional[str] = Field(None, description="Information of the Company")
    company_website: Optional[str] = Field(None, description="Website of the Company")
    company_problem: Optional[str] = Field(None, description="Problem of the Company")
    company_size: Optional[Union[int, str]] = Field(None, description="Size of the Company")

    @field_validator("company_size")
    @classmethod
    def clamp_size_to_realistic_range(cls, value):
        """The AI is asked for number of EMPLOYEES, but sometimes confuses this with
        users, guests, or revenue and returns a huge, wrong number (we saw 390,000,000
        for Airbnb, whose real employee count is ~8,200). No real company has more
        than a few million employees, so this catches and corrects that mistake.
        It also sometimes returns this as a string like "8500" or "5000+" instead of
        a plain number - this converts that to a clean integer instead of crashing."""
        if value is None:
            return value
        if isinstance(value, str):
            digits_only = "".join(c for c in value if c.isdigit())
            value = int(digits_only) if digits_only else 0
        return max(0, min(3_000_000, value))

# ── This class is used in the qualify node to analzye that company qialify or not base on this data ──────────────────────────────────────────
class qualifyinfo(BaseModel):
    qualify_score: int = Field(None, description=" Score for the Qualification")
    qualify_reason: str = Field(None, description="reason of the qualification")
    is_qualify: bool =  Field(None, description=" is company qualify or not")

    @field_validator("qualify_score")
    @classmethod
    def clamp_score_to_valid_range(cls, value):
        """The AI is asked for a 0-10 score, but sometimes returns a much bigger,
        wrong number by mistake. This corrects it automatically instead of trusting it blindly."""
        if value is None:
            return value
        return max(0, min(10, value))

# ── This pydantic classs is sued the the field for the EmailWrite node──────────────────────────────────────────
class Emailinfo(BaseModel):
    email_body: str = Field(None, description=" The email body")
    email_subject: str = Field(None, description=" The email subject")




# ── AgentState ──────────────────────────────────────────
class AgentState(TypedDict):
    company_name: str
    company_description: str
    product_description: str

    company_info: str
    company_website: str
    company_problem: str
    company_size: str

    qualify_score: int
    qualify_reason:str
    is_qualify: bool

    email_subject: str
    email_body: str

    is_approved: str
    human_feedback: str

    attempt_count: int
    max_attempts: int
    already_contacted: bool
    final_status: str

    escalation_summary: str


# ── Reseach company data/info ──────────────────────────────────────────
async def Research_company(state: AgentState):
    company_name = state['company_name']
    company_description = state['company_description']

    
    search_instruction = SystemMessage(content=f""" You a re good Researchers and good agent to use the SearchQuery and find us 
     the concise and good information about the company
     """)

    human_message = HumanMessage(content=f""" here as  the research data {company_name} and the {company_description}""")

    structured_output = llm.with_structured_output(SearchQuery)
    search_query = await invoke_with_retry(structured_output, [search_instruction] + [human_message])

    if not search_query.search_query:
        search_query.search_query = f"{company_name} company information"

    search_docs = await tavily_tool.ainvoke(search_query.search_query)
    

    # Format
    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document href="{doc["url"]}"/>\n{doc["content"]}\n</Document>'
            for doc in search_docs
        ]
    )


    search_instruction2 = SystemMessage(content=f""" You are a good extracter and good agent to find and extract correct and concise information of the compnay from the internet.
    You will be give the input as raw informatiaon:
    then you will need to extract the exact information like  the company_info, the compnay_size, the company_problem, the company_website.

    Rules:
    1. company_size means the NUMBER OF EMPLOYEES the company has - nothing else. Do not confuse it with number of users, customers, guests, hosts, bookings, downloads, or revenue figures, even if those numbers appear much more prominently in the search results. If the exact employee count is not stated, estimate a reasonable number based on context clues (e.g. "startup" ~10-50, "mid-size" ~200-1000, "large/enterprise/Fortune 500" ~5000+). Always give your best estimate rather than leaving it empty.
    2. If no explicit problem is stated, infer a likely business problem or challenge based on the company's industry and description.
    3. Only return null if there is truly zero information or context to make any reasonable estimate.
    4. company_size must be a plain integer number (e.g. 8500), never a string or text with commas or quotes.
    5. You are given the target company name below. Only extract information that is actually about that exact company. If the raw research data is mainly about a different company (a competitor, a tool built for the target company, or an unrelated business), ignore that unrelated data and do not use its name, website, or details. """)

    structured_output2 = llm.with_structured_output(companyinfo)
    extracted = await invoke_with_retry(structured_output2, [search_instruction2] + [HumanMessage(content=f"""Target Company Name: {company_name}
    Raw research data: {formatted_search_docs}""")])



    return{
        'company_info': extracted.company_info,
        'company_website': extracted.company_website,
        'company_problem': extracted.company_problem,
        'company_size': extracted.company_size
    }


async def Qualify(state: AgentState):
    company_name = state['company_name']
    company_info = state['company_info']
    company_website = state['company_website']
    company_problem = state['company_problem']
    company_size  = state['company_size']
    product_description = state['product_description']

    System_message = SystemMessage(content=f"""You are good Qualifer and AI Agent system:
    you need to qualify and classify the company based on how good a fit they are for the product/service described below - not on how successful or impressive the company is in general.
    qualify_score must be an integer between 0 and 10 (0 = not qualified at all, 10 = perfectly qualified). Do not use company size or any other raw number as the score.""")  

    human_message = HumanMessage(content= f"""Our Product/Service: {product_description}

    Company Name: {company_name}
    Company Info: {company_info}
    Company Website: {company_website}
    Company Problem: {company_problem}
    Company Size (employees): {company_size}""")

    structured_output = llm.with_structured_output(qualifyinfo)
    qualify_result = await invoke_with_retry(structured_output, [System_message] + [human_message])

    return{
        'qualify_score': qualify_result.qualify_score,
        'qualify_reason': qualify_result.qualify_reason,
        'is_qualify': qualify_result.is_qualify
    }


def route_After_qualify(state: AgentState):
    qualify_score = state['qualify_score']
    max_attempts = state.get('max_attempts',2)

    if qualify_score >= 7:
        return 'WriteEmail'
        

    else:
        return END    



async def WriteEmail(state: AgentState):
    company_name = state['company_name']
    company_info = state['company_info']
    company_problem = state['company_problem']
    company_website = state['company_website']
    qualify_score = state['qualify_score']
    qualify_reason = state['qualify_reason']
    is_qualify = state['is_qualify']
    human_feedback = state.get('human_feedback', '')
    product_description = state['product_description']

    System_message=SystemMessage(content=f""" You are expert technical  and E2B Email Communicater:
    Your task is to create a short, concise, easible and digestible email to the compnay
     that has alrady qualified (qualify_score of 7 or higher out of 10):

     instruction:
     1. tone: Keep your tone professional, peer to peer tone and confidence and light weight. avoid using ggressive 
     marketing or sale languages.
     2. Structure: start the email with a greeting using the ACTUAL company name given to you below (e.g. "Hi {company_name} Team") - never use the words "Volga Partner Team" or any other placeholder/example name, always use the real company name provided.
     then body of the email or the main content. laslty the tail of the email with Best Regards Muhammad ABBAS.
     3.Length: the length of the email msut be between 3 to 5 lines. and it concise and meaningfull.
     4. if {human_feedback} is empty then llm need to write the new template of email. incase the {human_feedback} contain the text then
     the previous email was rejected by human the {human_feedback} contain the previous issue you need to write the email again and fix 
     the previous issue
     5. Always mention the exact qualify_score value given to you in the data below, out of 10. Never assume, guess, or hardcode any score - use only the real number provided.
     6. The email must actually mention what OUR PRODUCT/SERVICE is (given below) and briefly connect it to the company's problem - do not write a generic "congrats you qualified" email with no mention of what is actually being offered. """)
     
    human_message = HumanMessage(content=f""" Our Product/Service: {product_description}

    Company Name: {company_name}
    Company Info: {company_info}
    Company Problem: {company_problem}
    Company Website: {company_website}
    Qualify Score (out of 10): {qualify_score}
    Qualify Reason: {qualify_reason}
    Is Qualified: {is_qualify}
    Previous Human Feedback: {human_feedback}""")

    structured_output = llm.with_structured_output(Emailinfo)
    email_content = await invoke_with_retry(structured_output, [System_message] + [human_message])
     
    return{
       'email_body': email_content.email_body,
       'email_subject': email_content.email_subject
    }

def Wait_for_human(state:AgentState):
    """No-op node that should be interrupted on"""
    pass    

def HUMAN_REVIEW(state: AgentState):
    is_approved = state['is_approved']
    attempt_count = state['attempt_count']

    if is_approved == False:
        attempt_count = attempt_count + 1
    

    return{
        'attempt_count': attempt_count
    }

def route_After_review(state: AgentState):
    is_approved = state['is_approved']
    attempt_count = state['attempt_count']
    max_attempts = state['max_attempts']

    if is_approved == True:
        return END

    if attempt_count < max_attempts:
        return "WriteEmail"
    else:
        return "MANUAL_ESCALATION"       


def MANUAL_ESCALATION(state: AgentState):
    company_name = state['company_name']
    company_info =state['company_info']
    company_problem = state['company_problem']
    company_size = state['company_size']
    company_website = state['company_website']
    email_body = state['email_body']
    email_subject = state['email_subject']
    human_feedback = state['human_feedback']


    escalation_summary = {
        "company": company_name,
        "company_info": company_info,
        "company_problem": company_problem,
        "company_size": company_size,
        "company_website": company_website,
        "email_body": email_body,
        "email_subject": email_subject,
        "human_feedback": human_feedback
    }

    print("Max attempt limit reached. Sending lead to human escalation queue.")



    return {
        "escalation_summary": escalation_summary

    }

async def build_graph():
    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("Research_company", Research_company)
    graph_builder.add_node("Qualify", Qualify)
    graph_builder.add_node("WriteEmail", WriteEmail)
    graph_builder.add_node("Wait_for_human", Wait_for_human)
    graph_builder.add_node("HUMAN_REVIEW", HUMAN_REVIEW)
    graph_builder.add_node("MANUAL_ESCALATION", MANUAL_ESCALATION)

    graph_builder.add_edge(START, "Research_company")
    graph_builder.add_edge("Research_company", "Qualify")
    graph_builder.add_edge("WriteEmail", "Wait_for_human")
    graph_builder.add_edge("Wait_for_human", "HUMAN_REVIEW")
    graph_builder.add_edge("MANUAL_ESCALATION", END)

    graph_builder.add_conditional_edges(
        "Qualify",
        route_After_qualify,
        {
            "WriteEmail": "WriteEmail",
            END: END

        }
    )    

    graph_builder.add_conditional_edges(
        
        "HUMAN_REVIEW",
        route_After_review,
        {
            "WriteEmail": "WriteEmail",
            "MANUAL_ESCALATION": "MANUAL_ESCALATION",
            END: END

        }
        
    )


    # Compile
    # The checkpointer needs a long-lived Postgres connection, so it uses the Session pooler
    # (port 5432) instead of the Transaction pooler in DATABASE_URL, which is only meant for
    # short connections.
    #
    # We use a connection POOL here (not a single raw connection) because a single connection
    # can silently die if it sits idle too long (Supabase closes idle connections) - and then
    # every request fails with "the connection is closed" until the whole app is restarted.
    # A pool with check=check_connection detects dead connections and replaces them automatically,
    # the same way database.py's DatabaseManager already does.
    checkpointer_db_url = config.DATABASE_URL.replace(":6543/", ":5432/")
    pool = AsyncConnectionPool(
        conninfo=checkpointer_db_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open()
    memory = AsyncPostgresSaver(pool)
    await memory.setup()
    graph = graph_builder.compile(interrupt_before=['Wait_for_human'], checkpointer=memory)
    #display(Image(graph.get_graph(xray=1).draw_mermaid_png()))

    return graph
