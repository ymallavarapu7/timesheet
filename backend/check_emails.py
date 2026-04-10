import asyncio
from app.db import AsyncSessionLocal
from sqlalchemy import text

async def run():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT 
                sender_email,
                has_attachments,
                COUNT(*) as count
            FROM ingested_emails
            WHERE tenant_id = 2
            GROUP BY sender_email, has_attachments
            ORDER BY count DESC
        """))
        rows = result.fetchall()
        print("Summary of ingested_emails for tenant 2:")
        for row in rows:
            sender = row[0] if row[0] else "(empty)"
            print(f"  sender={sender} has_attachments={row[1]} count={row[2]}")
        
        result2 = await session.execute(text("""
            SELECT COUNT(*) FROM ingested_emails WHERE tenant_id = 2
        """))
        total = result2.scalar()
        print(f"Total: {total} emails in table")

asyncio.run(run())
