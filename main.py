import requests
import base64
import socket
import time
import concurrent.futures
import re
from urllib.parse import unquote, quote

# --- НАСТРОЙКИ ---
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

MAX_SERVERS = 15       # Оставляем 15 лучших
MAX_PER_COUNTRY = 2    # Разнообразие стран
TIMEOUT = 2.0          # Тайм-аут проверки (быстрая проверка)
OUTPUT_FILE = 'FL1PVPN' # Имя файла подписки

def extract_vless_links(text):
    """Ищет vless:// ссылки через регулярные выражения"""
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str):
    """Разбирает ссылку для проверки"""
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            # Ищем имя (remark) после #
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
    """Проверяет подключение (TCP Ping)"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.time()
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
    print("--- ЗАПУСК FL1PVPN AGGREGATOR ---")
    raw_links = []

    # 1. Скачивание
    for url in SOURCE_URLS:
        try:
            print(f"Скачиваю: {url}")
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                found = extract_vless_links(content)
                
                if len(found) == 0:
                    try:
                        decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                        found = extract_vless_links(decoded)
                    except:
                        pass
                
                print(f"  -> Найдено ссылок: {len(found)}")
                raw_links.extend(found)
        except Exception as e:
            print(f"  -> Ошибка: {e}")

    raw_links = list(set(raw_links)) # Удаляем дубликаты
    
    servers_to_check = []
    for link in raw_links:
        parsed = parse_config_info(link)
        if parsed:
            servers_to_check.append(parsed)

    if not servers_to_check:
        print("!!! Ключи не найдены !!!")
        exit(1)

    # 2. Проверка
    print(f"\nНачинаю проверку {len(servers_to_check)} серверов...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_server, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    print(f"Рабочих серверов: {len(working_servers)}")
    working_servers.sort(key=lambda x: x['latency'])

    # 3. Фильтрация и ДОБАВЛЕНИЕ ПИНГА В ИМЯ
    final_list = []
    countries = {}
    
    print("\n--- ТОП СЕРВЕРОВ (FL1PVPN) ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS:
            break
            
        tag = s['remark'][:5] # Определяем страну
        
        if countries.get(tag, 0) < MAX_PER_COUNTRY:
            # === МАГИЯ ТУТ ===
            # Формируем новое имя: "🇩🇪 Germany | 45ms"
            ping_val = int(s['latency'])
            new_remark = f"{s['remark']} | {ping_val}ms"
            
            # Вставляем это имя обратно в ссылку (URL encoded)
            base_link = s['original'].split('#')[0]
            s['original'] = f"{base_link}#{quote(new_remark)}"
            s['remark'] = new_remark
            
            final_list.append(s)
            countries[tag] = countries.get(tag, 0) + 1
            print(f"[{ping_val}ms] {s['remark']}")

    # 4. Сохранение
    result_text = "\n".join([s['original'] for s in final_list])
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)

    print(f"\nФайл {OUTPUT_FILE} успешно записан!")

if __name__ == "__main__":
    main()
