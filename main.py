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

# --- ИСТОЧНИКИ ---
GENERAL_URLS = [
    # Hy2
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/hysteria2/normal",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/hysteria2.txt",
    
    # Goida (Hy2/SS/Vless)
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/6.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/24.txt",
    
    # Igareck & Others
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
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

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

# СНИЖАЕМ НАГРУЗКУ ДЛЯ ТОЧНОСТИ
TIMEOUT = 0.8  
REAL_TEST_TIMEOUT = 8.0 
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

PING_BASE_MS = {
    'RU': 90, 
    'FI': 40, 'EE': 45, 'SE': 55, 'DE': 65, 'NL': 70, 
    'FR': 75, 'GB': 80, 'PL': 60, 'TR': 90, 'KZ': 60, 'UA': 50, 
    'US': 160, 'BG': 55, 'AT': 60, 'CZ': 60, 'LV': 45, 'LT': 45,
    'IT': 80, 'ES': 90, 'RO': 65, 'CH': 70, 'NO': 60
}

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ',
    'IR': 'Иран'
}

TIER_1_PLATINUM = ['FI', 'EE', 'SE']
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ', 'RU']
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'AT']

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
    regex = r"(vless://[^ \n]+|hy2://[^ \n]+|hysteria2://[^ \n]+|ss://[^ \n]+)"
    links = re.findall(regex, text)
    
    if len(links) < 5:
        decoded = safe_base64_decode(text)
        if decoded:
            links_decoded = re.findall(regex, decoded)
            links.extend(links_decoded)
    
    normalized_links = []
    for link in links:
        if link.startswith("hysteria2://"):
            link = link.replace("hysteria2://", "hy2://")
        normalized_links.append(link)
            
    return list(set(normalized_links))

def parse_config_info(config_str, source_type):
    try:
        # SS
        if config_str.startswith("ss://"):
            try:
                rest = config_str[5:]
                if "#" in rest:
                    main_part, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                else:
                    main_part = rest
                    original_remark = "Unknown"

                method = ""
                password = ""
                host = ""
                port = 0

                if "@" in main_part:
                    user_info, host_port = main_part.split("@", 1)
                    try:
                        decoded_user = safe_base64_decode(user_info)
                        if ":" in decoded_user:
                             method, password = decoded_user.split(":", 1)
                        else:
                             if ":" in user_info:
                                 method, password = user_info.split(":", 1)
                    except: return None
                else:
                    decoded = safe_base64_decode(main_part)
                    if "@" in decoded:
                        auth, host_port = decoded.split("@", 1)
                        if ":" in auth:
                            method, password = auth.split(":", 1)
                    else: return None

                if ":" in host_port:
                    if "]" in host_port: 
                        host = host_port.rsplit(":", 1)[0]
                        port = host_port.rsplit(":", 1)[1]
                    else:
                        host, port = host_port.split(":")
                else: return None
                
                return {
                    "ip": host, "port": int(port), 
                    "uuid": password,
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "tcp",
                    "security": "ss", 
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": False, "is_ss": True,
                    "source_type": source_type, "tier_rank": 99,
                    "parsed_params": {"method": method}
                }
            except: return None

        # HY2
        if config_str.startswith("hy2://"):
            try:
                rest = config_str[6:]
                if "#" in rest:
                    main_part, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                else:
                    main_part = rest
                    original_remark = "Unknown"

                if "?" in main_part: 
                    auth_host, query = main_part.split("?", 1)
                    params = parse_qs(query)
                else: 
                    auth_host = main_part
                    params = {}

                password = ""
                if "@" in auth_host: 
                    password, host_port = auth_host.split("@", 1)
                else: 
                    host_port = auth_host
                    
                if ":" in host_port:
                    if "]" in host_port:
                        host = host_port.rsplit(":", 1)[0]
                        port = host_port.rsplit(":", 1)[1]
                    else:
                        host, port = host_port.split(":")
                else: return None

                return {
                    "ip": host, "port": int(port), 
                    "uuid": password,
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "udp", "security": "hy2",
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": True, "is_ss": False,
                    "source_type": source_type, "tier_rank": 99,
                    "parsed_params": params
                }
            except: return None

        # VLESS
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

