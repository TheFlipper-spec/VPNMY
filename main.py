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

# СТРОГИЕ ЛИМИТЫ
LIMIT_WHITELIST = 3   # Внизу
LIMIT_WARP = 5        # Максимум 5 WARP (если они качественные)
LIMIT_REALITY = 10    # Максимум 10 Реальных

TIMEOUT = 2.0          
OUTPUT_FILE = 'FL1PVPN'

# ПЕРЕВОДЧИК
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 
    'FI': 'Финляндия', 'RU': 'Россия', 'TR': 'Турция', 
    'GB': 'Великобритания', 'FR': 'Франция', 'SE': 'Швеция',
    'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония',
    'LV': 'Латвия', 'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур'
}

# СПИСОК "ГРЯЗНЫХ" ПРОВАЙДЕРОВ (ЭТО ТОЧНО WARP/CDN)
CDN_ISPS = [
    'cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 
    'digitalocean', 'fastly', 'akamai', 'cdn77', 'alibaba', 
    'tencent', 'huawei', 'hostinger', 'hetzner online gmbh', # Hetzner 50/50, но часто там прокси
    'ovh', 'choopa', 'vultr' 
    # Vultr и DO часто используются для VPN, но мы будем строги:
    # Если это хостинг - помечаем как WARP/VPS, а не "Домашний провайдер"
]
# Оставим Vultr и DigitalOcean как "Пограничные", но Cloudflare - точно бан.
STRICT_CDN = ['cloudflare', 'google', 'akamai', 'fastly', 'cdn77', 'g-core']

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_info_retry(ip):
    """Пытается узнать инфо об IP с повторными попытками"""
    for attempt in range(3):
        try:
            # Пауза зависит от попытки (чем больше неудач, тем дольше ждем)
            time.sleep(0.5 + attempt * 0.5) 
            url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,org,isp"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success':
                    return data
                else:
                    # Если API вернул fail (приватный IP), это тоже инфо
                    return {'status': 'fail', 'countryCode': 'XX', 'org': 'Private', 'isp': 'Private'}
            elif resp.status_code == 429:
                # Нас забанили по лимиту, ждем дольше
                time.sleep(2)
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

def check_server_sherlock(server):
    """Многоступенчатая проверка"""
    
    # 1. ПИНГ (3 раза)
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # 2. GEOIP & ISP (Самое важное)
    ip_data = get_ip_info_retry(server['ip'])
    
    if not ip_data:
        # Если API не ответил 3 раза - сервер мусор, выкидываем
        return None 
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    # 3. АНАЛИЗ (Real vs WARP)
    
    is_warp = False
    
    # Условие A: Пинг нереально низкий (<5)
    if avg_ping < 5: 
        is_warp = True
    
    # Условие B: Провайдер в списке CDN (Cloudflare и т.д.)
    if any(cdn in org_str for cdn in STRICT_CDN):
        is_warp = True
        
    # Условие C: Код страны XX (Private IP) - часто бывает у CDN
    if code == 'XX':
        is_warp = True

    # КАТЕГОРИИ
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp:
        server['category'] = 'WARP'
    else:
        # Если это не WL и не WARP - значит это Честный VPN
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
    print("--- ЗАПУСК V10 (SHERLOCK HOLMES) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())

    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers (SLOW & ACCURATE)...")
    working_servers = []
    
    # !!! ВАЖНО: Ставим всего 4 потока, чтобы API точно ответил и не забанил !!!
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(check_server_sherlock, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # Корзины
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    # Сортировка
    bucket_whitelist.sort(key=lambda x: x['latency'])
    bucket_reality.sort(key=lambda x: x['latency'])
    bucket_warp.sort(key=lambda x: x['latency'])

    # СБОРКА
    final_list = []
    final_list.extend(bucket_reality[:LIMIT_REALITY])
    final_list.extend(bucket_warp[:LIMIT_WARP])
    final_list.extend(bucket_whitelist[:LIMIT_WHITELIST])

    print("\n--- ИТОГОВЫЙ ОТЧЕТ ---")
    
    result_configs = []
    
    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        isp_name = s['info'].get('isp', 'Unknown')
        
        # Попытка спасти имя, если API вернул XX, но мы знаем, что это WARP
        if code == 'XX' and s['category'] == 'WARP':
            # Пытаемся вытащить из оригинального имени
            rem = s['original_remark'].lower()
            if "united states" in rem or "usa" in rem: code = 'US'
            elif "germany" in rem or "de" in rem: code = 'DE'
            elif "finland" in rem: code = 'FI'
            elif "netherlands" in rem: code = 'NL'
            else: code = 'XX' # Если не удалось спасти

        country_ru = RUS_NAMES.get(code, code)
        if code == 'XX': country_ru = "Глобал"

        flag = get_flag(code)
        ping = s['latency']
        
        new_remark = ""
        
        if s['category'] == 'WHITELIST':
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | {ping}ms"
            
        elif s['category'] == 'WARP':
            # Если WARP - пишем флаг, страну и WARP
            if code == 'XX': 
                new_remark = f"🌀 🌐 Cloudflare WARP | {ping}ms"
            else:
                new_remark = f"🌀 {flag} {country_ru} WARP | {ping}ms"
            
        else:
            # REALITY
            new_remark = f"⚡ {flag} {country_ru} | {ping}ms"

        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_configs.append(final_link)
        
        try:
            print(f"[{s['category']}] {country_ru} ({isp_name})")
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
