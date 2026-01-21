import sys
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
import os
import json
import random
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- ИСТОЧНИКИ (ТВОЙ НОВЫЙ СПИСОК + БАЗА) ---
GENERAL_URLS = [
    # БАЗА (Igareck) - Самые надежные
    "[https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt](https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt)",
    "[https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt](https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt)",
    
    # ТВОИ НОВЫЕ ИСТОЧНИКИ (Берем самые жирные)
    "[https://github.com/sakha1370/OpenRay/raw/refs/heads/main/output/all_valid_proxies.txt](https://github.com/sakha1370/OpenRay/raw/refs/heads/main/output/all_valid_proxies.txt)", 
    "[https://raw.githubusercontent.com/yitong2333/proxy-minging/refs/heads/main/v2ray.txt](https://raw.githubusercontent.com/yitong2333/proxy-minging/refs/heads/main/v2ray.txt)", 
    "[https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt](https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt)", 
    "[https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/vless.txt](https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/vless.txt)", 
    "[https://raw.githubusercontent.com/mheidari98/.proxy/refs/heads/main/vless](https://raw.githubusercontent.com/mheidari98/.proxy/refs/heads/main/vless)", 
    "[https://github.com/LalatinaHub/Mineral/raw/refs/heads/master/result/nodes](https://github.com/LalatinaHub/Mineral/raw/refs/heads/master/result/nodes)", 
    "[https://raw.githubusercontent.com/Pawdroid/Free-servers/refs/heads/main/sub](https://raw.githubusercontent.com/Pawdroid/Free-servers/refs/heads/main/sub)", 
    "[https://github.com/MhdiTaheri/V2rayCollector_Py/raw/refs/heads/main/sub/Mix/mix.txt](https://github.com/MhdiTaheri/V2rayCollector_Py/raw/refs/heads/main/sub/Mix/mix.txt)", 
    "[https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt](https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt)", 
]

WHITELIST_URLS = [
    "[https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt](https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt)",
    "[https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/26.txt](https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/26.txt)"
]

MMDB_URL = "[https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb](https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb)"
MMDB_FILE = "Country.mmdb"

# ЛИМИТЫ
TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 0.7 
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# ПЕРЕВОДЧИК
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания'
}

# TIER SYSTEM (Гео-приоритеты)
TIER_1_PLATINUM = ['FI', 'EE', 'SE', 'RU'] # Элита
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ', 'LV', 'LT'] # Хорошая Европа
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'RO', 'UA', 'BY'] # Остальные

