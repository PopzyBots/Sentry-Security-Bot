from io import BytesIO
from time import sleep
from typing import Optional

from telegram import TelegramError, Chat, Message, ParseMode
from telegram import Update, Bot
from telegram.error import BadRequest
from telegram.ext import MessageHandler, Filters, CommandHandler
from telegram.ext.dispatcher import run_async

import utils.modules.sql.users_sql as sql
from utils import dispatcher, OWNER_ID, LOGGER, MESSAGE_DUMP
from utils.modules.helper_funcs.filters import CustomFilters

USERS_GROUP = 4


def get_user_id(username):
    # ensure valid userid
    if len(username) <= 5:
        return None

    if username.startswith('@'):
        username = username[1:]

    users = sql.get_userid_by_name(username)

    if not users:
        return None

    elif len(users) == 1:
        return users[0].user_id

    else:
        for user_obj in users:
            try:
                userdat = dispatcher.bot.get_chat(user_obj.user_id)
                if userdat.username == username:
                    return userdat.id

            except BadRequest as excp:
                if excp.message == 'Chat not found':
                    pass
                else:
                    LOGGER.exception("Error extracting user ID")

    return None


@run_async
def broadcast(bot: Bot, update: Update):
    """
    Broadcast a message to all groups the bot is in.
    Only the bot owner can use this command.
    
    Usage:
    /broadcast <message> - Send text message to all groups
    /broadcast [reply to message] - Forward/send replied message to all groups
    """
    msg = update.effective_message
    user = update.effective_user
    
    # Double check owner (filter should handle this, but extra safety)
    if user.id != OWNER_ID:
        return
    
    # Check if replying to a message
    if msg.reply_to_message:
        to_broadcast = msg.reply_to_message
        broadcast_type = "forwarded message"
    else:
        # Extract message text
        to_send = msg.text.split(None, 1)
        if len(to_send) < 2:
            msg.reply_text(
                "❌ <b>Broadcast Usage:</b>\n\n"
                "<b>Method 1:</b> Send text message\n"
                "<code>/broadcast Your message here</code>\n\n"
                "<b>Method 2:</b> Forward any message (text, photo, video, etc.)\n"
                "Reply to any message with <code>/broadcast</code>",
                parse_mode="HTML"
            )
            return
        to_broadcast = to_send[1]
        broadcast_type = "text message"
    
    # Get all chats
    chats = sql.get_all_chats() or []
    
    if not chats:
        msg.reply_text("⚠️ No groups found in database!")
        return
    
    # Send acknowledgement to user
    msg.reply_text("Broadcast message is sent successfully ✅.")
    
    # Send initial status to log channel
    if MESSAGE_DUMP:
        try:
            status_msg = bot.send_message(
                MESSAGE_DUMP,
                f"📡 <b>Broadcast Started</b>\n\n"
                f"<b>Type:</b> {broadcast_type}\n"
                f"<b>Initiated by:</b> {user.first_name} (<code>{user.id}</code>)\n"
                f"<b>Total groups:</b> {len(chats)}\n"
                f"<b>Status:</b> In progress...",
                parse_mode="HTML"
            )
        except:
            status_msg = None
    else:
        status_msg = None
    
    # Broadcast to all chats
    success = 0
    failed = 0
    failed_chats = []
    
    for idx, chat in enumerate(chats):
        try:
            if msg.reply_to_message:
                # Try to copy the message (preserves formatting, media, etc.)
                try:
                    msg.reply_to_message.copy(chat.chat_id)
                except AttributeError:
                    # Fallback for older python-telegram-bot versions
                    msg.reply_to_message.forward(chat.chat_id)
            else:
                # Send text message
                bot.sendMessage(int(chat.chat_id), to_broadcast, parse_mode="HTML")
            
            success += 1
            sleep(0.1)  # Rate limiting
            
        except TelegramError as e:
            failed += 1
            failed_chats.append((chat.chat_name, chat.chat_id, str(e)))
            LOGGER.warning("Couldn't send broadcast to %s (ID: %s): %s", 
                          str(chat.chat_name), str(chat.chat_id), str(e))
        
        # Update progress in log channel every 20 chats
        if MESSAGE_DUMP and status_msg and ((idx + 1) % 20 == 0 or (idx + 1) == len(chats)):
            try:
                status_msg.edit_text(
                    f"📡 <b>Broadcast In Progress</b>\n\n"
                    f"<b>Type:</b> {broadcast_type}\n"
                    f"<b>Initiated by:</b> {user.first_name} (<code>{user.id}</code>)\n"
                    f"<b>Total groups:</b> {len(chats)}\n"
                    f"<b>Progress:</b> {idx + 1}/{len(chats)}\n"
                    f"<b>✅ Success:</b> {success}\n"
                    f"<b>❌ Failed:</b> {failed}",
                    parse_mode="HTML"
                )
            except:
                pass
    
    # Send final summary to log channel
    if MESSAGE_DUMP:
        summary = (
            f"✅ <b>Broadcast Complete</b>\n\n"
            f"<b>Type:</b> {broadcast_type}\n"
            f"<b>Initiated by:</b> {user.first_name} (<code>{user.id}</code>)\n\n"
            f"📊 <b>Statistics:</b>\n"
            f"• Total groups: {len(chats)}\n"
            f"• Successfully sent: {success}\n"
            f"• Failed: {failed}\n"
        )
        
        if failed > 0:
            summary += f"\n⚠️ <i>{failed} groups failed to receive the message</i>"
        
        try:
            if status_msg:
                status_msg.edit_text(summary, parse_mode="HTML")
            else:
                bot.send_message(MESSAGE_DUMP, summary, parse_mode="HTML")
        except:
            pass
        
        # Send detailed failure report to log channel if there are failures
        if failed_chats and failed <= 50:  # Show up to 50 failures
            failure_report = "<b>📋 Failed Groups Report:</b>\n\n"
            for name, chat_id, error in failed_chats[:50]:
                failure_report += f"• {name or 'Unknown'} (<code>{chat_id}</code>)\n  <i>Error: {error[:80]}</i>\n\n"
            
            try:
                bot.send_message(MESSAGE_DUMP, failure_report, parse_mode="HTML")
            except:
                pass


