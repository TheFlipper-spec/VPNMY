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
import uuid 
import binascii 
import geoip2.database 
import subprocess
import tempfile
import random
import shutil
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- НАСТРОЙКИ ОТБОРА (V3.1 ULTIMATE + NEW SOURCES) ---
TARGET_GAME = 1       # Только 1 лучший для игр
TARGET_UNIVERSAL = 3  # Только 3 лучших для всего остального
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

# ТАЙМАУТЫ
TIMEOUT = 0.8           # Быстрый TCP чек (отсев мертвых)
REAL_TEST_TIMEOUT = 5.0 # Тайм-аут на каждое соединение в Xray

OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# ИСТОЧНИКИ (ОБНОВЛЕННЫЙ СПИСОК)
GENERAL_URLS = [
    # Goida (Надежный источник)
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/6.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/24.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",

    # Igareck (База для РФ)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",

    # MatinGhanbari (Один из лучших мировых агрегаторов)
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/normal/mix.txt",

    # Epodonios (Огромная база, обновляется каждые 10 мин)
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    
    # Barry-Far (Тоже отличный запасной вариант)
    "https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ'
}

# ПРИОРИТЕТЫ (TIER)
TIER_1_PLATINUM = ['FI', 'EE', 'SE', 'RU'] # RU тут только для Whitelist
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ']
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'AT']

geo_reader = None

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(MMDB_URL, stream=True, headers=headers, timeout=20)
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

def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '')
    s += '=' * (-len(s) % 4)
    try: return base64.urlsafe_b64decode(s).decode('utf-8', errors='ignore')
    except:
        try: return base64.b64decode(s).decode('utf-8', errors='ignore')
        except: return ""

