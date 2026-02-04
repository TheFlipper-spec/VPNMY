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
try:
    import socks
except ImportError:
    socks = None
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- V105: ANTI-CRASH MASSIVE EDITION ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ИСТОЧНИКИ ---
PREMIUM_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/Config/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/hysteria2"
]

GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

TELEGRAM_CHANNELS = [
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir",
    "v2ray_configs_pool", "VlessConfig", "v2ray1_ng"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

# --- НАСТРОЙКИ (БЕЗОПАСНЫЕ) ---
# Снижаем нагрузку, чтобы не вылетать по памяти (OOM Killer)
MAX_WORKERS_SCAN = 60    # Скачивание легкое, оставляем 60
MAX_WORKERS_CUP = 15     # ВАЖНО: Только 15 одновременных проверок Xray (вместо 100)
TIMEOUT = 0.8            
REAL_TEST_TIMEOUT = 10.0 
SPEED_TEST_TIMEOUT = 7.0 

# --- ПАРАМЕТРЫ ОТБОРА ---
MIN_SPEED_GOD = 10.0     
MIN_SPEED_BACKUP = 3.0   
MIN_SPEED_RU = 0.5       

OUTPUT_FILE = 'FL1PVPN' 
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json' 

TIMEZONE_OFFSET = 3 
CACHE_TTL_HOURS = 4      
MAX_FAILURES = 2         

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'PL': 'Польша', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'NO': 'Норвегия'
}

BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP'] 

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
        if val.get('fails', 0) >= MAX_FAILURES:
            continue
        if current_ts - val['ts'] < (24 * 3600): 
            clean_history[key] = val
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(clean_history, f)
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

def get_streak(ip, port):
    key = f"{ip}:{port}"
    return server_history.get(key, {}).get('success_streak', 0)

def should_check_server(ip, port):
    key = f"{ip}:{port}"
    if key not in server_history: return True
    rec = server_history[key]
    if rec['fails'] >= MAX_FAILURES:
        age_hours = (time.time() - rec['ts']) / 3600
        if age_hours < CACHE_TTL_HOURS: return False 
    return True

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
    if missing_padding: s += '=' * (4 - missing_padding)
    try: return base64.urlsafe_b64decode(s).decode('utf-8', errors='ignore')
    except:
        try: return base64.b64decode(s).decode('utf-8', errors='ignore')
        except: return ""

