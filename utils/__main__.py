import importlib
import re
import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import Unauthorized, BadRequest, TimedOut, NetworkError, ChatMigrated, TelegramError
from telegram.ext import CommandHandler, Filters, MessageHandler, CallbackQueryHandler
from telegram.ext.dispatcher import run_async, DispatcherHandlerStop
from telegram.utils.helpers import escape_markdown

from utils import dispatcher, updater, TOKEN, WEBHOOK, OWNER_ID, CERT_PATH, PORT, URL, LOGGER, \
    ALLOW_EXCL
# needed to dynamically load modules
# NOTE: Module order is not guaranteed, specify that in the config file!
from utils.modules import ALL_MODULES
from utils.modules.helper_funcs.chat_status import is_user_admin
from utils.modules.helper_funcs.misc import paginate_modules
from utils.modules.sql import users_sql
from utils.modules.sql.users_sql import del_chat
from utils.modules.sql import connection_sql

PM_START_TEXT = """
👋 <b>Hey {first}, I'm {botname} — your smart security and moderation bot.</b>

<i>I'll keep chats clean, safe, and fully under control.</i>
"""

ABOUT_TEXT = """<b>About</b>

Sentry is a group security and moderation bot built to protect Telegram communities from spam, abuse, and disorder through automated rule enforcement.

<b>Features</b>

• Moderation tools (ban, mute, warn, kick)  
• Anti-spam and flood protection  
• Content locks and restrictions  
• Custom welcome and goodbye messages  
• Filters, notes, and admin utilities  
• Optional global moderation  
• Lightweight and fast
"""

HELP_TEXT = """<b>Essential Commands</b>
Core commands for moderation, security, and group management.

<b>Admin & Moderation</b>
/ban – Ban a user  
/unban – Unban a user  
/mute – Mute a user  
/warn – Warn a user  

<b>Security & Control</b>
/lock – Lock content such as links, media, or stickers  
/unlock – Unlock restricted content  

<b>Welcome System</b>
/setwelcome – Set a custom welcome message  
/welcome – View or toggle the welcome message  

<b>Utilities</b>
/rules – Show group rules  
/adminlist – Display the list of admins

"""
# PM_START_PHOTO_ID is fetched only from the environment. Set the env var PM_START_PHOTO_ID to a Telegram file_id
# Example: PM_START_PHOTO_ID=AgACAgUAAxkBAANDaUNt19igRloquRr_a0_pDk4P4WkAAoALaxvJIyFWRDreG7mSpR8ACAEAAwIAA3kABx4E
import os
PM_START_PHOTO_ID = os.getenv("PM_START_PHOTO_ID", "")

# Note: bundled sample image, automatic upload and caching have been removed. Use /genid store to manually set the file id.

HELP_STRINGS = """
Hey! My name is *{}*. I am a group management bot, here to help you get around and keep the order in your groups!
I have lots of handy features, such as flood control, a warning system, a note keeping system, and even predetermined replies on certain keywords.

*Helpful commands*:
- /start: Starts me! You've probably already used this.
- /settings: Sends this message; I'll tell you more about myself!

{}
All commands can be used with the following: / !
""".format(dispatcher.bot.first_name, "" if not ALLOW_EXCL else "If you have any bugs or questions on how to use me, have a look at my [Group](https://t.me/ProHelpDesk), or head to @ProIndians.")


IMPORTED = {}
MIGRATEABLE = []
HELPABLE = {}
STATS = []
USER_INFO = []
DATA_IMPORT = []
DATA_EXPORT = []

CHAT_SETTINGS = {}
USER_SETTINGS = {}