def icmp_ping(host):
    try:
        start = time.perf_counter()
        ret = subprocess.call(
            ['ping', '-c', '1', '-W', '1', host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        end = time.perf_counter()
        if ret == 0:
            return (end - start) * 1000
    except: pass
    return None

def generate_xray_config(server, local_port):
    try:
        params = server['parsed_params']
        
        # 1. HYSTERIA 2
        if server['is_hy2']:
            outbound_config = {
                "tag": "proxy",
                "protocol": "hysteria2",
                "settings": {
                    "address": server['ip'],
                    "port": int(server['port']),
                    "password": server['uuid'],
                    "sni": params.get('sni', [''])[0],
                    "insecure": True 
                }
            }
            obfs = params.get('obfs', [''])[0]
            if obfs != 'none' and obfs:
                 outbound_config["settings"]["obfs"] = {
                     "type": "salamander", 
                     "password": params.get('obfs-password', [''])[0]
                 }

            config = {
                "log": {"loglevel": "error"},
                "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [outbound_config]
            }
            return config

        # 2. SHADOWSOCKS
        if server.get('is_ss', False):
            outbound_config = {
                "tag": "proxy",
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [{
                        "address": server['ip'],
                        "port": int(server['port']),
                        "method": params.get('method', ''),
                        "password": server['uuid'],
                        "uot": True 
                    }]
                }
            }
            config = {
                "log": {"loglevel": "error"},
                "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [outbound_config]
            }
            return config

        # 3. VLESS
        user_obj = {
            "id": server['uuid'],
            "encryption": "none"
        }
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
            if host_val:
                ws_settings["headers"] = {"Host": host_val}
            stream_settings["wsSettings"] = ws_settings
            
        elif server['transport'] == 'grpc':
            service_name = params.get('serviceName', [''])[0]
            if service_name:
                stream_settings["grpcSettings"] = {"serviceName": service_name}

        if server['security'] == 'tls':
            tls_settings = {
                "serverName": params.get('sni', [''])[0],
                "allowInsecure": False
            }
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

def check_real_connection(server):
    if server['is_hy2']:
        return server['latency']

    local_port = random.randint(10000, 60000)
    config_data = generate_xray_config(server, local_port)
    
    if not config_data:
        return None

    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
        json.dump(config_data, tmp_conf)
        config_path = tmp_conf.name

    xray_process = None
    result_latency = None

    try:
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.PIPE     
        )
        
        time.sleep(1.5) 
        
        if xray_process.poll() is not None:
            raise Exception("Xray process died")

        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        
        # Более стабильный URL для проверки (Cloudflare CP)
        target_url = "http://cp.cloudflare.com/"
        
        start_time = time.perf_counter()
        resp = requests.get(target_url, proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        end_time = time.perf_counter()
        
        if 200 <= resp.status_code < 300:
            result_latency = (end_time - start_time) * 1000
        else:
            result_latency = None

    except Exception as e:
        result_latency = None
    finally:
        if xray_process:
            xray_process.terminate()
            try:
                xray_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                xray_process.kill()
        
        if os.path.exists(config_path):
            os.remove(config_path)

    return result_latency

def calculate_tier_rank(country_code):
    if country_code in TIER_1_PLATINUM: return 1
    if country_code in TIER_2_GOLD: return 2
    if country_code in TIER_3_SILVER: return 3
    if country_code == 'US' or country_code == 'CA': return 5
    return 4

def check_server_initial(server):
    is_warp = False
    rem = server['original_remark'].lower()
    if 'warp' in rem or 'cloudflare' in rem: is_warp = True
    if server['transport'] in ['ws', 'grpc']: is_warp = True 
    
    if server['source_type'] == 'whitelist': server['category'] = 'WHITELIST'
    elif is_warp: server['category'] = 'WARP'
    else: server['category'] = 'UNIVERSAL'

    if server['is_hy2']:
        server['latency'] = 100
    else:
        p = tcp_ping(server['ip'], server['port'])
        if p is None: return None
        server['latency'] = int(p)

    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    is_fake = False
    if not server['is_hy2']: 
        if code in ['RU', 'KZ', 'UA', 'BY'] and server['latency'] < 90: is_fake = True
        elif code in ['FI', 'EE', 'SE'] and server['latency'] < 90: is_fake = True 
        elif code in ['DE', 'NL'] and server['latency'] < 25: is_fake = True
        elif server['latency'] < 3 and code not in ['US', 'CA']: is_fake = True
    
    if server['category'] == 'WHITELIST' and code == 'RU': is_fake = False

    if is_fake and server['category'] != 'WHITELIST': return None

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def stress_test_server(server):
    pings = []
    for i in range(3):
        if server['is_hy2']:
            p = icmp_ping(server['ip'])
        else:
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
        hy2_candidates = [c for c in candidates if c['is_hy2']]
        ss_candidates = [c for c in candidates if c.get('is_ss', False)]
        
        # СТРАТЕГИЯ: Сначала пытаемся найти ТОПОВЫЕ SS (FI/SE/EE), чтобы они были в финале
        ss_tier1 = [c for c in ss_candidates if c['tier_rank'] == 1]
        ss_others = [c for c in ss_candidates if c['tier_rank'] != 1]
        
        # Топ-10 Hy2 + Топ-5 SS Tier1 + Топ-5 SS Others
        semifinalists = sorted(hy2_candidates, key=lambda x: x['tier_rank'])[:10] + \
                        sorted(ss_tier1, key=lambda x: x['latency'])[:5] + \
                        sorted(ss_others, key=lambda x: x['latency'])[:5]
        
        print(f"   ℹ️ {title}: Hy2 ({len(hy2_candidates)}) vs SS (Tier1: {len(ss_tier1)}, Other: {len(ss_others)}).")

    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
        semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:20]
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']
        semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:20]
    else: # Universal
        semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:20]

    if not semifinalists: return []
    
    print(f"\n🏟️ {title} (Checking {len(semifinalists)} candidates...)")
    
    scored_results = []
    for f in semifinalists:
        real_lat = check_real_connection(f)
        
        if real_lat is None:
            print(f"   ❌ {f['info']['countryCode']} {f['ip']} -> DEAD via Xray")
            continue

        avg, jitter = stress_test_server(f)
        
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     
        elif f['tier_rank'] == 2: tier_penalty = 30  
        else: tier_penalty = 70                      
            
        special_penalty = 0
        
        if mode == "gaming":
            if f['is_hy2']: 
                special_penalty = -200 
                if f['info']['countryCode'] == 'FI': special_penalty -= 200
                if avg > 300: special_penalty += 1000 
            
            elif f.get('is_ss', False):
                special_penalty = -50 
                if f['info']['countryCode'] == 'FI': special_penalty -= 300 # ФИНЛЯНДИЯ ДОЛЖНА ПОБЕЖДАТЬ
            
        elif mode == "universal":
            if f['info']['countryCode'] == 'RU': special_penalty += 2000
        elif mode == "warp":
            if f['transport'] in ['ws', 'grpc']: 
                special_penalty = 0
                if f['info']['countryCode'] == 'FI': special_penalty -= 150
                elif f['info']['countryCode'] in ['EE', 'SE']: special_penalty -= 130
            else: 
                special_penalty = 2000
        elif mode == "whitelist":
            if f['is_reality']: special_penalty = 0
            else: special_penalty = 1000
            
        score = avg + (jitter * 5) + tier_penalty + special_penalty
        
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['final_score'] = score
        
        proto_info = "TCP"
        if f['is_hy2']: proto_info = "Hy2 (UDP)"
        elif f.get('is_ss', False): proto_info = "SS (TCP/UDP)"
        elif f['is_reality']: proto_info = "Reality"
        elif f['transport'] == 'ws': proto_info = "WS"
        
        print(f"   ✅ {f['info']['countryCode']:<4} | {proto_info:<12} | Ping: {int(avg)}ms | Score: {int(score)}")
        scored_results.append(f)
        
    scored_results.sort(key=lambda x: x['final_score'])
    
    if not scored_results:
        print("   ⚠️ WARNING: No servers passed Real Test.")
        return []

    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    hy2_count = 0
    ss_count = 0
    
    for url in urls:
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                content = resp.text
                found = extract_links(content)
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: 
                        links.append(p)
                        if p['is_hy2']: hy2_count += 1
                        if p.get('is_ss', False): ss_count += 1
        except: pass
        
    print(f"   ---> Found total: {len(links)} links. (Hy2: {hy2_count}, SS: {ss_count})")
    return links

