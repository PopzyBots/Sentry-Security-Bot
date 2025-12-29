import os
from datetime import datetime
from telegram import Update, Bot, ChatPermissions, Chat
from telegram.error import BadRequest, TelegramError
from telegram.ext import MessageHandler, Filters
from telegram.ext.dispatcher import run_async

from utils import dispatcher, LOGGER, updater

# ================= CONFIG ================= #

REQUIRED_CHANNEL_1 = os.getenv("REQUIRED_CHANNEL_1", "")
REQUIRED_CHANNEL_2 = os.getenv("REQUIRED_CHANNEL_2", "")
REQUIRED_CHANNEL_3 = os.getenv("REQUIRED_CHANNEL_3", "")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID", "0"))

# Convert channel IDs
try:
    REQUIRED_CHANNELS = []
    if REQUIRED_CHANNEL_1:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_1))
    if REQUIRED_CHANNEL_2:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_2))
    if REQUIRED_CHANNEL_3:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_3))
except ValueError:
    LOGGER.warning("Invalid channel IDs. Channel verification disabled.")
    REQUIRED_CHANNELS = []

# ================= STATE ================= #

active_chats = set()
muted_users = {}  # {chat_id: set(user_ids)}

# ================= HELPERS ================= #

def log_unmute(bot: Bot, chat_id: int, user_id: int, user_name: str):
    if not LOGS_CHANNEL_ID:
        return
    try:
        bot.send_message(
            LOGS_CHANNEL_ID,
            f"✅ User unmuted\n"
            f"👤 {user_name}\n"
            f"🆔 {user_id}\n"
            f"💬 Chat: {chat_id}"
        )
    except TelegramError as e:
        LOGGER.warning(f"Failed to send unmute log: {e}")


def is_user_in_channel(bot: Bot, user_id: int, channel_id: int) -> bool:
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError:
        return False


def check_all_channels(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNELS:
        return True
    return all(is_user_in_channel(bot, user_id, ch) for ch in REQUIRED_CHANNELS)

# ================= CORE ================= #

def verify_and_restrict_user(bot: Bot, chat_id: int, user_id: int, user_name="User"):
    try:
        chat = bot.get_chat(chat_id)
        member = chat.get_member(user_id)

        if member.status in ("administrator", "creator"):
            return None

        if check_all_channels(bot, user_id):
            bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                ),
            )

            muted_users.get(chat_id, set()).discard(user_id)
            LOGGER.info(f"User {user_id} ({user_name}) unmuted in chat {chat_id}")
            log_unmute(bot, chat_id, user_id, user_name)
            return True

        else:
            bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_invite_users=False,
                ),
            )

            muted_users.setdefault(chat_id, set()).add(user_id)
            LOGGER.debug(f"User {user_id} ({user_name}) muted in chat {chat_id}")
            return False

    except TelegramError as e:
        LOGGER.error(f"Verification error for {user_id} in {chat_id}: {e}")
        return None

# ================= JOIN HANDLER ================= #

@run_async
def welcome_mute(bot: Bot, update: Update):
    chat = update.effective_chat
    message = update.effective_message

    if chat.type not in ("group", "supergroup"):
        return

    active_chats.add(chat.id)

    bot_member = chat.get_member(bot.id)
    if not bot_member.can_restrict_members:
        return

    for user in message.new_chat_members:
        if user.is_bot:
            continue

        LOGGER.info(f"User {user.id} joined chat {chat.id}")
        verify_and_restrict_user(bot, chat.id, user.id, user.first_name)

# ================= PERIODIC JOB ================= #

def periodic_verification_job(bot, job):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    LOGGER.info(f"Periodic check done at {now} UTC")

    for chat_id, users in list(muted_users.items()):
        if not users:
            continue

        try:
            chat = bot.get_chat(chat_id)
            bot_member = chat.get_member(bot.id)

            if not bot_member.can_restrict_members:
                continue

            for user_id in list(users):
                try:
                    member = chat.get_member(user_id)
                    name = member.user.first_name or "User"

                    if check_all_channels(bot, user_id):
                        verify_and_restrict_user(bot, chat_id, user_id, name)

                except TelegramError:
                    users.discard(user_id)

        except TelegramError:
            muted_users.pop(chat_id, None)

# ================= HANDLERS ================= #

WELCOME_MUTE_HANDLER = MessageHandler(
    Filters.status_update.new_chat_members,
    welcome_mute
)

dispatcher.add_handler(WELCOME_MUTE_HANDLER, group=1)

# ================= JOB ================= #

if REQUIRED_CHANNELS:
    updater.job_queue.run_repeating(
        periodic_verification_job,
        interval=10,
        first=10
    )
    LOGGER.info("Channel verification enabled (interval: 10 seconds)")