for module_name in ALL_MODULES:
    imported_module = importlib.import_module("utils.modules." + module_name)
    if not hasattr(imported_module, "__mod_name__"):
        imported_module.__mod_name__ = imported_module.__name__

    if not imported_module.__mod_name__.lower() in IMPORTED:
        IMPORTED[imported_module.__mod_name__.lower()] = imported_module
    else:
        raise Exception("Can't have two modules with the same name! Please change one")

    if hasattr(imported_module, "__help__") and imported_module.__help__:
        HELPABLE[imported_module.__mod_name__.lower()] = imported_module

    # Chats to migrate on chat_migrated events
    if hasattr(imported_module, "__migrate__"):
        MIGRATEABLE.append(imported_module)

    if hasattr(imported_module, "__stats__"):
        STATS.append(imported_module)

    if hasattr(imported_module, "__user_info__"):
        USER_INFO.append(imported_module)

    if hasattr(imported_module, "__import_data__"):
        DATA_IMPORT.append(imported_module)

    if hasattr(imported_module, "__export_data__"):
        DATA_EXPORT.append(imported_module)

    if hasattr(imported_module, "__chat_settings__"):
        CHAT_SETTINGS[imported_module.__mod_name__.lower()] = imported_module

    if hasattr(imported_module, "__user_settings__"):
        USER_SETTINGS[imported_module.__mod_name__.lower()] = imported_module


# do not async
def send_help(chat_id, text, keyboard=None):
    if not keyboard:
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "settings"))
    dispatcher.bot.send_message(chat_id=chat_id,
                                text=text,
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard)


@run_async
def test(bot: Bot, update: Update):
    # pprint(eval(str(update)))
    # update.effective_message.reply_text("Hola tester! _I_ *have* `markdown`", parse_mode=ParseMode.MARKDOWN)
    update.effective_message.reply_text("This person edited a message")
    print(update.effective_message)


