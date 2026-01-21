import telebot
from telebot import types
import os 

# --- НАСТРОЙКИ ---
# Токен берется из переменных среды (как у тебя и было настроено)
BOT_TOKEN = os.environ.get("BOT_TOKEN") 

# Ссылка на твой сайт (GitHub Pages)
WEB_APP_URL = "https://theflipper-spec.github.io/VPNMY/"

if not BOT_TOKEN:
    print("Ошибка: Токен не найден! Проверь Secrets в Replit/GitHub.")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # 1. Создаем клавиатуру
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    # 2. Настраиваем Web App (встроенный браузер)
    # Это ключевой момент: кнопка теперь открывает сайт внутри Telegram
    web_app_info = types.WebAppInfo(url=WEB_APP_URL)
    
    # 3. Создаем кнопку
    btn_status = types.KeyboardButton(text="📊 Статус серверов", web_app=web_app_info)
    
    # Добавляем кнопку на клавиатуру
    markup.add(btn_status)
    
    # 4. Приветственное сообщение
    welcome_text = (
        "👋 <b>Привет!</b>\n\n"
        "Теперь вся статистика, пинг и конфиги доступны в удобном мини-приложении прямо здесь.\n\n"
        "Нажми на кнопку <b>«📊 Статус серверов»</b> внизу 👇"
    )
    
    bot.send_message(message.chat.id, welcome_text, parse_mode="HTML", reply_markup=markup)

# Запуск бота
if __name__ == "__main__":
    print("✅ Бот запущен и готов открывать Web App...")
    bot.infinity_polling()
