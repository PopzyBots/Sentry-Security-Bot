import os
from telegram import Update, Bot, ChatPermissions
from telegram.error import BadRequest, TelegramError
from telegram.ext import MessageHandler, Filters
from telegram.ext.dispatcher import run_async

from utils import dispatcher, LOGGER

# Get channel IDs from environment variables
REQUIRED_CHANNEL_1 = os.getenv("REQUIRED_CHANNEL_1", "")
REQUIRED_CHANNEL_2 = os.getenv("REQUIRED_CHANNEL_2", "")
REQUIRED_CHANNEL_3 = os.getenv("REQUIRED_CHANNEL_3", "")

# Convert to integers if provided
try:
    REQUIRED_CHANNELS = []
    if REQUIRED_CHANNEL_1:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_1))
    if REQUIRED_CHANNEL_2:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_2))
    if REQUIRED_CHANNEL_3:
        REQUIRED_CHANNELS.append(int(REQUIRED_CHANNEL_3))
except ValueError:
    LOGGER.warning("Invalid channel IDs in environment variables. Channel verification disabled.")
    REQUIRED_CHANNELS = []


def is_user_in_channel(bot: Bot, user_id: int, channel_id: int) -> bool:
    """Check if a user is a member of a specific channel."""
    try:
        member = bot.get_chat_member(channel_id, user_id)
        # Check if user is a member (not left, kicked, or restricted)
        return member.status in ['member', 'administrator', 'creator']
    except (BadRequest, TelegramError) as e:
        LOGGER.warning(f"Error checking membership for user {user_id} in channel {channel_id}: {e}")
        return False


def check_all_channels(bot: Bot, user_id: int) -> bool:
    """Check if user is a member of all required channels."""
    if not REQUIRED_CHANNELS:
        return True  # If no channels configured, don't restrict
    
    for channel_id in REQUIRED_CHANNELS:
        if not is_user_in_channel(bot, user_id, channel_id):
            return False
    return True


@run_async
def welcome_mute(bot: Bot, update: Update):
    """Mute new members who join unless they're in all required channels."""
    message = update.effective_message
    chat = update.effective_chat
    
    # Only process in groups/supergroups
    if chat.type not in ['group', 'supergroup']:
        return
    
    # Check if bot has permission to restrict members
    bot_member = chat.get_member(bot.id)
    if not bot_member.can_restrict_members:
        LOGGER.warning(f"Bot doesn't have permission to restrict members in chat {chat.id}")
        return
    
    # Process new members
    new_members = message.new_chat_members
    if not new_members:
        return
    
    for new_member in new_members:
        # Skip bots
        if new_member.is_bot:
            continue
        
        user_id = new_member.id
        
        # Check if user is in all required channels
        if check_all_channels(bot, user_id):
            # User is in all channels, don't mute
            LOGGER.info(f"User {user_id} ({new_member.first_name}) joined chat {chat.id} - verified in all channels")
            try:
                # Ensure user is unmuted (in case they were muted before)
                bot.restrict_chat_member(
                    chat.id,
                    user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=True,
                        can_pin_messages=False
                    )
                )
                message.reply_text(
                    f"Welcome {new_member.first_name}! ✅ Channel verification successful.",
                    quote=False
                )
            except (BadRequest, TelegramError) as e:
                LOGGER.error(f"Error unmuting verified user {user_id}: {e}")
        else:
            # User is not in all channels, mute them
            LOGGER.info(f"User {user_id} ({new_member.first_name}) joined chat {chat.id} - not in all required channels, muting")
            try:
                bot.restrict_chat_member(
                    chat.id,
                    user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    )
                )
                
                # Build channel list message
                channel_mentions = []
                for i, channel_id in enumerate(REQUIRED_CHANNELS, 1):
                    try:
                        channel = bot.get_chat(channel_id)
                        if channel.username:
                            channel_mentions.append(f"@{channel.username}")
                        else:
                            channel_mentions.append(channel.title or f"Channel {i}")
                    except:
                        channel_mentions.append(f"Channel {i}")
                
                channels_text = ", ".join(channel_mentions)
                
                message.reply_text(
                    f"⚠️ {new_member.first_name} has been muted.\n\n"
                    f"To send messages in this group, you must join these channels:\n"
                    f"{channels_text}\n\n"
                    f"After joining, leave and rejoin this group to be verified.",
                    quote=False
                )
            except (BadRequest, TelegramError) as e:
                LOGGER.error(f"Error muting user {user_id}: {e}")


__mod_name__ = "Channel Verify"

__help__ = """
*Channel Verification*

Automatically mutes new members who join the group unless they are members of all required channels.

*Admin Commands:*
This module works automatically when new members join.

*Configuration:*
Set these environment variables:
• `REQUIRED_CHANNEL_1` - First required channel ID
• `REQUIRED_CHANNEL_2` - Second required channel ID  
• `REQUIRED_CHANNEL_3` - Third required channel ID

*Note:* Bot must have "Restrict Members" permission to use this feature.
"""


WELCOME_MUTE_HANDLER = MessageHandler(Filters.status_update.new_chat_members, welcome_mute)

dispatcher.add_handler(WELCOME_MUTE_HANDLER)