@run_async
def genid(bot: Bot, update: Update, args: List[str]):
    """Generate a Telegram file_id for a photo.

    Usage:
    - Reply to a photo with `/genid store` to save its file_id as the PM start photo (owner only).
    - Use `/genid clear` to remove the stored PM start photo id (owner only).
    - Send /genid while sending a photo (photo present in the same message) with `store` to save it.
    """
    msg = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]

    # parse optional command argument (e.g., store, clear)
    cmd = args[0].lower() if args else None
    global PM_START_PHOTO_ID

    # Handle clear/remove/delete commands (owner-only) even when no photo is present
    if cmd and cmd in ("clear", "remove", "delete"):
        if user.id != OWNER_ID:
            update.effective_message.reply_text("Only the bot owner can clear the stored PM start photo id.")
            return
        try:
            path = os.path.join(os.path.dirname(__file__), "pm_start_photo_id.txt")
            if os.path.exists(path):
                os.remove(path)
                PM_START_PHOTO_ID = ""
                update.effective_message.reply_text("Stored PM start photo id cleared and will no longer be used.")
                LOGGER.info("PM start photo id cleared via /genid by owner %s", user.id)
            else:
                # If file doesn't exist, still unset the in-memory id
                PM_START_PHOTO_ID = ""
                update.effective_message.reply_text("No stored PM start photo id found; in-memory id (if any) has been cleared.")
                LOGGER.info("/genid clear called but no stored file found; in-memory id cleared by owner %s", user.id)
        except Exception:
            LOGGER.exception("Failed to clear PM start photo id via /genid")
            update.effective_message.reply_text("Failed to clear stored file id.")
        return

    # try message itself first, then reply_to_message
    photo = None
    if msg.photo:
        photo = msg.photo[-1]
    elif msg.reply_to_message and msg.reply_to_message.photo:
        photo = msg.reply_to_message.photo[-1]

    # Only support storing the file id via: /genid store (owner only). Do not display file ids publicly.
    if not (cmd and cmd in ("store", "save", "set")):
        update.effective_message.reply_text(
            "Usage: reply to the photo with `/genid store` to save it as the PM start photo (bot owner only), or `/genid clear` to remove the stored id.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not photo:
        update.effective_message.reply_text(
            "Reply to a photo or send a photo with `/genid store` to save its file_id."
        )
        return

    # owner-only store
    if user.id != OWNER_ID:
        update.effective_message.reply_text("Only the bot owner can store the PM start photo file id.")
        return

    file_id = photo.file_id
    try:
        # Persist to disk so it survives restarts (optional helper for admins).
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pm_start_photo_id.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(file_id)
        PM_START_PHOTO_ID = file_id
        update.effective_message.reply_text("File id stored and will be used for the PM start message.")
        LOGGER.info("PM start photo id updated via /genid by owner %s", user.id)
    except Exception as e:
        LOGGER.exception("Failed to store PM start photo id via /genid")
        update.effective_message.reply_text(f"Failed to save file id to disk.\nError: {str(e)}\n\nTry checking file permissions in the bot directory.")


@run_async
def start(bot: Bot, update: Update, args: List[str]):
    if update.effective_chat.type == "private":
        if len(args) >= 1:
            cmd = args[0].lower()

            # Redirect legacy ?start=help to ?start=settings for backward compatibility
            if cmd == "help":
                cmd = "settings"

            if cmd == "settings":
                # Show help content when opened via ?start=settings
                send_help(update.effective_chat.id, HELP_STRINGS)

            elif cmd.startswith("stngs_"):
                match = re.match("stngs_(.*)", cmd)
                chat = dispatcher.bot.getChat(match.group(1))

                if is_user_admin(chat, update.effective_user.id):
                    send_settings(match.group(1), update.effective_user.id, False)
                else:
                    send_settings(match.group(1), update.effective_user.id, True)

            elif cmd == "about":
                # About message (legacy /start about)
                update.effective_message.reply_text(ABOUT_TEXT, parse_mode=ParseMode.HTML)

            elif args[0][1:].isdigit() and "rules" in IMPORTED:
                IMPORTED["rules"].send_rules(update, args[0], from_pm=True)

        else:
            first_name = update.effective_user.first_name
            user = update.effective_user
            # Format message using HTML with escaped values
            start_text = PM_START_TEXT.format(
                first=html.escape(first_name),
                botname=html.escape(bot.first_name),
            )
            
            # Check if user has an active connection
            connected_chat = connection_sql.get_connected_chat(user.id)
            has_connection = bool(connected_chat)
            
            # Build keyboard based on connection status
            keyboard_buttons = [
                [InlineKeyboardButton(text="➕ Add me to a Group ➕", url="t.me/{}?startgroup=true".format(bot.username))]
            ]
            
            # Only show Manage Group Settings button when connected
            if has_connection:
                keyboard_buttons.append([InlineKeyboardButton(text="⚙️ Manage Group Settings ✍️", callback_data="manage_settings")])
            
            keyboard_buttons.append([InlineKeyboardButton(text="Help", callback_data="settings"), InlineKeyboardButton(text="About", callback_data="about")])
            
            keyboard = InlineKeyboardMarkup(keyboard_buttons)

            if PM_START_PHOTO_ID:
                # Send cached Telegram file_id (fast) as photo with caption
                try:
                    update.effective_message.reply_photo(
                        photo=PM_START_PHOTO_ID,
                        caption=start_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_notification=False,
                    )
                except BadRequest:
                    # Fallback to text reply if file_id invalid or fails for any reason
                    update.effective_message.reply_text(
                        start_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                    )
            else:
                update.effective_message.reply_text(
                    start_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
    else:
        update.effective_message.reply_text("Hello all Join @ProIndians.")


# for test purposes
def error_callback(bot, update, error):
    try:
        raise error
    except Unauthorized:
        print("no nono1")
        print(error)
        # remove update.message.chat_id from conversation list
    except BadRequest:
        print("no nono2")
        print("BadRequest caught")
        print(error)

        # handle malformed requests - read more below!
    except TimedOut:
        print("no nono3")
        # handle slow connection problems
    except NetworkError:
        print("no nono4")
        # handle other connection problems
    except ChatMigrated as err:
        print("no nono5")
        print(err)
        # the chat_id of a group has changed, use e.new_chat_id instead
    except TelegramError:
        print(error)
        # handle all other telegram related errors


@run_async
def help_button(bot: Bot, update: Update):
    query = update.callback_query
    data = query.data
    msg = query.message

    # If user clicked the main Help button, show the help listing in-place
    if data == "settings":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="start_back")]])
        if msg.photo:
            msg.edit_caption(caption=HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            msg.edit_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        bot.answer_callback_query(query.id)
        return

    mod_match = re.match(r"settings_module\((.+?)\)", data)
    prev_match = re.match(r"settings_prev\((.+?)\)", data)
    next_match = re.match(r"settings_next\((.+?)\)", data)
    back_match = re.match(r"settings_back", data)
    try:
        if mod_match:
            module = mod_match.group(1)
            text = "Here is the help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
                   + HELPABLE[module].__help__
            query.message.reply_text(text=text,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         [[InlineKeyboardButton(text="Back", callback_data="settings_back")]]))

        elif prev_match:
            curr_page = int(prev_match.group(1))
            query.message.reply_text(HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(curr_page - 1, HELPABLE, "settings")))

        elif next_match:
            next_page = int(next_match.group(1))
            query.message.reply_text(HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(next_page + 1, HELPABLE, "settings")))

        elif back_match:
            query.message.reply_text(text=HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "settings")))

        # ensure no spinny white circle
        bot.answer_callback_query(query.id)
        query.message.delete()
    except BadRequest as excp:
        if excp.message == "Message is not modified":
            pass
        elif excp.message == "Query_id_invalid":
            pass
        elif excp.message == "Message can't be deleted":
            pass
        else:
            LOGGER.exception("Exception in help buttons. %s", str(query.data))


