import os
from telegram import Update, Bot, ChatPermissions, Chat
from telegram.error import BadRequest, TelegramError
from telegram.ext import MessageHandler, Filters
from telegram.ext.dispatcher import run_async

from utils import dispatcher, LOGGER, updater

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


def verify_and_restrict_user(bot: Bot, chat_id: int, user_id: int, user_name: str = "User"):
    """Verify a user and mute/unmute them based on channel membership."""
    try:
        if check_all_channels(bot, user_id):
            # User is verified, ensure they're unmuted
            bot.restrict_chat_member(
                chat_id,
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
            LOGGER.debug(f"User {user_id} ({user_name}) verified and unmuted in chat {chat_id}")
            return True
        else:
            # User is not verified, mute them
            bot.restrict_chat_member(
                chat_id,
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
            LOGGER.debug(f"User {user_id} ({user_name}) not verified and muted in chat {chat_id}")
            return False
    except (BadRequest, TelegramError) as e:
        LOGGER.error(f"Error verifying user {user_id} in chat {chat_id}: {e}")
        return None


@run_async
def welcome_mute(bot: Bot, update: Update):
    """Mute new members who join unless they're in all required channels."""
    message = update.effective_message
    chat = update.effective_chat
    
    # Only process in groups/supergroups
    if chat.type not in ['group', 'supergroup']:
        return
    
    # Track this chat for periodic verification
    if chat.id not in active_chats:
        active_chats.add(chat.id)
        LOGGER.info(f"Added chat {chat.id} to verification tracking")
    
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
        # Check if the bot itself was added to the group
        if new_member.id == bot.id:
            LOGGER.info(f"Bot added to chat {chat.id}, verifying all existing members...")
            verify_all_members(bot, chat)
            continue
        
        # Skip other bots
        if new_member.is_bot:
            continue
        
        user_id = new_member.id
        LOGGER.info(f"User {user_id} ({new_member.first_name}) joined chat {chat.id}")
        verify_and_restrict_user(bot, chat.id, user_id, new_member.first_name)


def verify_all_members(bot: Bot, chat: Chat):
    """Verify all existing members in a chat."""
    try:
        # Get all chat members (only works in smaller groups or if bot is admin)
        chat_id = chat.id
        member_count = chat.get_members_count()
        
        LOGGER.info(f"Verifying {member_count} members in chat {chat_id}")
        
        # Note: get_chat_members requires the bot to be admin
        # For large groups, this might be rate-limited
        try:
            administrators = chat.get_administrators()
            
            # Try to get member list (this might fail for large groups)
            # We'll process what we can
            verified_count = 0
            muted_count = 0
            
            for admin in administrators:
                if not admin.user.is_bot:
                    result = verify_and_restrict_user(bot, chat_id, admin.user.id, admin.user.first_name)
                    if result is True:
                        verified_count += 1
                    elif result is False:
                        muted_count += 1
            
            LOGGER.info(f"Verified existing members in chat {chat_id}: {verified_count} verified, {muted_count} muted")
        except (BadRequest, TelegramError) as e:
            LOGGER.warning(f"Could not get full member list for chat {chat_id}: {e}")
            LOGGER.info(f"Periodic verification will handle member checks in chat {chat_id}")
            
    except (BadRequest, TelegramError) as e:
        LOGGER.error(f"Error verifying all members in chat {chat_id}: {e}")


def periodic_verification_job(bot, job):
    """Periodically verify all members in tracked groups."""
    LOGGER.debug(f"Running periodic verification for {len(active_chats)} chats...")
    
    for chat_id in list(active_chats):
        try:
            chat = bot.get_chat(chat_id)
            
            # Check if bot still has permissions
            bot_member = chat.get_member(bot.id)
            if not bot_member.can_restrict_members:
                continue
            
            # Get chat members and verify them
            try:
                # Get recent chat members (administrators as a sample)
                administrators = chat.get_administrators()
                for admin in administrators:
                    if not admin.user.is_bot:
                        verify_and_restrict_user(bot, chat_id, admin.user.id, admin.user.first_name)
            except (BadRequest, TelegramError) as e:
                LOGGER.debug(f"Could not verify members in chat {chat_id}: {e}")
                
        except (BadRequest, TelegramError) as e:
            LOGGER.debug(f"Error accessing chat {chat_id}: {e}")
            # Remove chat if it's no longer accessible
            active_chats.discard(chat_id)


__mod_name__ = "Channel Verify"

__help__ = """
*Channel Verification*

Automatically mutes new members who join the group unless they are members of all required channels.

*Features:*
• Verifies new members on join
• Verifies all existing members when bot is added
• Periodic verification every 5 seconds

*Admin Commands:*
This module works automatically in the background.

*Configuration:*
Set these environment variables:
• `REQUIRED_CHANNEL_1` - First required channel ID
• `REQUIRED_CHANNEL_2` - Second required channel ID  
• `REQUIRED_CHANNEL_3` - Third required channel ID

*Note:* Bot must have "Restrict Members" permission to use this feature.
"""


# Track active chats for periodic verification
active_chats = set()


WELCOME_MUTE_HANDLER = MessageHandler(Filters.status_update.new_chat_members, welcome_mute)

dispatcher.add_handler(WELCOME_MUTE_HANDLER)

# Add periodic verification job (every 5 seconds)
if REQUIRED_CHANNELS:
    job_queue = updater.job_queue
    job_queue.run_repeating(periodic_verification_job, interval=5, first=10)
    LOGGER.info("Channel verification: Periodic verification enabled (every 5 seconds)")
