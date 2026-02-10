import sys
import logging
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

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# --- ИСТОЧНИКИ (PREMIUM AGGREGATORS) ---
# Мы берем пример с Go-репозитория и используем агрегаторы, которые обновляются каждую минуту.
# Добавлен параметр ?t=... при запросе, чтобы избежать кэширования.
GENERAL_URLS = [
    # Yebekhe (Top aggregator)
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    # Barry-Far
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub/Configs/vless.txt",
    # MahdiBland
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    # Ebrasha
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    # Igareck (Best for RU)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    # MatinGhanbari
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
    # MyDan
    "https://gbr.mydan.online/configs",
    # Roaster (Bypass filters)
    "https://raw.githubusercontent.com/roaster09/V2ray_Config/main/Vless_Config_Base64.txt"
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

# БАЛАНС СКОРОСТИ
TIMEOUT = 0.7            # Тайм-аут для TCP (быстрый отсев)
REAL_TEST_TIMEOUT = 5.0  # Тайм-аут для реальной проверки (Google)
OUTPUT_FILE = 'FL1PVPN' 
JSON_FILE = 'stats.json' 
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 1

# Словарь базовых пингов для красивого отображения (если реальный тест прошел)
PING_BASE_MS = {
    'RU': 90, 'FI': 40, 'EE': 45, 'SE': 55, 'DE': 65, 'NL': 70, 
    'FR': 75, 'GB': 80, 'PL': 60, 'TR': 90, 'KZ': 60, 'UA': 50, 
    'US': 160, 'BG': 55, 'AT': 60, 'CZ': 60, 'LV': 45, 'LT': 45,
    'IT': 80, 'ES': 90, 'RO': 65, 'CH': 70, 'NO': 60
}

# SPEED OF LIGHT CHECK (Защита от фейковых гео)
# Если сервер говорит "Я из США", но пинг 5 мс - это ложь (сервер в РФ/Европе с подменой IP).
MIN_THEORETICAL_LATENCY = {
    'FI': 15, 'EE': 20, 'SE': 20, 'DE': 35, 'NL': 40, 'GB': 45, 
    'FR': 45, 'PL': 30, 'UA': 20, 'TR': 40, 'IT': 50, 'ES': 60, 
    'US': 95, 'CA': 100, 'JP': 150, 'KR': 150, 'SG': 120, 'GR': 45,
    'BG': 40, 'RO': 35, 'CH': 40, 'NO': 35
}

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ',
    'XX': 'Неизвестно', 'GR': 'Греция', 'CH': 'Швейцария'
}

TIER_1_PLATINUM = ['FI', 'EE', 'SE', 'LV', 'LT', 'PL'] # Лучшие для игр
TIER_2_GOLD = ['DE', 'NL', 'FR', 'KZ', 'RU', 'UA']
TIER_3_SILVER = ['GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'AT', 'CH']

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        logger.info("Скачивание GeoLite2 базы...")
        try:
            r = requests.get(MMDB_URL, stream=True)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                logger.info("GeoLite2 база успешно скачана.")
        except Exception as e:
            logger.error(f"Ошибка скачивания MMDB: {e}")

def init_geoip():
    global geo_reader
    try: 
        geo_reader = geoip2.database.Reader(MMDB_FILE)
        logger.info("GeoIP инициализирован.")
    except Exception as e: 
        logger.error(f"Ошибка инициализации GeoIP: {e}")

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
    # Регулярка для VLESS, VMESS, SS
    regex = r"(vless://[^ \n]+|ss://[^ \n]+|vmess://[^ \n]+)"
    links = re.findall(regex, text)
    
    # Если ссылок мало, пробуем декодировать весь текст из base64
    if len(links) < 5:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_config_info(config_str, source_type):
    try:
        # --- SHADOWSOCKS PARSER ---
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

        # --- VLESS PARSER (ROBUST) ---
        if config_str.startswith("vless://"):
            parsed = urlparse(config_str)
            
            if '@' not in parsed.netloc:
                return None
            
            _uuid, host_port = parsed.netloc.split('@', 1)
            
            if ':' not in host_port:
                return None
                
            if ']' in host_port:
                 host = host_port.rsplit(':', 1)[0]
                 port = host_port.rsplit(':', 1)[1]
            else:
                 host, port = host_port.split(':', 1)

            query = parsed.query
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            flow_val = params.get('flow', [''])[0].lower()
            
            is_reality = (security == 'reality')
            
            # Валидация Reality ключей
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) < 10: # Минимальная проверка
                    return None
                sni = params.get('sni', [''])[0]
                if sni == host: # SNI не должен быть равен IP (обычно)
                    return None
            
            is_vision = ('vision' in flow_val)
            is_pure = (security == 'none' or security == 'tls') and not is_reality
            
            original_remark = "Unknown"
            if parsed.fragment:
                original_remark = unquote(parsed.fragment).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "uuid": _uuid, 
                "original": config_str, 
                "original_remark": original_remark, 
                "latency": 9999, 
                "jitter": 0, 
                "final_score": 9999, 
                "info": {},
                "transport": transport, 
                "security": security,
                "is_reality": is_reality, 
                "is_vision": is_vision, 
                "is_pure": is_pure, 
                "is_hy2": False, 
                "is_ss": False,
                "source_type": source_type, 
                "tier_rank": 99,
                "parsed_params": params
            }
    except Exception as e: 
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
        if res == 0: return (end - start) * 1000
    except: pass
    return None

