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
    [cite_start]# [cite: 1] Используем источник, предоставленный ранее
]

MAX_SERVERS = 15       
MAX_PER_COUNTRY = 3    
TIMEOUT = 1.5          # Тайм-аут пожестче, отсеиваем тормозов сразу
OUTPUT_FILE = 'FL1PVPN'

def get_flag(country_code):
    if not country_code: return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def get_real_geoip(ip):
    try:
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode"
        resp = requests.get(url, timeout=2)
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
            
            is_reality = False
            if "security=reality" in config_str or "pbk=" in config_str:
                is_reality = True
            
            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str, 
                "latency": 9999,
                "score": 9999,     # Новый параметр для умной сортировки
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

def check_server_smart(server):
    """Делаем замеры и вычисляем Балл Качества (Score)"""
    pings = []
    # 3 быстрых пинга
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
        
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # --- УМНАЯ СОРТИРОВКА (SMART SCORE) ---
    # Чем МЕНЬШЕ балл, тем выше сервер в списке.
    # Базовый балл = Пинг
    score = avg_ping
    
    # 1. Бонус для Reality (надежность): вычитаем 50 баллов
    # Reality с пингом 80 будет иметь score 30 (обгонит обычный с пингом 40)
    if server['is_reality']:
        score -= 50
    
    # 2. Штраф для подозрительно низкого пинга (CDN Fakes)
    # Если пинг < 5мс и это не Reality, значит это Cloudflare в РФ.
    # Штрафуем на +300, чтобы они упали вниз, но остались в списке как резерв
    if avg_ping < 5 and not server['is_reality']:
        score += 300
        server['real_country'] = "Cloudflare (CDN)"
        server['country_code'] = "CDN"
    else:
        # Пробиваем реальную страну только для нормальных серверов
        time.sleep(0.2)
        country, code = get_real_geoip(server['ip'])
        server['real_country'] = country if country else "Unknown"
        server['country_code'] = code if code else "XX"

    server['score'] = score
    return server

def main():
    print("--- ЗАПУСК V6 (SMART SCORING) ---")
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
        futures = [executor.submit(check_server_smart, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # Сортируем по Баллам (Score), а не просто по пингу
    working_servers.sort(key=lambda x: x['score'])

    final_list = []
    countries_count = {}
    
    print("\n--- ТОП СЕРВЕРОВ (SMART SORT) ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS: break
            
        country_name = s['real_country']
        country_code = s['country_code']
        
        # Упрощение имен
        short_name = country_name.replace("United States", "USA").replace("United Kingdom", "UK").replace("Russian Federation", "Russia").replace("Netherlands", "NL")
        if short_name == "Unknown": short_name = "Relay"

        # Лимит на страну (исключая CDN, их можно много, если они быстрые)
        limit = MAX_PER_COUNTRY
        if country_code == "CDN": limit = 1 # Оставляем только 1 фейковый CDN на всякий случай
        
        if countries_count.get(country_name, 0) < limit:
            
            # --- ВИЗУАЛИЗАЦИЯ СКОРОСТИ ---
            # Добавляем значки
            speed_icon = ""
            if s['latency'] < 50: speed_icon = "🚀"
            elif s['latency'] < 150: speed_icon = "⚡"
            else: speed_icon = "🐢"

            flag = get_flag(country_code) if country_code != "CDN" else "🌐"
            type_tag = "[REAL]" if s['is_reality'] else "[WS]"
            
            # Формируем имя: 🚀 🇩🇪 Germany [REAL] | 45ms
            new_remark = f"{speed_icon} {flag} {short_name} {type_tag} | {s['latency']}ms"
            
            base_link = s['original'].split('#')[0]
            s['original'] = f"{base_link}#{quote(new_remark)}"
            
            final_list.append(s)
            countries_count[country_name] = countries_count.get(country_name, 0) + 1
            
            print(f"Score: {s['score']} | {new_remark}")

    result_text = "\n".join([s['original'] for s in final_list])
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print("Saved.")

if __name__ == "__main__":
    main()