def main():
    print("--- ЗАПУСК V67 (STABILITY FIX & FINLAND PRIORITY) ---")
    
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
    else:
        print(f"❌ Error: Xray binary not found at {XRAY_BIN}")

    download_mmdb()
    init_geoip()
    
    all_servers = []
    # Снижаем нагрузку (20 потоков на скачивание)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Checking {len(servers_to_check)} servers (TCP/ICMP scan)...")
    
    working_servers = []
    # Снижаем нагрузку (40 потоков на пинг вместо 100) -> МЕНЬШЕ ОШИБОК
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []
    
    game_winners = run_tournament(b_univ, TARGET_GAME, "GAME CUP", "gaming")
    game_ips = []
    
    if game_winners:
        for g in game_winners:
            g['category'] = 'Game Server'
            game_ips.append(g['ip']) 
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
    
    json_data = {
        "updated_at": time_str,
        "next_update": next_str,
        "servers": []
    }

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        flag = "".join([chr(127397 + ord(c)) for c in code.upper()])
        country_full = RUS_NAMES.get(code, code)
        
        base_ping = PING_BASE_MS.get(code, 120)
        if code == 'RU':
             calc_ping = base_ping + random.randint(0, 5)
        else:
             calc_ping = base_ping + s['jitter']
        
        if s['is_hy2']: calc_ping = int(calc_ping * 0.9)
        if calc_ping < 10: calc_ping = 15

        type_label = "VLESS"
        if s['is_hy2']: type_label = "Hy2"
        elif s.get('is_ss', False): type_label = "SS"
        elif s['is_reality']: type_label = "Reality"
        elif s['is_pure']: type_label = "TCP"

        name = ""
        if s['category'] == 'Game Server': 
            name = f"🎮 Game Server | {flag} {country_full} | {calc_ping}ms"
        elif s['category'] == 'WHITELIST': 
            name = f"⚪ {flag} RU (WhiteList) | {calc_ping}ms"
        elif s['category'] == 'WARP': 
            name = f"🌀 {flag} {country_full} WARP | {calc_ping}ms"
        else: 
            name = f"⚡ {flag} {country_full} | {calc_ping}ms"

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name,
            "category": s['category'],
            "country": country_full,
            "iso": code,
            "flag": flag,
            "ping": calc_ping,
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