def generate_xray_config(server, local_port):
    try:
        params = server['parsed_params']
        
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
                "log": {"loglevel": "none"},
                "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [outbound_config]
            }
            return config

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

        def get_p(key, default=''):
            val = params.get(key, [default])
            return val[0] if isinstance(val, list) else val

        if server['transport'] == 'ws':
            ws_settings = {"path": get_p('path', '/')}
            host_val = get_p('host', '')
            if host_val:
                ws_settings["headers"] = {"Host": host_val}
            stream_settings["wsSettings"] = ws_settings
            
        elif server['transport'] == 'grpc':
            service_name = get_p('serviceName', '')
            if service_name:
                stream_settings["grpcSettings"] = {"serviceName": service_name}

        if server['security'] == 'tls':
            tls_settings = {
                "serverName": get_p('sni', ''),
                "allowInsecure": False
            }
            fp = get_p('fp', 'chrome')
            tls_settings["fingerprint"] = fp
            stream_settings["tlsSettings"] = tls_settings
            
        elif server['security'] == 'reality':
            reality_settings = {
                "show": False,
                "fingerprint": get_p('fp', 'chrome'),
                "serverName": get_p('sni', ''),
                "publicKey": get_p('pbk', ''),
                "shortId": get_p('sid', ''),
                "spiderX": get_p('spx', '/')
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
        logger.error(f"Ошибка генерации конфига Xray: {e}")
        return None

def check_real_connection(server):
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
        time.sleep(1.2) # Даем Xray чуть времени на разгон
        
        if xray_process.poll() is not None:
            return None

        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        # ИСПОЛЬЗУЕМ GOOGLE GENERATE 204 ДЛЯ ПРОВЕРКИ (Как в лучших практиках)
        # Это проверяет, проходит ли трафик РЕАЛЬНО, а не просто коннект к порту.
        target_url = "https://www.google.com/generate_204"
        
        start_time = time.perf_counter()
        # Verify=True важен для проверки валидности сертификатов (чтобы не было MITM)
        resp = requests.get(target_url, proxies=proxies, timeout=REAL_TEST_TIMEOUT, verify=True)
        end_time = time.perf_counter()
        
        if 200 <= resp.status_code < 300:
            result_latency = (end_time - start_time) * 1000
        else:
            result_latency = None

    except Exception:
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

    # TCP Ping - только для ПЕРВИЧНОГО отсева мертвых
    p = tcp_ping(server['ip'], server['port'])
    if p is None: return None
    server['tcp_latency'] = int(p) # Сохраняем TCP пинг отдельно
    
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}
    
    # --- ЭВРИСТИКА V78 (SPEED OF LIGHT) ---
    is_fake = False
    
    # 1. Глобальная физика: если не СНГ и пинг < 15 мс -> это РФ (Anycast/Fake)
    if code not in ['RU', 'BY', 'UA', 'KZ', 'XX'] and server['tcp_latency'] < 15:
        is_fake = True
    
    # 2. Табличная проверка: сравнение с MIN_THEORETICAL_LATENCY
    min_ping = MIN_THEORETICAL_LATENCY.get(code, 20)
    if server['tcp_latency'] < (min_ping - 5):
        # Если заявлена Греция, а пинг как до Яндекса - это фейк.
        is_fake = True

    # 3. Исключение для Whitelist (там мы знаем, что делаем)
    if server['category'] == 'WHITELIST' and code == 'RU': is_fake = False

    if is_fake and server['category'] != 'WHITELIST': 
        return None

    server['tier_rank'] = calculate_tier_rank(code)
    # По умолчанию latency ставим высоким, пока не пройдем Real Test
    server['latency'] = 9999 
    return server

