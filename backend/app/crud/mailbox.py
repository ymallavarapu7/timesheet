from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox import Mailbox
from app.services.encryption import encrypt


async def get_mailbox(
    session: AsyncSession,
    mailbox_id: int,
    tenant_id: int,
) -> Mailbox | None:
    result = await session.execute(
        select(Mailbox).where(
            (Mailbox.id == mailbox_id) &
            (Mailbox.tenant_id == tenant_id)
        )
    )
    return result.scalar_one_or_none()


async def list_mailboxes(session: AsyncSession, tenant_id: int) -> list[Mailbox]:
    result = await session.execute(
        select(Mailbox)
        .where(Mailbox.tenant_id == tenant_id)
        .order_by(Mailbox.created_at.desc())
    )
    return list(result.scalars().all())


async def create_mailbox(
    session: AsyncSession,
    tenant_id: int,
    data: dict,
) -> Mailbox:
    password = data.pop("password", None)
    smtp_password = data.pop("smtp_password", None)

    mailbox = Mailbox(tenant_id=tenant_id, **data)
    if password:
        mailbox.password_enc = encrypt(password)
    if smtp_password:
        mailbox.smtp_password_enc = encrypt(smtp_password)

    session.add(mailbox)
    await session.commit()
    await session.refresh(mailbox)
    return mailbox


async def update_mailbox(
    session: AsyncSession,
    mailbox: Mailbox,
    data: dict,
) -> Mailbox:
    password = data.pop("password", None)
    smtp_password = data.pop("smtp_password", None)

    for key, value in data.items():
        if value is not None:
            setattr(mailbox, key, value)

    if password:
        mailbox.password_enc = encrypt(password)
    if smtp_password:
        mailbox.smtp_password_enc = encrypt(smtp_password)

    await session.commit()
    await session.refresh(mailbox)
    return mailbox


async def delete_mailbox(session: AsyncSession, mailbox: Mailbox) -> None:
    await session.delete(mailbox)
    await session.commit()
