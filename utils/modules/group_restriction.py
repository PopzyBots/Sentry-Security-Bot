"""
Group Restriction Module
Restricts bot to work only in specified group(s).
Automatically leaves any other groups.
"""

from telegram import Update, Bot
from telegram.ext import MessageHandler, Filters
from telegram.ext.dispatcher import run_async

from utils import dispatcher, LOGGER

# Allowed group ID(s) - bot will only work in these groups
ALLOWED_GROUP_ID = -1003338915868

# You can add more allowed groups here as a list if needed
# ALLOWED_GROUP_IDS = [-1003338915868, -1002345678901, ...]


@run_async
def check_group_restriction(bot: Bot, update: Update):
    """
    Check if bot was added to an unauthorized group and leave if so.
    Also monitors messages to ensure bot stays only in allowed groups.
    """
    message = update.effective_message
    chat = update.effective_chat
    
    # Only process group chats
    if chat.type not in ['group', 'supergroup']:
        return
    
    # Check if this group is allowed
    if chat.id != ALLOWED_GROUP_ID:
        LOGGER.warning(f"Bot added to unauthorized group: {chat.id} ({chat.title}). Leaving automatically.")
        
        try:
            # Send a message before leaving (optional)
            bot.send_message(
                chat.id,
                "⚠️ This bot is restricted to authorized groups only. Leaving this chat."
            )
        except Exception:
            pass  # If can't send, just leave
        
        # Leave the group
        try:
            bot.leave_chat(chat.id)
            LOGGER.info(f"Successfully left unauthorized group: {chat.id}")
        except Exception as e:
            LOGGER.error(f"Failed to leave unauthorized group {chat.id}: {e}")


@run_async
def on_bot_added(bot: Bot, update: Update):
    """
    Triggered when bot is added to a group.
    Checks if the group is authorized.
    """
    message = update.effective_message
    chat = update.effective_chat
    
    # Only process group chats
    if chat.type not in ['group', 'supergroup']:
        return
    
    # Check if bot was added
    new_members = message.new_chat_members
    if not new_members:
        return
    
    for new_member in new_members:
        if new_member.id == bot.id:
            # Bot was just added to this group
            if chat.id != ALLOWED_GROUP_ID:
                LOGGER.warning(f"Bot was added to unauthorized group: {chat.id} ({chat.title}). Leaving immediately.")
                
                try:
                    # Send notification before leaving
                    bot.send_message(
                        chat.id,
                        "⚠️ <b>Unauthorized Group</b>\n\n"
                        "This bot is restricted and can only be used in authorized groups.\n"
                        "Leaving this chat automatically.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                
                # Leave the group immediately
                try:
                    bot.leave_chat(chat.id)
                    LOGGER.info(f"Successfully left unauthorized group: {chat.id}")
                except Exception as e:
                    LOGGER.error(f"Failed to leave unauthorized group {chat.id}: {e}")
            else:
                LOGGER.info(f"Bot added to authorized group: {chat.id} ({chat.title})")


__mod_name__ = "Group Restriction"

__help__ = """
*Group Restriction*

This bot is restricted to specific authorized groups only.

*Allowed Group:*
• Group ID: `{}`

If added to any unauthorized group, the bot will automatically leave.

*Note:* This is an automatic security feature and cannot be disabled.
""".format(ALLOWED_GROUP_ID)


# Handler for when bot is added to a group (runs first with group=-1)
BOT_ADDED_HANDLER = MessageHandler(
    Filters.status_update.new_chat_members,
    on_bot_added
)

# Handler for any message in groups (backup check)
GROUP_CHECK_HANDLER = MessageHandler(
    Filters.group,
    check_group_restriction
)

# Register handlers with high priority (negative group number = runs first)
dispatcher.add_handler(BOT_ADDED_HANDLER, group=-1)
dispatcher.add_handler(GROUP_CHECK_HANDLER, group=-1)

LOGGER.info(f"Group restriction enabled - Only allowing group ID: {ALLOWED_GROUP_ID}")