@run_async
def about_button(bot: Bot, update: Update):
    query = update.callback_query
    data = query.data
    try:
        # Determine whether the message is a photo (edit caption) or text (edit text)
        msg = query.message
        user = update.effective_user
        
        if data == "about":
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="start_back")]])
            if msg.photo:
                msg.edit_caption(caption=ABOUT_TEXT, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            else:
                msg.edit_text(ABOUT_TEXT, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            bot.answer_callback_query(query.id)
        elif data == "manage_settings":
            # Same behavior as /settings command
            bot.answer_callback_query(query.id)
            msg.delete()
            
            # Check if user has an active connection (flag logic)
            connected_chat = connection_sql.get_connected_chat(user.id)
            
            # Flag: True if connected, False if not connected
            has_connection = bool(connected_chat)
            
            # Debug message to show flag status
            dispatcher.bot.send_message(user.id, f"Flag Status: {has_connection}")
            
            if connected_chat:
                # User has an active connection (flag is True), show settings for that chat
                try:
                    send_settings(connected_chat.chat_id, user.id, False)
                except (BadRequest, TelegramError):
                    # Connection exists but chat is not accessible, disconnect user
                    connection_sql.disconnect(user.id)
                    text = (
                        "<b>😢 No connected group found.</b>\n\n"
                        "To manage group settings, use <code>/connect &lt;chat_id&gt;</code> to connect to a group.")
                    dispatcher.bot.send_message(user.id, text=text, parse_mode=ParseMode.HTML)
            else:
                # No active connection (flag is False), show message to connect
                text = (
                    "<b>😢 No connected group found.</b>\n\n"
                    "To manage group settings, use <code>/connect &lt;chat_id&gt;</code> to connect to a group.")
                dispatcher.bot.send_message(user.id, text=text, parse_mode=ParseMode.HTML)
        elif data == "start_back":
            # Rebuild the original start message and keyboard
            first_name = update.effective_user.first_name
            start_text = PM_START_TEXT.format(
                first=html.escape(first_name),
                botname=html.escape(bot.first_name),
            )
            
            # Check if user has an active connection
            connected_chat = connection_sql.get_connected_chat(user.id)
            has_connection = bool(connected_chat)
            
            # Build keyboard based on connection status
            keyboard_buttons = [
                [InlineKeyboardButton(text="➕ Add me to a Group ➕", url="t.me/{}?startgroup=true".format(bot.username))]
            ]
            
            # Only show Manage Group Settings button when connected
            if has_connection:
                keyboard_buttons.append([InlineKeyboardButton(text="⚙️ Manage Group Settings ✍️", callback_data="manage_settings")])
            
            keyboard_buttons.append([InlineKeyboardButton(text="Help", callback_data="settings"), InlineKeyboardButton(text="About", callback_data="about")])
            
            keyboard = InlineKeyboardMarkup(keyboard_buttons)
            
            if msg.photo:
                msg.edit_caption(caption=start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            else:
                msg.edit_text(start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            bot.answer_callback_query(query.id)
    except BadRequest as excp:
        LOGGER.exception("Exception in about button handler. %s", str(excp))
        try:
            bot.answer_callback_query(query.id, text="Action failed.")
        except Exception:
            pass


@run_async
def get_help(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]
    args = update.effective_message.text.split(None, 1)

    # ONLY send help in PM
    if chat.type != chat.PRIVATE:

        update.effective_message.reply_text("Contact me in PM to get the list of possible commands.",
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton(text="Help",
                                                                       url="t.me/{}?start=settings".format(
                                                                           bot.username))]]))
        return

    elif len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
        module = args[1].lower()
        text = "Here is the available help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
               + HELPABLE[module].__help__
        send_help(chat.id, text, InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="settings_back")]]))

