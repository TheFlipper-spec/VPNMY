import requests
import base64
import socket
import time
import concurrent.futures
import re
from urllib.parse import unquote

# --- ССЫЛКИ НА ИСТОЧНИКИ ---
# Я добавил сюда прямые ссылки на Raw версии твоих файлов и запасные
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

MAX_SERVERS = 15       # Количество серверов в итоге
MAX_PER_COUNTRY = 2    # Максимум от одной страны
TIMEOUT = 2.0          # Тайм-аут проверки (сек)

def extract_vless_links(text):
    """Ищет vless:// ссылки в любом тексте с помощью регулярных выражений"""
    # Ищем всё, что начинается на vless:// и идет до конца строки или пробела
    # Это позволяет игнорировать мусор вокруг
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str):
    """Разбирает ссылку на IP и Порт для проверки"""
    try:
        # vless://uuid@ip:port?param...
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            # Пытаемся вытащить имя (remark) после #
            remark = "Server"
            if "#" in config_str:
                remark = unquote(config_str.split("#")[-1]).strip()
            
            return {
                "ip": host, 
                "port": int(port), 
                "remark": remark, 
                "original": config_str, 
                "latency": 9999
            }
    except:
        pass
    return None

def check_server(server):
    """Проверяет подключение"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.time()
        # Пробуем подключиться
        res = sock.connect_ex((server['ip'], server['port']))
        diff = (time.time() - start) * 1000
        sock.close()
        
        if res == 0:
            server['latency'] = diff
            return server
    except:
        pass
    return None

def main():
    print("--- ЗАПУСК V3 (REGEX SEARCH) ---")
    raw_links = []

    # 1. Скачивание и поиск ссылок
    for url in SOURCE_URLS:
        try:
            print(f"Скачиваю: {url}")
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                
                # Попытка 1: Ищем в обычном тексте
                found = extract_vless_links(content)
                
                # Попытка 2: Если нашли мало, пробуем декодировать Base64
                if len(found) == 0:
                    try:
                        decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                        found = extract_vless_links(decoded)
                    except:
                        pass
                
                print(f"  -> Найдено ссылок: {len(found)}")
                raw_links.extend(found)
            else:
                print(f"  -> Ошибка доступа: {resp.status_code}")
        except Exception as e:
            print(f"  -> Сбой сети: {e}")

    # Удаляем дубликаты
    raw_links = list(set(raw_links))
    print(f"\nВсего уникальных ссылок для проверки: {len(raw_links)}")

    if len(raw_links) == 0:
        print("!!! ОШИБКА: Не найдено ни одной vless ссылки !!!")
        print("Проверьте, доступны ли URL источников.")
        exit(1) # Завершаем с ошибкой, чтобы в Actions был крестик

    # Подготовка к проверке
    servers_to_check = []
    for link in raw_links:
        parsed = parse_config_info(link)
        if parsed:
            servers_to_check.append(parsed)

    # 2. Массовая проверка скорости
    print(f"Начинаю проверку пинга для {len(servers_to_check)} серверов...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_server, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            result = f.result()
            if result:
                working_servers.append(result)

    print(f"\nРабочих серверов: {len(working_servers)}")

    if not working_servers:
        print("Все серверы недоступны. Возможно, GitHub блокирует порты или список устарел.")
        exit(1)

    # 3. Сортировка и выборка
    working_servers.sort(key=lambda x: x['latency'])
    
    final_list = []
    countries = {}
    
    print("\n--- ТОП СЕРВЕРОВ ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS:
            break
            
        # Определяем страну по эмодзи или первым буквам имени
        tag = s['remark'][:5] 
        
        # Логика разнообразия
        if countries.get(tag, 0) < MAX_PER_COUNTRY:
            final_list.append(s)
            countries[tag] = countries.get(tag, 0) + 1
            print(f"[{int(s['latency'])}ms] {s['remark']}")

    # 4. Сохранение результата
    # Собираем ссылки в строку
    result_text = "\n".join([s['original'] for s in final_list])
    
    # Кодируем в Base64 (обязательно для подписок)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open('sub.txt', 'w') as f:
        f.write(final_base64)

    print(f"\nФайл sub.txt успешно записан ({len(final_list)} шт).")

if __name__ == "__main__":
    main()
