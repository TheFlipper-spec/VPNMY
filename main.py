import requests
import base64
import socket
import time
import concurrent.futures
from urllib.parse import urlparse, unquote

# --- НАСТРОЙКИ ---
# Сюда можно добавлять ссылки на списки ключей (Raw format)
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    # Можно добавить другие ссылки через запятую
]
MAX_SERVERS = 10  # Сколько серверов оставить в итоге
MAX_PER_COUNTRY = 2  # Максимум серверов от одной страны (для разнообразия)
TIMEOUT = 2  # Тайм-аут проверки в секундах (если дольше - сервер считается плохим)

def parse_vless(config_str):
    """Вытаскивает IP, порт и имя из vless ссылки"""
    try:
        # Убираем пробелы и лишние символы
        config_str = config_str.strip()
        if not config_str.startswith("vless://"):
            return None
        
        # Парсим имя (то что после #)
        remark = "Unknown"
        if "#" in config_str:
            parts = config_str.split("#")
            remark = unquote(parts[-1]).strip()
            # Пытаемся определить страну по эмодзи флага или тексту
            # Это упрощенная логика, берет первые слова из названия
        
        # Парсим адрес и порт
        # vless://uuid@ip:port...
        main_part = config_str.split("@")[1].split("?")[0]
        host_port = main_part.split(":")
        ip = host_port[0]
        port = int(host_port[1])
        
        return {"ip": ip, "port": port, "remark": remark, "original": config_str, "latency": 9999}
    except Exception:
        return None

def check_server(server):
    """Проверяет реальное TCP подключение к порту"""
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        result = sock.connect_ex((server['ip'], server['port']))
        end_time = time.time()
        sock.close()
        
        if result == 0:
            server['latency'] = (end_time - start_time) * 1000 # перевод в мс
            return server
        else:
            return None # Порт закрыт или недоступен
    except:
        return None

def main():
    print("--- ЗАПУСК СКРИПТА ---")
    all_configs = []

    # 1. Скачивание конфигов
    for url in SOURCE_URLS:
        try:
            print(f"Скачиваю: {url}")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                lines = response.text.splitlines()
                # Декодируем base64 если файл зашифрован, если нет - берем как есть
                try:
                    decoded = base64.b64decode(response.text).decode('utf-8')
                    lines = decoded.splitlines()
                except:
                    pass # Значит обычный текст
                
                for line in lines:
                    parsed = parse_vless(line)
                    if parsed:
                        all_configs.append(parsed)
        except Exception as e:
            print(f"Ошибка при скачивании {url}: {e}")
            
    print(f"Всего найдено ключей: {len(all_configs)}")
    if len(all_configs) == 0:
        print("Не найдено рабочих конфигов для проверки.")
        return

    # 2. Проверка скорости (многопоточность)
    working_servers = []
    print("Начинаю проверку скорости...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        results = executor.map(check_server, all_configs)
        
    for res in results:
        if res:
            working_servers.append(res)
            
    print(f"Рабочих серверов: {len(working_servers)}")
    
    # 3. Сортировка и Фильтрация
    # Сначала сортируем от быстрого к медленному
    working_servers.sort(key=lambda x: x['latency'])
    
    final_list = []
    countries_count = {} # Счетчик стран: {'Germany': 1, 'Finland': 2}
    
    for server in working_servers:
        if len(final_list) >= MAX_SERVERS:
            break
            
        # Простая эвристика страны по названию (берем первые 5 символов названия как идентификатор страны)
        # Например "🇩🇪 Ger" или "🇫🇮 Fin"
        country_tag = server['remark'][:5] 
        
        current_count = countries_count.get(country_tag, 0)
        
        if current_count < MAX_PER_COUNTRY:
            final_list.append(server)
            countries_count[country_tag] = current_count + 1
            print(f"Добавлен: {server['remark']} | Пинг: {int(server['latency'])}ms")
        else:
            # Пропускаем, чтобы дать место другим странам
            continue

    # 4. Сохранение
    result_text = ""
    for s in final_list:
        result_text += s['original'] + "\n"
        
    # Кодируем в Base64 (чтобы приложение поняло как подписку)
    encoded_result = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open('sub.txt', 'w') as f:
        f.write(encoded_result)
        
    print("--- ГОТОВО. Файл sub.txt обновлен ---")

if __name__ == "__main__":
    main()
