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
TARGET_GAME = 1       
TARGET_REALITY = 3    
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 1.5
OUTPUT_FILE = 'FL1PVPN'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 3

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

# === TIER SYSTEM V30 (Strict Geo) ===
TIER_1_PLATINUM = ['FI', 'EE', 'RU']
TIER_2_GOLD = ['LV', 'LT', 'PL', 'KZ', 'BY', 'UA']
TIER_3_SILVER = ['SE', 'DE', 'NL', 'AT', 'CZ', 'BG', 'RO', 'NO', 'TR', 'DK', 'GB', 'FR', 'IT', 'ES']

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
            
            # --- DETECT ANY FLOW ---
            flow_val = params.get('flow', [''])[0].lower()
            # is_vision - это конкретно Vision
            is_vision = 'vision' in flow_val
            # has_flow - это вообще наличие flow (RAW)
            has_flow = len(flow_val) > 0
            
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
                "is_vision": is_vision, 
                "has_flow": has_flow, # Новый флаг для полной чистоты
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

def calculate_tier_rank(server):
    code = server['info'].get('countryCode', 'XX')
    if code in TIER_1_PLATINUM: return 1
    if code in TIER_2_GOLD: return 2
    if code in TIER_3_SILVER: return 3
    if code == 'US' or code == 'CA': return 5
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
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    ip_data = get_ip_info_retry(server['ip'])
    if not ip_data:
        if server['source_type'] == 'whitelist':
             ip_data = {'countryCode': 'RU', 'org': 'Unknown', 'isp': 'Unknown'}
        else:
             return None 
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    # ФИЗИЧЕСКИЙ ДЕТЕКТОР ЛЖИ
    is_fake = False
    if code in ['RU', 'KZ', 'UA', 'BY'] and avg_ping < 90: is_fake = True
    elif code in ['FI', 'EE', 'LV', 'LT', 'SE'] and avg_ping < 90: is_fake = True 
    elif code in ['DE', 'NL', 'FR', 'IT'] and avg_ping < 30: is_fake = True
    elif avg_ping < 3 and code not in ['US', 'CA']: is_fake = True

    if is_fake: return None

    is_warp_cdn = False
    if server['transport'] in ['ws', 'grpc']: is_warp_cdn = True
    if any(cdn in org_str for cdn in CDN_ISPS): is_warp_cdn = True
    if server['security'] != 'reality': is_warp_cdn = True

    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp_cdn:
        server['category'] = 'WARP'
    else:
        server['category'] = 'REALITY'

    server['tier_rank'] = calculate_tier_rank(server)
    return server

def stress_test_server(server):
    pings = []
    for _ in range(5):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.12)
    
    if len(pings) < 4: 
        return 9999, 9999, [] 
        
    avg_ping = statistics.mean(pings)
    try:
        jitter = statistics.stdev(pings)
    except:
        jitter = 0
    return avg_ping, jitter, pings

def run_tournament(candidates, winners_needed, title="TOURNAMENT", is_gaming=False):
    if not candidates: 
        print(f"   ⚠️ Нет кандидатов для {title}")
        return []
    
    filtered = candidates
    
    # 1. СТРОГИЙ ФИЛЬТР: ТОЛЬКО PURE TCP ДЛЯ ИГР
    if is_gaming:
        # Ищем сервера, у которых flow вообще ПУСТОЙ (has_flow == False)
        # И которые входят в Тир 1, 2 или 3
        pure_tcp = [c for c in candidates if not c.get('has_flow', False) and c['tier_rank'] <= 3]
        
        if len(pure_tcp) >= 3:
            print(f"   ✅ Найдены ИДЕАЛЬНЫЕ (PURE TCP) сервера ({len(pure_tcp)} шт).")
            filtered = pure_tcp
        else:
            # Если идеальных нет, пробуем хотя бы без Vision
            print(f"   ⚠️ Мало Pure TCP. Ищем без Vision...")
            no_vision = [c for c in candidates if not c.get('is_vision', False) and c['tier_rank'] <= 3]
            if no_vision:
                 filtered = no_vision
            else:
                 print(f"   ⚠️ Придется брать RAW с огромным штрафом.")
                 filtered = [c for c in candidates if c['tier_rank'] <= 3]
    
    if not filtered: return []
    
    finalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:12]
    
    print(f"\n🏟️ {title} - НАЧАЛО ({len(finalists)} финалистов)")
    print(f"   {'Страна':<10} | {'RAW?':<6} | {'Тир':<4} | {'Пинг (GH)':<10} | {'СЧЕТ':<6}")
    print("-" * 75)
    
    scored_results = []
    
    for f in finalists:
        avg, jitter, raw_pings = stress_test_server(f)
        
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     
        elif f['tier_rank'] == 2: tier_penalty = 20  
        elif f['tier_rank'] == 3: tier_penalty = 60  
        else: tier_penalty = 999
            
        raw_penalty = 0
        # Если все-таки пролез RAW сервер (has_flow=True), даем ему штраф
        if f.get('has_flow', False) and is_gaming:
            raw_penalty = 500 # Смертельный штраф
        
        score = avg + (jitter * 3) + tier_penalty + raw_penalty
        
        code = f['info'].get('countryCode')
        rank = f['tier_rank']
        # Логируем, есть ли flow
        is_raw = "YES" if f.get('has_flow') else "NO"
        
        ping_str = f"{int(avg)}"
        print(f"   {code:<10} | {is_raw:<6} | {rank:<4} | {ping_str:<10} | {int(score):<6}")
             
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['final_score'] = score
        scored_results.append(f)
        
    scored_results.sort(key=lambda x: x['final_score'])
    
    winners = scored_results[:winners_needed]
    print(f"🏆 ПОБЕДИТЕЛИ {title}: {[w['info'].get('countryCode') for w in winners]}")
    
    return winners

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
    print("--- ЗАПУСК V30 (PURE TCP ENFORCER) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    if not servers_to_check: exit(1)

    print(f"\n🔍 Первичная проверка {len(servers_to_check)} серверов...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []

    # 1. GAME SERVER
    game_winners = run_tournament(bucket_reality, TARGET_GAME, title="GAME CUP", is_gaming=True)
    if game_winners:
        champion = copy.deepcopy(game_winners[0])
        champion['category'] = 'GAMING'
        final_list.append(champion)
        bucket_reality = [s for s in bucket_reality if s['ip'] != champion['ip'] or s['port'] != champion['port']]

    # 2. TOP REALITY
    reality_winners = run_tournament(bucket_reality, TARGET_REALITY, title="REALITY CUP", is_gaming=False)
    final_list.extend(reality_winners)

    # 3. TOP WARP
    warp_winners = run_tournament(bucket_warp, TARGET_WARP, title="WARP CUP", is_gaming=False)
    final_list.extend(warp_winners)

    # 4. TOP WHITELIST
    wl_winners = run_tournament(bucket_whitelist, TARGET_WHITELIST, title="WHITELIST CUP", is_gaming=False)
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
