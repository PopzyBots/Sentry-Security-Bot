import importlib
import re
import html
from typing import Optional, List

from telegram import Message, Chat, Update, Bot, User
from telegram import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.error import Unauthorized, BadRequest, TimedOut, NetworkError, ChatMigrated, TelegramError
from telegram.ext import CommandHandler, Filters, MessageHandler, CallbackQueryHandler
from telegram.ext.dispatcher import run_async, DispatcherHandlerStop
from telegram.utils.helpers import escape_markdown

from utils import dispatcher, updater, TOKEN, WEBHOOK, OWNER_ID, DONATION_LINK, CERT_PATH, PORT, URL, LOGGER, \
    ALLOW_EXCL
# needed to dynamically load modules
# NOTE: Module order is not guaranteed, specify that in the config file!
from utils.modules import ALL_MODULES
from utils.modules.helper_funcs.chat_status import is_user_admin
from utils.modules.helper_funcs.misc import paginate_modules

PM_START_TEXT = """
👋 <b>Hey {first}, I'm {botname} — your smart security and moderation bot.</b>

<i>I keep chats clean, safe, and fully under control 🛡️</i>
"""

# PM_START_PHOTO_ID is read from disk (if stored via /genid store) or from the environment.
# If a file `pm_start_photo_id.txt` exists in this package, its contents will override the environment variable.
# Example env var: PM_START_PHOTO_ID=AgACAgUAAxkBAANDaUNt19igRloquRr_a0_pDk4P4WkAAoALaxvJIyFWRDreG7mSpR8ACAEAAwIAA3kABx4E
import os
import json
PM_START_PHOTO_ID = os.getenv("PM_START_PHOTO_ID", "")

# Load stored file id (if previously saved via `/genid store`) so it persists across restarts
try:
    _pm_path = os.path.join(os.path.dirname(__file__), "pm_start_photo_id.txt")
    if os.path.exists(_pm_path):
        with open(_pm_path, "r", encoding="utf-8") as _f:
            _file_id = _f.read().strip()
            if _file_id:
                PM_START_PHOTO_ID = _file_id
                LOGGER.info("Loaded PM_START_PHOTO_ID from pm_start_photo_id.txt")
            else:
                LOGGER.info("Found pm_start_photo_id.txt but it was empty; using environment variable (if any)")
except Exception:
    LOGGER.exception("Failed to load pm_start_photo_id.txt; continuing with environment value")

# Note: bundled sample image, automatic upload and caching have been removed. Use /genid store to manually set the file id.

SETTINGS_STRINGS = """
Hey! My name is *{}*. I am a group management bot, here to help you get around and keep the order in your groups!
I have lots of handy features, such as flood control, a warning system, a note keeping system, and even predetermined replies on certain keywords.

*Helpful commands*:
- /start: Starts me! You've probably already used this.
- /help: Opens the usage guide telling you how to use the bot and its commands.
- /settings: Shows detailed help about features and how to configure them for your chats.
- /about: Short information about the bot.
- /donate: Gives you info on how to support me and my creator.

{}
All commands can be used with the following: / !
""".format(dispatcher.bot.first_name, "" if not ALLOW_EXCL else "If you have any bugs or questions on how to use me, have a look at my [Group](https://t.me/ProHelpDesk), or head to @ProIndians.")

HELP_STRINGS = """
Quick usage guide for *{}* — how to use this bot 📘

- /start: Begin a private chat with me and see quick actions (add me to a group, manage settings, help, about).
- /help: Show this usage guide (what commands do and how to use them).
- /settings: View detailed help about features and configuration options for the bot (same content as prior help).
- /about: Learn more about the bot and its capabilities.
- /genid store (reply to photo): Store a photo file_id to use for the PM start image (owner only).
- /genid clear: Clear the stored PM start photo id (owner only).
- /donate: Information on donating to the project's creator.

For module-specific help, use `/help <module>` (e.g. `/help welcomes`).
""".format(dispatcher.bot.first_name)

DONATE_STRING = """Heya, glad to hear you want to donate!
It took lots of work for [my creator](t.me/SonOfLars) to get me to where I am now, and every donation helps \
motivate him to make me even better. All the donation money will go to a better VPS to host me, and/or beer \
(see his bio!). He's just a poor student, so every little helps!
There are two ways of paying him; [PayPal](paypal.me/PaulSonOfLars), or [Monzo](monzo.me/paulnionvestergaardlarsen)."""

