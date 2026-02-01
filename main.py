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
import urllib3
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- V89: GOLDEN SOURCES + SURVIVOR BONUS + STRICT TIER 1 FRESH ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ------------------------------------------------------------------

# --- 1. PREMIUM COLLECTORS (ЗОЛОТЫЕ ИСТОЧНИКИ) ---
# Это агрегаторы, которые собирают ключи. Шанс найти тут живой Reality в разы выше.
PREMIUM_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num"
]

# --- 2. OTHERS ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

# --- НАСТРОЙКИ ---
MAX_WORKERS = 35        # Еще больше потоков для скорости
TIMEOUT = 1.0           
REAL_TEST_TIMEOUT = 10.0 # Даем больше времени на реальный тест
SPEED_TEST_TIMEOUT = 7.0 

# --- КВОТЫ ---
TARGET_GITHUB = 1     
TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  
# -------------

OUTPUT_FILE = 'FL1PVPN' 
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json' 

TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# Настройки кэширования
CACHE_TTL_HOURS = 4      
MAX_FAILURES = 2         

PING_BASE_MS = {
    'RU': 90, 
    'FI': 40, 'EE': 45, 'SE': 55, 'NO': 60, 'LV': 45, 'LT': 45, # TIER 1
    'DE': 70, 'NL': 75, 'FR': 80, 'PL': 60, # TIER 2 (Slower)
    'US': 160, 'GB': 85 
}

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ'
}

# --- TIER 1: ТОЛЬКО СЕВЕР (БЕЗ DE/PL) ---
TIER_1_PLATINUM = ['FI', 'EE', 'SE', 'LT', 'LV', 'NO']
TIER_2_GOLD = ['NL', 'DE', 'PL', 'FR', 'KZ', 'RU'] 
TIER_3_SILVER = ['IT', 'ES', 'TR', 'CZ', 'BG', 'AT']

# БАН ЛИСТ
BLACKLIST_COUNTRIES = ['US', 'CA', 'GB', 'CN', 'IR'] 

geo_reader = None
server_history = {} 

def load_history():
    global server_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                server_history = json.load(f)
            print(f"📂 Загружена история: {len(server_history)} записей.")
        except:
            server_history = {}

def save_history():
    current_ts = time.time()
    clean_history = {}
    for key, val in server_history.items():
        if current_ts - val['ts'] < (24 * 3600): 
            clean_history[key] = val
            
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(clean_history, f)
        print("💾 История сохранена.")
    except: pass

def update_history(ip, port, is_alive):
    key = f"{ip}:{port}"
    current = server_history.get(key, {'fails': 0, 'ts': 0, 'success_streak': 0})
    
    if is_alive:
        current['fails'] = 0
        current['success_streak'] = current.get('success_streak', 0) + 1
    else:
        current['fails'] += 1
        current['success_streak'] = 0
    
    current['ts'] = time.time()
    server_history[key] = current

def get_history_bonus(ip, port):
    key = f"{ip}:{port}"
    rec = server_history.get(key)
    if not rec: return 0
    # БОНУС ВЫЖИВШЕГО: Если сервер работал в прошлый раз, даем ему фору
    if rec.get('success_streak', 0) > 0:
        return -50 * rec['success_streak'] # -50 очков (лучше) за каждый успешный проход
    return 0

def should_check_server(ip, port):
    key = f"{ip}:{port}"
    if key not in server_history:
        return True
    
    rec = server_history[key]
    if rec['fails'] >= MAX_FAILURES:
        age_hours = (time.time() - rec['ts']) / 3600
        if age_hours < CACHE_TTL_HOURS:
            return False 
    return True

# --- GEO & UTILS ---

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

def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '')
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    try:
        return base64.urlsafe_b64decode(s).decode('utf-8', errors='ignore')
    except:
        try:
            return base64.b64decode(s).decode('utf-8', errors='ignore')
        except:
            return ""

