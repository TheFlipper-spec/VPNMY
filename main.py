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
import random
import os
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt", 
    "https://github.com/LalatinaHub/Mineral/raw/refs/heads/master/result/nodes",
    "https://raw.githubusercontent.com/mheidari98/.proxy/refs/heads/main/vless",
    "https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/26.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 1.0 
OUTPUT_FILE = 'FL1PVPN'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 3

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания'
}

TIER_1_PLATINUM = ['FI', 'EE', 'RU']
TIER_2_GOLD = ['LV', 'LT', 'PL', 'KZ', 'BY', 'UA']
TIER_3_SILVER = ['SE', 'DE', 'NL', 'AT', 'CZ', 'BG', 'RO', 'NO', 'TR', 'DK', 'GB', 'FR', 'IT', 'ES']

CDN_ISPS = [
    'cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 
    'fastly', 'akamai', 'cdn77', 'g-core', 'alibaba', 'tencent',
    'edgecenter', 'servers.com', 'digitalocean', 'vultr'
]

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        print("📥 Скачивание базы GeoIP (MMDB)...")
        try:
            r = requests.get(MMDB_URL, stream=True)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                print("✅ База успешно скачана.")
            else:
                print("❌ Ошибка скачивания базы.")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
    except:
        pass

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_country_local(ip):
    if not geo_reader: return 'XX'
    try:
        response = geo_reader.country(ip)
        return response.country.iso_code
    except:
        return 'XX'

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
            
            flow_val = params.get('flow', [''])[0].lower()
            is_reality = (security == 'reality')
            is_vision = ('vision' in flow_val)
            is_pure = (security == 'none' or security == 'tls') and not is_reality
            
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str,
                "original_remark": original_remark,
                "latency": 9999,
                "jitter": 0,
                "final_score": 9999,
                "info": {},
                "transport": transport, 
                "security": security,
                "is_reality": is_reality,
                "is_vision": is_vision, 
                "is_pure": is_pure, 
                "source_type": source_type,
                "tier_rank": 99
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

