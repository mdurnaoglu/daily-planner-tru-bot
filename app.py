import asyncio
import json
import logging
import os
import re
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums.parse_mode import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

import asyncpg

from db import (
    add_reminder,
    add_user,
    fetch_due_reminders,
    get_daily_state,
    init_db,
    list_users,
    list_pending_reminders,
    get_quiz_state,
    mark_reminders_sent,
    remove_user,
    set_quiz_state,
    clear_quiz_state,
    update_daily_state,
    update_user_lang,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
TZ_NAME = os.getenv("TZ", "Europe/Istanbul")
DAILY_HOUR = int(os.getenv("DAILY_HOUR", "10"))
DAILY_MINUTE = int(os.getenv("DAILY_MINUTE", "0"))
WORDS_PER_DAY = int(os.getenv("WORDS_PER_DAY", "5"))
PORT = int(os.getenv("PORT", "10000"))
WORDS_FILE = os.getenv("WORDS_FILE", "words.json")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

TZ = ZoneInfo(TZ_NAME)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

TIME_RE = re.compile(r"(?i)\b(?:saat\s*)?(\d{1,2})[:.](\d{2})\b")
LOVE_TRIGGERS = {
    "tr": ["mert beni seviyor mu"],
    "ru": ["мерт меня любит", "мерт меня любит?"],
}
LOVE_REPLY_TR = "Mert seni inanılmaz derecede çok seviyor. ve seni sürekli olarak özlüyor"
LOVE_REPLY_RU = "Мерт тебя безумно сильно любит и постоянно скучает по тебе."

REPLIES = {
    "tr": {
        "start": (
            "Merhaba!\n"
            "Neler yapabiliyorum:\n"
            "• Her gün 10:00'da 5 Rusça kelime gönderirim.\n"
            "• Hatırlatıcı kurarım (örn: 'saat 15:00 toplantısını hatırlat').\n"
            "• 15:00'te su içmeyi hatırlatırım.\n"
            "• 15:02'de mini quiz gönderirim.\n"
            "• /reminders ile bekleyen hatırlatmalarını listelerim."
        ),
        "reminder_set": "Tamam. {time} için hatırlatıcı kurdum.",
        "reminder_due": "Merhaba, bana '{text}' demiştin. Saat geldi, aksiyon almak ister misin ? )",
        "daily_title": "*Words of the day*",
        "water_reminder": "💧 Su içmeyi unutma!",
        "reminders_empty": "Bekleyen hatırlatman yok.",
        "reminders_title": "Bekleyen hatırlatmalar:",
        "quiz_intro": "Ufak bir mola! Şimdi Quiz zamanı.",
        "quiz_question": "Kelime: {word}\nA) {a}\nB) {b}\nC) {c}\nCevabını A/B/C olarak yaz.",
        "quiz_correct": "Harika! Doğru cevap.",
        "quiz_wrong": "Yaklaştın! Doğru cevap {answer}.",
    },
    "ru": {
        "start": (
            "Привет!\n"
            "Что я умею:\n"
            "• Каждый день в 10:00 отправляю 5 русских слов.\n"
            "• Ставлю напоминания (например: «в 15:00 напомни про встречу»).\n"
            "• В 15:00 напомню попить воды.\n"
            "• В 15:02 пришлю мини‑викторину.\n"
            "• /reminders покажет ожидающие напоминания."
        ),
        "reminder_set": "Готово. Поставил напоминание на {time}.",
        "reminder_due": "Привет! Ты просил(а): «{text}». Время пришло — хочешь заняться этим сейчас? )",
        "daily_title": "*Words of the day*",
        "water_reminder": "💧 Не забудь попить воды!",
        "reminders_empty": "У тебя нет ожидающих напоминаний.",
        "reminders_title": "Ожидающие напоминания:",
        "quiz_intro": "Небольшая пауза! Время мини‑викторины.",
        "quiz_question": "Слово: {word}\nA) {a}\nB) {b}\nC) {c}\nОтветь A/B/C.",
        "quiz_correct": "Отлично! Правильный ответ.",
        "quiz_wrong": "Почти! Правильный ответ: {answer}.",
    },
}


def load_words() -> list[dict]:
    with open(WORDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


WORDS = load_words()


def detect_lang(text: str) -> str:
    if not text:
        return "tr"
    cyrillic = sum(1 for ch in text if "А" <= ch <= "я" or ch in ("ё", "Ё"))
    latin = sum(1 for ch in text if "A" <= ch <= "Z" or "a" <= ch <= "z")
    return "ru" if cyrillic > latin else "tr"


def parse_time_from_text(text: str):
    match = TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour=hour, minute=minute)


def build_quiz():
    if len(WORDS) < 4:
        return None
    word = random.choice(WORDS)
    correct = word["tr"]
    wrongs = [w["tr"] for w in random.sample(WORDS, 3) if w["tr"] != correct]
    if len(wrongs) < 2:
        return None
    options = [correct, wrongs[0], wrongs[1]]
    random.shuffle(options)
    letters = ["A", "B", "C"]
    correct_letter = letters[options.index(correct)]
    return word["word"], options, correct_letter


async def send_daily_words(bot: Bot, pool: asyncpg.Pool) -> None:
    today = datetime.now(TZ).date()
    last_date, last_index = await get_daily_state(pool)
    if last_date == today:
        return

    if not WORDS:
        logger.warning("Words list is empty")
        return

    start = last_index % len(WORDS)
    end = start + WORDS_PER_DAY
    slice_words = [WORDS[i % len(WORDS)] for i in range(start, end)]

    users = await list_users(pool)
    for chat_id, lang in users:
        lines = [REPLIES.get(lang, REPLIES["tr"])["daily_title"]]
        for w in slice_words:
            lines.append(f"• {w['word']} — {w['tr']} ({w.get('note','')})")
        message = "\n".join(lines)
        try:
            await bot.send_message(chat_id, message, parse_mode=ParseMode.MARKDOWN)
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send daily words to %s", chat_id)

    await update_daily_state(pool, today, end % len(WORDS))


async def check_reminders(bot: Bot, pool: asyncpg.Pool) -> None:
    now = datetime.now(TZ)
    due = await fetch_due_reminders(pool, now)
    if not due:
        return

    sent_ids = []
    for reminder_id, chat_id, text in due:
        lang = detect_lang(text)
        message = REPLIES.get(lang, REPLIES["tr"])["reminder_due"].format(text=text)
        try:
            await bot.send_message(chat_id, message)
            sent_ids.append(reminder_id)
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
            sent_ids.append(reminder_id)
        except Exception:
            logger.exception("Failed to send reminder %s", reminder_id)

    await mark_reminders_sent(pool, sent_ids, now)


async def send_water_reminder(bot: Bot, pool: asyncpg.Pool) -> None:
    users = await list_users(pool)
    for chat_id, lang in users:
        message = REPLIES.get(lang, REPLIES["tr"])["water_reminder"]
        try:
            await bot.send_message(chat_id, message)
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send water reminder to %s", chat_id)


async def send_quiz(bot: Bot, pool: asyncpg.Pool) -> None:
    users = await list_users(pool)
    quiz = build_quiz()
    if not quiz:
        return
    word, options, correct_letter = quiz
    for chat_id, lang in users:
        t = REPLIES.get(lang, REPLIES["tr"])
        message = t["quiz_intro"] + "\n\n" + t["quiz_question"].format(
            word=word, a=options[0], b=options[1], c=options[2]
        )
        try:
            await bot.send_message(chat_id, message)
            await set_quiz_state(pool, chat_id, correct_letter)
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send quiz to %s", chat_id)


async def on_startup(bot: Bot, pool: asyncpg.Pool) -> None:
    await init_db(pool)
    logger.info("DB initialized")


async def handle_start(message: Message, pool: asyncpg.Pool) -> None:
    lang = detect_lang(message.text or "")
    await add_user(pool, message.chat.id, lang)
    await update_user_lang(pool, message.chat.id, lang)
    await message.answer(REPLIES.get(lang, REPLIES["tr"])["start"])


async def handle_message(message: Message, bot: Bot, pool: asyncpg.Pool) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    lang = detect_lang(text)
    await add_user(pool, message.chat.id, lang)
    await update_user_lang(pool, message.chat.id, lang)

    if text.strip().upper() in {"A", "B", "C"}:
        state = await get_quiz_state(pool, message.chat.id)
        if state:
            correct_letter, _ = state
            t = REPLIES.get(lang, REPLIES["tr"])
            if text.strip().upper() == correct_letter:
                await message.answer(t["quiz_correct"])
            else:
                await message.answer(t["quiz_wrong"].format(answer=correct_letter))
            await clear_quiz_state(pool, message.chat.id)
            return

    lowered = text.lower()
    if lowered in LOVE_TRIGGERS.get(lang, []) or lowered in LOVE_TRIGGERS["tr"]:
        reply = LOVE_REPLY_RU if lang == "ru" else LOVE_REPLY_TR
        await message.answer(reply)
        return

    t = parse_time_from_text(text)
    if not t:
        return

    now = datetime.now(TZ)
    remind_at = datetime.combine(now.date(), t, tzinfo=TZ)
    if remind_at <= now:
        remind_at = remind_at + timedelta(days=1)

    await add_reminder(pool, message.chat.id, remind_at, text)
    await message.answer(
        REPLIES.get(lang, REPLIES["tr"])["reminder_set"].format(time=t.strftime("%H:%M"))
    )


async def handle_reminders(message: Message, pool: asyncpg.Pool) -> None:
    lang = detect_lang(message.text or "")
    await add_user(pool, message.chat.id, lang)
    await update_user_lang(pool, message.chat.id, lang)

    items = await list_pending_reminders(pool, message.chat.id, limit=20)
    if not items:
        await message.answer(REPLIES.get(lang, REPLIES["tr"])["reminders_empty"])
        return

    lines = [REPLIES.get(lang, REPLIES["tr"])["reminders_title"]]
    for reminder_id, remind_at, text in items:
        local_time = remind_at.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
        lines.append(f"- #{reminder_id} {local_time} — {text}")
    await message.answer("\n".join(lines))


async def start_health_server() -> web.AppRunner:
    async def health(_):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    return runner


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    await on_startup(bot, pool)

    async def start_handler(message: Message):
        await handle_start(message, pool)

    async def reminders_handler(message: Message):
        await handle_reminders(message, pool)

    async def message_handler(message: Message):
        await handle_message(message, bot, pool)

    dp.message.register(start_handler, CommandStart())
    dp.message.register(reminders_handler, F.text == "/reminders")
    dp.message.register(message_handler, F.text)

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(send_daily_words, "cron", hour=DAILY_HOUR, minute=DAILY_MINUTE, args=[bot, pool])
    scheduler.add_job(send_water_reminder, "cron", hour=15, minute=0, args=[bot, pool])
    scheduler.add_job(send_quiz, "cron", hour=15, minute=2, args=[bot, pool])
    scheduler.add_job(check_reminders, "interval", minutes=1, args=[bot, pool])
    scheduler.start()

    await start_health_server()

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