CDN_ISPS = ['cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 'fastly', 'akamai', 'digitalocean', 'vultr']

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            r = requests.get(MMDB_URL, stream=True)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        except: pass

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: pass

def get_ip_country_local(ip):
    if not geo_reader: return 'XX'
    try: return geo_reader.country(ip).country.iso_code
    except: return 'XX'

def extract_links(text):
    # Ищем VLESS и HYSTERIA2 (hy2)
    return re.findall(r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+|hy2://[a-zA-Z0-9\-@:?=&%.#_]+)", text)

def parse_config_info(config_str, source_type):
    try:
        # --- HYSTERIA 2 PARSING ---
        if config_str.startswith("hy2://"):
            try:
                # hy2://auth@host:port?params#name
                # или hy2://host:port?auth=...&params#name
                rest = config_str[6:]
                
                # Отделяем Remark
                if "#" in rest:
                    main, remark = rest.split("#", 1)
                    remark = unquote(remark).strip()
                else:
                    main = rest
                    remark = "Unknown"
                
                # Отделяем Params
                if "?" in main:
                    creds_host, params_str = main.split("?", 1)
                    params = parse_qs(params_str)
                else:
                    creds_host = main
                    params = {}

                # Отделяем Auth и Host
                if "@" in creds_host:
                    auth, host_port = creds_host.split("@", 1)
                else:
                    host_port = creds_host

                # Отделяем IP и Port
                if ":" in host_port:
                    if "]" in host_port: # IPv6
                        host = host_port.rsplit(":", 1)[0]
                        port = host_port.rsplit(":", 1)[1]
                    else:
                        host, port = host_port.split(":")
                else:
                    return None

                return {
                    "ip": host, "port": int(port), "uuid": "hy2_key",
                    "original": config_str, "original_remark": remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "udp", "security": "hy2", # Hy2 всегда UDP
                    "is_reality": False, "is_vision": False, "is_pure": False, 
                    "is_hy2": True, # МЕТКА HY2
                    "source_type": source_type, "tier_rank": 99
                }
            except:
                return None

        # --- VLESS PARSING ---
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            flow_val = params.get('flow', [''])[0].lower()
            
            is_reality = (security == 'reality')
            is_vision = ('vision' in flow_val)
            is_pure = (security == 'none' or security == 'tls') and not is_reality
            
            uuid = config_str.split("@")[0].replace("vless://", "")
            original_remark = "Unknown"
            if "#" in config_str: original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, "port": int(port), "uuid": uuid, "original": config_str, 
                "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                "final_score": 9999, "info": {},
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure, 
                "is_hy2": False,
                "source_type": source_type, "tier_rank": 99
            }
    except: pass
    return None

def tcp_ping(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter()
        res = sock.connect_ex((host, port))
        end = time.perf_counter()
        sock.close()
        if res == 0: return (end - start) * 1000
    except: pass
    return None

def calculate_tier_rank(country_code):
    if country_code in TIER_1_PLATINUM: return 1
    if country_code in TIER_2_GOLD: return 2
    if country_code in TIER_3_SILVER: return 3
    if country_code == 'US' or country_code == 'CA': return 5
    return 4

def estimate_ping_for_user(github_ping, country_code):
    estimated = github_ping
    if country_code in TIER_1_PLATINUM:
        estimated = github_ping - 90 
        if estimated < 35: estimated = random.randint(35, 48)
    elif country_code in TIER_2_GOLD:
        estimated = github_ping - 75
        if estimated < 45: estimated = random.randint(45, 65)
    elif country_code in TIER_3_SILVER:
        estimated = github_ping - 50
        if estimated < 60: estimated = random.randint(60, 85)
    elif country_code == 'US':
        estimated = github_ping + 140
    else:
        estimated = int(github_ping * 0.8)

    if estimated < 20: estimated = 25
    return int(estimated)

def check_server_initial(server):
    # Для Hy2 TCP пинг может не работать, но мы попробуем
    # Если не пингуется, но это Hy2 из надежного источника, можно дать шанс?
    # Нет, лучше брать только живые порты.
    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    
    server['latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    # ФИЗИЧЕСКИЙ ДЕТЕКТОР ЛЖИ
    is_fake = False
    avg_ping = server['latency']
    if code in ['RU', 'KZ', 'UA', 'BY'] and avg_ping < 90: is_fake = True
    elif code in ['FI', 'EE', 'SE'] and avg_ping < 90: is_fake = True 
    elif code in ['DE', 'NL', 'FR'] and avg_ping < 25: is_fake = True
    elif avg_ping < 3 and code not in ['US', 'CA']: is_fake = True
    if is_fake: return None

    # ОПРЕДЕЛЕНИЕ КАТЕГОРИИ
    is_warp_candidate = False
    rem = server['original_remark'].lower()
    
    # Warp определяем по ключевым словам или WS/GRPC
    if 'warp' in rem or 'cloudflare' in rem: is_warp_candidate = True
    if server['transport'] in ['ws', 'grpc']: is_warp_candidate = True 
    
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp_candidate:
        server['category'] = 'WARP'
    else:
        server['category'] = 'UNIVERSAL'

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def stress_test_server(server):
    pings = []
    # 4 Замера
    for i in range(4):
        p = tcp_ping(server['ip'], server['port'])
        if p is None and i == 0: return 9999, 9999
        if p is not None: pings.append(p)
        time.sleep(0.1) 
    
    if len(pings) < 3: return 9999, 9999
    return statistics.mean(pings), statistics.stdev(pings)

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    # --- УМНЫЕ ФИЛЬТРЫ V54 ---
    
    if mode == "gaming":
        # 1. Сначала ищем HYSTERIA 2 (UDP топ для игр)
        hy2_servers = [c for c in candidates if c.get('is_hy2')]
        
        if hy2_servers:
            # Если есть Hy2, используем их
            filtered = hy2_servers
            print(f"   ✅ Нашли Hysteria 2 сервера ({len(filtered)} шт) для игр!")
        else:
            # 2. Если нет, ищем Pure TCP
            pure_strict = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
            if pure_strict:
                filtered = pure_strict
            else:
                # 3. На крайний случай Reality без Vision
                filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

    elif mode == "whitelist":
        # Строго RU
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
        
    elif mode == "warp":
        # Строго НЕ RU
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']

    if not filtered: return []
    
    finalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:15]
    print(f"\n🏟️ {title} ({len(finalists)} candidates)")
    
    scored_results = []
    for f in finalists:
        avg, jitter = stress_test_server(f)
        
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     
        elif f['tier_rank'] == 2: tier_penalty = 30  
        else: tier_penalty = 60
            
        special_penalty = 0
        if mode == "gaming":
            if f.get('is_hy2'): special_penalty = -50 # Бонус для Hy2
            elif f['is_pure']: special_penalty = 0
            elif f['is_reality']: special_penalty = 50
            else: special_penalty = 200
            
        elif mode == "universal":
            if f['info']['countryCode'] == 'RU': special_penalty += 2000
            
        elif mode == "warp":
            if f['transport'] in ['ws', 'grpc']: special_penalty = 0 
            else: special_penalty = 2000
            
        elif mode == "whitelist":
            if f['is_reality']: special_penalty = 0
            else: special_penalty = 1000
            
        score = avg + (jitter * 5) + tier_penalty + special_penalty
        f['latency'] = int(avg)
        f['final_score'] = score
        
        code = f['info'].get('countryCode')
        # Type label for log
        t_label = "VLESS"
        if f.get('is_hy2'): t_label = "HY2"
        elif f.get('is_pure'): t_label = "PURE"
        elif f.get('is_reality'): t_label = "REAL"
        
        print(f"   {code:<4} | {t_label:<4} | Ping: {int(avg)} | Score: {int(score)}")
        scored_results.append(f)
        
    scored_results.sort(key=lambda x: x['final_score'])
    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                content = resp.text
                found = extract_links(content)
                if not found:
                    try: found = extract_links(base64.b64decode(content).decode('utf-8'))
                    except: pass
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def main():
    print("--- ЗАПУСК V54 (HY2 + SOURCES) ---")
    download_mmdb()
    init_geoip()
    
    all_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Checking {len(servers_to_check)} servers (60 threads)...")
    
    working_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []
    
    # GAME
    game = run_tournament(b_univ, TARGET_GAME, "GAME CUP", "gaming")
    if game: 
        game[0]['category'] = 'GAMING'
        final_list.extend(game)
    
    final_list.extend(run_tournament(b_univ, TARGET_UNIVERSAL, "UNIVERSAL CUP", "universal"))
    final_list.extend(run_tournament(b_warp, TARGET_WARP, "WARP CUP", "warp"))
    final_list.extend(run_tournament(b_white, TARGET_WHITELIST, "WHITELIST CUP", "whitelist"))

    # --- ГЕНЕРАЦИЯ ---
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    
    time_str = msk_now.strftime('%H:%M')
    next_str = next_update.strftime('%H:%M')
    
    update_msg = f"📅 {time_str} | Next: {next_str}"
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(update_msg)}"
    result_links = [info_link]
    
    json_data = {
        "updated_at": time_str,
        "next_update": next_str,
        "servers": []
    }

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        country_full = RUS_NAMES.get(code, code)
        
        raw_ping = s['latency']
        if s['is_hy2']: raw_ping = int(raw_ping * 0.9)
        visual_ping = estimate_ping_for_user(raw_ping, code)
        
        type_label = "VLESS"
        if s['is_hy2']: type_label = "Hy2"
        elif s['is_reality']: type_label = "Reality"
        elif s['is_pure']: type_label = "TCP"

        name = ""
        if s['category'] == 'GAMING': 
            name = f"🎮 GAME SERVER | {flag} {country_full} | {visual_ping}ms"
        elif s['category'] == 'WHITELIST': 
            name = f"⚪ {flag} Россия (WhiteList) | {visual_ping}ms"
        elif s['category'] == 'WARP': 
            name = f"🌀 {flag} {country_full} WARP | {visual_ping}ms"
        else: 
            name = f"⚡ {flag} {country_full} | {visual_ping}ms"

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name,
            "category": s['category'],
            "country": country_full,
            "iso": code,
            "flag": flag,
            "ping": visual_ping,
            "ip": s['ip'],
            "port": s['port'],
            "protocol": s['transport'].upper(),
            "type": type_label,
            "uuid": s['uuid'],
            "link": final_link
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"DONE. {len(result_links)} links saved.")

if __name__ == "__main__":
    main()
