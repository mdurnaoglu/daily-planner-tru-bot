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
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

import asyncpg

from db import (
    add_reminder,
    add_user,
    fetch_due_reminders,
    get_daily_state,
    get_schedule_state,
    init_db,
    list_users,
    list_pending_reminders,
    get_quiz_state,
    mark_reminders_sent,
    remove_user,
    set_quiz_state,
    clear_quiz_state,
    update_daily_state,
    update_last_apology_date,
    update_last_eat_date,
    update_last_love_date,
    update_last_quiz_date,
    update_last_water_date,
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
SONGS_FILE = os.getenv("SONGS_FILE", "songs.json")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

TZ = ZoneInfo(TZ_NAME)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

TIME_RE = re.compile(r"(?i)\b(?:saat\s*)?(\d{1,2})[:.](\d{2})\b")
TIME_HOUR_ONLY_TR = re.compile(r"(?i)\b(\d{1,2})\s*'?\s*(?:te|ta)\b")
TIME_HOUR_ONLY_RU = re.compile(r"(?i)\b(?:в)\s*(\d{1,2})\b")
LOVE_TRIGGERS = {
    "tr": ["mert beni seviyor mu"],
    "ru": ["мерт меня любит", "мерт меня любит?"],
}
LOVE_REPLY_TR = "Mert seni inanılmaz derecede çok seviyor. ve seni sürekli olarak özlüyor"
LOVE_REPLY_RU = "Мерт тебя безумно сильно любит и постоянно скучает по тебе."

START_MESSAGE = (
    "Привет, Российская Федерация)\n"
    "Хочу рассказать тебе о некоторых своих возможностях)\n\n"
    "Я могу планировать для тебя дела. Например, если ты скажешь «у меня встреча в 15:00», я напишу в это время и напомню. Или если ты скажешь «мама звонила», я напомню тебе перезвонить.\n"
    "У меня есть особые способности. Эти особые сведения может рассказать только особенный человек. Спроси его.\n"
    "У меня есть некоторые ежедневные напоминания; я буду о них напоминать.\n"
    "А ещё я буду помогать нам учить язык, отправляя каждый день 5 переводов слов.\n\n"
    "Merhaba Rusya Federasyonu)\n"
    "Sana bazı kabiliyetlerimden bahsetmek istiyorum)\n\n"
    "Senin için planlama yapabilirim. Örneğin saat 15:00'te toplantım var dersen o saatte sana mesaj atıp sana bunu hatırlatabilirim. Veya annen seni aradı ve geri araman gerektiğini sana hatırlatabilirim.\n"
    "Bazı özel yeteneklerim var. Bu özel bilgileri sana sadece özel biri söyleyebilir. Ona sormalısın.\n"
    "Günlük sana hatırlatmam gereken bazı şeyler var, bunları hatırlatacağım.\n"
    "Aynı zamanda günlük 5 tane kelime çevirisi atarak dil öğrenmemize fayda sağlayacağım."
)

REPLIES = {
    "tr": {
        "start": START_MESSAGE,
        "reminder_set": "Tamam. {time} için hatırlatıcı kurdum.",
        "reminder_due": "Merhaba, bana '{text}' demiştin. Saat geldi, aksiyon almak ister misin ? )",
        "daily_title": "*Words of the day*",
        "apology_reminder": "Я прошу прощения у Российской Федерации за то, что не говорю по-русски.",
        "eat_reminder": "Какой бы цвет лака ты ни сделала, тебе всё будет очень идти. Потому что Мерт правда обожает твои руки — в любом виде, какими бы они ни были.",
        "love_reminder": "Мерт безумно тебя любит и правда сейчас очень расстроен.\nНа самом деле он просто боялся, что вашей любви может что-то навредить. Но он сказал мне, что ты — самая лучшая девушка в мире. Я тоже хотела передать тебе это.\nВы ещё будете смеяться, вспоминая эти дни. И в тот момент Мерт будет так близко к тебе, что сможет поцеловать тебя в лоб.",
        "water_reminder": "💧 Su içmeyi unutma!",
        "reminders_empty": "Bekleyen hatırlatman yok.",
        "reminders_title": "Bekleyen hatırlatmalar:",
        "quiz_intro": "Ufak bir mola! Şimdi Quiz zamanı.",
        "quiz_question": "Kelime: {word}\nA) {a}\nB) {b}\nC) {c}\nCevabını A/B/C olarak yaz.",
        "quiz_correct": "Harika! Doğru cevap.",
        "quiz_wrong": "Yaklaştın! Doğru cevap {answer}.",
    },
    "ru": {
        "start": START_MESSAGE,
        "reminder_set": "Готово. Поставил напоминание на {time}.",
        "reminder_due": "Привет! Ты просил(а): «{text}». Время пришло — хочешь заняться этим сейчас? )",
        "daily_title": "*Words of the day*",
        "apology_reminder": "Я прошу прощения у Российской Федерации за то, что не говорю по-русски.",
        "eat_reminder": "Какой бы цвет лака ты ни сделала, тебе всё будет очень идти. Потому что Мерт правда обожает твои руки — в любом виде, какими бы они ни были.",
        "love_reminder": "Мерт безумно тебя любит и правда сейчас очень расстроен.\nНа самом деле он просто боялся, что вашей любви может что-то навредить. Но он сказал мне, что ты — самая лучшая девушка в мире. Я тоже хотела передать тебе это.\nВы ещё будете смеяться, вспоминая эти дни. И в тот момент Мерт будет так близко к тебе, что сможет поцеловать тебя в лоб.",
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


def load_songs() -> list[dict]:
    with open(SONGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


SONGS = load_songs()


def detect_lang(text: str) -> str:
    if not text:
        return "tr"
    cyrillic = sum(1 for ch in text if "А" <= ch <= "я" or ch in ("ё", "Ё"))
    latin = sum(1 for ch in text if "A" <= ch <= "Z" or "a" <= ch <= "z")
    return "ru" if cyrillic > latin else "tr"


def parse_time_from_text(text: str):
    match = TIME_RE.search(text)
    if not match:
        match_tr = TIME_HOUR_ONLY_TR.search(text)
        if match_tr:
            hour = int(match_tr.group(1))
            minute = 0
            if hour < 0 or hour > 23:
                return None
            return time(hour=hour, minute=minute)
        match_ru = TIME_HOUR_ONLY_RU.search(text)
        if match_ru:
            hour = int(match_ru.group(1))
            minute = 0
            if hour < 0 or hour > 23:
                return None
            return time(hour=hour, minute=minute)
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


async def send_water_reminder(bot: Bot, pool: asyncpg.Pool) -> int:
    users = await list_users(pool)
    sent_count = 0
    for chat_id, lang in users:
        message = REPLIES.get(lang, REPLIES["tr"])["water_reminder"]
        try:
            await bot.send_message(chat_id, message)
            sent_count += 1
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send water reminder to %s", chat_id)
    return sent_count


async def send_eat_reminder(bot: Bot, pool: asyncpg.Pool) -> int:
    users = await list_users(pool)
    sent_count = 0
    for chat_id, lang in users:
        message = REPLIES.get(lang, REPLIES["tr"])["eat_reminder"]
        try:
            await bot.send_message(chat_id, message)
            sent_count += 1
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send eat reminder to %s", chat_id)
    return sent_count


async def send_love_reminder(bot: Bot, pool: asyncpg.Pool) -> int:
    users = await list_users(pool)
    sent_count = 0
    for chat_id, lang in users:
        message = REPLIES.get(lang, REPLIES["tr"])["love_reminder"]
        try:
            await bot.send_message(chat_id, message)
            sent_count += 1
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send love reminder to %s", chat_id)
    return sent_count


async def send_apology_reminder(bot: Bot, pool: asyncpg.Pool) -> int:
    users = await list_users(pool)
    sent_count = 0
    for chat_id, lang in users:
        message = REPLIES.get(lang, REPLIES["tr"])["apology_reminder"]
        try:
            await bot.send_message(chat_id, message)
            sent_count += 1
        except TelegramForbiddenError:
            await remove_user(pool, chat_id)
        except Exception:
            logger.exception("Failed to send apology reminder to %s", chat_id)
    return sent_count


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


def _passed_time(now: datetime, hour: int, minute: int) -> bool:
    return (now.hour, now.minute) >= (hour, minute)


async def run_scheduled_broadcasts(bot: Bot, pool: asyncpg.Pool) -> None:
    now = datetime.now(TZ)
    today = now.date()

    if _passed_time(now, DAILY_HOUR, DAILY_MINUTE):
        await send_daily_words(bot, pool)

    last_apology_date, last_eat_date, last_love_date, last_water_date, last_quiz_date = await get_schedule_state(pool)

    if _passed_time(now, 1, 17) and last_apology_date != today:
        apology_sent = await send_apology_reminder(bot, pool)
        if apology_sent > 0:
            await update_last_apology_date(pool, today)

    if _passed_time(now, 12, 0) and last_eat_date != today:
        eat_sent = await send_eat_reminder(bot, pool)
        if eat_sent > 0:
            await update_last_eat_date(pool, today)

    if _passed_time(now, 14, 50) and last_love_date != today:
        love_sent = await send_love_reminder(bot, pool)
        if love_sent > 0:
            await update_last_love_date(pool, today)

    if _passed_time(now, 15, 0) and last_water_date != today:
        water_sent = await send_water_reminder(bot, pool)
        if water_sent > 0:
            await update_last_water_date(pool, today)

    if _passed_time(now, 15, 2) and last_quiz_date != today:
        await send_quiz(bot, pool)
        await update_last_quiz_date(pool, today)


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

    normalized = text.lower().strip()
    if normalized in {"turkishmusic", "songsuggestion", "/songsuggestion"}:
        await handle_song_suggestion(message, pool)
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

    lowered = text.lower()
    wants_reminder = ("hatırlat" in lowered) or ("напомн" in lowered)
    t = parse_time_from_text(text)
    if not t:
        if wants_reminder:
            await message.answer(
                "Hangi saat için hatırlatayım? Örn: 'saat 15:00' ya da '15'te hatırlat'"
            )
        return

    now = datetime.now(TZ)
    remind_at = datetime.combine(now.date(), t, tzinfo=TZ)
    if remind_at <= now:
        remind_at = remind_at + timedelta(days=1)

    if wants_reminder:
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


def build_song_message(song: dict) -> str:
    title = song.get("title", "")
    artist = song.get("artist", "")
    genre = song.get("genre", "")
    ru_link = song.get("ru_link")
    lines = [
        f"Песня: {title} • {artist}",
        f"Жанр: {genre}" if genre else "Жанр: -",
    ]
    if ru_link:
        lines.append(f"Перевод: {ru_link}")
    else:
        lines.append("Перевод: перевод не найден")
    return "\n".join(lines)


def build_next_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Next", callback_data="next_song")
    return kb.as_markup()


async def handle_song_suggestion(message: Message, pool: asyncpg.Pool) -> None:
    lang = detect_lang(message.text or "")
    await add_user(pool, message.chat.id, lang)
    await update_user_lang(pool, message.chat.id, lang)
    if not SONGS:
        await message.answer("Şarkı listesi boş.")
        return
    song = random.choice(SONGS)
    await message.answer(build_song_message(song), reply_markup=build_next_keyboard())


async def handle_send_love_now(message: Message, bot: Bot, pool: asyncpg.Pool) -> None:
    lang = detect_lang(message.text or "")
    await add_user(pool, message.chat.id, lang)
    await update_user_lang(pool, message.chat.id, lang)
    sent = await send_love_reminder(bot, pool)
    await message.answer(f"Love bildirimi gönderildi. Alıcı sayısı: {sent}")


async def handle_next_song(callback: CallbackQuery) -> None:
    if not SONGS:
        await callback.answer("Şarkı listesi boş.", show_alert=True)
        return
    song = random.choice(SONGS)
    await callback.message.edit_text(build_song_message(song), reply_markup=build_next_keyboard())
    await callback.answer()


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

    async def song_handler(message: Message):
        await handle_song_suggestion(message, pool)

    async def next_song_handler(callback: CallbackQuery):
        await handle_next_song(callback)

    async def send_love_now_handler(message: Message):
        await handle_send_love_now(message, bot, pool)

    async def message_handler(message: Message):
        await handle_message(message, bot, pool)

    dp.message.register(start_handler, CommandStart())
    dp.message.register(reminders_handler, Command("reminders"))
    dp.message.register(song_handler, Command("songsuggestion"))
    dp.message.register(send_love_now_handler, Command("sendlove"))
    dp.callback_query.register(next_song_handler, F.data == "next_song")
    dp.message.register(message_handler, F.text)

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(run_scheduled_broadcasts, "interval", minutes=1, args=[bot, pool])
    scheduler.add_job(check_reminders, "interval", minutes=1, args=[bot, pool])
    scheduler.start()

    # Catch up immediately after startup if a scheduled minute was missed during sleep/restart.
    await run_scheduled_broadcasts(bot, pool)

    await start_health_server()

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