IMPORTED = {}
MIGRATEABLE = []
HELPABLE = {}
STATS = []
USER_INFO = []
DATA_IMPORT = []
DATA_EXPORT = []

CHAT_SETTINGS = {}
USER_SETTINGS = {}

# Track last bot-sent message in PMs so we can edit it in-place (welcome <-> about)
# Structure: LAST_PM_MESSAGE[chat_id] = {
#   'message_id': int,
#   'is_photo': bool,
#   'photo_id': str or None,
#   'text': str (the caption or text),
#   'orig_*' optional fields for restoring when About is shown
# }
LAST_PM_MESSAGE = {}

# Persistence for LAST_PM_MESSAGE across restarts
_last_pm_path = os.path.join(os.path.dirname(__file__), "last_pm_message.json")

def _save_last_pm():
    """Persist LAST_PM_MESSAGE to disk as JSON (keys -> str)."""
    try:
        with open(_last_pm_path, "w", encoding="utf-8") as _f:
            json.dump({str(k): v for k, v in LAST_PM_MESSAGE.items()}, _f, ensure_ascii=False)
    except Exception:
        LOGGER.exception("Failed to save LAST_PM_MESSAGE to disk")


def _load_last_pm():
    """Load LAST_PM_MESSAGE from disk if present."""
    try:
        if os.path.exists(_last_pm_path):
            with open(_last_pm_path, "r", encoding="utf-8") as _f:
                data = json.load(_f)
            for k, v in data.items():
                try:
                    LAST_PM_MESSAGE[int(k)] = v
                except ValueError:
                    LAST_PM_MESSAGE[k] = v
            LOGGER.info("Loaded LAST_PM_MESSAGE from last_pm_message.json")
    except Exception:
        LOGGER.exception("Failed to load last_pm_message.json; starting with empty LAST_PM_MESSAGE")

# Load persisted last PM messages on startup
_load_last_pm()

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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])
    try:
        sent = dispatcher.bot.send_message(chat_id=chat_id,
                                    text=text,
                                    parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=keyboard)
    except BadRequest as excp:
        # Handle malformed markup/entities by falling back to plain text (no parse_mode)
        LOGGER.warning("send_help: BadRequest while sending help (will fallback to plain text): %s", excp)
        LOGGER.debug("send_help: help text preview: %s", text[:400])
        sent = dispatcher.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True, reply_markup=keyboard)

    # Record this help message so we can edit it in-place later
    try:
        LAST_PM_MESSAGE[chat_id] = {
            'message_id': sent.message_id,
            'is_photo': False,
            'photo_id': None,
            'text': text,
            'is_help': True,
        }
        _save_last_pm()
    except Exception:
        LOGGER.exception("Failed to record help message in LAST_PM_MESSAGE")


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
    # Declare global before any use/assignment in this function to avoid SyntaxError
    global PM_START_PHOTO_ID

    msg = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]

    # parse optional command argument (e.g., store, clear)
    cmd = args[0].lower() if args else None

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
        with open(os.path.join(os.path.dirname(__file__), "pm_start_photo_id.txt"), "w", encoding="utf-8") as f:
            f.write(file_id)
        PM_START_PHOTO_ID = file_id
        update.effective_message.reply_text("File id stored and will be used for the PM start message.")
        LOGGER.info("PM start photo id updated via /genid by owner %s", user.id)
    except Exception:
        LOGGER.exception("Failed to store PM start photo id via /genid")
        update.effective_message.reply_text("Failed to save file id to disk.")


