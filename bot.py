"""Небольшой Telegram-бот, открывающий статус и подписку FL1P VPN."""

from __future__ import annotations

import logging
import os

import telebot
from telebot import types

LOGGER = logging.getLogger("vpnmy.bot")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://theflipper-spec.github.io/VPNMY/")


def create_bot(token: str) -> telebot.TeleBot:
    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start", "help"])
    def send_welcome(message: types.Message) -> None:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(
                text="Открыть FL1P VPN",
                web_app=types.WebAppInfo(url=WEB_APP_URL),
            )
        )
        bot.send_message(
            message.chat.id,
            (
                "Привет! Здесь можно скопировать актуальную VPN-подписку и посмотреть "
                "результаты автоматической проверки серверов. Подписка обновляется каждые 10 минут."
            ),
            reply_markup=keyboard,
        )

    return bot


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    if not BOT_TOKEN:
        LOGGER.error("Переменная окружения BOT_TOKEN не задана")
        return 1
    LOGGER.info("Telegram-бот запущен")
    create_bot(BOT_TOKEN).infinity_polling(skip_pending=True, timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
