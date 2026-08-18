import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import uuid
from datetime import datetime
from config import DATABASE_URL


class DatabaseManager:
    """
    Database manager for Supabase PostgreSQL (async version, with connection pooling)

    Functions:
    1. create_lead() - Create new lead
    2. update_lead() - Update lead info
    3. get_pending_escalations() - Get all escalated leads
    4. save_draft() - Save an email draft attempt
    """

    def __init__(self, db_url):
        """Initialize with database connection string. The pool itself is not
        opened yet here - call open_pool() once, at app startup, since opening
        a pool requires an async context."""
        self.db_url = db_url
        self.pool = AsyncConnectionPool(
            conninfo=db_url,
            open=False,
            kwargs={"autocommit": True},
            check=AsyncConnectionPool.check_connection,
            max_idle=60,
        )

    async def open_pool(self):
        """Call this once, at app startup, to actually open the connection pool."""
        await self.pool.open()

    async def close_pool(self):
        """Call this once, at app shutdown, to cleanly close all pooled connections."""
        await self.pool.close()

    async def create_lead(self, company_name, company_description):
        lead_id = f"LEAD-{uuid.uuid4().hex[:8].upper()}"

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                INSERT INTO leads (lead_id, company_name, company_description, status)
                VALUES (%s, %s, %s, 'processing')
                RETURNING lead_id """, (lead_id, company_name, company_description))

                result = await cur.fetchone()

        print(f"✅ Created lead: {lead_id}")
        return result[0]

    async def update_lead(self, lead_id, **kwargs):
        "update lead with new information"
        updates = []
        values = []

        for key, value in kwargs.items():
            updates.append(f"{key} = %s")
            values.append(value)

        values.append(lead_id)

        query = f"""
            UPDATE leads
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE lead_id = %s
        """

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, values)

    async def get_pending_escalations(self):
        async with self.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(" SELECT * FROM leads WHERE status = %s ", ("escalated",))
                results = await cur.fetchall()

        return [dict(row) for row in results]

    async def save_draft(self, lead_id, attempt_number, email_subject, email_body, is_approved, human_feedback):
        draft_id = f"DRAFT-{uuid.uuid4().hex[:8].upper()}"

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO lead_drafts (draft_id, lead_id, attempt_number, email_subject, email_body, is_approved, human_feedback)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (draft_id, lead_id, attempt_number, email_subject, email_body, is_approved, human_feedback))