@run_async
def start(bot: Bot, update: Update, args: List[str]):
    if update.effective_chat.type == "private":
        if len(args) >= 1:
            if args[0].lower() == "help":
                send_help(update.effective_chat.id, HELP_STRINGS)

            elif args[0].lower() == "settings":
                # Show detailed help/settings content in PM (maps to previous help text)
                send_help(update.effective_chat.id, SETTINGS_STRINGS)

            elif args[0].lower().startswith("stngs_"):
                match = re.match("stngs_(.*)", args[0].lower())
                chat = dispatcher.bot.getChat(match.group(1))

                if is_user_admin(chat, update.effective_user.id):
                    send_settings(match.group(1), update.effective_user.id, False)
                else:
                    send_settings(match.group(1), update.effective_user.id, True)

            elif args[0].lower() == "about":
                # Try to edit the existing welcome message in-place to show About (preferred)
                chat_id = update.effective_chat.id
                about_text = "\n".join([
                    f"<b>About {html.escape(bot.first_name)}</b>",
                    "\n<b>What I do</b>: I help moderate groups and keep chats safe and organized.",
                    "\n<b>Key features</b>:",
                    "• Flood control and anti-spam",
                    "• Warnings, bans, mutes and global moderation tools",
                    "• Custom welcome & goodbye messages",
                    "• Notes, reminders and message filters",
                    "• Logging and audit features for moderators",
                    "• Translation and utility commands",
                    "\nUse <b>/help</b> for usage instructions or <b>/settings</b> to see configuration options."
                ])
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

                info = LAST_PM_MESSAGE.get(chat_id)
                if info:
                    # Save original if not already saved
                    if 'orig_saved' not in info:
                        info['orig_saved'] = True
                        info['orig_is_photo'] = info['is_photo']
                        info['orig_photo_id'] = info.get('photo_id')
                        info['orig_text'] = info.get('text')

                    try:
                        if info['is_photo']:
                            # edit caption of the photo message to show about
                            bot.edit_message_caption(chat_id=chat_id, message_id=info['message_id'], caption=about_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                        else:
                            bot.edit_message_text(chat_id=chat_id, message_id=info['message_id'], text=about_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                        # mark that we currently show about
                        info['is_about'] = True
                        info['text'] = about_text
                    except BadRequest:
                        # fallback to sending a new about message
                        about(bot, update)
                else:
                    # No previous start message known; just send a normal about message
                    about(bot, update)

            elif args[0][1:].isdigit() and "rules" in IMPORTED:
                IMPORTED["rules"].send_rules(update, args[0], from_pm=True)

        else:
            first_name = update.effective_user.first_name
            # Format message using HTML with escaped values
            start_text = PM_START_TEXT.format(
                first=html.escape(first_name),
                botname=html.escape(bot.first_name),
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="➕ Add me to a Group ➕", url="t.me/{}?startgroup=true".format(bot.username))],
                [InlineKeyboardButton(text="⚙️ Manage Group Settings ✍️", url="t.me/{}?start=settings".format(bot.username))],
                # Use callbacks for Help and About to edit the existing message in-place instead of deep-linking
                [InlineKeyboardButton(text="Help", callback_data="help_cb"), InlineKeyboardButton(text="About", callback_data="about_cb")]
            ])

            if PM_START_PHOTO_ID:
                # Send cached Telegram file_id (fast) as photo with caption
                try:
                    sent = update.effective_message.reply_photo(
                        photo=PM_START_PHOTO_ID,
                        caption=start_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_notification=False,
                    )
                    # remember last bot message in this PM
                    LAST_PM_MESSAGE[update.effective_chat.id] = {
                        'message_id': sent.message_id,
                        'is_photo': True,
                        'photo_id': PM_START_PHOTO_ID,
                        'text': start_text,
                    }
                    _save_last_pm()
                except BadRequest:
                    # Fallback to text reply if file_id invalid or fails for any reason
                    sent = update.effective_message.reply_text(
                        start_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                    )
                    LAST_PM_MESSAGE[update.effective_chat.id] = {
                        'message_id': sent.message_id,
                        'is_photo': False,
                        'photo_id': None,
                        'text': start_text,
                    }
                    _save_last_pm()
            else:
                sent = update.effective_message.reply_text(
                    start_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
                LAST_PM_MESSAGE[update.effective_chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': start_text,
                }
                _save_last_pm()
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
    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)
    try:
        if mod_match:
            module = mod_match.group(1)
            text = "Here is the help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
                   + HELPABLE[module].__help__
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

            # Try to edit in-place
            try:
                query.message.edit_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': query.message.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return
            except BadRequest as excp:
                if excp.message == "Message is not modified":
                    bot.answer_callback_query(query.id)
                    return
                LOGGER.warning("help_button: BadRequest while sending module help for %s: %s", module, excp)
                LOGGER.debug("help_button: help text preview: %s", text[:400])
                # fallback to sending a new message and deleting the old one
                # Send without parse mode to avoid entity parse errors
                sent = query.message.reply_text(text=text, reply_markup=keyboard)
                try:
                    query.message.delete()
                except Exception:
                    pass
                LAST_PM_MESSAGE[sent.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return

        elif prev_match:
            curr_page = int(prev_match.group(1))
            text = HELP_STRINGS
            # Only provide a single Back button (restores welcome/start)
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

            try:
                query.message.edit_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': query.message.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return
            except BadRequest as excp:
                if excp.message == "Message is not modified":
                    bot.answer_callback_query(query.id)
                    return
                # Send without parse mode to avoid entity parse errors
                sent = query.message.reply_text(text, reply_markup=keyboard)
                try:
                    query.message.delete()
                except Exception:
                    pass
                LAST_PM_MESSAGE[sent.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return

        elif next_match:
            next_page = int(next_match.group(1))
            text = HELP_STRINGS
            # Only provide a single Back button (restores welcome/start)
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

            try:
                query.message.edit_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': query.message.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return
            except BadRequest as excp:
                if excp.message == "Message is not modified":
                    bot.answer_callback_query(query.id)
                    return
                # Send without parse mode to avoid entity parse errors
                sent = query.message.reply_text(text, reply_markup=keyboard)
                try:
                    query.message.delete()
                except Exception:
                    pass
                LAST_PM_MESSAGE[sent.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return

        elif back_match:
            text = HELP_STRINGS
            # Only provide a single Back button (restores welcome/start)
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])
            try:
                query.message.edit_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': query.message.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return
            except BadRequest as excp:
                if excp.message == "Message is not modified":
                    bot.answer_callback_query(query.id)
                    return
                # Send without parse mode to avoid entity parse errors
                sent = query.message.reply_text(text=text, reply_markup=keyboard)
                try:
                    query.message.delete()
                except Exception:
                    pass
                LAST_PM_MESSAGE[sent.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': text,
                    'is_help': True,
                }
                _save_last_pm()
                bot.answer_callback_query(query.id)
                return

    except BadRequest as excp:
        if excp.message == "Message is not modified":
            pass
        elif excp.message == "Query_id_invalid":
            pass
        elif excp.message == "Message can't be deleted":
            pass
        else:
            # Log additional context to aid in diagnosing malformed entity errors.
            try:
                preview = query.message.text or query.message.caption or ""
            except Exception:
                preview = ""
            LOGGER.warning("help_button: unexpected BadRequest for query %s: %s", str(query.data), excp)
            LOGGER.debug("help_button: message preview: %s", preview[:400])
            LOGGER.exception("Exception in help buttons. %s", str(query.data))


@run_async
def get_help(bot: Bot, update: Update):
    chat = update.effective_chat  # type: Optional[Chat]
    args = update.effective_message.text.split(None, 1)

    # ONLY send help in PM
    if chat.type != chat.PRIVATE:

        update.effective_message.reply_text("Contact me in PM to get the list of possible commands.",
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton(text="Help",
                                                                       url="t.me/{}?start=help".format(
                                                                           bot.username))]]))
        return

    elif len(args) >= 2 and any(args[1].lower() == x for x in HELPABLE):
        module = args[1].lower()
        text = "Here is the available help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
               + HELPABLE[module].__help__
        # Only provide a single Back button (restores welcome/start)
        send_help(chat.id, text, InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]]))

    else:
        send_help(chat.id, HELP_STRINGS)