def send_settings(chat_id, user_id, user=False):
    if user:
        if USER_SETTINGS:
            settings = "\n\n".join(
                "*{}*:\n{}".format(mod.__mod_name__, mod.__user_settings__(user_id)) for mod in USER_SETTINGS.values())
            dispatcher.bot.send_message(user_id, "These are your current settings:" + "\n\n" + settings,
                                        parse_mode=ParseMode.MARKDOWN)

        else:
            dispatcher.bot.send_message(user_id, "Seems like there aren't any user specific settings available :'(",
                                        parse_mode=ParseMode.MARKDOWN)

    else:
        if CHAT_SETTINGS:
            chat_name = dispatcher.bot.getChat(chat_id).title
            text = "<b>SETTINGS\nGroup:</b> <code>{}</code>\n\n<i>Select one of the settings that you want to change.</i>".format(
                html.escape(chat_name))
            dispatcher.bot.send_message(user_id, text=text, parse_mode=ParseMode.HTML,
                                        reply_markup=InlineKeyboardMarkup(
                                            paginate_modules(0, CHAT_SETTINGS, "stngs", chat=chat_id)))
        else:
            dispatcher.bot.send_message(user_id, "Seems like there aren't any chat settings available :'(\nSend this "
                                                 "in a group chat you're admin in to find its current settings!",
                                        parse_mode=ParseMode.MARKDOWN)


