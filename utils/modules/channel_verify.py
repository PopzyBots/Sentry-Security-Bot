import os
from datetime import datetime

from telegram import Update, Bot, ChatPermissions, Chat
from telegram.error import BadRequest, TelegramError
from telegram.ext import MessageHandler, Filters

from utils import dispatcher, LOGGER, updater

# ==============================
# GLOBALS
# ==============================

job_queue = updater.job_queue
active_chats = set()
known_members = {}

# ==============================
# CONFIG
# ==============================

REQUIRED_CHANNEL_IDS = []
LOG_CHANNEL_ID = None

try:
    for var in ("REQUIRED_CHANNEL_1", "REQUIRED_CHANNEL_2", "REQUIRED_CHANNEL_3"):
        cid = os.getenv(var)
        if cid:
            REQUIRED_CHANNEL_IDS.append(int(cid))

    log_id = os.getenv("LOG_CHANNEL_ID")
    if log_id:
        LOG_CHANNEL_ID = int(log_id)

except ValueError:
    LOGGER.warning("Invalid channel IDs provided. Channel verification disabled.")
    REQUIRED_CHANNEL_IDS = []

# ==============================
# HELPERS
# ==============================

def is_user_in_channel(bot: Bot, user_id: int, channel_id: int) -> bool:
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError:
        return False


def check_all_channels(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL_IDS:
        return True
    return all(is_user_in_channel(bot, user_id, cid) for cid in REQUIRED_CHANNEL_IDS)


def track_member(user_id: int, chat_id: int, first_name: str):
    known_members.setdefault(chat_id, {})[user_id] = first_name


# ==============================
# CORE LOGIC
# ==============================

def verify_and_restrict_user(
    bot: Bot,
    chat_id: int,
    user_id: int,
    user_name: str = "User",
):
    try:
        chat = bot.get_chat(chat_id)
        member = chat.get_member(user_id)

        if member.status in ("creator", "administrator"):
            return None

        verified = check_all_channels(bot, user_id)

        permissions = ChatPermissions(
            can_send_messages=verified,
            can_send_media_messages=verified,
            can_send_polls=verified,
            can_send_other_messages=verified,
            can_add_web_page_previews=verified,
            can_invite_users=verified,
            can_change_info=False,
            can_pin_messages=False,
        )

        bot.restrict_chat_member(chat_id, user_id, permissions)

        if LOG_CHANNEL_ID:
            status = "unmuted" if verified else "muted"
            emoji = "✅" if verified else "❌"
            bot.send_message(
                LOG_CHANNEL_ID,
                f"{emoji} User {user_name} ({user_id}) {status} in chat {chat_id}",
            )

        return verified

    except TelegramError as e:
        LOGGER.error(f"Verification failed for {user_id} in {chat_id}: {e}")
        return None


def verify_all_members(bot: Bot, chat: Chat):
    try:
        admins = chat.get_administrators()
        for admin in admins:
            if not admin.user.is_bot:
                verify_and_restrict_user(
                    bot,
                    chat.id,
                    admin.user.id,
                    admin.user.first_name,
                )
    except TelegramError as e:
        LOGGER.warning(f"Could not verify existing members in {chat.id}: {e}")


# ==============================
# HANDLERS
# ==============================

def welcome_mute(update: Update, context):
    bot = context.bot
    chat = update.effective_chat
    message = update.effective_message

    if not chat or chat.type not in ("group", "supergroup"):
        return

    active_chats.add(chat.id)

    if not message or not message.new_chat_members:
        return

    for user in message.new_chat_members:
        if user.id == bot.id:
            LOGGER.info(f"Bot added to chat {chat.id}, verifying members")
            verify_all_members(bot, chat)
            continue

        if user.is_bot:
            continue

        track_member(user.id, chat.id, user.first_name)
        verify_and_restrict_user(bot, chat.id, user.id, user.first_name)


def verify_on_message(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user

    if not chat or chat.type not in ("group", "supergroup"):
        return
    if user.is_bot:
        return

    active_chats.add(chat.id)
    track_member(user.id, chat.id, user.first_name)
    verify_and_restrict_user(context.bot, chat.id, user.id, user.first_name)


# ==============================
# PERIODIC JOB
# ==============================

def periodic_verification_job(bot, job):
    bot = context.bot
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    LOGGER.debug(f"Periodic verification @ {now} UTC")

    for chat_id in list(active_chats):
        try:
            chat = bot.get_chat(chat_id)
            bot_member = chat.get_member(bot.id)

            if not bot_member.can_restrict_members:
                continue

            members = known_members.get(chat_id, {})
            for uid, name in members.items():
                verify_and_restrict_user(bot, chat_id, uid, name)

        except TelegramError:
            active_chats.discard(chat_id)


# ==============================
# REGISTRATION
# ==============================

dispatcher.add_handler(
    MessageHandler(Filters.status_update.new_chat_members, welcome_mute),
    group=1,
)

dispatcher.add_handler(
    MessageHandler(Filters.text & ~Filters.command, verify_on_message),
    group=2,
)

if REQUIRED_CHANNEL_IDS:
    job_queue.run_repeating(periodic_verification_job, interval=5, first=10)
    LOGGER.info("Channel verification enabled (every 5 seconds)")


# ==============================
# MODULE META
# ==============================

__mod_name__ = "Channel Verify"

__help__ = """
*Channel Verification*

Automatically mutes users unless they are members of required channels.

• Verifies users on join
• Verifies users on message
• Periodic re-verification
• Admins are never muted

Environment variables:
• REQUIRED_CHANNEL_1
• REQUIRED_CHANNEL_2
• REQUIRED_CHANNEL_3
• LOG_CHANNEL_ID
"""