@run_async
def pmstatus(bot: Bot, update: Update):
    """Diagnostic command: show the saved LAST_PM_MESSAGE for this chat (use in PM)."""
    chat = update.effective_chat
    if chat.type != chat.PRIVATE:
        update.effective_message.reply_text("Use /pmstatus in a private chat with the bot to inspect its saved PM state for your chat.")
        return
    info = LAST_PM_MESSAGE.get(chat.id)
    if not info:
        update.effective_message.reply_text("No saved PM message info for this chat.")
        return
    # Pretty-print the info, but hide possibly large photo_id
    display = dict(info)
    if 'photo_id' in display and display['photo_id']:
        display['photo_id'] = display['photo_id'][:60] + '...'
    update.effective_message.reply_text("LAST_PM_MESSAGE:\n" + json.dumps(display, ensure_ascii=False, indent=2))


@run_async
def about(bot: Bot, update: Update):
    """Send an informative about message including name, purpose and features.

    The message includes a 'Back' inline button that will replace the about message with
    the original welcome (start) message when pressed.
    """
    bot_name = html.escape(bot.first_name)
    about_lines = [
        f"<b>About {bot_name}</b>",
        "\n<b>What I do</b>: I help moderate groups and keep chats safe and organized.",
        "\n<b>Key features</b>:",
        "• Flood control and anti-spam",
        "• Warnings, bans, mutes and global moderation tools",
        "• Custom welcome & goodbye messages",
        "• Notes, reminders and message filters",
        "• Logging and audit features for moderators",
        "• Translation and utility commands",
        "\nUse <b>/help</b> for usage instructions or <b>/settings</b> to see configuration options."
    ]
    about_text = "\n".join(about_lines)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="Back", callback_data="about_back")]
    ])

    # If invoked via callback or command, reply with an about message that has a Back button
    update.effective_message.reply_text(about_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)


