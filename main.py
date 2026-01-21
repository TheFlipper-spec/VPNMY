import sys
import requests
import socket
import time
import concurrent.futures
import re
import statistics
import os
import json
import subprocess
import geoip2.database 
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/1.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/6.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/22.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/23.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/24.txt",
    "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror/25.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray" 

# --- ПАРАМЕТРЫ ОТБОРА ---
TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

# Таймауты стали жестче для скорости
TCP_TIMEOUT = 0.5 
REAL_TEST_TIMEOUT = 4.0

OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'

BANNED_COUNTRIES = ['CN', 'IR', 'KP'] 

PING_BASE_MS = {
    'RU': 25, 'FI': 40, 'EE': 45, 'SE': 55, 'DE': 65, 'NL': 70, 
    'FR': 75, 'GB': 80, 'PL': 60, 'KZ': 60, 'UA': 50, 'US': 150
}

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'PL': 'Польша', 'UA': 'Украина', 'KZ': 'Казахстан',
    'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва', 'AT': 'Австрия',
    'CZ': 'Чехия', 'BG': 'Болгария', 'IT': 'Италия', 'ES': 'Испания'
}

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            r = requests.get(MMDB_URL, stream=True)
            with open(MMDB_FILE, 'wb') as f:
                for chunk in r.iter_content(1024): f.write(chunk)
        except: pass

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: pass

def get_ip_country(ip):
    if not geo_reader: return 'XX'
    try: return geo_reader.country(ip).country.iso_code
    except: return 'XX'

def extract_links(text):
    return re.findall(r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)", text)

def parse_vless(link, source_type):
    try:
        part = link.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
        else:
            return None
            
        query = link.split("?")[1].split("#")[0]
        params = parse_qs(query)
        
        return {
            "ip": host, "port": int(port), "original": link,
            "uuid": link.split("@")[0].replace("vless://", ""),
            "transport": params.get('type', ['tcp'])[0],
            "security": params.get('security', ['none'])[0],
            "flow": params.get('flow', [''])[0],
            "sni": params.get('sni', [''])[0],
            "fp": params.get('fp', ['chrome'])[0],
            "path": params.get('path', ['/'])[0],
            "pbk": params.get('pbk', [''])[0],
            "sid": params.get('sid', [''])[0],
            "source_type": source_type,
            "latency": 9999, "real_delay": 9999
        }
    except: return None

def tcp_ping(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        start = time.perf_counter()
        if sock.connect_ex((host, port)) == 0:
            return (time.perf_counter() - start) * 1000
        sock.close()
    except: pass
    return None

def generate_xray_config(server, local_port):
    outbound = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": server['ip'],
                "port": server['port'],
                "users": [{"id": server['uuid'], "encryption": "none", "flow": server['flow']}]
            }]
        },
        "streamSettings": {
            "network": server['transport'],
            "security": server['security'],
        }
    }
    
    s = outbound["streamSettings"]
    if server['security'] == 'reality':
        s['realitySettings'] = {
            "publicKey": server['pbk'], "shortId": server['sid'], 
            "serverName": server['sni'], "fingerprint": server['fp']
        }
    elif server['security'] == 'tls':
        s['tlsSettings'] = {"serverName": server['sni'], "fingerprint": server['fp']}
        
    if server['transport'] == 'ws':
        s['wsSettings'] = {"path": server['path'], "headers": {"Host": server['sni']}}
    elif server['transport'] == 'grpc':
        s['grpcSettings'] = {"serviceName": server['path']}

    config = {
        "log": {"loglevel": "none"}, # Отключаем логи для скорости
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound]
    }
    return config

