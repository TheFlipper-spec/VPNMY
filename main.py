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
    # Goida (Источник SS и Reality)
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/6.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/24.txt",
    
    # Igareck (База)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",

    # Типо одни из самых лучших
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",

    # FreeVPNKeys
    "https://freevpnkeys.com/wp-content/uploads/vpn-subscriptions/raw.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

TARGET_GAME = 2       
TARGET_UNIVERSAL = 5  
TARGET_WARP = 2       
TARGET_WHITELIST = 3  

# ТАЙМАУТЫ
TIMEOUT = 0.8           # Быстрый TCP чек (предварительный отсев)
REAL_TEST_TIMEOUT = 5.0 # Xray чек (реальная загрузка)
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ'
}

# Приоритет стран для игр/скорости
TIER_1_PLATINUM = ['FI', 'EE', 'SE', 'RU'] # RU тут, если сервер быстрый
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ']
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'AT']

geo_reader = None

def get_free_port():
    """Находит гарантированно свободный порт"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            print("📥 Downloading GeoIP database...")
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(MMDB_URL, stream=True, headers=headers, timeout=20)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        except Exception as e: 
            print(f"⚠️ MMDB Download failed: {e}")

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: pass

def get_ip_country_local(ip):
    if not geo_reader: return 'XX'
    try: return geo_reader.country(ip).country.iso_code
    except: return 'XX'

def safe_base64_decode(s):
    """Надежное декодирование Base64 (URL-safe и стандарт)"""
    s = s.strip().replace('\n', '').replace('\r', '')
    # Добиваем паддинг
    s += '=' * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s).decode('utf-8', errors='ignore')
    except:
        try:
            return base64.b64decode(s).decode('utf-8', errors='ignore')
        except:
            return ""

def extract_links(text):
    # Улучшенный regex
    regex = r"(vless://[a-zA-Z0-9\-\_\=\:\@\.\?\&\#\%]+|ss://[a-zA-Z0-9\-\_\=\:\@\.\#]+)"
    links = re.findall(regex, text)
    if len(links) < 2:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_config_info(config_str, source_type):
    try:
        # --- SHADOWSOCKS ---
        if config_str.startswith("ss://"):
            try:
                # Парсинг SIP002 и старых форматов
                rest = config_str[5:]
                original_remark = "Unknown"
                if "#" in rest:
                    rest, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                
                if "@" in rest:
                    # user:pass@host:port
                    user_part, host_part = rest.split("@", 1)
                    # user_part может быть base64
                    try:
                        decoded_user = safe_base64_decode(user_part)
                        if decoded_user and ":" in decoded_user:
                            method, password = decoded_user.split(":", 1)
                        elif ":" in user_part:
                            method, password = user_part.split(":", 1)
                        else:
                            return None # Invalid SS
                    except: return None
                else:
                    # Вся строка в base64 (старый формат)
                    decoded = safe_base64_decode(rest)
                    if not decoded: return None
                    if "@" in decoded:
                        auth, host_part = decoded.split("@", 1)
                        if ":" in auth: method, password = auth.split(":", 1)
                        else: return None
                    else: return None

                # Host Parsing IPv4/IPv6
                if "]" in host_part:
                    host = host_part.rsplit(":", 1)[0]
                    port = host_part.rsplit(":", 1)[1]
                elif ":" in host_part:
                    host, port = host_part.split(":")
                else: return None

                return {
                    "ip": host, "port": int(port), 
                    "uuid": password,
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "tcp", "security": "ss", 
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": False, "is_ss": True,
                    "source_type": source_type, "tier_rank": 99,
                    "parsed_params": {"method": method}
                }
            except: return None

        # --- VLESS ---
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
        
        # 1. SHADOWSOCKS
        if server.get('is_ss', False):
            outbound = {
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
        # 2. VLESS
        else:
            user_obj = {"id": server['uuid'], "encryption": "none"}
            if params.get('flow', [''])[0]: user_obj["flow"] = params.get('flow', [''])[0]

            outbound_settings = {
                "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [user_obj]}]
            }

            stream_settings = {"network": server['transport'], "security": server['security']}

            if server['transport'] == 'ws':
                ws_settings = {"path": params.get('path', ['/'])[0]}
                if params.get('host', [''])[0]: ws_settings["headers"] = {"Host": params.get('host', [''])[0]}
                stream_settings["wsSettings"] = ws_settings
                
            elif server['transport'] == 'grpc':
                if params.get('serviceName', [''])[0]:
                    stream_settings["grpcSettings"] = {"serviceName": params.get('serviceName', [''])[0]}

            if server['security'] == 'tls':
                tls_settings = {"serverName": params.get('sni', [''])[0], "allowInsecure": True} # Allow insecure for tests
                if params.get('fp', [''])[0]: tls_settings["fingerprint"] = params.get('fp', ['chrome'])[0]
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

            outbound = {
                "tag": "proxy",
                "protocol": "vless",
                "settings": outbound_settings,
                "streamSettings": stream_settings
            }

        config = {
            "log": {"loglevel": "error"},
            "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [outbound]
        }
        return config
    except Exception as e:
        return None

def check_real_connection(server):
    """
    Полноценная проверка через Xray.
    Возвращает (latency_ms, jitter_ms) или None, если не работает.
    """
    local_port = get_free_port()
    config_data = generate_xray_config(server, local_port)
    
    if not config_data: return None

    # Уникальное имя файла для параллельности
    unique_name = f"config_{uuid.uuid4().hex}.json"
    temp_dir = tempfile.gettempdir()
    config_path = os.path.join(temp_dir, unique_name)

    xray_process = None
    result = None

    try:
        with open(config_path, 'w') as f:
            json.dump(config_data, f)

        # Запускаем Xray
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(1) # Даем время на старт
        
        if xray_process.poll() is not None:
            return None # Упал при старте

        proxies = {
            'http': f'socks5h://127.0.0.1:{local_port}',
            'https': f'socks5h://127.0.0.1:{local_port}'
        }
        
        # Тестируем на Cloudflare (быстро) или Google
        target_url = "https://cp.cloudflare.com/"
        
        latencies = []
        # Делаем 3 запроса для расчета джиттера
        for _ in range(3):
            start = time.perf_counter()
            resp = requests.get(target_url, proxies=proxies, timeout=REAL_TEST_TIMEOUT)
            end = time.perf_counter()
            
            if 200 <= resp.status_code < 300:
                latencies.append((end - start) * 1000)
            else:
                break # Ошибка
            time.sleep(0.2)

        if len(latencies) >= 2:
            avg_lat = statistics.mean(latencies)
            jitter = statistics.stdev(latencies)
            result = (avg_lat, jitter)

    except Exception as e:
        result = None
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
    """Быстрый фильтр по TCP"""
    # Категоризация
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
    
    # Фильтр совсем мертвых или подозрительно локальных
    # (Если пинг < 2мс и это не локалхост - странно, но оставим, вдруг VPS рядом)
    if server['latency'] < 1 and server['ip'] not in ['127.0.0.1', 'localhost']: 
        return None 

    server['tier_rank'] = calculate_tier_rank(code)
    return server

def process_tournament_batch(candidates, mode):
    """
    Параллельная проверка группы серверов через Xray.
    Возвращает список проверенных объектов с обновленным пингом.
    """
    checked_servers = []
    
    print(f"   🚀 Running parallel Xray test for {len(candidates)} configs...")
    
    # ПАРАЛЛЕЛЬНЫЙ ЗАПУСК REAL TEST (главное ускорение)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_server = {executor.submit(check_real_connection, s): s for s in candidates}
        
        for future in concurrent.futures.as_completed(future_to_server):
            srv = future_to_server[future]
            res = future.result()
            
            if res:
                real_avg, real_jitter = res
                
                # Штрафы для сортировки (Rank)
                score = real_avg + (real_jitter * 2)
                
                if mode == "gaming":
                    # Для игр важен джиттер и SS
                    if srv.get('is_ss', False): score -= 30
                    score += (real_jitter * 10) # Сильный штраф за джиттер
                
                elif mode == "universal":
                     if srv['info']['countryCode'] == 'RU': score += 500
                
                srv['latency'] = int(real_avg)
                srv['jitter'] = int(real_jitter)
                srv['final_score'] = score
                
                checked_servers.append(srv)
                print(f"      ✅ {srv['info']['countryCode']} | {int(real_avg)}ms (Jitter: {int(real_jitter)})")
            else:
                # print(f"      ❌ {srv['info']['countryCode']} Dead")
                pass

    return checked_servers

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    # Предварительная фильтрация по типу
    if mode == "gaming":
        filtered = [c for c in candidates if c.get('is_ss', False) or c['is_reality']]
        # Стараемся брать Tier 1
        tier1 = [c for c in filtered if c['tier_rank'] == 1]
        if len(tier1) > 5: filtered = tier1
            
    elif mode == "universal":
        filtered = [c for c in candidates if c['is_reality']]
    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']

    if not filtered: return []
    
    # Берем ТОП-25 по TCP пингу на проверку
    semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:25]
    
    print(f"\n🏟️ {title} (Testing top {len(semifinalists)} candidates)")
    
    # Запускаем параллельную проверку
    scored_results = process_tournament_batch(semifinalists, mode)
    
    # Сортируем по финальному баллу (качество)
    scored_results.sort(key=lambda x: x['final_score'])
    
    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                found = extract_links(content)
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    return links

def main():
    print("--- ЗАПУСК V69 (OPTIMIZED) ---")
    
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
    else:
        print(f"❌ Error: Xray binary not found at {XRAY_BIN}")
        # Можно тут выйти, если Xray критичен
        # return 

    download_mmdb()
    init_geoip()
    
    all_servers = []
    print("🔍 Fetching URLs...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    # Удаление дубликатов
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Found {len(servers_to_check)} unique configs. Initial TCP scan...")
    
    working_servers = []
    # Первичный быстрый отсев
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

    # Формирование вывода
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
        
        # ЧЕСТНЫЙ ПИНГ (никакого рандома)
        real_ping = s.get('latency', 999)
        if real_ping < 10: real_ping = "<10"

        name = ""
        ping_str = f"{real_ping}ms"
        
        if s['category'] == 'Game Server': 
            name = f"🎮 Game | {flag} {country_full} | {ping_str}"
        elif s['category'] == 'WHITELIST': 
            name = f"⚪ {flag} RU (WhiteList) | {ping_str}"
        elif s['category'] == 'WARP': 
            name = f"🌀 {flag} {country_full} WARP | {ping_str}"
        else: 
            name = f"⚡ {flag} {country_full} | {ping_str}"

        # Собираем ссылку обратно
        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name,
            "category": s['category'],
            "country": country_full,
            "iso": code,
            "ping": s.get('latency', 0),
            "ip": s['ip'],
            "type": s['security'].upper() if s.get('is_reality') else "TCP",
            "link": final_link
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"DONE. {len(result_links)} best servers saved.")

if __name__ == "__main__":
    main()