def extract_links(text):
    regex = r"(vless://[^ \n]+|ss://[^ \n]+|hy2://[^ \n]+)"
    links = re.findall(regex, text)
    if len(links) < 3:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_config_info(config_str, source_type):
    try:
        if config_str.startswith("hy2://"):
            part = config_str.split("@")
            password = part[0].replace("hy2://", "")
            host_port_query = part[1]
            if "?" in host_port_query:
                host_port, query = host_port_query.split("?", 1)
            else:
                host_port = host_port_query
                query = ""
            if "#" in query: query, remark = query.split("#", 1)
            elif "#" in host_port: host_port, remark = host_port.split("#", 1)
            else: remark = "Hy2"

            if ":" not in host_port: return None
            host, port = host_port.split(":")
            params = parse_qs(query)
            sni = params.get('sni', [''])[0]
            
            return {
                "ip": host, "port": int(port), "uuid": password, "original": config_str,
                "original_remark": unquote(remark).strip(), "latency": 9999, "jitter": 0,
                "final_score": 9999, "info": {}, "speed_mbps": 0.0,
                "transport": "udp", "security": "tls",
                "is_reality": False, "source_type": source_type, "parsed_params": params, "sni": sni, "is_hy2": True
            }

        if config_str.startswith("vless://"):
            part = config_str.split("@")[1].split("?")[0]
            if ":" in part:
                host, port = part.split(":")
                query = config_str.split("?")[1].split("#")[0]
                params = parse_qs(query)
                transport = params.get('type', ['tcp'])[0].lower()
                security = params.get('security', ['none'])[0].lower()
                is_reality = (security == 'reality')
                if is_reality:
                    pbk = params.get('pbk', [''])[0]
                    if len(pbk) != 43: return None
                    sni = params.get('sni', [''])[0]
                    if sni == host: return None 
                
                _uuid = config_str.split("@")[0].replace("vless://", "")
                original_remark = "Unknown"
                if "#" in config_str: original_remark = unquote(config_str.split("#")[-1]).strip()

                return {
                    "ip": host, "port": int(port), "uuid": _uuid, "original": config_str, 
                    "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                    "final_score": 9999, "info": {},
                    "speed_mbps": 0.0,
                    "transport": transport, "security": security,
                    "is_reality": is_reality,
                    "is_hy2": False,
                    "source_type": source_type,
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
        if server.get('is_hy2'):
            outbound_settings = {
                "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [{"password": server['uuid']}]}]
            }
            stream_settings = {
                "network": "udp", "security": "tls", "tlsSettings": {"serverName": server.get('sni', ''), "allowInsecure": True}
            }
            protocol = "hysteria2"
        else:
            params = server['parsed_params']
            user_obj = { "id": server['uuid'], "encryption": "none" }
            if params.get('flow', [''])[0]: user_obj["flow"] = params.get('flow', [''])[0]
            outbound_settings = { "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [user_obj]}] }
            stream_settings = { "network": server['transport'], "security": server['security'] }

            if server['transport'] == 'ws':
                ws_settings = {"path": params.get('path', ['/'])[0]}
                host_val = params.get('host', [''])[0]
                if host_val: ws_settings["headers"] = {"Host": host_val}
                stream_settings["wsSettings"] = ws_settings
            elif server['transport'] == 'grpc':
                service_name = params.get('serviceName', [''])[0]
                if service_name: stream_settings["grpcSettings"] = {"serviceName": service_name}

            if server['security'] == 'tls':
                tls_settings = { "serverName": params.get('sni', [''])[0], "allowInsecure": False, "fingerprint": params.get('fp', ['chrome'])[0] }
                stream_settings["tlsSettings"] = tls_settings
            elif server['security'] == 'reality':
                reality_settings = {
                    "show": False, "fingerprint": params.get('fp', ['chrome'])[0], "serverName": params.get('sni', [''])[0],
                    "publicKey": params.get('pbk', [''])[0], "shortId": params.get('sid', [''])[0], "spiderX": params.get('spx', ['/'])[0]
                }
                stream_settings["realitySettings"] = reality_settings
            protocol = "vless"

        config = {
            "log": {"loglevel": "error"},
            "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True, "auth": "noauth"}}],
            "outbounds": [{"tag": "proxy", "protocol": protocol, "settings": outbound_settings, "streamSettings": stream_settings}]
        }
        return config
    except: return None

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
                if total_bytes > 2 * 1024 * 1024: break 
            duration = time.time() - start_time
            if duration <= 0: duration = 0.1
            return round((total_bytes * 8) / (duration * 1_000_000), 2)
    except: return 0.0

def check_udp_dns(local_port):
    if not socks: return False
    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
        s.set_proxy(socks.SOCKS5, "127.0.0.1", local_port)
        s.settimeout(3.0)
        dns_query = binascii.unhexlify("aaaa0100000100000000000006676f6f676c6503636f6d0000010001")
        s.sendto(dns_query, ("8.8.8.8", 53))
        data, addr = s.recvfrom(1024)
        s.close()
        return True
    except: return False

def check_real_connection(server):
    local_port = random.randint(10000, 60000)
    config_data = generate_xray_config(server, local_port)
    if not config_data: return None, 0.0, False

    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
        json.dump(config_data, tmp_conf)
        config_path = tmp_conf.name

    xray_process = None
    result_latency = None
    result_speed = 0.0
    udp_success = False

    try:
        xray_process = subprocess.Popen([XRAY_BIN, "-config", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(1.0) # Быстрый старт
        if xray_process.poll() is not None: raise Exception("Xray died")

        proxies = { 'http': f'socks5://127.0.0.1:{local_port}', 'https': f'socks5://127.0.0.1:{local_port}' }
        start_time = time.perf_counter()
        resp = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=REAL_TEST_TIMEOUT, verify=False)
        end_time = time.perf_counter()
        
        if 200 <= resp.status_code < 300:
            result_latency = (end_time - start_time) * 1000
            udp_success = check_udp_dns(local_port)
            result_speed = measure_speed(local_port)
            update_history(server['ip'], server['port'], True)
        else:
            update_history(server['ip'], server['port'], False)
    except:
        update_history(server['ip'], server['port'], False)
    finally:
        if xray_process:
            xray_process.terminate()
            try: xray_process.wait(timeout=1)
            except: xray_process.kill()
        if os.path.exists(config_path): os.remove(config_path)

    return result_latency, result_speed, udp_success

def check_server_initial(server):
    if not should_check_server(server['ip'], server['port']): return None 
    
    code = get_ip_country_local(server['ip'])
    if code in BLACKLIST_COUNTRIES: return None

    p = tcp_ping(server['ip'], server['port'])
    if p is None: 
        update_history(server['ip'], server['port'], False)
        return None
        
    server['latency'] = int(p)
    server['info'] = {'countryCode': code}
    server['streak'] = get_streak(server['ip'], server['port'])
    return server

def check_full_server(server):
    lat, speed, udp = check_real_connection(server)
    if lat is None: return None
    server['real_latency'] = lat
    server['speed_mbps'] = speed
    server['udp_enabled'] = udp
    
    display_ping = lat
    if server['info']['countryCode'] in ['DE', 'NL', 'GB', 'FR']:
        display_ping += 35
    server['display_ping'] = int(display_ping)
    
    return server

def get_best_candidates(servers, limit=100):
    def sort_key(s):
        cc = s['info']['countryCode']
        prio = 0
        if cc in ['FI', 'EE', 'SE', 'NO']: prio = -2
        elif cc in ['DE', 'NL']: prio = -1
        return (prio, s['latency'])
    return sorted(servers, key=sort_key)[:limit]

def fetch_telegram_channels():
    print(f"✈️ Telegram...")
    links = []
    for channel in TELEGRAM_CHANNELS:
        try:
            resp = requests.get(f"https://t.me/s/{channel}", timeout=5)
            if resp.status_code == 200:
                for link in extract_links(resp.text):
                    p = parse_config_info(link, 'telegram')
                    if p: links.append(p)
        except: pass
    return links

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                for link in extract_links(resp.text):
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def main():
    print("--- ЗАПУСК V105 (ANTI-CRASH) ---")
    load_history()
    if os.path.exists(XRAY_BIN): os.chmod(XRAY_BIN, 0o755)
    download_mmdb()
    init_geoip()
    
    # 1. СБОР
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'static')
        f3 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        f4 = executor.submit(process_urls, PREMIUM_URLS, 'premium') 
        f_tg = executor.submit(fetch_telegram_channels)
        all_servers = f1.result() + f3.result() + f4.result() + f_tg.result()
    
    unique_servers = {}
    for s in all_servers:
        unique_servers[f"{s['ip']}:{s['port']}"] = s
    candidates = list(unique_servers.values())
    print(f"🔍 Найдено: {len(candidates)}")

    # 2. ПИНГ ТЕСТ
    alive_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as executor:
        futures = [executor.submit(check_server_initial, s) for s in candidates]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: alive_servers.append(res)
            
    print(f"⚡ Живых TCP: {len(alive_servers)}")
    
    # 3. ОТБОР КАНДИДАТОВ
    ru_candidates = [s for s in alive_servers if s['info']['countryCode'] == 'RU']
    global_candidates = [s for s in alive_servers if s['info']['countryCode'] != 'RU']
    
    # Берем 1500 (безопасное число) вместо 2000
    top_global = get_best_candidates(global_candidates, 1500)
    top_ru = ru_candidates # Все RU
    
    full_check_list = top_global + top_ru
    verified_servers = []
    
    print(f"🧪 Глубокая проверка {len(full_check_list)} серверов...")
    # ТУТ ГЛАВНОЕ ИЗМЕНЕНИЕ: max_workers=MAX_WORKERS_CUP (15)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_CUP) as executor:
        futures = {executor.submit(check_full_server, s): s for s in full_check_list}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: verified_servers.append(res)
    
    print(f"✅ Проверку прошли: {len(verified_servers)}")
            
    # 4. ФИНАЛЬНЫЙ ОТБОР
    final_4 = []
    used_ips = []
    
    verified_ru = [s for s in verified_servers if s['info']['countryCode'] == 'RU']
    verified_global = [s for s in verified_servers if s['info']['countryCode'] != 'RU']
    
    # --- 1. ОСНОВНОЙ ---
    god_candidates = sorted(
        [s for s in verified_global if s['speed_mbps'] > MIN_SPEED_GOD and s['udp_enabled']],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not god_candidates:
         god_candidates = sorted(verified_global, key=lambda x: x['speed_mbps'], reverse=True)

    if god_candidates:
        server_god = god_candidates[0]
        used_ips.append(server_god['ip'])
        msk_time = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime('%H:%M')
        flag = "".join([chr(127397 + ord(c)) for c in server_god['info']['countryCode'].upper()])
        server_god['final_name'] = f"ОСНОВНОЙ {flag} (Обн. {msk_time})"
        final_4.append(server_god)
    
    # --- 2. ЗАПАСНОЙ ---
    backup_candidates = sorted(
        [s for s in verified_global if s['ip'] not in used_ips and s['speed_mbps'] > MIN_SPEED_BACKUP],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not backup_candidates:
        backup_candidates = sorted(
             [s for s in verified_global if s['ip'] not in used_ips],
             key=lambda x: x['speed_mbps'], reverse=True
        )
    
    if backup_candidates:
        server_backup = backup_candidates[0]
        used_ips.append(server_backup['ip'])
        flag = "".join([chr(127397 + ord(c)) for c in server_backup['info']['countryCode'].upper()])
        server_backup['final_name'] = f"ЗАПАСНОЙ {flag}"
        final_4.append(server_backup)
        
    # --- 3. РЕЗЕРВНЫЙ ---
    stable_candidates = sorted(
        [s for s in verified_global if s['ip'] not in used_ips],
        key=lambda x: (x['streak'], x['speed_mbps']), reverse=True
    )
    
    if stable_candidates:
        server_stable = stable_candidates[0]
        used_ips.append(server_stable['ip'])
        flag = "".join([chr(127397 + ord(c)) for c in server_stable['info']['countryCode'].upper()])
        server_stable['final_name'] = f"РЕЗЕРВНЫЙ {flag}"
        final_4.append(server_stable)
        
    # --- 4. WHITELIST ---
    ru_final = sorted(
        [s for s in verified_ru if s['speed_mbps'] > MIN_SPEED_RU],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not ru_final:
         ru_final = sorted(verified_ru, key=lambda x: x['speed_mbps'], reverse=True)
    
    if ru_final:
        server_ru = ru_final[0]
        flag = "".join([chr(127397 + ord(c)) for c in server_ru['info']['countryCode'].upper()])
        server_ru['final_name'] = f"WHITELIST {flag}"
        final_4.append(server_ru)

    # ЗАПИСЬ
    result_links = []
    json_data = {"servers": []}
    
    print("\n🏆 --- THE CHOSEN FOUR ---")
    for s in final_4:
        print(f"   🌟 {s['final_name']} ({s['ip']})")
        base = s['original'].split('#')[0]
        link = f"{base}#{quote(s['final_name'])}"
        result_links.append(link)
        
        json_data["servers"].append({
            "name": s['final_name'],
            "ip": s['ip'],
            "country": s['info']['countryCode'],
            "speed": s['speed_mbps']
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
    
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    save_history()
    print("DONE.")

if __name__ == "__main__":
    main()
