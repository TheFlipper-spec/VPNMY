import telebot
from telebot import types
import requests
import base64
import re
import os # Добавили модуль для работы с секретами

# --- НАСТРОЙКИ ---
# Бот теперь берет токен из переменных окружения сервера
BOT_TOKEN = os.environ.get("BOT_TOKEN") 

# Ссылку оставь как есть
SUBSCRIPTION_URL = "https://raw.githubusercontent.com/TheFlipper-spec/VPNMY/main/FL1PVPN"

if not BOT_TOKEN:
    print("Ошибка: Токен не найден!")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)

def get_data_from_github():
    try:
        # Анти-кэш трюк
        url = f"{SUBSCRIPTION_URL}?t={requests.utils.quote(str(re.sub(r'[^0-9]', '', str(base64.b64encode(str(telebot).encode())))))}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            decoded = base64.b64decode(response.text).decode('utf-8')
            return decoded
    except Exception as e:
        print(f"Error fetching: {e}")
    return None

def parse_servers(text):
    servers = []
    info_header = "Нет данных о времени"
    
    if not text: return info_header, servers

    lines = text.split('\n')
    for line in lines:
        if not line.strip(): continue
        
        name = "Unknown"
        if '#' in line:
            name = requests.utils.unquote(line.split('#')[-1])
        
        if "📅" in name or "Обновлено" in name:
            info_header = name
            continue 

        ping = 999
        match = re.search(r'~(\d+)ms', name)
        if match:
            ping = int(match.group(1))
        
        servers.append({
            'name': name,
            'ping': ping,
            'original_link': line
        })
        
    return info_header, servers

def get_speed_bar(ping):
    if ping < 60: return "🟩🟩🟩🟩🟩 (Летает 🚀)"
    elif ping < 110: return "🟨🟨🟨⬜⬜ (Хорошо 👌)"
    elif ping < 200: return "🟧🟧⬜⬜⬜ (Пойдет 😐)"
    else: return "🟥⬜⬜⬜⬜ (Медленно 🐢)"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("📊 Статус серверов")
    btn2 = types.KeyboardButton("🏆 Топ-3 Скоростных")
    btn3 = types.KeyboardButton("🔑 Моя подписка")
    
    markup.add(btn1, btn2)
    markup.add(btn3)
    
    bot.reply_to(message, "Привет! Я бот мониторинга FL1PVPN.", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔑 Моя подписка")
def send_link(message):
    msg = "Вот твоя прямая ссылка для приложений:\n\n"
    msg += f"`{SUBSCRIPTION_URL}`"
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "📊 Статус серверов")
def send_status(message):
    raw_data = get_data_from_github()
    if not raw_data:
        bot.reply_to(message, "⚠️ Не удалось получить данные (возможно, GitHub обновляется).")
        return

    header, servers = parse_servers(raw_data)
    
    msg = f"📡 <b>СТАТУС СЕТИ FL1PVPN</b>\n\n"
    msg += f"ℹ️ <i>{header}</i>\n"
    msg += f"📦 Всего серверов: <b>{len(servers)}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    
    for s in servers:
        clean_name = s['name'].strip()
        msg += f"🔹 {clean_name}\n"

    bot.send_message(message.chat.id, msg, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == "🏆 Топ-3 Скоростных")
def send_top(message):
    raw_data = get_data_from_github()
    if not raw_data:
        bot.reply_to(message, "⚠️ Ошибка данных.")
        return

    header, servers = parse_servers(raw_data)
    
    sorted_servers = sorted(servers, key=lambda x: x['ping'])
    top_3 = sorted_servers[:3]
    
    msg = f"🏆 <b>ТОП-3 ЛУЧШИХ СЕРВЕРА</b>\n"
    msg += f"ℹ️ <i>{header}</i>\n\n"
    
    for i, s in enumerate(top_3, 1):
        bar = get_speed_bar(s['ping'])
        clean_name = s['name'].strip()
        msg += f"<b>{i}. {clean_name}</b>\n"
        msg += f"   └ {bar}\n\n"
        
    bot.send_message(message.chat.id, msg, parse_mode='HTML')

# Запуск
if __name__ == "__main__":
    bot.polling(none_stop=True)
