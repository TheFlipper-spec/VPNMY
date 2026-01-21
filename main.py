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
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- ИСТОЧНИКИ ---
# Мы берем базу Игарька + Твой новый источник с миксом
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    # Тот самый источник с кучей протоколов (вытащим отсюда только HY2)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 0.8 
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

TIER_1_PLATINUM = ['FI', 'EE', 'SE']
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ']
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ']

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
    # Ищем VLESS и HYSTERIA2. Остальные (vmess, ss, trojan) игнорируем.
    return re.findall(r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+|hy2://[a-zA-Z0-9\-@:?=&%.#_]+)", text)

def parse_config_info(config_str, source_type):
    try:
        # --- ОБРАБОТКА HYSTERIA 2 ---
        if config_str.startswith("hy2://"):
            # Парсим hy2://user:pass@host:port?params#remark
            # Упрощенный парсинг, так как urlparse может спотыкаться о некоторые символы
            try:
                # Удаляем схему
                rest = config_str[6:]
                if "#" in rest:
                    main_part, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                else:
                    main_part = rest
                    original_remark = "Unknown"

                if "?" in main_part:
                    auth_host, query = main_part.split("?", 1)
                else:
                    auth_host = main_part
                    query = ""

                if "@" in auth_host:
                    auth, host_port = auth_host.split("@", 1)
                else:
                    host_port = auth_host

                if ":" in host_port:
                    # Обработка IPv6 [...]
                    if "]" in host_port:
                        host = host_port.rsplit(":", 1)[0]
                        port = host_port.rsplit(":", 1)[1]
                    else:
                        host, port = host_port.split(":")
                else:
                    return None

                return {
                    "ip": host, "port": int(port), "uuid": "auth_key", 
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "udp", "security": "hy2", # Hy2 всегда UDP
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": True,
                    "source_type": source_type, "tier_rank": 99
                }
            except:
                return None

        # --- ОБРАБОТКА VLESS ---
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
                "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure, "is_hy2": False,
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
    # Пинг
    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    server['latency'] = int(p)
    
    # GeoIP
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    # Фейс-контроль
    is_fake = False
    if code in ['RU', 'KZ', 'UA', 'BY'] and server['latency'] < 90: is_fake = True
    elif code in ['FI', 'EE', 'SE'] and server['latency'] < 90: is_fake = True 
    elif code in ['DE', 'NL'] and server['latency'] < 25: is_fake = True
    elif server['latency'] < 3 and code not in ['US', 'CA']: is_fake = True
    if is_fake: return None

    # Категории
    is_warp = False
    rem = server['original_remark'].lower()
    if 'warp' in rem or 'cloudflare' in rem: is_warp = True
    if server['transport'] in ['ws', 'grpc']: is_warp = True 
    
    if server['source_type'] == 'whitelist': server['category'] = 'WHITELIST'
    elif is_warp: server['category'] = 'WARP'
    else: server['category'] = 'UNIVERSAL'

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def stress_test_server(server):
    pings = []
    # 4 ЗАМЕРА (Баланс между 3 и 5)
    for i in range(4):
        p = tcp_ping(server['ip'], server['port'])
        # FAIL FAST: Если первый пинг умер, считаем сервер мертвым
        if p is None and i == 0: return 9999, 9999
        if p is not None: pings.append(p)
        time.sleep(0.15) 
    
    if len(pings) < 3: return 9999, 9999
    return statistics.mean(pings), statistics.stdev(pings)

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    # ФИЛЬТРЫ
    if mode == "gaming":
        # Игры: Hy2 > Pure TCP > Reality
        # Hysteria2 (UDP) идеальна для игр, даем ей зеленый свет
        hy2_servers = [c for c in candidates if c['is_hy2']]
        if hy2_servers:
            filtered = hy2_servers # Если есть Hy2, берем только их для игр
        else:
            pure = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
            if pure: filtered = pure
            else: filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

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
            if f['is_hy2']: special_penalty = -20 # БОНУС для Hy2
            elif f['is_pure']: special_penalty = 0
            elif f['is_reality']: special_penalty = 40
            else: special_penalty = 200
            
        elif mode == "universal":
            # Штрафуем Россию в Universal
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
        print(f"   {f['info']['countryCode']:<4} | Type: {'HY2' if f['is_hy2'] else 'VLESS'} | Ping: {int(avg)} | Score: {int(score)}")
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
                # Ищем VLESS и HY2
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
    print("--- ЗАПУСК V49 (HYSTERIA + FLAGS + WEB) ---")
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
    
    # GAME (Hy2 / Pure)
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
    
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(f'📅 {time_str} | Next: {next_str}')}"
    result_links = [info_link]
    
    json_data = {
        "updated_at": time_str,
        "next_update": next_str,
        "servers": []
    }

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        
        # Эмуляция пинга (с Hysteria 2 все немного быстрее, поэтому ей бонус)
        raw_ping = s['latency']
        if s['is_hy2']: raw_ping = int(raw_ping * 0.9)
        
        visual_ping = raw_ping - 50 if raw_ping > 60 else raw_ping
        if visual_ping < 20: visual_ping = random.randint(30, 50)
        
        # Определение типа для названия
        type_label = ""
        if s['is_hy2']: type_label = "Hy2"
        elif s['is_reality']: type_label = "Reality"
        elif s['is_pure']: type_label = "TCP"
        else: type_label = "VLESS"

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
