#!/usr/bin/env python3
# pylint: disable=missing-docstring

import os
import subprocess
import functools
import glob
import textwrap
import tempfile
import logging
import pickle
import yaml
import telegram as tgm
import telegram.ext as tgme

### Globals
CARCAMAL_BOT_TOKEN = os.path.join(
    os.getenv("HOME"),
    ".carcamalbot.telegram.token"
)

CARCAMAL_BOT_CONFIG = os.path.join(
    os.getenv("HOME"),
    ".carcamalbot.config.yaml"
)

with open(CARCAMAL_BOT_CONFIG) as config_f:
    CONFIG = yaml.load(config_f)


### Access decorators
def restricted(func):
    @functools.wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in CONFIG["users"]:
            print("Unauthorized access denied for {}".format(user_id)) # logging
            bot.send_message(chat_id=update.message.chat_id,
                             text="Unauthorized, please send command /start "
                                  "and wait for an admin to accept your request",
                             parse_mode=tgm.ParseMode.MARKDOWN)
            return
        return func(bot, update, *args, **kwargs)
    return wrapped

def admin(func):
    @functools.wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        if update.effective_user.id != CONFIG["admin"]["id"]:
            return
        return func(bot, update, *args, **kwargs)
    return wrapped

def private(func):
    @functools.wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        if bot.getChat(update.message.chat_id).type != tgm.Chat.PRIVATE:
            update.message.reply_text("This command is for private chats only")
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


### Administration
@private
def command_start(bot, update):
    uid = update.effective_user.id
    if uid == CONFIG["admin"]["id"]:
        CONFIG["admin"]["chat_id"] = update.message.chat_id
        CONFIG["users"][uid]["chat_id"] = update.message.chat_id
        update.message.reply_text("Started bot as admin")
    elif update.effective_user.id in CONFIG["users"]:
        CONFIG["users"][uid]["chat_id"] = update.message.chat_id
        update.message.reply_text("Started bot as user")
    else:
        update.message.reply_text("Started bot as a new user, some services will be disabled")
        if "chat_id" in CONFIG["admin"]:
            bot.send_message(
                chat_id=CONFIG["admin"]["chat_id"],
                parse_mode=tgm.ParseMode.MARKDOWN,
                text="[{user}](tg://user?id={uid}) with id:{uid} has /start ed the bot".format(
                    user=update.effective_user.first_name,
                    uid=uid
                )
            )
            update.message.reply_text("An admin has been notified")
    update.message.reply_text("Use /help command to see what this bot can do")

@admin
@private
def command_status(bot, update):
    update.message.reply_text(yaml.dump(CONFIG))


### Fortune
def command_fortune(bot, update):
    msg = subprocess.check_output("fortune").decode("utf-8")
    bot.send_message(chat_id=update.message.chat_id,
                     text=msg)


### Youtube
@restricted
@tgme.dispatcher.run_async
def command_ytaudio(bot, update):
    afmt = "mp3"
    try:
        (_, url, *_) = update.message.text.split(" ")
    except ValueError:
        update.message.reply_text("usage: /ytaudio url")
        return

    bot.send_chat_action(chat_id=update.message.chat_id,
                         action=tgm.ChatAction.TYPING)
    with tempfile.TemporaryDirectory() as tempdir:
        try:
            subprocess.check_call([
                "youtube-dl",
                "--audio-format", afmt,
                "-o", os.path.join(tempdir, "%(title)s.%(ext)s"),
                "-x", url
            ])
        except subprocess.CalledProcessError:
            update.message.reply_text("Download failed... bad URL?")
        else:
            afname = glob.glob(os.path.join(tempdir, "*.{}".format(afmt)))[0]
            bot.send_audio(chat_id=update.message.chat_id,
                           audio=open(afname, "rb"))


### Groceries
class GroceriesOperation:
    def __init__(self, oid, name, next_state, msg):
        self.oid = oid
        self.name = name
        self.next_state = next_state
        self.msg = msg

    def __eq__(self, other):
        return self.name == other.name

class GroceriesState:
    def __init__(self, name, transitions):
        self.name = name
        self.transitions = transitions

    def transition_names(self):
        return [x.name for x in self.transitions]

    def transition_regex(self):
        return "^{}$".format("|".join(self.transition_names()))

class GroceriesStateMachine:
    ADDING = GroceriesState("ADDING", [])
    REMOVING = GroceriesState("REMOVING", [])
    START = GroceriesState(
        "START",
        [
            GroceriesOperation(
                "ADDING",
                "Add to groceries list",
                ADDING,
                "What item do you want to add?",
            ),
            GroceriesOperation(
                "REMOVING",
                "Remove from groceries list",
                REMOVING,
                "What item do you want to remove?",
            ),
            GroceriesOperation(
                "EXITING",
                "Exit groceries list mode",
                tgme.ConversationHandler.END,
                "Good bye!"
            )
        ]
    )