@run_async
def log_user(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]
    msg = update.effective_message  # type: Optional[Message]

    sql.update_user(msg.from_user.id,
                    msg.from_user.username,
                    chat.id,
                    chat.title)

    if msg.reply_to_message:
        sql.update_user(msg.reply_to_message.from_user.id,
                        msg.reply_to_message.from_user.username,
                        chat.id,
                        chat.title)

    if msg.forward_from:
        sql.update_user(msg.forward_from.id,
                        msg.forward_from.username)


@run_async
def chats(bot: Bot, update: Update):
    all_chats = sql.get_all_chats() or []
    chatfile = 'List of chats.\n'
    for chat in all_chats:
        chatfile += "{} - ({})\n".format(chat.chat_name, chat.chat_id)

    with BytesIO(str.encode(chatfile)) as output:
        output.name = "chatlist.txt"
        update.effective_message.reply_document(document=output, filename="chatlist.txt",
                                                caption="Here is the list of chats in my database.")


def __user_info__(user_id):
    if user_id == dispatcher.bot.id:
        return """I've seen them in... Wow. Are they stalking me? They're in all the same places I am... oh. It's me."""
    num_chats = sql.get_user_num_chats(user_id)
    return """I've seen them in <code>{}</code> chats in total.""".format(num_chats)


def __stats__():
    return "{} users, across {} chats".format(sql.num_users(), sql.num_chats())


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


__help__ = ""  # no help string

__mod_name__ = "Users"

BROADCAST_HANDLER = CommandHandler("broadcast", broadcast, filters=Filters.user(OWNER_ID))
USER_HANDLER = MessageHandler(Filters.all & Filters.group, log_user)
CHATLIST_HANDLER = CommandHandler("chatlist", chats, filters=CustomFilters.sudo_filter)

dispatcher.add_handler(USER_HANDLER, USERS_GROUP)
dispatcher.add_handler(BROADCAST_HANDLER)
dispatcher.add_handler(CHATLIST_HANDLER)