@run_async
def settings_button(bot: Bot, update: Update):
    query = update.callback_query
    user = update.effective_user
    msg = query.message
    data = query.data
    
    # Handle Back button to welcome screen from settings
    if data == "start_back":
        first_name = user.first_name
        start_text = PM_START_TEXT.format(
            first=html.escape(first_name),
            botname=html.escape(query.message.bot.first_name),
        )
        
        # Check if user has an active connection
        connected_chat = connection_sql.get_connected_chat(user.id)
        has_connection = bool(connected_chat)
        
        # Build keyboard based on connection status
        keyboard_buttons = [
            [InlineKeyboardButton(text="➕ Add me to a Group ➕", url="t.me/{}?startgroup=true".format(query.message.bot.username))]
        ]
        
        # Only show Manage Group Settings button when connected
        if has_connection:
            keyboard_buttons.append([InlineKeyboardButton(text="⚙️ Manage Group Settings ✍️", callback_data="manage_settings")])
        
        keyboard_buttons.append([InlineKeyboardButton(text="Help", callback_data="settings"), InlineKeyboardButton(text="About", callback_data="about")])
        
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        
        try:
            msg.edit_text(start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except BadRequest:
            msg.delete()
            dispatcher.bot.send_message(user.id, start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        bot.answer_callback_query(query.id)
        return
    
    mod_match = re.match(r"stngs_module\((.+?),(.+?)\)", query.data)
    prev_match = re.match(r"stngs_prev\((.+?),(.+?)\)", query.data)
    next_match = re.match(r"stngs_next\((.+?),(.+?)\)", query.data)
    back_match = re.match(r"stngs_back\((.+?)\)", query.data)
    try:
        if mod_match:
            chat_id = mod_match.group(1)
            module = mod_match.group(2)
            chat = bot.get_chat(chat_id)
            text = "*{}* has the following settings for the *{}* module:\n\n".format(escape_markdown(chat.title),
                                                                                     CHAT_SETTINGS[module].__mod_name__) + \
                   CHAT_SETTINGS[module].__chat_settings__(chat_id, user.id)
            query.message.reply_text(text=text,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         [[InlineKeyboardButton(text="Back",
                                                                callback_data="stngs_back({})".format(chat_id))]]))

        elif prev_match:
            chat_id = prev_match.group(1)
            curr_page = int(prev_match.group(2))
            chat = bot.get_chat(chat_id)
            query.message.reply_text("Hi there! There are quite a few settings for {} - go ahead and pick what "
                                     "you're interested in.".format(chat.title),
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(curr_page - 1, CHAT_SETTINGS, "stngs",
                                                          chat=chat_id)))

        elif next_match:
            chat_id = next_match.group(1)
            next_page = int(next_match.group(2))
            chat = bot.get_chat(chat_id)
            query.message.reply_text("Hi there! There are quite a few settings for {} - go ahead and pick what "
                                     "you're interested in.".format(chat.title),
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(next_page + 1, CHAT_SETTINGS, "stngs",
                                                          chat=chat_id)))

        elif back_match:
            chat_id = back_match.group(1)
            chat = bot.get_chat(chat_id)
            query.message.reply_text(text="Hi there! There are quite a few settings for {} - go ahead and pick what "
                                          "you're interested in.".format(escape_markdown(chat.title)),
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(paginate_modules(0, CHAT_SETTINGS, "stngs",
                                                                                        chat=chat_id)))

        # ensure no spinny white circle
        bot.answer_callback_query(query.id)
        query.message.delete()
    except BadRequest as excp:
        if excp.message == "Message is not modified":
            pass
        elif excp.message == "Query_id_invalid":
            pass
        elif excp.message == "Message can't be deleted":
            pass
        else:
            LOGGER.exception("Exception in settings buttons. %s", str(query.data))