@run_async
def about_callback(bot: Bot, update: Update):
    """Callback handler for pressing About on the start message (edits start -> about in-place)."""
    query = update.callback_query
    chat_id = query.message.chat.id

    about_text = "\n".join([
        f"<b>About {html.escape(bot.first_name)}</b>",
        "\n<b>What I do</b>: I help moderate groups and keep chats safe and organized.",
        "\n<b>Key features</b>:",
        "• Flood control and anti-spam",
        "• Warnings, bans, mutes and global moderation tools",
        "• Custom welcome & goodbye messages",
        "• Notes, reminders and message filters",
        "• Logging and audit features for moderators",
        "• Translation and utility commands",
        "\nUse <b>/help</b> for usage instructions or <b>/settings</b> to see configuration options."
    ])

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

    info = LAST_PM_MESSAGE.get(chat_id)
    if info:
        # Save original if not already saved
        if 'orig_saved' not in info:
            info['orig_saved'] = True
            info['orig_is_photo'] = info['is_photo']
            info['orig_photo_id'] = info.get('photo_id')
            info['orig_text'] = info.get('text')

        try:
            if info['is_photo']:
                bot.edit_message_caption(chat_id=chat_id, message_id=info['message_id'], caption=about_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            else:
                bot.edit_message_text(chat_id=chat_id, message_id=info['message_id'], text=about_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

            info['is_about'] = True
            info['text'] = about_text
            _save_last_pm()
            bot.answer_callback_query(query.id)
            return
        except BadRequest:
            # fallback to sending a new about message
            pass

    # If we couldn't edit in-place, send a normal about message as a fallback
    about(bot, update)


@run_async
def help_cb(bot: Bot, update: Update):
    """Callback handler for pressing Help on the start message (edits start -> help in-place)."""
    query = update.callback_query
    chat_id = query.message.chat.id

    help_text = HELP_STRINGS
    # Only provide a single Back button (restores welcome/start)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="about_back")]])

    info = LAST_PM_MESSAGE.get(chat_id)
    if info:
        # Save original if not already saved
        if 'orig_saved' not in info:
            info['orig_saved'] = True
            info['orig_is_photo'] = info['is_photo']
            info['orig_photo_id'] = info.get('photo_id')
            info['orig_text'] = info.get('text')

        try:
            if info['is_photo']:
                # edit caption
                bot.edit_message_caption(chat_id=chat_id, message_id=info['message_id'], caption=help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            else:
                bot.edit_message_text(chat_id=chat_id, message_id=info['message_id'], text=help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

            info['is_help'] = True
            info['text'] = help_text
            _save_last_pm()
            bot.answer_callback_query(query.id)
            return
        except BadRequest:
            # fallback to sending a new help message
            pass

    # fallback: send normal help message (send_help will persist it)
    send_help(chat_id, help_text)
    bot.answer_callback_query(query.id)


@run_async
def about_back(bot: Bot, update: Update):
    """Callback query handler to replace the about message with the welcome/start text."""
    query = update.callback_query
    user = query.from_user

    # Build the start text using the clicking user's first name
    start_text = PM_START_TEXT.format(
        first=html.escape(user.first_name),
        botname=html.escape(bot.first_name),
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="➕ Add me to a Group ➕", url=f"t.me/{bot.username}?startgroup=true")],
        [InlineKeyboardButton(text="⚙️ Manage Group Settings ✍️", url=f"t.me/{bot.username}?start=settings")],
        [InlineKeyboardButton(text="Help", callback_data="help_cb"), InlineKeyboardButton(text="About", callback_data="about_cb")]
    ])

    try:
        # Prefer to use the saved original start message data if available
        info = LAST_PM_MESSAGE.get(query.message.chat.id)
        target_is_photo = False
        target_photo_id = None
        target_text = start_text

        if info and info.get('orig_saved'):
            target_is_photo = info.get('orig_is_photo', False)
            target_photo_id = info.get('orig_photo_id')
            target_text = info.get('orig_text', start_text)
        else:
            # Fallback to configured PM_START_PHOTO_ID
            target_is_photo = bool(PM_START_PHOTO_ID)
            target_photo_id = PM_START_PHOTO_ID if PM_START_PHOTO_ID else None
            target_text = start_text

        if target_is_photo and target_photo_id:
            media = InputMediaPhoto(media=target_photo_id, caption=target_text, parse_mode=ParseMode.HTML)
            query.message.edit_media(media=media, reply_markup=keyboard)
            # Update LAST_PM_MESSAGE to reflect restored state
            LAST_PM_MESSAGE[query.message.chat.id] = {
                'message_id': query.message.message_id,
                'is_photo': True,
                'photo_id': target_photo_id,
                'text': target_text,
            }
            _save_last_pm()
        else:
            query.message.edit_text(target_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            LAST_PM_MESSAGE[query.message.chat.id] = {
                'message_id': query.message.message_id,
                'is_photo': False,
                'photo_id': None,
                'text': target_text,
            }
            _save_last_pm()
        bot.answer_callback_query(query.id)
    except BadRequest:
        # If edit fails (e.g., message is too old or media can't be edited), send a new start message instead
        try:
            if PM_START_PHOTO_ID:
                sent = query.message.reply_photo(photo=PM_START_PHOTO_ID, caption=start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': True,
                    'photo_id': PM_START_PHOTO_ID,
                    'text': start_text,
                }
                _save_last_pm()
            else:
                sent = query.message.reply_text(start_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                LAST_PM_MESSAGE[query.message.chat.id] = {
                    'message_id': sent.message_id,
                    'is_photo': False,
                    'photo_id': None,
                    'text': start_text,
                }
                _save_last_pm()
            bot.answer_callback_query(query.id)
        except Exception:
            LOGGER.exception("Failed to restore start message from about_back callback")
            bot.answer_callback_query(query.id, text="Could not go back to the welcome message.")


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
            dispatcher.bot.send_message(user_id,
                                        text="Which module would you like to check {}'s settings for?".format(
                                            chat_name),
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
                                                      url="t.me/{}?start=settings".format(
                                                          bot.username))]]))
        else:
            text = "Click here to check your settings."

    else:
        # In PM, show the detailed settings/help content (matches previous help output)
        send_help(chat.id, SETTINGS_STRINGS)