def calculate_tier_rank(country_code, ping):
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
    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    
    server['latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code, 'org': 'Unknown', 'isp': 'Unknown'}
    
    is_fake = False
    avg_ping = server['latency']
    if code in ['RU', 'KZ', 'UA', 'BY'] and avg_ping < 90: is_fake = True
    elif code in ['FI', 'EE', 'LV', 'LT', 'SE'] and avg_ping < 90: is_fake = True 
    elif code in ['DE', 'NL', 'FR', 'IT', 'GB'] and avg_ping < 25: is_fake = True
    elif avg_ping < 3 and code not in ['US', 'CA']: is_fake = True

    if is_fake: return None

    # --- КАТЕГОРИИ V41 ---
    is_warp_candidate = False
    rem = server['original_remark'].lower()
    
    if 'warp' in rem or 'cloudflare' in rem or 'clash' in rem: 
        is_warp_candidate = True
    if server['transport'] in ['ws', 'grpc']: is_warp_candidate = True
    
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp_candidate:
        server['category'] = 'WARP'
    else:
        server['category'] = 'UNIVERSAL'

    server['tier_rank'] = calculate_tier_rank(code, avg_ping)
    return server

def stress_test_server(server):
    pings = []
    for _ in range(5):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.2) 
    
    if len(pings) < 4: 
        return 9999, 9999, [] 
        
    avg_ping = statistics.mean(pings)
    try:
        jitter = statistics.stdev(pings)
    except:
        jitter = 0
    return avg_ping, jitter, pings

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: 
        print(f"   ⚠️ Нет кандидатов для {title}")
        return []
    
    filtered = candidates
    
    if mode == "gaming":
        # Игры: Приоритет PURE, но берем и аккуратный Reality
        pure_strict = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
        if pure_strict:
            filtered = pure_strict
        else:
            filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

    elif mode == "whitelist":
        only_ru = [c for c in candidates if c['info'].get('countryCode') == 'RU']
        if only_ru:
            print(f"   ✅ Найдены RU сервера для Whitelist ({len(only_ru)} шт).")
            filtered = only_ru
        else:
            return []

    elif mode == "warp":
        filtered = candidates

    elif mode == "universal":
        filtered = candidates

    if not filtered: return []
    
    finalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:12]
    
    print(f"\n🏟️ {title} - НАЧАЛО ({len(finalists)} финалистов)")
    print(f"   {'Страна':<10} | {'TYPE':<8} | {'Тир':<4} | {'Пинг (GH)':<10} | {'СЧЕТ':<6}")
    print("-" * 75)
    
    scored_results = []
    
    for f in finalists:
        avg, jitter, raw_pings = stress_test_server(f)
        
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     
        elif f['tier_rank'] == 2: tier_penalty = 20  
        elif f['tier_rank'] == 3: tier_penalty = 60  
        else: tier_penalty = 999
            
        type_penalty = 0
        
        if mode == "gaming":
            if f['is_pure']: type_penalty = 0
            elif f['is_reality']: type_penalty = 50 
            else: type_penalty = 200
            
        elif mode == "universal":
            if f['is_reality']: type_penalty = 0     
            elif f['is_pure']: type_penalty = 20     
            elif f['is_vision']: type_penalty = 100  
        
        elif mode == "warp":
            # --- НОВОЕ ПРАВИЛО WARP ---
            # Приоритет WS/GRPC (это признаки CDN/Cloudflare)
            # Штрафуем TCP/Reality, потому что они редко бывают WARP-ом
            is_ws_grpc = f['transport'] in ['ws', 'grpc']
            if is_ws_grpc:
                type_penalty = 0  # Идеально для WARP
            else:
                type_penalty = 1000 # Почти бан для обычного TCP
        
        score = avg + (jitter * 3) + tier_penalty + type_penalty
        
        code = f['info'].get('countryCode')
        rank = f['tier_rank']
        srv_type = "PURE" if f['is_pure'] else ("VIS" if f['is_vision'] else "REAL")
        
        # Добавляем инфо о транспорте в лог
        transp = f['transport'].upper()
        
        ping_str = f"{int(avg)}"
        print(f"   {code:<10} | {transp:<5} {srv_type:<4} | {rank:<4} | {ping_str:<10} | {int(score):<6}")
             
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['final_score'] = score
        scored_results.append(f)
        
    scored_results.sort(key=lambda x: x['final_score'])
    
    # --- ЛОГИКА РАЗНООБРАЗИЯ (DIVERSITY) ---
    # Не даем одной стране занять все места (кроме Whitelist)
    final_winners = []
    used_countries = []
    
    if mode == "whitelist":
        final_winners = scored_results[:winners_needed]
    else:
        for s in scored_results:
            code = s['info'].get('countryCode')
            # Если страна уже есть в победителях - пропускаем (если есть другие варианты)
            if code in used_countries and len(final_winners) < winners_needed:
                # Но если вариантов мало, берем что есть
                continue
            
            final_winners.append(s)
            used_countries.append(code)
            
            if len(final_winners) >= winners_needed:
                break
        
        # Если после фильтрации не набрали нужное кол-во, добиваем остатками
        if len(final_winners) < winners_needed:
            remaining = [s for s in scored_results if s not in final_winners]
            final_winners.extend(remaining[:winners_needed - len(final_winners)])

    print(f"🏆 ПОБЕДИТЕЛИ {title}: {[w['info'].get('countryCode') for w in final_winners]}")
    return final_winners

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
    print("--- ЗАПУСК V41 (DIVERSITY & WARP FIX) ---")
    
    download_mmdb()
    init_geoip()
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    if not servers_to_check: exit(1)

    print(f"\n🔍 Первичная проверка {len(servers_to_check)} серверов...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_universal = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []

    # 1. GAME SERVER
    game_winners = run_tournament(bucket_universal, TARGET_GAME, title="GAME CUP", mode="gaming")
    if game_winners:
        champion = copy.deepcopy(game_winners[0])
        champion['category'] = 'GAMING'
        final_list.append(champion)
        bucket_universal = [s for s in bucket_universal if s['ip'] != champion['ip'] or s['port'] != champion['port']]

    # 2. UNIVERSAL
    universal_winners = run_tournament(bucket_universal, TARGET_UNIVERSAL, title="UNIVERSAL CUP", mode="universal")
    final_list.extend(universal_winners)

    # 3. WARP
    warp_winners = run_tournament(bucket_warp, TARGET_WARP, title="WARP CUP", mode="warp")
    final_list.extend(warp_winners)

    # 4. WHITELIST
    wl_winners = run_tournament(bucket_whitelist, TARGET_WHITELIST, title="WHITELIST CUP", mode="whitelist")
    final_list.extend(wl_winners)

    print("\n--- СБОРКА ПОДПИСКИ ---")
    
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    info_remark = f"📅 Обновлено: {msk_now.strftime('%H:%M')} | След: {next_update.strftime('%H:%M')}"
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(info_remark)}"
    
    result_links = [info_link]

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
        
        raw_ping = s['latency']
        visual_ping = estimate_ping_for_user(raw_ping, code)
        
        new_remark = ""
        
        if s['category'] == 'GAMING':
            new_remark = f"🎮 GAME SERVER | {country_ru} | ~{visual_ping}ms"

        elif s['category'] == 'WHITELIST':
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | ~{visual_ping}ms"
            
        elif s['category'] == 'WARP':
            new_remark = f"🌀 {flag} {country_ru} WARP | ~{visual_ping}ms"
            
        else:
            isp_lower = (s['info'].get('isp', '')).lower()
            vps_tag = ""
            if any(v in isp_lower for v in ['hetzner', 'aeza', 'm247', 'stark']):
                vps_tag = " (VPS)"
            
            new_remark = f"⚡ {flag} {country_ru}{vps_tag} | ~{visual_ping}ms"

        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_links.append(final_link)
        
        print(f"[{s['category']}] {new_remark}")

    result_text = "\n".join(result_links)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(result_links)} links.")

if __name__ == "__main__":
    main()
