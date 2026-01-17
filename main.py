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
from urllib.parse import unquote, quote, urlparse, parse_qs

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

# 1. ЯВНЫЕ CDN ПРОВАЙДЕРЫ (Точно WARP)
STRICT_CDN_ISPS = [
    'cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 
    'fastly', 'akamai', 'cdn77', 'g-core', 'alibaba', 'tencent',
    'edgecenter', 'servers.com', 'selectel'
]

# 2. ПОДОЗРИТЕЛЬНЫЕ ХОСТИНГИ (Часто используются как прокладка для WARP)
# Если провайдер тут - мы проверим строже.
VPS_HOSTING_ISPS = [
    'digitalocean', 'hetzner', 'vultr', 'ovh', 'choopa', 
    'hostinger', 'm247', 'datacamp', 'stark industries', 'aeza'
]

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_info_retry(ip):
    # Уменьшили паузы, так как потоков больше
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

def check_link_internals(config_str):
    """Ищет признаки CDN внутри самой ссылки (sni, host)"""
    config_str_lower = config_str.lower()
    
    # Ключевые слова, указывающие на CDN
    cdn_triggers = ['cloudflare', 'workers.dev', 'gcore', 'cloudfront', 'fastly', 'edge', 'cdn']
    
    # Парсим параметры
    try:
        if "?" in config_str:
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            # Проверяем SNI и HOST
            sni = params.get('sni', [''])[0].lower()
            host = params.get('host', [''])[0].lower()
            
            for trigger in cdn_triggers:
                if trigger in sni or trigger in host:
                    return True # Это CDN/WARP
    except:
        pass
        
    return False

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
                "info": {}, 
                "is_reality": is_reality,
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

def check_server_deep(server):
    """Глубокая проверка"""
    
    # 1. ПИНГ
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # 2. АНАЛИЗ ССЫЛКИ (До запроса к API)
    is_hidden_cdn = check_link_internals(server['original'])
    
    # 3. GEOIP
    ip_data = get_ip_info_retry(server['ip'])
    
    if not ip_data:
        # Если API молчит, но мы нашли признаки CDN в ссылке - помечаем как WARP
        if is_hidden_cdn:
             ip_data = {'countryCode': 'XX', 'org': 'Cloudflare (Hidden)', 'isp': 'CDN'}
        else:
             return None # Выкидываем неизвестных
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    # 4. ВЕРДИКТ: REAL или WARP
    
    is_warp = False
    
    # A. Если нашли CDN в ссылке
    if is_hidden_cdn: is_warp = True
    
    # B. Если провайдер в жестком списке CDN
    if any(cdn in org_str for cdn in STRICT_CDN_ISPS): is_warp = True
    
    # C. Если провайдер - VPS хостинг, а пинг подозрительно низкий (<3ms)
    # (Это значит сервер в том же датацентре, что и GitHub -> скорее всего просто прокси)
    if avg_ping < 3 and any(vps in org_str for vps in VPS_HOSTING_ISPS):
        is_warp = True

    # D. Если пинг экстремально низкий (<2ms) для любого сервера
    if avg_ping < 2: is_warp = True

    # КАТЕГОРИИ
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp:
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
                # Декодирование если base64
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
    print("--- ЗАПУСК V11 (TRUTH SEEKER) ---")
    
    # СБОР ДАННЫХ
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())

    # ОТВЕТ НА ВОПРОС ПОЛЬЗОВАТЕЛЯ
    print(f"\n>>> В БАЗЕ НАЙДЕНО ССЫЛОК: {len(servers_to_check)} шт. <<<")
    
    if not servers_to_check: exit(1)

    print(f"Начинаю проверку в 10 потоков...")
    working_servers = []
    
    # Вернули 10 потоков по просьбе
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_server_deep, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # РАСПРЕДЕЛЕНИЕ
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # СОРТИРОВКА
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # ИТОГОВЫЙ СПИСОК
    final_list = []
    final_list.extend(bucket_reality[:LIMIT_REALITY])
    final_list.extend(bucket_warp[:LIMIT_WARP])
    final_list.extend(bucket_whitelist[:LIMIT_WHITELIST])

    print("\n--- ИТОГ ---")
    
    result_configs = []
    
    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        
        # Исправление имени, если API подвел, но мы знаем, что это WARP
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
        
        if s['category'] == 'WHITELIST':
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | {ping}ms"
            
        elif s['category'] == 'WARP':
            # Если код XX - пишем Глобал WARP
            if code == 'XX':
                new_remark = f"🌀 🌐 Cloudflare WARP | {ping}ms"
            else:
                new_remark = f"🌀 {flag} {country_ru} WARP | {ping}ms"
            
        else:
            # REALITY (Если прошел все проверки)
            # Для честности добавим метку VPS, если это хостинг
            isp_lower = (s['info'].get('isp', '')).lower()
            vps_tag = ""
            if any(v in isp_lower for v in VPS_HOSTING_ISPS):
                vps_tag = " (VPS)"
                
            new_remark = f"⚡ {flag} {country_ru}{vps_tag} | {ping}ms"

        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_configs.append(final_link)
        
        try:
            print(f"[{s['category']}] {new_remark} [ISP: {s['info'].get('org', 'Unknown')}]")
        except:
            pass

    result_text = "\n".join(result_configs)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(final_list)} servers.")

if __name__ == "__main__":
    main()