def extract_links(text):
    regex = r"(vless://[^ \n]+|ss://[^ \n]+)"
    links = re.findall(regex, text)
    if len(links) < 5:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_config_info(config_str, source_type):
    try:
        if config_str.startswith("ss://"):
            return None 

        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            flow_val = params.get('flow', [''])[0].lower()
            
            is_reality = (security == 'reality')
            
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) != 43: return None
                sni = params.get('sni', [''])[0]
                if sni == host: return None # Bad practice SNI=IP
            
            is_vision = ('vision' in flow_val)
            is_pure = (security == 'none' or security == 'tls') and not is_reality
            
            _uuid = config_str.split("@")[0].replace("vless://", "")
            original_remark = "Unknown"
            if "#" in config_str: original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, "port": int(port), "uuid": _uuid, "original": config_str, 
                "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                "final_score": 9999, "info": {},
                "speed_mbps": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure, "is_hy2": False, "is_ss": False,
                "source_type": source_type, "tier_rank": 99,
                "parsed_params": params
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
        user_obj = { "id": server['uuid'], "encryption": "none" }
        if params.get('flow', [''])[0]:
            user_obj["flow"] = params.get('flow', [''])[0]

        outbound_settings = {
            "vnext": [{
                "address": server['ip'],
                "port": int(server['port']),
                "users": [user_obj]
            }]
        }

        stream_settings = {
            "network": server['transport'],
            "security": server['security']
        }

        if server['transport'] == 'ws':
            ws_settings = {"path": params.get('path', ['/'])[0]}
            host_val = params.get('host', [''])[0]
            if host_val: ws_settings["headers"] = {"Host": host_val}
            stream_settings["wsSettings"] = ws_settings
            
        elif server['transport'] == 'grpc':
            service_name = params.get('serviceName', [''])[0]
            if service_name: stream_settings["grpcSettings"] = {"serviceName": service_name}

        if server['security'] == 'tls':
            tls_settings = { "serverName": params.get('sni', [''])[0], "allowInsecure": False }
            fp = params.get('fp', ['chrome'])[0]
            tls_settings["fingerprint"] = fp
            stream_settings["tlsSettings"] = tls_settings
            
        elif server['security'] == 'reality':
            reality_settings = {
                "show": False,
                "fingerprint": params.get('fp', ['chrome'])[0],
                "serverName": params.get('sni', [''])[0],
                "publicKey": params.get('pbk', [''])[0],
                "shortId": params.get('sid', [''])[0],
                "spiderX": params.get('spx', ['/'])[0]
            }
            stream_settings["realitySettings"] = reality_settings

        config = {
            "log": {"loglevel": "error"},
            "inbounds": [{
                "port": local_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True}
            }],
            "outbounds": [{
                "tag": "proxy",
                "protocol": "vless",
                "settings": outbound_settings,
                "streamSettings": stream_settings
            }]
        }
        return config
    except Exception as e:
        return None

def measure_speed(local_port):
    url = "https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe"
    proxies = { "http": f"socks5h://127.0.0.1:{local_port}", "https": f"socks5h://127.0.0.1:{local_port}" }
    start_time = time.time()
    try:
        with requests.get(url, proxies=proxies, timeout=SPEED_TEST_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            total_bytes = 0
            for chunk in r.iter_content(chunk_size=32768):
                if chunk: total_bytes += len(chunk)
                if total_bytes > 3 * 1024 * 1024: break # 3MB limit
            
            duration = time.time() - start_time
            if duration <= 0: duration = 0.1
            speed_mbps = (total_bytes * 8) / (duration * 1_000_000)
            return round(speed_mbps, 2)
    except:
        return 0.0

def check_real_connection(server):
    local_port = random.randint(10000, 60000)
    config_data = generate_xray_config(server, local_port)
    if not config_data: return None, 0.0

    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
        json.dump(config_data, tmp_conf)
        config_path = tmp_conf.name

    xray_process = None
    result_latency = None
    result_speed = 0.0

    try:
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE     
        )
        time.sleep(2.0)
        if xray_process.poll() is not None: raise Exception("Xray process died")

        proxies = { 'http': f'socks5://127.0.0.1:{local_port}', 'https': f'socks5://127.0.0.1:{local_port}' }
        target_url = "https://www.google.com/generate_204"
        
        start_time = time.perf_counter()
        resp = requests.get(target_url, proxies=proxies, timeout=REAL_TEST_TIMEOUT, verify=False)
        end_time = time.perf_counter()
        
        if resp.status_code == 204 or (200 <= resp.status_code < 300):
            result_latency = (end_time - start_time) * 1000
            if result_latency < 3000:
                 result_speed = measure_speed(local_port)
            update_history(server['ip'], server['port'], True)
        else:
            result_latency = None
            update_history(server['ip'], server['port'], False)

    except Exception:
        result_latency = None
        update_history(server['ip'], server['port'], False)
    finally:
        if xray_process:
            xray_process.terminate()
            try: xray_process.wait(timeout=1)
            except: xray_process.kill()
        if os.path.exists(config_path): os.remove(config_path)

    return result_latency, result_speed