@private
@restricted
def conv_groceries_entry(bot, update, user_data):
    reply_markup = tgm.ReplyKeyboardMarkup(
        [[x] for x in GroceriesStateMachine.START.transition_names()],
        one_time_keyboard=True
    )

    uid = update.effective_user.id
    pickle_file = os.path.join(
        os.getenv("HOME"),
        ".carcamalbot.pickle.groceries.{}".format(uid)
    )

    if not user_data and os.path.exists(pickle_file):
        # If we didn't get any user_data but pickle exists, load it.
        with open(pickle_file, "rb") as f:
            user_data.update(pickle.load(f))

    # Store any data we have
    with open(pickle_file, "wb") as f:
        pickle.dump(user_data, f)

    list_items = []
    for (k, state) in user_data.items():
        if state:
            list_items.append(k)

    msg = ""
    if list_items:
        msg += "*The list contains:*"
        for i in list_items:
            msg += "\n  - {}".format(i)
        msg += "\n"
    msg += "*Select an action*"

    bot.send_message(chat_id=update.message.chat_id,
                     text=msg,
                     parse_mode=tgm.ParseMode.MARKDOWN,
                     reply_markup=reply_markup)

    return GroceriesStateMachine.START

def conv_groceries_start(bot, update, user_data):
    for trans in GroceriesStateMachine.START.transitions:
        if trans.name == update.message.text.strip():
            opts = None
            if trans.oid == "ADDING":
                opts = [[k] for (k, v) in user_data.items() if v == False]
            elif trans.oid == "REMOVING":
                opts = [[k] for (k, v) in user_data.items() if v == True]

            if opts:
                reply_markup = tgm.ReplyKeyboardMarkup(
                    opts, one_time_keyboard=True
                )
                bot.send_message(chat_id=update.message.chat_id,
                                 text=trans.msg,
                                 reply_markup=reply_markup)
            else:
                bot.send_message(chat_id=update.message.chat_id,
                                 text=trans.msg)

            return trans.next_state
    return GroceriesStateMachine.START

def conv_groceries_adding(bot, update, user_data):
    item = update.message.text.strip()
    user_data[update.message.text.strip()] = True
    bot.send_message(
        chat_id=update.message.chat_id,
        text="{} added to groceries".format(item)
    )

    return conv_groceries_entry(bot, update, user_data)

def conv_groceries_removing(bot, update, user_data):
    item = update.message.text.strip()
    if item in user_data:
        user_data[update.message.text.strip()] = False
        bot.send_message(
            chat_id=update.message.chat_id,
            text="{} added to groceries".format(item)
        )
    else:
        bot.send_message(
            chat_id=update.message.chat_id,
            text="{} was not found in your groceries".format(item)
        )

    return conv_groceries_entry(bot, update, user_data)


### Help
def command_help(bot, update):
    help_msg = textwrap.dedent(
        """
        *List of available commands*
        /fortune - print a random, hopefully interesting, adage

        *Registered users only*
        /ytaudio <url> - obtain an mp3 from a youtube link
        /groceries - start groceries list mode

        *Source code*
        https://github.com/gerard/nebot
        """
    )
    bot.send_message(chat_id=update.message.chat_id,
                     text=help_msg,
                     parse_mode=tgm.ParseMode.MARKDOWN)


### Main
def main():
    with open(CARCAMAL_BOT_TOKEN) as f:
        token = f.read().strip()

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

    updater = tgme.Updater(token=token)
    for gl_k, gl_v in globals().items():
        if not gl_k.startswith("command_"):
            continue

        updater.dispatcher.add_handler(
            tgme.CommandHandler(gl_k.split("_", 1)[1], gl_v)
        )

        updater.dispatcher.add_handler(
            tgme.ConversationHandler(
                entry_points=[
                    tgme.CommandHandler(
                        "groceries",
                        conv_groceries_entry,
                        pass_user_data=True
                    )
                ],
                states={
                    GroceriesStateMachine.START: [
                        tgme.RegexHandler(
                            GroceriesStateMachine.START.transition_regex(),
                            conv_groceries_start,
                            pass_user_data=True
                        )
                    ],
                    GroceriesStateMachine.ADDING: [
                        tgme.MessageHandler(
                            tgme.Filters.text,
                            conv_groceries_adding,
                            pass_user_data=True
                        )
                    ],
                    GroceriesStateMachine.REMOVING: [
                        tgme.MessageHandler(
                            tgme.Filters.text,
                            conv_groceries_removing,
                            pass_user_data=True
                        )
                    ]
                },
                fallbacks=[],
            )
        )

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
