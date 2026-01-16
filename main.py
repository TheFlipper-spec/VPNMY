import requests
import base64
import socket
import time
import concurrent.futures
import re
import statistics
from urllib.parse import unquote, quote

# --- НАСТРОЙКИ ---
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

MAX_SERVERS = 15       # Оставляем 15 лучших
MAX_PER_COUNTRY = 2    # Разнообразие стран
TIMEOUT = 3.0          # Тайм-аут чуть больше для точности
OUTPUT_FILE = 'FL1PVPN'

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            # Ищем имя (remark)
            remark = "Server"
            if "#" in config_str:
                raw_remark = config_str.split("#")[-1]
                remark = unquote(raw_remark).strip()
            
            # Если имя пустое или похоже на IP, пробуем определить страну по хосту (упрощенно)
            if remark == "Server" or remark == "":
                remark = f"Location {host[:4]}.."

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

def tcp_ping(host, port):
    """Высокоточный замер одного пинга"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter() # Используем наносекундный таймер
        res = sock.connect_ex((host, port))
        end = time.perf_counter()
        sock.close()
        
        if res == 0:
            return (end - start) * 1000 # Переводим в мс
    except:
        pass
    return None

def check_server_precision(server):
    """Делает 3 замера и берет среднее, чтобы исключить случайные 0ms"""
    pings = []
    # Делаем 3 попытки пинга для точности
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None:
            pings.append(p)
        time.sleep(0.1) # Микро-пауза между пингами
    
    if not pings:
        return None
        
    avg_ping = statistics.mean(pings)
    
    # КОРРЕКЦИЯ ДЛЯ РЕАЛИСТИЧНОСТИ:
    # GitHub находится в датацентре. Если пинг < 2мс, это значит сервер стоит "в соседней стойке".
    # Для пользователя из России это будет не 1мс, а скорее 40-50мс.
    # Мы не можем узнать реальный пинг пользователя, но чтобы не писать глупое "0ms",
    # мы округляем минимум до 10мс, если это Cloudflare, или оставляем как есть.
    
    final_ping = int(avg_ping)
    if final_ping < 5: 
        final_ping = 5 # Минимальный порог отображения
        
    server['latency'] = final_ping
    return server

def main():
    print("--- ЗАПУСК FL1PVPN (PRECISION MODE) ---")
    raw_links = []

    # 1. Скачивание
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                found = extract_vless_links(content)
                if not found:
                    try:
                        decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                        found = extract_vless_links(decoded)
                    except: pass
                raw_links.extend(found)
        except Exception as e:
            print(f"Ошибка {url}: {e}")

    raw_links = list(set(raw_links))
    servers_to_check = []
    for link in raw_links:
        p = parse_config_info(link)
        if p: servers_to_check.append(p)

    if not servers_to_check: exit(1)

    print(f"Проверка {len(servers_to_check)} серверов (x3 ping)...")
    working_servers = []
    
    # Уменьшаем кол-во потоков, так как теперь нагрузка выше (3 пинга)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(check_server_precision, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    working_servers.sort(key=lambda x: x['latency'])

    # 3. Фильтрация и запись
    final_list = []
    countries = {}
    
    print("\n--- ТОП СЕРВЕРОВ ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS: break
            
        tag = s['remark'][:5]
        if countries.get(tag, 0) < MAX_PER_COUNTRY:
            
            # Формируем имя с пингом
            ping_val = s['latency']
            new_remark = f"{s['remark']} | {ping_val}ms"
            
            # Чистим старое имя и ставим новое
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
    print("Готово.")

if __name__ == "__main__":
    main()
