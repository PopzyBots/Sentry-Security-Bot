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

# PM_START_PHOTO_ID is fetched only from the environment. Set the env var PM_START_PHOTO_ID to a Telegram file_id
# Example: PM_START_PHOTO_ID=AgACAgUAAxkBAANDaUNt19igRloquRr_a0_pDk4P4WkAAoALaxvJIyFWRDreG7mSpR8ACAEAAwIAA3kABx4E
import os
PM_START_PHOTO_ID = os.getenv("PM_START_PHOTO_ID", "")

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
        keyboard = InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help"))
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
                # Simple about message
                about_text = "<b>About {}</b>\nI keep chats clean, safe, and fully under control. For help, click Help.".format(html.escape(bot.first_name))
                update.effective_message.reply_text(about_text, parse_mode=ParseMode.HTML)

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
                [InlineKeyboardButton(text="Help", url="t.me/{}?start=help".format(bot.username)), InlineKeyboardButton(text="About", url="t.me/{}?start=about".format(bot.username))]
            ])

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
    mod_match = re.match(r"help_module\((.+?)\)", query.data)
    prev_match = re.match(r"help_prev\((.+?)\)", query.data)
    next_match = re.match(r"help_next\((.+?)\)", query.data)
    back_match = re.match(r"help_back", query.data)
    try:
        if mod_match:
            module = mod_match.group(1)
            text = "Here is the help for the *{}* module:\n".format(HELPABLE[module].__mod_name__) \
                   + HELPABLE[module].__help__
            query.message.reply_text(text=text,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         [[InlineKeyboardButton(text="Back", callback_data="help_back")]]))

        elif prev_match:
            curr_page = int(prev_match.group(1))
            query.message.reply_text(HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(curr_page - 1, HELPABLE, "help")))

        elif next_match:
            next_page = int(next_match.group(1))
            query.message.reply_text(HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(
                                         paginate_modules(next_page + 1, HELPABLE, "help")))

        elif back_match:
            query.message.reply_text(text=HELP_STRINGS,
                                     parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(paginate_modules(0, HELPABLE, "help")))

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
        send_help(chat.id, text, InlineKeyboardMarkup([[InlineKeyboardButton(text="Back", callback_data="help_back")]]))

    else:
        send_help(chat.id, HELP_STRINGS)


@run_async
def about(bot: Bot, update: Update):
    about_text = "<b>About {}</b>\nI keep chats clean, safe, and fully under control. For help, click Help.".format(html.escape(bot.first_name))
    update.effective_message.reply_text(about_text, parse_mode=ParseMode.HTML)


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

    donate_handler = CommandHandler("donate", donate)
    migrate_handler = MessageHandler(Filters.status_update.migrate, migrate_chats)

    # dispatcher.add_handler(test_handler)
    dispatcher.add_handler(test_handler)
    dispatcher.add_handler(genid_handler)
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(help_handler)
    dispatcher.add_handler(settings_handler)
    dispatcher.add_handler(about_handler)
    dispatcher.add_handler(help_callback_handler)
    dispatcher.add_handler(settings_callback_handler)
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
