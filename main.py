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
LIMIT_REALITY = 10

TIMEOUT = 1.5
OUTPUT_FILE = 'FL1PVPN'

# ПЕРЕВОДЧИК
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур'
}

# СТРАНЫ, ПОДХОДЯЩИЕ ДЛЯ ИГР ИЗ РФ (Низкий пинг)
GAMING_ALLOWED_COUNTRIES = [
    'FI', 'SE', 'EE', 'LV', 'LT', 'DE', 'NL', 'PL', 'RU', 'KZ', 'BY', 'TR', 'UA'
]

# СПИСОК "ГРЯЗНЫХ" ПРОВАЙДЕРОВ (CDN)
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

def check_server_strict_v12(server):
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
    
    # Если API не ответил, пытаемся спасти страну из названия (Fallback)
    if not ip_data:
        # Для WS можно предположить CDN
        if server['transport'] in ['ws', 'grpc']:
             ip_data = {'countryCode': 'XX', 'org': 'Cloudflare', 'isp': 'CDN'}
        else:
             # Для TCP Reality пробуем угадать по имени, иначе удаляем
             rem = server['original_remark'].lower()
             if "germany" in rem: ip_data = {'countryCode': 'DE', 'org': 'Unknown', 'isp': 'Unknown'}
             elif "finland" in rem: ip_data = {'countryCode': 'FI', 'org': 'Unknown', 'isp': 'Unknown'}
             elif "netherlands" in rem: ip_data = {'countryCode': 'NL', 'org': 'Unknown', 'isp': 'Unknown'}
             else: return None
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    # 3. КЛАССИФИКАЦИЯ
    is_warp_cdn = False
    
    if server['transport'] == 'ws' or server['transport'] == 'grpc':
        is_warp_cdn = True
    if any(cdn in org_str for cdn in CDN_ISPS):
        is_warp_cdn = True
    # Убираем жесткий бан по пингу <3, так как мы теперь смотрим протокол
    # Но если пинг 0-1ms - это все равно подозрительно для Reality
    if avg_ping < 2:
        is_warp_cdn = True
    if server['security'] != 'reality':
        is_warp_cdn = True

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
    print("--- ЗАПУСК V14 (EURO-GAMING PRIORITY) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_server_strict_v12, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # РАСПРЕДЕЛЕНИЕ
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # СОРТИРОВКА (По пингу к GitHub, но мы будем учитывать страну ниже)
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # --- ЛОГИКА ИГРОВОГО СЕРВЕРА ---
    # Мы ищем ПЕРВЫЙ Reality сервер, который находится в БЛИЖНЕМ ЗАРУБЕЖЬЕ
    gaming_server = None
    
    for s in bucket_reality:
        code = s['info'].get('countryCode', 'XX')
        # Если страна в списке "Игровых" (FI, SE, DE, NL...)
        if code in GAMING_ALLOWED_COUNTRIES:
            gaming_server = copy.deepcopy(s)
            gaming_server['category'] = 'GAMING'
            break
            
    # Если европейский сервер не найден, берем просто самый быстрый Reality
    if not gaming_server and len(bucket_reality) > 0:
         gaming_server = copy.deepcopy(bucket_reality[0])
         gaming_server['category'] = 'GAMING'

    # ИТОГОВЫЙ СПИСОК
    final_list = []
    
    if gaming_server:
        final_list.append(gaming_server)

    final_list.extend(bucket_reality[:LIMIT_REALITY])
    final_list.extend(bucket_warp[:LIMIT_WARP])
    final_list.extend(bucket_whitelist[:LIMIT_WHITELIST])

    print("\n--- ИТОГОВЫЙ СПИСОК ---")
    
    result_configs = []
    
    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        
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
            new_remark = f"🎮 GAME SERVER | {country_ru} | {ping}ms"

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
        result_configs.append(final_link)
        
        try:
            print(f"[{s['category']}] {new_remark}")
        except:
            pass

    result_text = "\n".join(result_configs)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(final_list)} servers.")

if __name__ == "__main__":
    main()
