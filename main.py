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

MAX_SERVERS = 15       # Итоговое количество
MAX_PER_COUNTRY = 2    # Максимум от одной РЕАЛЬНОЙ страны
TIMEOUT = 2.0          # Тайм-аут пинга
OUTPUT_FILE = 'FL1PVPN'

# --- ПОМОЩНИКИ ---

def get_flag(country_code):
    """Превращает код страны (RU, US) в эмодзи флага 🇷🇺"""
    if not country_code: return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def get_real_geoip(ip):
    """Спрашивает у API реальную страну IP адреса"""
    try:
        # Используем ip-api.com (бесплатно, лимит 45 запросов в минуту)
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            country = data.get('country', 'Unknown')
            code = data.get('countryCode', 'XX')
            return country, code
    except:
        pass
    return None, None

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            # Нам не важно старое имя, мы его всё равно заменим
            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str, 
                "latency": 9999,
                "real_country": None,
                "country_code": None
            }
    except:
        pass
    return None

def tcp_ping(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter()
        res = sock.connect_ex((host, port))
        end = time.perf_counter()
        sock.close()
        if res == 0:
            return (end - start) * 1000
    except:
        pass
    return None

def check_server_precision(server):
    """Пинг + Реальный GeoIP (только если сервер жив)"""
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None:
            pings.append(p)
        time.sleep(0.05)
    
    if not pings:
        return None
        
    # Считаем средний пинг
    avg_ping = statistics.mean(pings)
    final_ping = int(avg_ping)
    if final_ping < 5: final_ping = 5 # Коррекция для Cloudflare
    
    server['latency'] = final_ping
    
    # Если сервер жив, узнаем его РЕАЛЬНУЮ страну
    # Делаем паузу, чтобы не забанили API
    time.sleep(0.5) 
    country, code = get_real_geoip(server['ip'])
    
    if country:
        server['real_country'] = country
        server['country_code'] = code
    else:
        server['real_country'] = "Unknown"
        server['country_code'] = "XX"
        
    return server

# --- MAIN ---

def main():
    print("--- ЗАПУСК FL1PVPN (REAL GEOIP & SHORT NAMES) ---")
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

    print(f"Проверка {len(servers_to_check)} серверов...")
    working_servers = []
    
    # max_workers поменьше, чтобы не долбить GeoIP API слишком сильно
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_server_precision, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # Сортировка по скорости
    working_servers.sort(key=lambda x: x['latency'])

    # 3. Фильтрация и Переименование
    final_list = []
    countries_count = {}
    
    print("\n--- ТОП СЕРВЕРОВ (REAL LOCATION) ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS: break
            
        country_name = s['real_country']
        country_code = s['country_code']
        
        # Проверка лимита стран
        if countries_count.get(country_name, 0) < MAX_PER_COUNTRY:
            
            # === ГЕНЕРАЦИЯ КОРОТКОГО ИМЕНИ ===
            # Формат: "Flag Country | 45ms"
            # Пример: "🇷🇺 Russia | 15ms" или "🇩🇪 Germany | 45ms"
            flag = get_flag(country_code)
            ping_val = s['latency']
            
            # Упрощаем названия стран (чтобы не было длинных "United Kingdom etc")
            short_name = country_name.replace("United States", "USA").replace("United Kingdom", "UK").replace("Russian Federation", "Russia")
            
            new_remark = f"{flag} {short_name} | {ping_val}ms"
            
            # Обновляем ссылку
            base_link = s['original'].split('#')[0]
            s['original'] = f"{base_link}#{quote(new_remark)}"
            s['remark'] = new_remark
            
            final_list.append(s)
            countries_count[country_name] = countries_count.get(country_name, 0) + 1
            print(f"[{ping_val}ms] {new_remark} (Real IP: {s['ip']})")

    # 4. Сохранение
    result_text = "\n".join([s['original'] for s in final_list])
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print("Готово.")

if __name__ == "__main__":
    main()