def extract_links(text):
    regex = r"(vless://[a-zA-Z0-9\-\_\=\:\@\.\?\&\#\%]+|ss://[a-zA-Z0-9\-\_\=\:\@\.\#]+)"
    links = re.findall(regex, text)
    if len(links) < 2:
        decoded = safe_base64_decode(text)
        if decoded: links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_config_info(config_str, source_type):
    try:
        if config_str.startswith("ss://"):
            try:
                rest = config_str[5:]
                original_remark = "Unknown"
                if "#" in rest:
                    rest, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                
                if "@" in rest:
                    user_part, host_part = rest.split("@", 1)
                    try:
                        decoded_user = safe_base64_decode(user_part)
                        if decoded_user and ":" in decoded_user:
                            method, password = decoded_user.split(":", 1)
                        elif ":" in user_part:
                            method, password = user_part.split(":", 1)
                        else: return None 
                    except: return None
                else:
                    decoded = safe_base64_decode(rest)
                    if not decoded: return None
                    if "@" in decoded:
                        auth, host_part = decoded.split("@", 1)
                        if ":" in auth: method, password = auth.split(":", 1)
                        else: return None
                    else: return None

                if "]" in host_part:
                    host = host_part.rsplit(":", 1)[0]
                    port = host_port.rsplit(":", 1)[1]
                elif ":" in host_part:
                    host, port = host_part.split(":")
                else: return None

                return {
                    "ip": host, "port": int(port), "uuid": password,
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "tcp", "security": "ss", 
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": False, "is_ss": True,
                    "source_type": source_type, "tier_rank": 99, "parsed_params": {"method": method}
                }
            except: return None

        if config_str.startswith("vless://"):
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
                
                _uuid = config_str.split("@")[0].replace("vless://", "")
                original_remark = "Unknown"
                if "#" in config_str: original_remark = unquote(config_str.split("#")[-1]).strip()

                return {
                    "ip": host, "port": int(port), "uuid": _uuid, "original": config_str, 
                    "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                    "final_score": 9999, "info": {},
                    "transport": transport, "security": security,
                    "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure, "is_hy2": False, "is_ss": False,
                    "source_type": source_type, "tier_rank": 99, "parsed_params": params
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

def generate_xray_config(server, local_port):
    try:
        params = server['parsed_params']
        if server.get('is_ss', False):
            outbound = {
                "tag": "proxy", "protocol": "shadowsocks",
                "settings": {"servers": [{"address": server['ip'], "port": int(server['port']), "method": params.get('method', ''), "password": server['uuid'], "uot": True}]}
            }
        else:
            user_obj = {"id": server['uuid'], "encryption": "none"}
            if params.get('flow', [''])[0]: user_obj["flow"] = params.get('flow', [''])[0]
            stream_settings = {"network": server['transport'], "security": server['security']}

            if server['transport'] == 'ws':
                ws_settings = {"path": params.get('path', ['/'])[0]}
                if params.get('host', [''])[0]: ws_settings["headers"] = {"Host": params.get('host', [''])[0]}
                stream_settings["wsSettings"] = ws_settings
            elif server['transport'] == 'grpc':
                if params.get('serviceName', [''])[0]: stream_settings["grpcSettings"] = {"serviceName": params.get('serviceName', [''])[0]}
            
            if server['security'] == 'tls':
                stream_settings["tlsSettings"] = {"serverName": params.get('sni', [''])[0], "allowInsecure": True, "fingerprint": params.get('fp', ['chrome'])[0]}
            elif server['security'] == 'reality':
                stream_settings["realitySettings"] = {
                    "show": False, "fingerprint": params.get('fp', ['chrome'])[0], "serverName": params.get('sni', [''])[0],
                    "publicKey": params.get('pbk', [''])[0], "shortId": params.get('sid', [''])[0], "spiderX": params.get('spx', ['/'])[0]
                }

            outbound = {"tag": "proxy", "protocol": "vless", "settings": {"vnext": [{"address": server['ip'], "port": int(server['port']), "users": [user_obj]}]}, "streamSettings": stream_settings}

        return {"log": {"loglevel": "error"}, "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}], "outbounds": [outbound]}
    except: return None

def check_real_connection(server):
    """
    ULTIMATE TEST: Ping + Packet Loss + Speed (Download)
    """
    local_port = get_free_port()
    config_data = generate_xray_config(server, local_port)
    if not config_data: return None
    
    unique_name = f"config_{uuid.uuid4().hex}.json"
    config_path = os.path.join(tempfile.gettempdir(), unique_name)
    xray_process = None
    result = None

    try:
        with open(config_path, 'w') as f: json.dump(config_data, f)
        xray_process = subprocess.Popen([XRAY_BIN, "-config", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0) 
        if xray_process.poll() is not None: return None

        proxies = {'http': f'socks5h://127.0.0.1:{local_port}', 'https': f'socks5h://127.0.0.1:{local_port}'}
        
        # 1. СТАБИЛЬНОСТЬ (5 запросов к Google)
        target_ping = "https://www.gstatic.com/generate_204"
        latencies = []
        for _ in range(5):
            try:
                start = time.perf_counter()
                resp = requests.get(target_ping, proxies=proxies, timeout=3.0)
                if resp.status_code == 204:
                    latencies.append((time.perf_counter() - start) * 1000)
                else:
                    latencies.append(9999) 
            except:
                latencies.append(9999) 
            time.sleep(0.05)

        failed_count = len([l for l in latencies if l > 5000])
        if failed_count > 1: return None 
        
        valid_latencies = [l for l in latencies if l < 5000]
        if not valid_latencies: return None

        avg_lat = statistics.mean(valid_latencies)
        jitter = statistics.stdev(valid_latencies) if len(valid_latencies) > 1 else 0

        # 2. ТЕСТ СКОРОСТИ (СКАЧИВАНИЕ)
        speed_score = 0
        try:
            speed_target = "https://speed.cloudflare.com/__down?bytes=100000"
            start_dl = time.perf_counter()
            r_speed = requests.get(speed_target, proxies=proxies, timeout=5.0)
            duration = time.perf_counter() - start_dl
            
            if r_speed.status_code == 200:
                speed_score = duration * 1000 
            else:
                speed_score = 5000 
        except:
            speed_score = 5000 

        result = (avg_lat, jitter, speed_score)

    except: pass
    finally:
        if xray_process:
            xray_process.terminate()
            try: xray_process.wait(timeout=1)
            except: xray_process.kill()
        if os.path.exists(config_path):
            try: os.remove(config_path)
            except: pass

    return result

def calculate_tier_rank(country_code):
    if country_code in TIER_1_PLATINUM: return 1
    if country_code in TIER_2_GOLD: return 2
    if country_code in TIER_3_SILVER: return 3
    if country_code in ['US', 'CA']: return 5 
    return 4

def check_server_initial(server):
    """
    Быстрый фильтр + БАН РОССИИ
    """
    is_warp = False
    rem = server['original_remark'].lower()
    if 'warp' in rem or 'cloudflare' in rem: is_warp = True
    if server['transport'] in ['ws', 'grpc']: is_warp = True 
    
    if server['source_type'] == 'whitelist': server['category'] = 'WHITELIST'
    elif is_warp: server['category'] = 'WARP'
    else: server['category'] = 'UNIVERSAL'

    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    
    server['latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    # --- [ЖЕСТКИЙ БАН РФ] ---
    if code == 'RU' and server['category'] != 'WHITELIST':
        return None

    # --- ANTI-FAKE CHECK ---
    is_fake = False
    
    # Fake KZ/UA (физически в США)
    if code in ['KZ', 'UA', 'BY'] and server['latency'] < 80: 
        is_fake = True
    # Fake Europe
    elif code in ['FI', 'EE', 'SE', 'DE', 'NL'] and server['latency'] < 10: 
        is_fake = True 
    # Localhost
    elif server['latency'] < 1 and code not in ['US', 'CA']: 
        is_fake = True
    
    if is_fake and server['category'] != 'WHITELIST': return None

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def process_tournament_batch(candidates, mode):
    checked_servers = []
    print(f"   🚀 Running ULTIMATE test (Ping + Jitter + Speed) for {len(candidates)} configs...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_server = {executor.submit(check_real_connection, s): s for s in candidates}
        
        for future in concurrent.futures.as_completed(future_to_server):
            srv = future_to_server[future]
            res = future.result()
            
            if res:
                real_avg, real_jitter, speed_penalty = res
                
                # --- ФОРМУЛА КАЧЕСТВА ---
                score = real_avg 
                score += (real_jitter * 3)   
                score += (speed_penalty * 0.5) 
                
                tier_penalty = 0
                if srv['tier_rank'] == 1: tier_penalty = 0
                elif srv['tier_rank'] == 2: tier_penalty = 10
                elif srv['tier_rank'] == 3: tier_penalty = 40
                else: tier_penalty = 600 
                
                score += tier_penalty

                if mode == "gaming":
                    if srv.get('is_ss', False): score -= 40 
                
                srv['latency'] = int(real_avg)
                srv['jitter'] = int(real_jitter)
                srv['speed_val'] = int(speed_penalty)
                srv['final_score'] = score
                
                checked_servers.append(srv)
                print(f"      ✅ {srv['info']['countryCode']} | Ping:{int(real_avg)} | Speed:{int(speed_penalty)} | Score:{int(score)}")

    return checked_servers

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    if mode == "gaming":
        filtered = [c for c in candidates if c.get('is_ss', False) or c['is_reality']]
        tier1 = [c for c in filtered if c['tier_rank'] <= 2] 
        if len(tier1) > 5: filtered = tier1
            
    elif mode == "universal":
        filtered = [c for c in candidates if c['is_reality']]
    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']

    if not filtered: return []
    
    semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:30]
    
    print(f"\n🏟️ {title} (Testing top {len(semifinalists)} candidates)")
    scored_results = process_tournament_batch(semifinalists, mode)
    scored_results.sort(key=lambda x: x['final_score'])
    
    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                found = extract_links(resp.text)
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def main():
    print("--- ЗАПУСК V3.1 ULTIMATE (SPEED TEST + NEW SOURCES) ---")
    
    if os.path.exists(XRAY_BIN): os.chmod(XRAY_BIN, 0o755)
    else: print(f"❌ Error: Xray binary not found at {XRAY_BIN}")

    download_mmdb()
    init_geoip()
    
    all_servers = []
    print("🔍 Fetching URLs...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Found {len(servers_to_check)} unique configs. Initial TCP scan...")
    
    working_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    print(f"✅ Live TCP servers: {len(working_servers)}")

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []
    
    # Турниры
    game_winners = run_tournament(b_univ, TARGET_GAME, "GAME CUP", "gaming")
    game_ips = [g['ip'] for g in game_winners]
    
    if game_winners:
        for g in game_winners: g['category'] = 'Game Server'
        final_list.extend(game_winners)
    
    b_univ_filtered = [s for s in b_univ if s['ip'] not in game_ips]
    final_list.extend(run_tournament(b_univ_filtered, TARGET_UNIVERSAL, "UNIVERSAL CUP", "universal"))
    final_list.extend(run_tournament(b_warp, TARGET_WARP, "WARP CUP", "warp"))
    final_list.extend(run_tournament(b_white, TARGET_WHITELIST, "WHITELIST CUP", "whitelist"))

    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    
    time_str = msk_now.strftime('%H:%M')
    next_str = next_update.strftime('%H:%M')
    
    update_msg = f"📅 Обновлено: {time_str} (МСК) | След. обновление: {next_str}"
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(update_msg)}"
    result_links = [info_link]
    
    json_data = {"updated_at": time_str, "next_update": next_str, "servers": []}

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        country_full = RUS_NAMES.get(code, code)
        
        real_ping = s.get('latency', 999)
        if real_ping < 10: real_ping = "<10"
        ping_str = f"{real_ping}ms"
        
        if s['category'] == 'Game Server': name = f"🎮 Game | {flag} {country_full} | {ping_str}"
        elif s['category'] == 'WHITELIST': name = f"⚪ {flag} RU (WhiteList) | {ping_str}"
        elif s['category'] == 'WARP': name = f"🌀 {flag} {country_full} WARP | {ping_str}"
        else: name = f"⚡ {flag} {country_full} | {ping_str}"

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name, "category": s['category'], "country": country_full, "iso": code,
            "ping": s.get('latency', 0), "ip": s['ip'], "type": s['security'].upper() if s.get('is_reality') else "TCP", "link": final_link
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"DONE. {len(result_links)} best servers saved.")

if __name__ == "__main__":
    main()
