import asyncpg
from typing import List, Tuple

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    chat_id BIGINT PRIMARY KEY,
    lang TEXT NOT NULL DEFAULT 'tr',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    remind_at TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON reminders (remind_at)
    WHERE sent_at IS NULL;

CREATE TABLE IF NOT EXISTS daily_state (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_sent_date DATE,
    last_index INT NOT NULL DEFAULT 0,
    last_eat_date DATE,
    last_love_date DATE,
    last_water_date DATE,
    last_quiz_date DATE
);

CREATE TABLE IF NOT EXISTS quiz_state (
    chat_id BIGINT PRIMARY KEY,
    correct_option CHAR(1) NOT NULL,
    asked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

ALTER_USERS_LANG_SQL = "ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT NOT NULL DEFAULT 'tr';"
ALTER_DAILY_STATE_SQL = """
ALTER TABLE daily_state ADD COLUMN IF NOT EXISTS last_eat_date DATE;
ALTER TABLE daily_state ADD COLUMN IF NOT EXISTS last_love_date DATE;
ALTER TABLE daily_state ADD COLUMN IF NOT EXISTS last_water_date DATE;
ALTER TABLE daily_state ADD COLUMN IF NOT EXISTS last_quiz_date DATE;
"""


async def init_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        await conn.execute(ALTER_USERS_LANG_SQL)
        await conn.execute(ALTER_DAILY_STATE_SQL)
        await conn.execute(
            "INSERT INTO daily_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )


async def add_user(pool: asyncpg.Pool, chat_id: int, lang: str = "tr") -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (chat_id, lang) VALUES ($1, $2) ON CONFLICT (chat_id) DO NOTHING",
            chat_id,
            lang,
        )


async def remove_user(pool: asyncpg.Pool, chat_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE chat_id=$1", chat_id)


async def list_users(pool: asyncpg.Pool) -> List[Tuple[int, str]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT chat_id, lang FROM users")
    return [(int(r["chat_id"]), str(r["lang"])) for r in rows]


async def update_user_lang(pool: asyncpg.Pool, chat_id: int, lang: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET lang=$1 WHERE chat_id=$2",
            lang,
            chat_id,
        )


async def add_reminder(pool: asyncpg.Pool, chat_id: int, remind_at, text: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (chat_id, remind_at, text) VALUES ($1, $2, $3)",
            chat_id,
            remind_at,
            text,
        )


async def fetch_due_reminders(pool: asyncpg.Pool, now) -> List[Tuple[int, int, str]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, text FROM reminders WHERE sent_at IS NULL AND remind_at <= $1",
            now,
        )
    return [(int(r["id"]), int(r["chat_id"]), r["text"]) for r in rows]


async def mark_reminders_sent(pool: asyncpg.Pool, ids: List[int], sent_at) -> None:
    if not ids:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reminders SET sent_at=$1 WHERE id = ANY($2)",
            sent_at,
            ids,
        )


async def get_daily_state(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_sent_date, last_index FROM daily_state WHERE id=1"
        )
    return row["last_sent_date"], int(row["last_index"])


async def update_daily_state(pool: asyncpg.Pool, last_sent_date, last_index: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE daily_state SET last_sent_date=$1, last_index=$2 WHERE id=1",
            last_sent_date,
            last_index,
        )


async def get_schedule_state(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_eat_date, last_love_date, last_water_date, last_quiz_date FROM daily_state WHERE id=1"
        )
    return row["last_eat_date"], row["last_love_date"], row["last_water_date"], row["last_quiz_date"]


async def update_last_eat_date(pool: asyncpg.Pool, last_eat_date) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE daily_state SET last_eat_date=$1 WHERE id=1",
            last_eat_date,
        )


async def update_last_love_date(pool: asyncpg.Pool, last_love_date) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE daily_state SET last_love_date=$1 WHERE id=1",
            last_love_date,
        )


async def update_last_water_date(pool: asyncpg.Pool, last_water_date) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE daily_state SET last_water_date=$1 WHERE id=1",
            last_water_date,
        )


async def update_last_quiz_date(pool: asyncpg.Pool, last_quiz_date) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE daily_state SET last_quiz_date=$1 WHERE id=1",
            last_quiz_date,
        )


async def list_pending_reminders(pool: asyncpg.Pool, chat_id: int, limit: int = 20):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, remind_at, text FROM reminders "
            "WHERE chat_id=$1 AND sent_at IS NULL "
            "ORDER BY remind_at ASC "
            "LIMIT $2",
            chat_id,
            limit,
        )
    return [(int(r["id"]), r["remind_at"], r["text"]) for r in rows]


async def set_quiz_state(pool: asyncpg.Pool, chat_id: int, correct_option: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO quiz_state (chat_id, correct_option) VALUES ($1, $2) "
            "ON CONFLICT (chat_id) DO UPDATE SET correct_option=EXCLUDED.correct_option, asked_at=NOW()",
            chat_id,
            correct_option,
        )


async def get_quiz_state(pool: asyncpg.Pool, chat_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT correct_option, asked_at FROM quiz_state WHERE chat_id=$1",
            chat_id,
        )
    if not row:
        return None
    return str(row["correct_option"]), row["asked_at"]


async def clear_quiz_state(pool: asyncpg.Pool, chat_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM quiz_state WHERE chat_id=$1", chat_id)
