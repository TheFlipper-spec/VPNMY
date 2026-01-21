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
import json # Для сайта
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- 1. ЭЛИТНЫЕ ИСТОЧНИКИ (NO TRASH) ---
GENERAL_URLS = [
    # Igareck (Основа)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    
    # Roosterkid (Высокая надежность)
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt", 
    
    # Lalatina (Хороший европейский микс)
    "https://github.com/LalatinaHub/Mineral/raw/refs/heads/master/result/nodes",
    
    # Mheidari98 (Спец по VLESS, полезен для Warp)
    "https://raw.githubusercontent.com/mheidari98/.proxy/refs/heads/main/vless"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 0.8 
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json' # Файл для сайта
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# TIER SYSTEM (FINLAND SUPREMACY)
TIER_1_PLATINUM = ['FI', 'EE', 'SE'] 
TIER_2_GOLD = ['DE', 'NL', 'FR', 'GB', 'PL']
TIER_3_SILVER = ['KZ', 'UA', 'TR', 'CZ', 'BG', 'RO', 'IT', 'ES']

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

    # ОПРЕДЕЛЕНИЕ КАТЕГОРИИ
    is_warp_candidate = False
    rem = server['original_remark'].lower()
    if 'warp' in rem or 'cloudflare' in rem or 'clash' in rem: is_warp_candidate = True
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
        time.sleep(0.1) # Fast interval
    
    if len(pings) < 3: return 9999, 9999, [] 
    return statistics.mean(pings), statistics.stdev(pings), pings

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    # ФИЛЬТРЫ
    if mode == "gaming":
        # Игры: Чистый TCP или Reality (No Vision)
        pure_strict = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
        if pure_strict: filtered = pure_strict
        else: filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

    elif mode == "whitelist":
        # Whitelist: ТОЛЬКО REALITY (Стабильность)
        filtered = [c for c in candidates if c['is_reality'] and c['info'].get('countryCode') == 'RU']

    elif mode == "warp":
        # Warp: Только НЕ Россия
        filtered = [c for c in candidates if c['info'].get('countryCode') != 'RU']

    if not filtered: return []
    
    finalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:15]
    print(f"\n🏟️ {title} ({len(finalists)} fighters)")
    
    scored_results = []
    for f in finalists:
        avg, jitter, _ = stress_test_server(f)
        
        # ШТРАФЫ
        tier
