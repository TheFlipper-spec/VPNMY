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
import copy
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
]

# ЛИМИТЫ
LIMIT_WHITELIST = 3
LIMIT_WARP = 5
LIMIT_REALITY = 12

TIMEOUT = 1.5
OUTPUT_FILE = 'FL1PVPN'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 6

# ПЕРЕВОДЧИК
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания'
}

# ТОЛЬКО ЭТИ СТРАНЫ МОГУТ БЫТЬ ИГРОВЫМИ (Ближняя Европа)
EUROPE_GAMING_CODES = [
    'FI', 'SE', 'EE', 'LV', 'LT', 'DE', 'NL', 'PL', 'RU', 'KZ', 'BY', 'UA', 'TR', 'CZ', 'BG', 'RO'
]

# "ГРЯЗНЫЕ" ПРОВАЙДЕРЫ
CDN_ISPS = [
    'cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 
    'fastly', 'akamai', 'cdn77', 'g-core', 'alibaba', 'tencent',
    'edgecenter', 'servers.com', 'digitalocean', 'vultr'
]

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_info_retry(ip):
    for attempt in range(2):
        try:
            time.sleep(0.2 + attempt * 0.2) 
            url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,org,isp"
            resp = requests.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success':
                    return data
                return {'status': 'fail', 'countryCode': 'XX', 'org': 'Private', 'isp': 'Private'}
        except:
            pass
    return None

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str, source_type):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str,
                "original_remark": original_remark,
                "latency": 9999,
                "info": {},
                "transport": transport, 
                "security": security,
                "source_type": source_type
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

def check_server_strict_v17(server):
    # 1. ПИНГ
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # 2. GEOIP
    ip_data = get_ip_info_retry(server['ip'])
    
    if not ip_data:
        if server['source_type'] == 'whitelist':
             ip_data = {'countryCode': 'RU', 'org': 'Unknown', 'isp': 'Unknown'}
        else:
             return None 
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    # 3. КЛАССИФИКАЦИЯ
    is_warp_cdn = False
    
    if server['transport'] in ['ws', 'grpc']: is_warp_cdn = True
    if any(cdn in org_str for cdn in CDN_ISPS): is_warp_cdn = True
    # ВАЖНО: Пинг < 2мс = локальный CDN (почти всегда)
    if avg_ping < 2: is_warp_cdn = True
    if server['security'] != 'reality': is_warp_cdn = True

    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp_cdn:
        server['category'] = 'WARP'
    else:
        server['category'] = 'REALITY'

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
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except Exception as e:
            print(f"Error {url}: {e}")
    return links

def main():
    print("--- ЗАПУСК V17 (PHYSICS LAW FILTER) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers (10 threads)...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_server_strict_v17, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # Сортировка по пингу (от GitHub)
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # --- ЖЕСТКАЯ ЛОГИКА ИГРОВОГО СЕРВЕРА ---
    gaming_server = None
    
    print("\n--- ПОДБОР ИГРОВОГО СЕРВЕРА ---")
    
    # Проходим по всем REALITY серверам
    for s in bucket_reality:
        code = s['info'].get('countryCode', 'XX')
        ping_from_github = s['latency']
        
        # 1. ПРОВЕРКА СТРАНЫ (Только Европа/РФ)
        if code not in EUROPE_GAMING_CODES:
            print(f"Skip {code} (Not Europe)")
            continue
            
        # 2. ПРОВЕРКА ФИЗИКИ (Самое важное!)
        # GitHub Actions обычно в США.
        # Если пинг < 40мс -> Сервер слишком близко к США. Это ФЕЙКОВАЯ Европа.
        # Если пинг > 40мс -> Сервер реально далеко (через океан). Это НАСТОЯЩАЯ Европа.
        
        MIN_LATENCY_FOR_EUROPE = 40 # Минимум 40мс через Атлантику
        
        if ping_from_github < MIN_LATENCY_FOR_EUROPE:
            print(f"Skip {code} (Ping {ping_from_github}ms is suspicious/Fake Geo)")
            continue
            
        # 3. ПРОВЕРКА НА БРЕД (Если пинг > 250, то это уже Азия/Австралия)
        if ping_from_github > 250:
            print(f"Skip {code} (Ping {ping_from_github}ms is too high)")
            continue

        # Если прошли все фильтры - это ИДЕАЛЬНЫЙ КАНДИДАТ
        print(f">>> WINNER: {code} with ping {ping_from_github}ms (Verified Distance)")
        gaming_server = copy.deepcopy(s)
        gaming_server['category'] = 'GAMING'
        break

    # ИТОГОВЫЙ СПИСОК
    final_objects = []
    
    # Инфо-панель
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    time_str = msk_now.strftime("%H:%M")
    next_str = next_update.strftime("%H:%M")
    info_remark = f"📅 Обновлено: {time_str} | След: {next_str}"
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(info_remark)}"
    
    result_links = [info_link] # 1. Инфо

    if gaming_server:          # 2. Игровой
        final_objects.append(gaming_server)
        
    final_objects.extend(bucket_reality[:LIMIT_REALITY]) # 3. Элита
    final_objects.extend(bucket_warp[:LIMIT_WARP])       # 4. Warp
    final_objects.extend(bucket_whitelist[:LIMIT_WHITELIST]) # 5. WL

    print("\n--- ГЕНЕРАЦИЯ ---")
    
    for s in final_objects:
        code = s['info'].get('countryCode', 'XX')
        
        # Исправление имени для WARP
        if code == 'XX' and s['category'] == 'WARP':
            rem = s['original_remark'].lower()
            if "united states" in rem or "usa" in rem: code = 'US'
            elif "germany" in rem: code = 'DE'
            elif "finland" in rem: code = 'FI'
            elif "netherlands" in rem: code = 'NL'
        
        country_ru = RUS_NAMES.get(code, code)
        if code == 'XX': country_ru = "Глобал"

        flag = get_flag(code)
        ping = s['latency']
        
        new_remark = ""
        
        if s['category'] == 'GAMING':
            # Особое имя
            new_remark = f"🎮 GAME SERVER | {country_ru} | Low Ping"

        elif s['category'] == 'WHITELIST':
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | {ping}ms"
            
        elif s['category'] == 'WARP':
            if code == 'XX':
                new_remark = f"🌀 🌐 Cloudflare WARP | {ping}ms"
            else:
                new_remark = f"🌀 {flag} {country_ru} WARP | {ping}ms"
            
        else:
            isp_lower = (s['info'].get('isp', '')).lower()
            vps_tag = ""
            if any(v in isp_lower for v in ['hetzner', 'aeza', 'm247', 'stark']):
                vps_tag = " (VPS)"
                
            new_remark = f"⚡ {flag} {country_ru}{vps_tag} | {ping}ms"

        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_links.append(final_link)
        
        try:
            print(f"[{s['category']}] {new_remark}")
        except:
            pass

    result_text = "\n".join(result_links)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(result_links)} links.")

if __name__ == "__main__":
    main()