@run_async
def donate(bot: Bot, update: Update):
    user = update.effective_message.from_user
    chat = update.effective_chat  # type: Optional[Chat]

    if chat.type == "private":
        update.effective_message.reply_text(DONATE_STRING, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

        if OWNER_ID != 254318997 and DONATION_LINK:
            update.effective_message.reply_text("You can also donate to the person currently running me "
                                                "[here]({})".format(DONATION_LINK),
                                                parse_mode=ParseMode.MARKDOWN)

    else:
        try:
            bot.send_message(user.id, DONATE_STRING, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

            update.effective_message.reply_text("I've PM'ed you about donating to my creator!")
        except Unauthorized:
            update.effective_message.reply_text("Contact me in PM first to get donation information.")


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


def main():
    test_handler = CommandHandler("test", test)
    genid_handler = CommandHandler("genid", genid, pass_args=True)
    start_handler = CommandHandler("start", start, pass_args=True)

    help_handler = CommandHandler("help", get_help)
    help_callback_handler = CallbackQueryHandler(help_button, pattern=r"help_")

    settings_handler = CommandHandler("settings", get_settings)
    about_handler = CommandHandler("about", about)
    settings_callback_handler = CallbackQueryHandler(settings_button, pattern=r"stngs_")
    about_callback_handler = CallbackQueryHandler(about_back, pattern=r"about_back")
    about_inline_handler = CallbackQueryHandler(about_callback, pattern=r"about_cb")
    help_inline_handler = CallbackQueryHandler(help_cb, pattern=r"help_cb")

    # diagnostic commands
    pmstatus_handler = CommandHandler("pmstatus", pmstatus)

    donate_handler = CommandHandler("donate", donate)
    migrate_handler = MessageHandler(Filters.status_update.migrate, migrate_chats)

    # dispatcher.add_handler(test_handler)
    dispatcher.add_handler(test_handler)
    dispatcher.add_handler(genid_handler)
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(help_handler)
    dispatcher.add_handler(settings_handler)
    dispatcher.add_handler(about_handler)
    dispatcher.add_handler(about_callback_handler)
    dispatcher.add_handler(about_inline_handler)
    dispatcher.add_handler(help_inline_handler)
    dispatcher.add_handler(help_callback_handler)
    dispatcher.add_handler(settings_callback_handler)
    dispatcher.add_handler(pmstatus_handler)
    dispatcher.add_handler(migrate_handler)
    dispatcher.add_handler(donate_handler)

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
