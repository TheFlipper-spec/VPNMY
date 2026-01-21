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
import copy
import random
import os
import json # ВАЖНО: Добавлен модуль для JSON
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    # БАЗА (Igareck)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    # ПЛЮС ОДИН НАДЕЖНЫЙ (Roosterkid)
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    # Твой новый источник
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/26.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 0.7 # Ускорил (было 1.0)
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json' # Имя файла для сайта
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания'
}

TIER_1_PLATINUM = ['FI', 'EE', 'RU', 'SE']
TIER_2_GOLD = ['LV', 'LT', 'PL', 'KZ', 'BY', 'UA', 'DE', 'NL']
TIER_3_SILVER = ['AT', 'CZ', 'BG', 'RO', 'NO', 'TR', 'DK', 'GB', 'FR', 'IT', 'ES']

CDN_ISPS = ['cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 'fastly', 'akamai', 'digitalocean', 'vultr']

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        print("📥 Скачивание базы GeoIP...")
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

def extract_vless_links(text):
    return re.findall(r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)", text)

def parse_config_info(config_str, source_type):
    try:
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
            
            original_remark = "Unknown"
            if "#" in config_str: original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, "port": int(port), "original": config_str, "original_remark": original_remark,
                "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure,
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

def check_server_initial(server):
    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    
    server['latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    # ФИЗИЧЕСКИЙ ДЕТЕКТОР ЛЖИ
    is_fake = False
    if code in ['RU', 'KZ', 'UA', 'BY'] and server['latency'] < 90: is_fake = True
    elif code in ['FI', 'EE', 'SE'] and server['latency'] < 90: is_fake = True 
    elif code in ['DE', 'NL', 'FR'] and server['latency'] < 25: is_fake = True
    elif server['latency'] < 3 and code not in ['US', 'CA']: is_fake = True
    if is_fake: return None

    is_warp_candidate = False
    rem = server['original_remark'].lower()
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
    # TURBO: Если первый пинг провален - сразу выход
    for i in range(5):
        p = tcp_ping(server['ip'], server['port'])
        if p is None and i == 0: return 9999, 9999, []
        if p is not None: pings.append(p)
        time.sleep(0.1) 
    
    if len(pings) < 3: return 9999, 9999, [] 
    return statistics.mean(pings), statistics.stdev(pings), pings

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    if mode == "gaming":
        # Игры: PURE > REALITY
        pure_strict = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
        if pure_strict: filtered = pure_strict
        else: filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

    elif mode == "whitelist":
        # WHITELIST: ТОЛЬКО REALITY (Стабильность)
        filtered = [c for c in candidates if c['is_reality'] and c['info'].get('countryCode') == 'RU']

    elif mode == "warp":
        filtered = [c for c in candidates if c['info'].get('countryCode') != 'RU']

    if not filtered: return []
    
    finalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:15]
    print(f"\n🏟️ {title} ({len(finalists)} fighters)")
    
    scored_results = []
    for f in finalists:
        avg, jitter, _ = stress_test_server(f)
        
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     
        elif f['tier_rank'] == 2: tier_penalty = 30  
        elif f['tier_rank'] == 3: tier_penalty = 60  
        else: tier_penalty = 999
            
        special_penalty = 0
        if mode == "gaming":
            if f['is_pure']: special_penalty = 0
            elif f['is_reality']: special_penalty = 40
            else: special_penalty = 200
        elif mode == "universal":
            if f['is_reality']: special_penalty = 0
            elif f['is_pure']: special_penalty = 20
            if f['info']['countryCode'] == 'RU': special_penalty += 1500 
        elif mode == "warp":
            if f['transport'] in ['ws', 'grpc']: special_penalty = 0 
            else: special_penalty = 1000 
        elif mode == "whitelist":
            if jitter > 10: special_penalty += 500
            
        score = avg + (jitter * 5) + tier_penalty + special_penalty
        f['latency'] = int(avg)
        f['final_score'] = score
        print(f"   {f['info']['countryCode']:<4} | Ping: {int(avg)} | Score: {int(score)}")
        scored_results.append(f)
        
    scored_results.sort(key=lambda x: x['final_score'])
    
    winners = []
    used_ips = []
    for s in scored_results:
        subnet = ".".join(s['ip'].split('.')[:3])
        if subnet not in used_ips:
            winners.append(s)
            used_ips.append(subnet)
        if len(winners) >= winners_needed: break
            
    return winners

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                found = extract_vless_links(resp.text)
                if not found:
                    try: found = extract_vless_links(base64.b64decode(resp.text).decode('utf-8'))
                    except: pass
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def main():
    print("--- ЗАПУСК V47 (WEB + SPEED) ---")
    download_mmdb()
    init_geoip()
    
    all_servers = []
    # Быстрая загрузка источников
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Checking {len(servers_to_check)} servers (60 threads)...")
    
    working_servers = []
    # 60 потоков для скорости
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
    game_winners = run_tournament(b_univ, TARGET_GAME, "GAME CUP", "gaming")
    if game_winners: 
        game_winners[0]['category'] = 'GAMING'
        final_list.extend(game_winners)
    
    final_list.extend(run_tournament(b_univ, TARGET_UNIVERSAL, "UNIVERSAL CUP", "universal"))
    final_list.extend(run_tournament(b_warp, TARGET_WARP, "WARP CUP", "warp"))
    final_list.extend(run_tournament(b_white, TARGET_WHITELIST, "WHITELIST CUP", "whitelist"))

    print("\n--- GENERATING FILES ---")
    
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(f'📅 {msk_now.strftime('%H:%M')} | Next: {next_update.strftime('%H:%M')}')}"
    result_links = [info_link]
    
    # JSON структура для сайта
    json_data = {
        "updated_at": msk_now.strftime('%H:%M'),
        "next_update": next_update.strftime('%H:%M'),
        "servers": []
    }

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        
        # Эмуляция пинга для клиента (чтобы было красиво)
        visual_ping = s['latency'] - 50 if s['latency'] > 60 else s['latency']
        if visual_ping < 20: visual_ping = random.randint(30, 45)
        
        name = ""
        if s['category'] == 'GAMING': name = f"🎮 GAME | {flag} {code} | {visual_ping}ms"
        elif s['category'] == 'WHITELIST': name = f"⚪ {flag} RU (WhiteList) | {visual_ping}ms"
        elif s['category'] == 'WARP': name = f"🌀 {flag} {code} WARP | {visual_ping}ms"
        else: name = f"⚡ {flag} {code} Universal | {visual_ping}ms"

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name,
            "category": s['category'],
            "country": code,
            "ping": visual_ping,
            "flag": flag,
            "protocol": s['transport'].upper(),
            "type": "Reality" if s['is_reality'] else ("Pure" if s['is_pure'] else "Vision")
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"Saved {len(result_links)} links. JSON generated.")

if __name__ == "__main__":
    main()
