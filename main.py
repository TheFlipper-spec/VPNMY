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

MAX_SERVERS = 15       
MAX_PER_COUNTRY = 3    # Чуть больше разнообразия
TIMEOUT = 2.0          
OUTPUT_FILE = 'FL1PVPN'

def get_flag(country_code):
    if not country_code: return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def get_real_geoip(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('country', 'Unknown'), data.get('countryCode', 'XX')
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
            
            # ОПРЕДЕЛЯЕМ ТИП: REALITY ИЛИ НЕТ
            # Reality обычно имеет pbk=... и security=reality
            is_reality = False
            if "security=reality" in config_str or "pbk=" in config_str:
                is_reality = True
            
            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str, 
                "latency": 9999,
                "real_country": None,
                "country_code": None,
                "is_reality": is_reality
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
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
        
    final_ping = int(statistics.mean(pings))
    server['latency'] = final_ping
    
    # Гео-проверка только для живых
    time.sleep(0.3)
    country, code = get_real_geoip(server['ip'])
    
    if country:
        server['real_country'] = country
        server['country_code'] = code
    else:
        server['real_country'] = "Unknown"
        server['country_code'] = "XX"
        
    return server

def main():
    print("--- ЗАПУСК V5 (PRIORITY: REALITY) ---")
    raw_links = []

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
            print(f"Error {url}: {e}")

    raw_links = list(set(raw_links))
    servers_to_check = []
    for link in raw_links:
        p = parse_config_info(link)
        if p: servers_to_check.append(p)

    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(check_server_precision, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # === ГЛАВНОЕ ИЗМЕНЕНИЕ: СОРТИРОВКА ===
    # 1. Сначала Reality (True идет перед False при сортировке с минусом или reverse=True, 
    # но в python False=0, True=1. Мы хотим True первым.
    # Поэтому сортируем по кортежу: (not is_reality, latency).
    # Если Reality (True) -> not True = False (0). 
    # Если не Reality -> not False = True (1).
    # 0 меньше 1, значит Reality встанут в начало списка.
    
    working_servers.sort(key=lambda x: (not x['is_reality'], x['latency']))

    final_list = []
    countries_count = {}
    
    print("\n--- ТОП СЕРВЕРОВ ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS: break
            
        country_name = s['real_country']
        country_code = s['country_code']
        
        # Если пинг подозрительно низкий (<5мс) и это НЕ Reality - скорее всего это CDN Домодедово
        if s['latency'] < 5 and not s['is_reality']:
             country_name = "Cloudflare (Ru?)"
             country_code = "CDN"
        
        # Упрощаем имена
        short_name = country_name.replace("United States", "USA").replace("United Kingdom", "UK").replace("Russian Federation", "Russia").replace("Netherlands", "NL")
        
        if countries_count.get(country_name, 0) < MAX_PER_COUNTRY:
            
            flag = get_flag(country_code) if country_code != "CDN" else "☁️"
            ping_val = s['latency']
            
            # Добавляем метку типа
            type_tag = "⚡" if s['is_reality'] else "🌐"
            
            new_remark = f"{flag} {short_name} {type_tag} | {ping_val}ms"
            
            base_link = s['original'].split('#')[0]
            s['original'] = f"{base_link}#{quote(new_remark)}"
            s['remark'] = new_remark
            
            final_list.append(s)
            countries_count[country_name] = countries_count.get(country_name, 0) + 1
            
            print(f"[{'REALITY' if s['is_reality'] else 'WS'}] {new_remark}")

    result_text = "\n".join([s['original'] for s in final_list])
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print("Saved.")

if __name__ == "__main__":
    main()