# Функция-обертка для параллельного запуска
def check_real_server_wrapper(args):
    server, unique_id = args
    local_port = 10000 + unique_id
    
    conf_name = f"config_{local_port}.json"
    config = generate_xray_config(server, local_port)
    
    with open(conf_name, 'w') as f: json.dump(config, f)
    
    proc = subprocess.Popen([XRAY_BIN, "-c", conf_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4) # Чуть уменьшили время на старт
    
    success = False
    delay = 9999
    
    try:
        proxies = {'http': f'socks5://127.0.0.1:{local_port}', 'https': f'socks5://127.0.0.1:{local_port}'}
        start = time.perf_counter()
        # Используем таймаут 4 сек для реальной проверки
        r = requests.get('http://cp.cloudflare.com/', proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        if r.status_code == 204 or r.status_code == 200:
            delay = (time.perf_counter() - start) * 1000
            success = True
    except: pass
    finally:
        proc.terminate()
        try: os.remove(conf_name)
        except: pass
        
    if success:
        return True, delay, server
    return False, 9999, server

def process_batch(servers):
    valid = []
    for s in servers:
        s['country'] = get_ip_country(s['ip'])
        if s['country'] in BANNED_COUNTRIES: continue
        
        p = tcp_ping(s['ip'], s['port'])
        if p:
            s['latency'] = int(p)
            valid.append(s)
    return valid

def run_tournament(candidates, needed, title):
    if not candidates: return []
    
    # Берем ТОП-30 кандидатов по TCP (больше выборка для надежности)
    candidates.sort(key=lambda x: x['latency'])
    semi_finalists = candidates[:30]
    
    print(f"\n🏟️ {title} (Parallel checking {len(semi_finalists)} candidates)...")
    
    real_winners = []
    
    # ПАРАЛЛЕЛЬНЫЙ ЗАПУСК XRAY
    # Используем 8 потоков для Xray (безопасно для 2-core CPU на GitHub)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Передаем (сервер, уникальный_id) чтобы порты не пересекались
        tasks = [(s, i) for i, s in enumerate(semi_finalists)]
        results = list(executor.map(check_real_server_wrapper, tasks))
        
        for success, delay, s in results:
            if success:
                s['real_delay'] = int(delay)
                # Штраф Universal серверам из СНГ (чтобы не перебивали Европу пингом)
                tier_penalty = 0
                if title == "UNIVERSAL CUP" and s['country'] in ['RU', 'KZ', 'UA', 'BY']:
                    tier_penalty = 1000 
                
                s['score'] = s['real_delay'] + tier_penalty
                print(f"   ✅ {s['country']} | TCP: {s['latency']}ms | REAL: {int(delay)}ms")
                real_winners.append(s)
            else:
                print(f"   ❌ {s['country']} | TCP: {s['latency']}ms | REAL: FAIL")

    real_winners.sort(key=lambda x: x['score'])
    return real_winners[:needed]

def main():
    print("--- STARTING V70 (TURBO XRAY) ---")
    download_mmdb()
    init_geoip()
    
    # 1. СБОР ССЫЛОК (Параллельно)
    all_raw = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        f1 = ex.submit(lambda: [parse_vless(l, 'gen') for u in GENERAL_URLS for l in extract_links(requests.get(u, timeout=5).text)])
        f2 = ex.submit(lambda: [parse_vless(l, 'white') for u in WHITELIST_URLS for l in extract_links(requests.get(u, timeout=5).text)])
        try:
            all_raw = [x for x in (f1.result() + f2.result()) if x]
        except:
            print("Error downloading sources")
            return

    unique = list({s['original']: s for s in all_raw}.values())
    print(f"Total Unique Configs: {len(unique)}")
    
    # 2. МАССОВЫЙ TCP ПИНГ (100 потоков - безопасно для IO операций)
    tcp_survivors = []
    print("🚀 Mass TCP Pinging...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
        chunk_size = 50
        chunks = [unique[i:i + chunk_size] for i in range(0, len(unique), chunk_size)]
        for res in ex.map(process_batch, chunks):
            tcp_survivors.extend(res)
            
    print(f"TCP Survivors: {len(tcp_survivors)}")
    
    gaming_pool = [s for s in tcp_survivors if s['country'] in ['FI','SE','EE','DE','NL'] and s['latency'] < 80]
    universal_pool = [s for s in tcp_survivors if s['source_type'] == 'gen']
    whitelist_pool = [s for s in tcp_survivors if s['source_type'] == 'white' or s['country'] == 'RU']
    
    final_list = []
    
    # 3. ФИНАЛЫ (Параллельный Xray)
    final_list.extend(run_tournament(gaming_pool, TARGET_GAME, "GAME CUP"))
    final_list.extend(run_tournament(universal_pool, TARGET_UNIVERSAL, "UNIVERSAL CUP"))
    final_list.extend(run_tournament(whitelist_pool, TARGET_WHITELIST, "WHITELIST CUP"))
    
    # 4. СОХРАНЕНИЕ
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=3)
    
    json_data = {"updated_at": msk_now.strftime('%H:%M'), "servers": []}
    result_links = [f"vless://fake@1.1.1.1:80?#{quote(f'Обновлено: {msk_now.strftime('%H:%M')}')}"]
    
    for s in final_list:
        flag = "".join([chr(127397 + ord(c)) for c in s['country'].upper()])
        name_c = RUS_NAMES.get(s['country'], s['country'])
        
        cat = "UNIVERSAL"
        if s in gaming_pool and s['score'] < 100: cat = "GAMING"
        if s['country'] == 'RU': cat = "WHITELIST"
        
        label = f"⚡ {flag} {name_c} | {s['real_delay']}ms"
        if cat == 'GAMING': label = f"🎮 {flag} {name_c} | {s['real_delay']}ms"
        if cat == 'WHITELIST': label = f"⚪ {flag} {name_c} | {s['real_delay']}ms"
        
        final_link = f"{s['original'].split('#')[0]}#{quote(label)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": label, "country": name_c, "iso": s['country'],
            "ping": s['real_delay'], "ip": s['ip'], "link": final_link,
            "category": cat, "protocol": s['transport'].upper(), "type": "VLESS"
        })
        
    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"DONE. Saved {len(final_list)} verified servers.")

if __name__ == "__main__":
    main()
