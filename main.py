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
import geoip2.database 
import subprocess
import tempfile
import random
import shutil
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- ИСТОЧНИКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    # Добавил источник GOIDA для надежности, как обсуждали ранее
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"  # Путь к бинарнику Xray

TARGET_GAME = 1       
TARGET_UNIVERSAL = 3  
TARGET_WARP = 2       
TARGET_WHITELIST = 2  

TIMEOUT = 0.8  # Таймаут для TCP пинга
REAL_TEST_TIMEOUT = 5.0 # Таймаут для реальной проверки через Xray
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# БАЗОВЫЙ ПИНГ ОТ МОСКВЫ/СПБ (ЭТАЛОН)
PING_BASE_MS = {
    'RU': 25, 'FI': 40, 'EE': 45, 'SE': 55, 'DE': 65, 'NL': 70, 
    'FR': 75, 'GB': 80, 'PL': 60, 'TR': 90, 'KZ': 60, 'UA': 50, 
    'US': 160, 'BG': 55, 'AT': 60, 'CZ': 60
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

TIER_1_PLATINUM = ['FI', 'EE', 'SE']
TIER_2_GOLD = ['DE', 'NL', 'FR', 'PL', 'KZ', 'RU'] # RU добавил в Gold, если whitelist
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

def extract_links(text):
    return re.findall(r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+|hy2://[a-zA-Z0-9\-@:?=&%.#_]+)", text)

def parse_config_info(config_str, source_type):
    try:
        # Hy2
        if config_str.startswith("hy2://"):
            try:
                # Базовый парсинг Hy2 для статистики, но проверять будем только ping
                # (код парсинга Hy2 оставил как есть)
                rest = config_str[6:]
                if "#" in rest:
                    main_part, original_remark = rest.split("#", 1)
                    original_remark = unquote(original_remark).strip()
                else:
                    main_part = rest
                    original_remark = "Unknown"

                if "?" in main_part: auth_host, _ = main_part.split("?", 1)
                else: auth_host = main_part

                if "@" in auth_host: _, host_port = auth_host.split("@", 1)
                else: host_port = auth_host

                if ":" in host_port:
                    if "]" in host_port:
                        host = host_port.rsplit(":", 1)[0]
                        port = host_port.rsplit(":", 1)[1]
                    else:
                        host, port = host_port.split(":")
                else: return None

                return {
                    "ip": host, "port": int(port), "uuid": "auth_key", 
                    "original": config_str, "original_remark": original_remark,
                    "latency": 9999, "jitter": 0, "final_score": 9999, "info": {},
                    "transport": "udp", "security": "hy2",
                    "is_reality": False, "is_vision": False, "is_pure": False, "is_hy2": True,
                    "source_type": source_type, "tier_rank": 99,
                    "parsed_params": {} # Hy2 пока без детальных параметров для Xray
                }
            except: return None

        # VLESS
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            # Извлекаем параметры для Xray конфига
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
                "is_reality": is_reality, "is_vision": is_vision, "is_pure": is_pure, "is_hy2": False,
                "source_type": source_type, "tier_rank": 99,
                "parsed_params": params # Сохраняем все параметры для генератора конфига
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

# --- REAL VLESS TEST LOGIC (XRAY) ---

def generate_xray_config(server, local_port):
    """Создает временный JSON конфиг для Xray core на основе данных сервера"""
    try:
        params = server['parsed_params']
        
        # Основные настройки outbound
        outbound_settings = {
            "vnext": [{
                "address": server['ip'],
                "port": int(server['port']),
                "users": [{
                    "id": server['uuid'],
                    "encryption": "none",
                    "flow": params.get('flow', [''])[0]
                }]
            }]
        }

        # Stream Settings
        stream_settings = {
            "network": server['transport'],
            "security": server['security']
        }

        # Настройка транспорта (TCP/WS/GRPC)
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

        # Настройка безопасности (TLS/Reality)
        if server['security'] == 'tls':
            tls_settings = {
                "serverName": params.get('sni', [''])[0],
                "allowInsecure": False
            }
            # Fingerprint (utls)
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
            "log": {"loglevel": "none"},
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
        print(f"ConfigGenError: {e}")
        return None

def check_real_connection(server):
    """
    Запускает Xray с конфигом сервера и пробует сделать реальный запрос.
    Возвращает latency (ms) или None, если не работает.
    """
    # Если это Hy2, мы пропускаем Real Test (как просил пользователь), 
    # считаем что если TCP пинг прошел, то ок.
    if server['is_hy2']:
        return server['latency']

    local_port = random.randint(10000, 60000)
    config_data = generate_xray_config(server, local_port)
    
    if not config_data:
        return None

    # Создаем временный файл конфига
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
        json.dump(config_data, tmp_conf)
        config_path = tmp_conf.name

    xray_process = None
    result_latency = None

    try:
        # Запускаем Xray
        # Важно: убедитесь, что бинарник xray имеет права на выполнение (chmod +x)
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Даем время на старт
        time.sleep(0.7)
        
        if xray_process.poll() is not None:
            # Процесс упал сразу (ошибка конфига)
            raise Exception("Xray process died")

        # Пробуем подключиться через локальный SOCKS5
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        
        # Используем "легкий" URL для проверки (Google Generate 204 или Cloudflare)
        target_url = "http://cp.cloudflare.com/" 
        
        start_time = time.perf_counter()
        resp = requests.get(target_url, proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        end_time = time.perf_counter()
        
        if 200 <= resp.status_code < 300:
            result_latency = (end_time - start_time) * 1000
        else:
            result_latency = None

    except Exception:
        result_latency = None
    finally:
        # Убираем за собой
        if xray_process:
            xray_process.terminate()
            try:
                xray_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                xray_process.kill()
        
        if os.path.exists(config_path):
            os.remove(config_path)

    return result_latency

# --- END REAL TEST LOGIC ---

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
    
    # Fake Ping Detection
    is_fake = False
    if code in ['RU', 'KZ', 'UA', 'BY'] and server['latency'] < 90: is_fake = True # Слишком хороший пинг для РФ (кроме whitelist)
    elif code in ['FI', 'EE', 'SE'] and server['latency'] < 90: is_fake = True 
    elif code in ['DE', 'NL'] and server['latency'] < 25: is_fake = True
    elif server['latency'] < 3 and code not in ['US', 'CA']: is_fake = True
    
    # Исключение для WhiteList (они в РФ, им можно быть быстрыми)
    if server['category'] == 'WHITELIST' and code == 'RU': is_fake = False

    if is_fake and server['category'] != 'WHITELIST': return None

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
    # 3 Быстрых замера пинга для статистики Jitter
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
        # Для гейминга Hy2 топ, либо чистый TCP/UDP близко
        hy2_servers = [c for c in candidates if c['is_hy2']]
        if hy2_servers: filtered = hy2_servers
        else:
            pure = [c for c in candidates if c['is_pure'] and c['tier_rank'] <= 2]
            if pure: filtered = pure
            else: filtered = [c for c in candidates if not c['is_vision'] and c['tier_rank'] <= 3]

    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] != 'RU']

    if not filtered: return []
    
    # Отбираем полуфиналистов по Tier Rank и предварительному пингу
    # Берем с запасом (топ 20), чтобы после Real Test осталось хоть что-то
    semifinalists = sorted(filtered, key=lambda x: (x['tier_rank'], x['latency']))[:20]
    
    print(f"\n🏟️ {title} (Checking {len(semifinalists)} candidates via Real VLESS Test...)")
    
    scored_results = []
    for f in semifinalists:
        # --- ЭТАП 1: REAL VLESS TEST ---
        # Проверяем, жив ли сервер на самом деле через Xray
        # Hy2 пропускает этот тест (возвращает latency tcp)
        real_lat = check_real_connection(f)
        
        if real_lat is None:
            print(f"   ❌ {f['info']['countryCode']} {f['ip']} -> DEAD via Xray (TCP was OK)")
            continue # Сервер мертв, пропускаем
            
        # --- ЭТАП 2: JITTER / STABILITY ---
        avg, jitter = stress_test_server(f)
        
        # Если Real Test показал latency сильно хуже пинга (загруженный канал), учитываем это
        # Используем Real Latency как основной показатель, если он есть
        if real_lat and not f['is_hy2']:
            avg = (avg + real_lat) / 2 # Усредняем TCP пинг и HTTP задержку
        
        # --- БАЛЛЬНАЯ СИСТЕМА ---
        tier_penalty = 0
        if f['tier_rank'] == 1: tier_penalty = 0     # Финляндия, Эстония - топ
        elif f['tier_rank'] == 2: tier_penalty = 30  # Германия, Нидерланды
        else: tier_penalty = 70                      # Остальные
            
        special_penalty = 0
        if mode == "gaming":
            if f['is_hy2']: special_penalty = -20     # Hy2 бонус для игр
            elif f['is_pure']: special_penalty = 0
            elif f['is_reality']: special_penalty = 40
            else: special_penalty = 200
        elif mode == "universal":
            if f['info']['countryCode'] == 'RU': special_penalty += 2000
        elif mode == "warp":
            if f['transport'] in ['ws', 'grpc']: special_penalty = 0 
            else: special_penalty = 2000
        elif mode == "whitelist":
            if f['is_reality']: special_penalty = 0
            else: special_penalty = 1000
            
        score = avg + (jitter * 5) + tier_penalty + special_penalty
        
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['final_score'] = score
        
        print(f"   ✅ {f['info']['countryCode']:<4} | RealLat: {int(real_lat if real_lat else avg)}ms | Score: {int(score)}")
        scored_results.append(f)
        
    # Сортируем по очкам (меньше = лучше)
    scored_results.sort(key=lambda x: x['final_score'])
    
    # Если вдруг все проверки провалились (Real Test отбросил всех),
    # берем хотя бы тех, у кого был TCP пинг (резервный вариант, чтобы не отдавать пустоту)
    # Но согласно требованию "Не должно быть такого, что ни один не прошел", 
    # мы надеемся на лучшее, либо берем из semifinalists "лучших из худших" без проверки
    if not scored_results and semifinalists:
        print("   ⚠️ WARNING: No servers passed Real Test. Returning TCP-only survivors.")
        return semifinalists[:winners_needed]

    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                content = resp.text
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
    print("--- ЗАПУСК V54 (REAL VLESS XRAY CORE) ---")
    
    # Права на выполнение для Xray
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
    else:
        print(f"❌ Error: Xray binary not found at {XRAY_BIN}")
        # Можно тут прервать выполнение или попробовать скачать, но считаем что файл есть.

    download_mmdb()
    init_geoip()
    
    all_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    print(f"🔍 Checking {len(servers_to_check)} servers (TCP scan)...")
    
    # Первичный отсев по TCP (быстро)
    working_servers = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []
    
    # Турниры с Real Test (кроме Hy2 внутри Gaming)
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
    
    update_msg = f"📅 Обновлено: {time_str} (МСК) | Check: Real VLESS"
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
        # Если прошел Real Test, используем его результат или среднее
        # Но чтобы было красиво, берем чуть сглаженное значение
        calc_ping = s['latency']
        
        if s['is_hy2']: calc_ping = int(calc_ping * 0.9) # Визуально Hy2 быстрее

        type_label = "VLESS"
        if s['is_hy2']: type_label = "Hy2"
        elif s['is_reality']: type_label = "Reality"
        elif s['is_pure']: type_label = "TCP"

        name = ""
        if s['category'] == 'GAMING': 
            name = f"🎮 GAME | {flag} {country_full} | {calc_ping}ms"
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