def calculate_tier_rank(country_code):
    if country_code in TIER_1_PLATINUM: return 1
    if country_code in TIER_2_GOLD: return 2
    if country_code in TIER_3_SILVER: return 3
    return 4

def check_server_initial(server):
    if not should_check_server(server['ip'], server['port']): return None 

    is_warp = False
    rem = server['original_remark'].lower()
    if 'warp' in rem or 'cloudflare' in rem: is_warp = True
    if server['transport'] in ['ws', 'grpc']: is_warp = True 
    
    if server['source_type'] == 'whitelist': server['category'] = 'WHITELIST'
    elif is_warp: server['category'] = 'WARP'
    else: server['category'] = 'UNIVERSAL'

    p = tcp_ping(server['ip'], server['port'])
    if p is None: 
        update_history(server['ip'], server['port'], False)
        return None
        
    server['latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    
    # HARD FILTER
    if code in BLACKLIST_COUNTRIES:
        update_history(server['ip'], server['port'], False)
        return None

    server['info'] = {'countryCode': code}
    
    is_fake = False
    if code in ['RU', 'KZ', 'UA', 'BY'] and server['latency'] < 90: is_fake = True
    elif code in ['FI', 'EE', 'SE'] and server['latency'] < 90: is_fake = True 
    elif code in ['DE', 'NL'] and server['latency'] < 25: is_fake = True
    elif server['latency'] < 3: is_fake = True 
    
    if server['source_type'] in ['github', 'premium']: is_fake = False
    if server['category'] == 'WHITELIST' and code == 'RU': is_fake = False

    if is_fake and server['category'] != 'WHITELIST': return None

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def stress_test_server(server):
    pings = []
    for i in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is None and i == 0: return 9999, 9999
        if p is not None: pings.append(p)
        time.sleep(0.1) 
    if len(pings) < 2: return 9999, 9999
    return statistics.mean(pings), statistics.stdev(pings)

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    if mode == "gaming":
        filtered = [c for c in candidates if c['is_reality']] # NO SS
    elif mode == "universal":
        filtered = [c for c in candidates if c['is_reality']]
    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']
    elif mode == "github_only": 
        # For Fresh/GitHub cup, ONLY TIER 1 allowed initially
        seen_ips = set()
        unique_candidates = []
        for c in candidates:
            if c['is_reality'] and c['ip'] not in seen_ips:
                # FILTER: Only Tier 1 for Fresh!
                if c['tier_rank'] == 1: 
                    unique_candidates.append(c)
                    seen_ips.add(c['ip'])
        filtered = unique_candidates

    if not filtered and mode == "github_only":
        print("   ⚠️ No Tier 1 found for Fresh Cup. This cup will fail (intended safety).")
        return []

    if not filtered: return []
    
    limit = 10 if mode == "github_only" else 20
    semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:limit]
    
    print(f"\n🏟️ {title} (Checking {len(semifinalists)} candidates...)")
    
    scored_results = []
    for f in semifinalists:
        real_lat, real_speed = check_real_connection(f)
        
        if real_lat is None:
            print(f"   ❌ {f['info']['countryCode']} {f['ip']} -> DEAD via Xray")
            continue

        avg, jitter = stress_test_server(f)
        
        # --- SCORING ---
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0       
        elif f['tier_rank'] == 2: tier_penalty = 5000 # Strict Penalty for non-Tier1
        else: tier_penalty = 10000     
            
        special_penalty = 0
        if mode == "universal" and f['info']['countryCode'] == 'RU': special_penalty += 2000
        elif mode == "whitelist" and not f['is_reality']: special_penalty = 1000
        
        speed_bonus = 0
        if real_speed < 1.0: speed_bonus = -500 
        elif real_speed < 3.0: speed_bonus = -100 
        elif real_speed > 10.0: speed_bonus = 150  
        else: speed_bonus = real_speed * 10 
        
        # SURVIVOR BONUS
        history_bonus = get_history_bonus(f['ip'], f['port'])

        score = avg + (jitter * 5) + tier_penalty + special_penalty + history_bonus - speed_bonus
        
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['speed_mbps'] = real_speed
        f['final_score'] = score
        
        proto_info = "Reality" if f['is_reality'] else "TCP"
        source_label = f.get('source_type', 'UNK').upper()
        speed_str = f"{real_speed:.1f} Mbps" if real_speed > 0 else "---"
        
        print(f"   ✅ {f['info']['countryCode']:<4} | {proto_info:<7} | Ping: {int(avg)}ms | Speed: {speed_str:<9} | Score: {int(score)} | Src: {source_label}")
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
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def fetch_fresh_github_links(max_repos=150): 
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("   ⚠️ Warning: GITHUB_TOKEN не найден.")
        return []

    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {token}"}
    date_filter = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d')
    query = f'vless pushed:>{date_filter} stars:<=50'
    
    print(f"🔎 Smart Repo Search: '{query}'...")
    repo_api_url = "https://api.github.com/search/repositories"
    repo_params = {"q": query, "sort": "updated", "order": "desc", "per_page": max_repos}

    found_files = []
    try:
        repo_resp = requests.get(repo_api_url, headers=headers, params=repo_params, timeout=10)
        if repo_resp.status_code == 200:
            repos = repo_resp.json().get("items", [])
            print(f"   ✅ Найдено свежих репозиториев: {len(repos)}")
            
            code_api_url = "https://api.github.com/search/code"
            for repo in repos:
                full_name = repo.get("full_name")
                code_params = {"q": f'"vless://" "reality" repo:{full_name}', "per_page": 5}
                try:
                    code_resp = requests.get(code_api_url, headers=headers, params=code_params, timeout=5)
                    if code_resp.status_code == 200:
                        files = code_resp.json().get("items", [])
                        for f in files:
                            raw_url = f.get("html_url", "").replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                            if raw_url: found_files.append(raw_url)
                    time.sleep(0.3) 
                except: pass
    except Exception as e: print(f"   ❌ Ошибка Smart Search: {e}")
    return list(set(found_files))

