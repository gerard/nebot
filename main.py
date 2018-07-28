#!/usr/bin/env python3

import os
import subprocess
import functools
import glob
import yaml
import logging
import telegram.ext
import tempfile

CARCAMAL_BOT_TOKEN = os.path.join(
    os.getenv("HOME"),
    ".carcamalbot.telegram.token"
)

CARCAMAL_BOT_CONFIG = os.path.join(
    os.getenv("HOME"),
    ".carcamalbot.config.yaml"
)

with open(CARCAMAL_BOT_CONFIG) as f:
    CONFIG = yaml.load(f)


def restricted(func):
    @functools.wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in CONFIG["users"]:
            print("Unauthorized access denied for {}".format(user_id)) # logging
            bot.send_message(chat_id=update.message.chat_id,
                             text="Unauthorized, please send command /start "
                                  "and wait for an admin to accept your request",
                             parse_mode=telegram.ParseMode.MARKDOWN)
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
        if bot.getChat(update.message.chat_id).type != telegram.Chat.PRIVATE:
            update.message.reply_text("This command is for private chats only")
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


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
                parse_mode=telegram.ParseMode.MARKDOWN,
                text="[{user}](tg://user?id={uid}) with id:{uid} has /start ed the bot".format(
                    user=update.effective_user.first_name,
                    uid=uid
                )
            )
            update.message.reply_text("An admin has been notified")

@admin
@private
def command_status(bot, update):
    update.message.reply_text(yaml.dump(CONFIG))

def command_fortune(bot, update):
    msg = subprocess.check_output("fortune").decode("utf-8")
    bot.send_message(chat_id=update.message.chat_id,
                     text=msg)

def command_menu(bot, update):
    reply_markup = telegram.ReplyKeyboardMarkup(
        [["A", "B", "C", "D"]]
    )
    bot.send_message(chat_id=update.message.chat_id,
                     text="Pick an option",
                     reply_markup=reply_markup
    )

@restricted
@telegram.ext.dispatcher.run_async
def command_ytaudio(bot, update):
    afmt = "mp3"
    try:
        (cmd, url, *_) = update.message.text.split(" ")
    except ValueError:
        update.message.reply_text("usage: cmd url")
        return

    bot.send_chat_action(chat_id=update.message.chat_id,
                         action=telegram.ChatAction.TYPING)
    with tempfile.TemporaryDirectory() as tempdir:
        subprocess.check_call([
            "youtube-dl",
            "--audio-format", afmt,
            "-o", os.path.join(tempdir, "%(title)s.%(ext)s"),
            "-x", url
        ])
        afname = glob.glob(os.path.join(tempdir, "*.{}".format(afmt)))[0]
        bot.send_audio(chat_id=update.message.chat_id,
                       audio=open(afname, "rb"))

shop_lists = {}
def command_shopadd(bot, update):
    reply_markup = telegram.ReplyKeyboardRemove()
    uid = update.message.from_user.id
    if uid not in shop_lists:
        shop_lists[uid] = {}

    try:
        item = update.message.text.split(" ", 1)[1].strip()
    except IndexError:
        msg = "usage: /shopadd <item>"
    else:
        shop_lists[uid][item] = True
        msg = "shoplist: added {}".format(item)

    bot.send_message(chat_id=update.message.chat_id,
                     text=msg,
                     reply_markup=reply_markup)

def command_shoplist(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text="shoplist: your shoplist contains:")

    for item in shop_lists[update.message.from_user.id].keys():
        bot.send_message(chat_id=update.message.chat_id,
                         text=" * {}".format(item))
    bot.send_message(chat_id=update.message.chat_id,
                     text="shoplist: done")


def main():
    with open(CARCAMAL_BOT_TOKEN) as f:
        token = f.read().strip()

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)

    updater = telegram.ext.Updater(token=token)
    for gl_k, gl_v in globals().items():
        if not gl_k.startswith("command_"):
            continue

        updater.dispatcher.add_handler(
            telegram.ext.CommandHandler(gl_k.split("_", 1)[1], gl_v)
        )

    updater.start_polling()


if __name__ == "__main__":
    main()
