import sys
# --- ПАТЧ КОДИРОВКИ ---
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import requests
import base64
import socket
import time
import concurrent.futures
import re
import statistics
from urllib.parse import unquote, quote

# --- НАСТРОЙКИ ИСТОЧНИКОВ ---

# 1. Ссылки на ОБЫЧНЫЕ базы (отсюда берем Reality и WARP)
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

# 2. Ссылки на БЕЛЫЕ СПИСКИ (специальные конфиги)
WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
]

# --- НАСТРОЙКИ КВОТ (Сколько серверов каждого типа брать) ---
LIMIT_WHITELIST = 3   # Сколько спец. серверов для обхода (⚪)
LIMIT_WARP = 3        # Максимум WARP/CDN (не больше 3 штук!)
LIMIT_REALITY = 10    # Остальное заполняем реальными серверами (⚡)

TIMEOUT = 1.5          
OUTPUT_FILE = 'FL1PVPN'

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_real_geoip(ip):
    try:
        time.sleep(0.1) 
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('country', None), data.get('countryCode', None)
    except:
        pass
    return None, None

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str, source_type):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            
            is_reality = False
            if "security=reality" in config_str or "pbk=" in config_str:
                is_reality = True
            
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str,
                "original_remark": original_remark, 
                "latency": 9999,
                "real_country": None,
                "country_code": None,
                "is_reality": is_reality,
                "source_type": source_type # 'general' или 'whitelist'
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

def check_server_full(server):
    """Полная проверка: пинг + GeoIP + определение типа"""
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
        
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # ОПРЕДЕЛЯЕМ КАТЕГОРИЮ (TAG)
    # 1. Если из файла WhiteList -> WL
    # 2. Если пинг < 5мс и не Reality -> WARP
    # 3. Остальное -> REAL
    
    is_warp = False
    
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif avg_ping < 5 and not server['is_reality']:
        server['category'] = 'WARP'
        is_warp = True
    else:
        server['category'] = 'REALITY'

    # GEOIP ЛОГИКА
    country = None
    code = None
    
    # Для WhiteList и Reality пытаемся узнать страну
    if not is_warp:
        country, code = get_real_geoip(server['ip'])
    
    # Fallback (если API не ответил или это WARP)
    if not country:
        rem = server['original_remark'].lower()
        if "united states" in rem or "usa" in rem or "🇺🇸" in rem: country, code = "United States", "US"
        elif "germany" in rem or "🇩🇪" in rem: country, code = "Germany", "DE"
        elif "netherlands" in rem or "🇳🇱" in rem: country, code = "Netherlands", "NL"
        elif "finland" in rem or "🇫🇮" in rem: country, code = "Finland", "FI"
        elif "russia" in rem or "🇷🇺" in rem: country, code = "Russia", "RU"
        elif "turkey" in rem or "🇹🇷" in rem: country, code = "Turkey", "TR"
        else:
            country = "Relay" if not is_warp else "Cloudflare"
            code = "XX" if not is_warp else "CDN"

    server['real_country'] = country
    server['country_code'] = code
    return server

def process_urls(urls, source_type):
    links = []
    for url in urls:
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
                
                # Создаем объекты серверов
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except Exception as e:
            print(f"Error loading {url}: {e}")
    return links

def main():
    print("--- ЗАПУСК V8 (BUCKETS SYSTEM) ---")
    
    # 1. Сбор всех ссылок
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    # Удаляем дубликаты по ссылке
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())

    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(check_server_full, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # 2. РАСКЛАДЫВАЕМ ПО КОРЗИНАМ
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # Сортируем каждую корзину по пингу (от быстрого к медленному)
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # 3. НАБИРАЕМ ФИНАЛЬНЫЙ СПИСОК (КВОТЫ)
    final_list = []
    
    # Сначала берем WhiteList (показываем первыми, так как они важны для РФ)
    final_list.extend(bucket_whitelist[:LIMIT_WHITELIST])
    
    # Потом берем Reality (самые качественные)
    final_list.extend(bucket_reality[:LIMIT_REALITY])
    
    # В конце добавляем немного WARP (для резерва)
    final_list.extend(bucket_warp[:LIMIT_WARP])

    print("\n--- ИТОГОВЫЙ СПИСОК ---")
    
    result_configs = []
    
    for s in final_list:
        # ГЕНЕРАЦИЯ ИМЕНИ
        
        # Иконка типа
        icon = ""
        if s['category'] == 'WHITELIST': icon = "⚪"  # Белый круг
        elif s['category'] == 'REALITY': icon = "⚡"  # Молния
        elif s['category'] == 'WARP':    icon = "🌀"  # Спираль (Warp)

        flag = get_flag(s['country_code']) if s['country_code'] != "CDN" else "🌐"
        
        # Упрощаем название страны
        country_name = s['real_country']
        country_name = country_name.replace("United States", "USA").replace("United Kingdom", "UK").replace("Russian Federation", "Russia")
        if s['category'] == 'WHITELIST': country_name = "WhiteList" # Для WL пишем просто WhiteList или Russia

        ping = s['latency']
        
        # Формат: ⚪ 🇷🇺 Russia | 45ms
        # Формат: ⚡ 🇩🇪 Germany | 55ms
        # Формат: 🌀 🌐 Cloudflare | 5ms
        
        if s['category'] == 'WARP':
            new_remark = f"{icon} WARP (CDN) | {ping}ms"
        else:
            new_remark = f"{icon} {flag} {country_name} | {ping}ms"

        # Вставляем имя в ссылку
        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_configs.append(final_link)
        
        try:
            print(f"[{s['category']}] {new_remark}")
        except:
            pass

    # Сохранение
    result_text = "\n".join(result_configs)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(final_list)} servers.")

if __name__ == "__main__":
    main()