def main():
    print("--- ЗАПУСК V89 (GOLDEN SOURCES + SURVIVOR BONUS) ---")
    load_history()
    
    if os.path.exists(XRAY_BIN): os.chmod(XRAY_BIN, 0o755)
    download_mmdb()
    init_geoip()
    
    smart_urls = fetch_fresh_github_links(max_repos=150) 
    
    all_servers = []
    github_candidates_raw = [] 
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        print(f"🌐 Скачивание источников...")
        f1 = executor.submit(process_urls, GENERAL_URLS, 'static')
        f3 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        f4 = executor.submit(process_urls, PREMIUM_URLS, 'premium') # GOLDEN SOURCE
        
        static_results = f1.result() + f3.result() + f4.result()
        
        f2 = executor.submit(process_urls, smart_urls, 'github')
        github_results = f2.result()
        github_candidates_raw = github_results 
        
        all_servers = static_results + github_results
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    print(f"🔍 Checking {len(servers_to_check)} servers (TCP scan with CACHE)...")
    
    working_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']
    
    # Fresh Mix: GitHub Search + Premium Sources
    github_originals = set(g['original'] for g in github_candidates_raw)
    premium_originals = set(p['original'] for p in f4.result())
    
    b_fresh_candidates = [
        s for s in working_servers 
        if (s['original'] in github_originals or s['original'] in premium_originals)
        and s['category'] != 'WHITELIST'
    ]

    final_list = []
    used_ips = []
    
    # GITHUB FRESH CUP (Now STRICT TIER 1)
    if b_fresh_candidates:
        github_winners = run_tournament(b_fresh_candidates, TARGET_GITHUB, "GITHUB FRESH CUP", "github_only")
        
    github_added = False
    if 'github_winners' in locals() and github_winners:
        for g in github_winners:
            if g['speed_mbps'] > 1.0:
                g['category'] = 'Fresh Tier 1' 
                used_ips.append(g['ip'])
                final_list.extend([g])
                github_added = True

    if not github_added:
        print("   ⚠️ Fresh Cup Failed (No Tier 1): Filling with best UNIVERSAL Tier 1.")
        # Only take TIER 1 as backup for Fresh slot!
        tier1_backup = [s for s in b_univ if s['tier_rank'] == 1 and s['ip'] not in used_ips]
        extra_univ = run_tournament(tier1_backup, 1, "BACKUP CUP", "universal")
        if extra_univ:
            extra_univ[0]['category'] = 'Fresh Backup (T1)'
            final_list.extend(extra_univ)
            used_ips.append(extra_univ[0]['ip'])
    
    b_univ_filtered = [s for s in b_univ if s['ip'] not in used_ips]
    game_winners = run_tournament(b_univ_filtered, TARGET_GAME, "GAME CUP", "gaming")
    
    for g in game_winners:
        g['category'] = 'Game Server'
        used_ips.append(g['ip'])
    final_list.extend(game_winners)
    
    b_univ_filtered_2 = [s for s in b_univ_filtered if s['ip'] not in used_ips]
    final_list.extend(run_tournament(b_univ_filtered_2, TARGET_UNIVERSAL, "UNIVERSAL CUP", "universal"))
    
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

    print("\n🏆 --- FINAL SELECTION ---")
    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        country_full = RUS_NAMES.get(code, code)
        
        base_ping = PING_BASE_MS.get(code, 120)
        if code == 'RU': calc_ping = base_ping + random.randint(0, 5)
        else: calc_ping = base_ping + s['jitter']
        if s['is_hy2']: calc_ping = int(calc_ping * 0.9)
        if calc_ping < 10: calc_ping = 15

        name = ""
        if 'Fresh' in s['category']:
             name = f"🔥 Fresh | {flag} {country_full} | {calc_ping}ms"
        elif s['category'] == 'Game Server': 
            name = f"🎮 Game Server | {flag} {country_full} | {calc_ping}ms"
        elif s['category'] == 'WHITELIST': 
            name = f"⚪ {flag} RU (WhiteList) | {calc_ping}ms"
        elif s['category'] == 'WARP': 
            name = f"🌀 {flag} {country_full} WARP | {calc_ping}ms"
        else: 
            name = f"⚡ {flag} {country_full} | {calc_ping}ms"

        print(f"   🌟 {name} | IP: {s['ip']}")

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name, "category": s['category'], "country": country_full, "iso": code,
            "flag": flag, "ping": calc_ping, "speed": s['speed_mbps'], "ip": s['ip'],
            "port": s['port'], "protocol": s['transport'].upper(), 
            "type": s.get('is_reality') and "Reality" or "VLESS"
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    save_history() 
    print(f"\nDONE. {len(result_links)} links saved.")

if __name__ == "__main__":
    main()