@run_async
def get_settings(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = msg.text.split(None, 1)

    # ONLY send settings in PM
    if chat.type != chat.PRIVATE:
        if is_user_admin(chat, user.id):
            text = "Click here to get this chat's settings, as well as yours."
            msg.reply_text(text,
                           reply_markup=InlineKeyboardMarkup(
                               [[InlineKeyboardButton(text="Settings",
                                                      url="t.me/{}?start=stngs_{}".format(
                                                          bot.username, chat.id))]]))
        else:
            text = "Click here to check your settings."

    else:
        parts = msg.text.split()
        # Default behavior: no args -> show the user's settings in PM
        if len(parts) == 1:
            # Check if user has an active connection (flag logic)
            connected_chat = connection_sql.get_connected_chat(user.id)
            
            # Flag: True if connected, False if not connected
            has_connection = bool(connected_chat)
            
            # Debug message to show flag status
            msg.reply_text(f"Flag Status: {has_connection}")
            
            if connected_chat:
                # User has an active connection (flag is True), show settings for that chat
                try:
                    send_settings(connected_chat.chat_id, user.id, False)
                except (BadRequest, TelegramError):
                    # Connection exists but chat is not accessible, disconnect user
                    connection_sql.disconnect(user.id)
                    text = (
                        "<b>😢 No connected group found.</b>\n\n"
                        "To manage group settings, use <code>/connect &lt;chat_id&gt;</code> to connect to a group.")
                    msg.reply_text(text=text, parse_mode=ParseMode.HTML)
            else:
                # No active connection (flag is False), show message to connect
                text = (
                    "<b>😢 No connected group found.</b>\n\n"
                    "To manage group settings, use <code>/connect &lt;chat_id&gt;</code> to connect to a group.")
                msg.reply_text(text=text, parse_mode=ParseMode.HTML)
        # If the user explicitly asks for help, show the help text
        elif len(parts) > 1 and parts[1].lower() == 'help':
            send_help(chat.id, HELP_STRINGS)
        else:
            send_settings(chat.id, user.id, True)




def migrate_chats(bot: Bot, update: Update):
    msg = update.effective_message  # type: Optional[Message]
    if msg.migrate_to_chat_id:
        old_chat = update.effective_chat.id
        new_chat = msg.migrate_to_chat_id
    elif msg.migrate_from_chat_id:
        old_chat = msg.migrate_from_chat_id
        new_chat = update.effective_chat.id
    else:
        return

    LOGGER.info("Migrating from %s, to %s", str(old_chat), str(new_chat))
    for mod in MIGRATEABLE:
        mod.__migrate__(old_chat, new_chat)

    LOGGER.info("Successfully migrated!")
    raise DispatcherHandlerStop


@run_async
def left_chat(bot: Bot, update: Update):
    """Handler for when bot leaves or is removed from a group."""
    chat = update.effective_chat
    left_member = update.effective_message.left_chat_member
    
    # Check if the bot itself was removed
    if left_member.id == bot.id:
        LOGGER.info("Bot was removed from chat %s (%s)", chat.id, chat.title)
        # Remove chat from database
        del_chat(chat.id)
        LOGGER.info("Chat %s removed from database", chat.id)


def main():
    test_handler = CommandHandler("test", test)
    genid_handler = CommandHandler("genid", genid, pass_args=True)
    start_handler = CommandHandler("start", start, pass_args=True)

    # /help command migrated to /settings (handled inside get_settings for PM usage)
    help_callback_handler = CallbackQueryHandler(help_button, pattern=r"^settings")
    about_callback_handler = CallbackQueryHandler(about_button, pattern=r"^(about|manage_settings)$")
    settings_callback_handler = CallbackQueryHandler(settings_button, pattern=r"(stngs_|start_back)")

    settings_handler = CommandHandler("settings", get_settings)

    migrate_handler = MessageHandler(Filters.status_update.migrate, migrate_chats)
    left_chat_handler = MessageHandler(Filters.status_update.left_chat_member, left_chat)

    # dispatcher.add_handler(test_handler)
    dispatcher.add_handler(test_handler)
    dispatcher.add_handler(genid_handler)
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(settings_handler)
    dispatcher.add_handler(help_callback_handler)
    dispatcher.add_handler(about_callback_handler)
    dispatcher.add_handler(settings_callback_handler)
    dispatcher.add_handler(migrate_handler)
    dispatcher.add_handler(left_chat_handler)


    # dispatcher.add_error_handler(error_callback)



    if WEBHOOK:
        LOGGER.info("Using webhooks.")
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=TOKEN)

        if CERT_PATH:
            updater.bot.set_webhook(url=URL + TOKEN,
                                    certificate=open(CERT_PATH, 'rb'))
        else:
            updater.bot.set_webhook(url=URL + TOKEN)

    else:
        LOGGER.info("Using long polling.")
        updater.start_polling(timeout=15, read_latency=4)

    updater.idle()


if __name__ == '__main__':
    LOGGER.info("Successfully loaded modules: " + str(ALL_MODULES))
    main()