def run_tournament(candidates, winners_needed, title="TOURNAMENT", mode="mixed"):
    if not candidates: return []
    filtered = candidates
    
    # --- СТРОГАЯ ФИЛЬТРАЦИЯ (BEST PRACTICES) ---
    if mode == "gaming":
        # Гейминг: Строго Reality + Иностранные (без RU/XX) + Низкий пинг
        filtered = [
            c for c in candidates 
            if c['is_reality'] 
            and c['info']['countryCode'] != 'RU'
            and c['info']['countryCode'] != 'XX' 
        ]
        logger.info(f"{title}: Фильтр Reality+Foreign (No RU/XX).")
            
    elif mode == "universal":
        # Универсал: Reality + Иностранные
        filtered = [
            c for c in candidates 
            if c['is_reality']
            and c['info']['countryCode'] != 'RU' 
            and c['info']['countryCode'] != 'XX'
        ]
        logger.info(f"{title}: Фильтр Reality+Foreign (No RU/XX).")
        
    elif mode == "whitelist":
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == "warp":
        filtered = [c for c in candidates if c['info']['countryCode'] not in ['RU', 'XX']]

    if not filtered: return []
    
    # Для реального теста берем ТОП-40 по предварительному TCP пингу
    # (чтобы не тратить время на проверку медленных серверов)
    semifinalists = sorted(filtered, key=lambda x: x['tcp_latency'])[:40]
    
    logger.info(f"🏟️ {title} (Проверка Xray: {len(semifinalists)} кандидатов...)")
    
    scored_results = []
    for f in semifinalists:
        # REAL LATENCY CHECK (Самое важное!)
        real_lat = check_real_connection(f)
        
        if real_lat is None:
            continue

        # Перезаписываем latency на РЕАЛЬНУЮ. Теперь сортировка будет честной.
        f['latency'] = int(real_lat)
        
        # Если реальный пинг выше 600мс - это мусор, даже если TCP был быстрый
        if real_lat > 600:
            continue
            
        tier_penalty = 0
        special_penalty = 0

        # В игровом режиме страна не так важна, важен пинг. В остальных - даем бонус Tier 1.
        if mode != "gaming":
            if f['tier_rank'] == 1: tier_penalty = 0     
            elif f['tier_rank'] == 2: tier_penalty = 30  
            else: tier_penalty = 70                      
            
        if mode == "warp":
            if f['transport'] in ['ws', 'grpc']: 
                special_penalty = 0
            else: 
                special_penalty = 2000
        
        # Формула: Реальный пинг + Штрафы. Чем меньше, тем лучше.
        score = real_lat + tier_penalty + special_penalty
        f['final_score'] = score
        
        proto_info = "TCP"
        if f.get('is_ss', False): proto_info = "SS"
        elif f['is_reality']: proto_info = "Reality"
        elif f['transport'] == 'ws': proto_info = "WS"
        
        logger.info(f"✅ {f['info']['countryCode']:<4} | {proto_info:<8} | RealPing: {int(real_lat)}ms (TCP: {f['tcp_latency']}ms) | Score: {int(score)}")
        scored_results.append(f)
        
    # Сортируем по итоговому баллу (основанному на Real Latency)
    scored_results.sort(key=lambda x: x['final_score'])
    
    if not scored_results:
        logger.warning(f"⚠️ {title}: Не найдено рабочих серверов.")
        return []

    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    # Добавляем случайный параметр, чтобы избежать кэширования (Anti-Cache)
    ts = int(time.time())
    
    for url in urls:
        try:
            # Если URL уже содержит параметры, добавляем &t=, иначе ?t=
            separator = "&" if "?" in url else "?"
            final_url = f"{url}{separator}t={ts}"
            
            resp = requests.get(final_url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                found = extract_links(content)
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except: pass
    return links

def fetch_smart_github_links(max_files_per_query=20):
    # Эта функция теперь второстепенна, так как мы добавили мощные прямые ссылки в GENERAL_URLS.
    # Но мы оставим её как "план Б".
    logger.info(f"🧠 GitHub Backup Search...")
    token = os.environ.get("GITHUB_TOKEN") 
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token: headers["Authorization"] = f"token {token}"

    # Используем максимально широкий поиск
    queries = [
        'vless:// reality extension:txt', 
        'vmess:// extension:txt',
        'vless:// subscription'
    ]
    api_url = "https://api.github.com/search/code"
    raw_links = set()

    for q in queries:
        # Сортируем по индексации (свежее)
        params = {"q": q, "sort": "indexed", "order": "desc", "per_page": max_files_per_query}
        try:
            resp = requests.get(api_url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for item in items:
                    raw_url = item.get("html_url", "").replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                    if raw_url: raw_links.add(raw_url)
            time.sleep(1.5) 
        except Exception: pass
    return list(raw_links)

def main():
    logger.info("--- ЗАПУСК V78 (HYBRID: GO-STYLE SOURCES + REAL LATENCY CORE) ---")
    
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
    else:
        logger.error(f"❌ Error: Xray binary not found at {XRAY_BIN}")

    download_mmdb()
    init_geoip()
    
    # 1. Скачивание (Прямые ссылки + GitHub Backup)
    dynamic_urls = fetch_smart_github_links(max_files_per_query=10)
    combined_general_urls = GENERAL_URLS + dynamic_urls

    all_servers = []
    # Увеличиваем кол-во потоков для скачивания (как в Go воркерах)
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        logger.info(f"🌐 Скачивание источников ({len(combined_general_urls)} combined + {len(WHITELIST_URLS)} whitelist)...")
        f1 = executor.submit(process_urls, combined_general_urls, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()
    
    # Удаляем дубликаты
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    logger.info(f"🔍 Найдено {len(servers_to_check)} серверов. Начинаем TCP-сканирование...")
    
    working_servers = []
    # TURBO SCAN: 100 потоков для первичной проверки (аналог WorkersCount = 40 в Go, но Python GIL требует больше)
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: working_servers.append(res)

    b_white = [s for s in working_servers if s['category'] == 'WHITELIST']
    b_univ = [s for s in working_servers if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []
    
    # --- ТУРНИРЫ ---
    # 1. Game Server (Самый низкий реальный пинг, только Reality)
    game_winners = run_tournament(b_univ, TARGET_GAME, "GAME CUP", "gaming")
    game_ips = []
    
    if game_winners:
        for g in game_winners:
            g['category'] = 'Game Server'
            game_ips.append(g['ip']) 
        final_list.extend(game_winners)
    
    # 2. Universal (Исключаем IP игровых, чтобы не дублировать)
    b_univ_filtered = [s for s in b_univ if s['ip'] not in game_ips]
    
    final_list.extend(run_tournament(b_univ_filtered, TARGET_UNIVERSAL, "UNIVERSAL CUP", "universal"))
    final_list.extend(run_tournament(b_warp, TARGET_WARP, "WARP CUP", "warp"))
    final_list.extend(run_tournament(b_white, TARGET_WHITELIST, "WHITELIST CUP", "whitelist"))

    # Генерация времени
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
        
        # Используем РЕАЛЬНЫЙ пинг, который мы замерили в турнире
        final_ping = s.get('latency', 999)
        
        # Небольшая косметика для совсем низких значений, чтобы не выглядело как фейк
        if final_ping < 10: final_ping = 15

        type_label = "VLESS"
        if s['is_hy2']: type_label = "Hy2"
        elif s.get('is_ss', False): type_label = "SS"
        elif s['is_reality']: type_label = "Reality"
        elif s['is_pure']: type_label = "TCP"

        name = ""
        if s['category'] == 'Game Server': 
            name = f"🎮 Game Reality | {flag} {country_full} | {final_ping}ms"
        elif s['category'] == 'WHITELIST': 
            name = f"⚪ {flag} RU (WhiteList) | {final_ping}ms"
        elif s['category'] == 'WARP': 
            name = f"🌀 {flag} {country_full} WARP | {final_ping}ms"
        else: 
            name = f"⚡ {flag} {country_full} | {final_ping}ms"

        base = s['original'].split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_data["servers"].append({
            "name": name,
            "category": s['category'],
            "country": country_full,
            "iso": code,
            "flag": flag,
            "ping": final_ping,
            "ip": s['ip'],       
            "port": s['port'],
            "protocol": s['transport'].upper(),
            "type": type_label
        })

    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"DONE. {len(result_links)} links saved to {OUTPUT_FILE}.")
    logger.info(f"SECURE stats saved to {JSON_FILE} (No configs inside).")

if __name__ == "__main__":
    main()
