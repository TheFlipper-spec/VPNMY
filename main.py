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

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
]

# Лимиты
LIMIT_WHITELIST = 3   # Внизу списка
LIMIT_WARP = 3        # Резерв
LIMIT_REALITY = 12    # Основа

TIMEOUT = 1.5          
OUTPUT_FILE = 'FL1PVPN'

# Словарь для перевода стран
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 
    'FI': 'Финляндия', 'RU': 'Россия', 'TR': 'Турция', 
    'GB': 'Великобритания', 'FR': 'Франция', 'SE': 'Швеция',
    'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь'
}

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_info(ip):
    """Узнаем Страну и ПРОВАЙДЕРА (чтобы ловить Cloudflare)"""
    try:
        time.sleep(0.15) # Пауза для API
        # Запрашиваем поле 'org' и 'isp'
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode,org,isp"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            return resp.json()
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
                "info": {}, # Сюда положим данные от API
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

def check_server_strict(server):
    """Строгая проверка с детектором CDN"""
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
        
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # 1. ЗАПРОС К API (ОБЯЗАТЕЛЬНО)
    ip_data = get_ip_info(server['ip'])
    
    # Фолбэк, если API не ответил
    if not ip_data:
        ip_data = {'countryCode': 'XX', 'org': 'Unknown', 'isp': 'Unknown'}

    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_name = (ip_data.get('org', '') + ip_data.get('isp', '')).lower()

    # 2. ЖЕСТКАЯ ЛОГИКА ОПРЕДЕЛЕНИЯ WARP/CDN
    # Список провайдеров, которые мы считаем "грязными" (CDN/Hosting)
    cdn_keywords = ['cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 'digitalocean', 'fastly', 'akamai']
    
    is_cdn_detected = False
    
    # Если пинг подозрительно низкий (<5) ИЛИ имя провайдера содержит Cloudflare/Google...
    if avg_ping < 5 or any(k in org_name for k in cdn_keywords):
        is_cdn_detected = True

    # 3. ПРИСВОЕНИЕ КАТЕГОРИИ
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_cdn_detected:
        server['category'] = 'WARP'
    else:
        server['category'] = 'REALITY' # Только если пинг > 5 и провайдер чистый

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
    print("--- ЗАПУСК V9 (STRICT ISP CHECK & RUS NAMES) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())

    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers (with ISP check)...")
    working_servers = []
    
    # Меньше потоков, чтобы API успевал отвечать
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(check_server_strict, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # Раскладываем по корзинам
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # Сортировка внутри корзин
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # === СБОРКА ИТОГОВОГО СПИСКА ===
    final_list = []
    
    # 1. Сначала ЭЛИТА (Reality)
    final_list.extend(bucket_reality[:LIMIT_REALITY])
    
    # 2. Потом WARP (Резерв)
    final_list.extend(bucket_warp[:LIMIT_WARP])
    
    # 3. В самом низу - WHITELIST (Спецрезерв)
    final_list.extend(bucket_whitelist[:LIMIT_WHITELIST])

    print("\n--- ИТОГ (РУССКИЕ НАЗВАНИЯ) ---")
    
    result_configs = []
    
    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        
        # Перевод страны на Русский
        country_ru = RUS_NAMES.get(code, code) # Если нет в словаре, берем код (US)
        if code == 'XX': country_ru = "Европа"

        flag = get_flag(code)
        ping = s['latency']
        
        # ФОРМИРОВАНИЕ ИМЕНИ
        new_remark = ""
        
        if s['category'] == 'WHITELIST':
            # Для Вайтлистов обычно это РФ
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | {ping}ms"
            
        elif s['category'] == 'WARP':
            # WARP
            flag = get_flag(code) if code != "XX" else "🌐"
            new_remark = f"🌀 {flag} {country_ru} WARP | {ping}ms"
            
        else:
            # REALITY (Чистый)
            new_remark = f"⚡ {flag} {country_ru} | {ping}ms"

        # Вставляем в ссылку
        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_configs.append(final_link)
        
        try:
            print(f"[{s['category']}] {new_remark} (ISP: {s['info'].get('org', 'Unknown')})")
        except:
            pass

    # Save
    result_text = "\n".join(result_configs)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(final_list)} servers.")

if __name__ == "__main__":
    main()
