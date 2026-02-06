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
import os
import json
import binascii 
import geoip2.database 
import subprocess
import tempfile
import random
import urllib3
import logging
from threading import Lock
try:
    import socks
except ImportError:
    socks = None
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- V124: ULTIMATE EDITION (FULL CHECKS + NEW STRUCTURE) ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ═══════════════════════════════════════════════════════════════
LOG_FILE = 'vpn_scanner.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class ProgressCounter:
    def __init__(self, total=0, name=""):
        self.current = 0
        self.total = total
        self.name = name
        self.success = 0
        self.failed = 0
        self.lock = Lock()
    
    def increment(self, success=True):
        with self.lock:
            self.current += 1
            if success:
                self.success += 1
            else:
                self.failed += 1
            
            if self.total > 0 and self.current % max(1, self.total // 10) == 0:
                pct = (self.current / self.total) * 100
                logger.info(f"   📊 {self.name}: {self.current}/{self.total} ({pct:.0f}%) | ✅{self.success} ❌{self.failed}")

# ═══════════════════════════════════════════════════════════════
# 🔥 ИСТОЧНИКИ
# ═══════════════════════════════════════════════════════════════

# 🛡️ REALITY & VLESS SOURCES
REALITY_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/lagzian/SS-Collector/main/realitiy_api.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/reality.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/reality.txt",
]

PREMIUM_URLS = [
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/Config/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/vless",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/hysteria2",
]

# 📦 GENERAL (Включая перемещенные списки)
GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/master/collected-proxies/row-url/all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",
]

# 🇷🇺 WHITELIST (RU ONLY)
WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt",
]

SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/master/sub/share/vless",
]

TELEGRAM_CHANNELS = [
    "PrivateVPNs", "iSegaro", "reality_daily",
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir",
    "v2ray_configs_pool", "VlessConfig", "v2ray1_ng",
    "DirectVPN", "v2ray_alpha", "customv2ray", 
    "ConfigsHUB", "freev2rayssr", "VmessProtocol", 
    "ServerNett", "V2RayTz",
]

GITHUB_ISSUES_REPOS = [
    "barry-far/V2ray-Configs",
    "Pawdroid/Free-servers", 
    "mahdibland/V2RayAggregator",
    "yebekhe/TelegramV2rayCollector",
]

# ═══════════════════════════════════════════════════════════════
# СИСТЕМНЫЕ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

MAX_WORKERS_SCAN = 80
MAX_WORKERS_CUP = 15
MAX_WORKERS_FETCH = 20

TIMEOUT = 0.8            
SPEED_TEST_TIMEOUT = 8.0 
FETCH_TIMEOUT = 8.0

# 📁 ФАЙЛЫ
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

TIMEZONE_OFFSET = 3 
CACHE_TTL_HOURS = 4      
MAX_FAILURES = 2

# 🔄 НАСТРОЙКИ СТРУКТУРЫ
COUNT_GAME = 2
COUNT_UNIVERSAL = 3
COUNT_WARP = 2
COUNT_WHITELIST = 2

# 🚫 ЗАБЛОКИРОВАННЫЕ SNI (ВЕРНУЛ ОБЯЗАТЕЛЬНО!)
BLOCKED_SNIS = [
    'discord.com', 'www.discord.com', 'discordapp.com',
    'twitter.com', 'www.twitter.com', 'x.com',
    'facebook.com', 'www.facebook.com',
    'instagram.com', 'www.instagram.com',
    'linkedin.com', 'www.linkedin.com',
    'bbc.com', 'dw.com', 'meduza.io',
    'svoboda.org', 'voiceofamerica.com'
]

# ═══════════════════════════════════════════════════════════════
# GEO НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
RUS_NAMES = {
    'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'PL': 'Польша', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'NO': 'Норвегия', 'AT': 'Австрия', 'CZ': 'Чехия',
    'UA': 'Украина', 'KZ': 'Казахстан', 'BG': 'Болгария', 'RO': 'Румыния', 
    'HU': 'Венгрия', 'SK': 'Словакия', 'CH': 'Швейцария', 'IT': 'Италия', 
    'ES': 'Испания', 'US': 'США', 'JP': 'Япония', 'SG': 'Сингапур'
}

BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP']
EXCLUDE_FROM_GLOBAL = ['RU', 'BY'] 

# 🎯 GAME COUNTRIES (Ближние к РФ)
GAME_COUNTRIES = [
    'FI', 'EE', 'LV', 'LT', 'SE', 'NO', 'PL', 'DE', 'NL'
]

# ═══════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
geo_reader = None
server_history = {} 

def get_beautiful_time():
    now_utc = datetime.now(timezone.utc)
    msk_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    return msk_time.strftime('%H:%M')

def get_country_flag(country_code):
    if not country_code or len(country_code) != 2 or country_code == 'XX':
        return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def format_server_name(base_name, country_code, index):
    flag = get_country_flag(country_code)
    time_str = get_beautiful_time()
    return f"{flag} {base_name} {index} | {time_str}"

def load_history():
    global server_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                server_history = json.load(f)
            logger.info(f"📂 Загружена история: {len(server_history)} записей")
        except:
            server_history = {}

def save_history():
    current_ts = time.time()
    clean_history = {}
    for key, val in server_history.items():
        if val.get('fails', 0) >= MAX_FAILURES: continue
        if current_ts - val.get('ts', 0) < (24 * 3600):
            clean_history[key] = val
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(clean_history, f, indent=2)
    except: pass

def update_history(ip, port, is_alive):
    key = f"{ip}:{port}"
    current = server_history.get(key, {'fails': 0, 'ts': 0, 'success_streak': 0})
    if is_alive:
        current['fails'] = 0
        current['success_streak'] = current.get('success_streak', 0) + 1
    else:
        current['fails'] = current.get('fails', 0) + 1
        current['success_streak'] = 0
    current['ts'] = time.time()
    server_history[key] = current

def should_check_server(ip, port):
    key = f"{ip}:{port}"
    if key not in server_history: return True
    rec = server_history[key]
    if rec.get('fails', 0) >= MAX_FAILURES:
        if (time.time() - rec.get('ts', 0)) / 3600 < CACHE_TTL_HOURS:
            return False
    return True

# ═══════════════════════════════════════════════════════════════
# GEOIP (HYBRID SYSTEM)
# ═══════════════════════════════════════════════════════════════
def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=30)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024): f.write(chunk)
                logger.info("✅ GeoIP база скачана")
        except: pass

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: geo_reader = None

def close_geoip():
    if geo_reader:
        try: geo_reader.close()
        except: pass

def get_country_online_fallback(ip):
    """Онлайн проверка, если локальная база подвела"""
    try:
        time.sleep(0.1) # Вежливость к API
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=2)
        if r.status_code == 200:
            return r.json().get('countryCode', 'XX')
    except: pass
    return 'XX'

def get_ip_country_local(ip):
    if geo_reader:
        try:
            return geo_reader.country(ip).country.iso_code or 'XX'
        except: pass
    return 'XX'

# ═══════════════════════════════════════════════════════════════
# ПАРСИНГ (RESTORED ROBUST VERSION)
# ═══════════════════════════════════════════════════════════════
def safe_base64_decode(s):
    """Надежный декодер Base64"""
    s = s.strip().replace('\n', '').replace('\r', '')
    missing_padding = len(s) % 4
    if missing_padding: s += '=' * (4 - missing_padding)
    
    for decoder in [base64.urlsafe_b64decode, base64.b64decode]:
        try:
            return decoder(s).decode('utf-8', errors='ignore')
        except: continue
    return ""

def extract_links(text):
    """Извлекает ссылки из любого мусора"""
    regex = r"(vless://[^\s\n<>\"']+|ss://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+|hysteria2://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    
    if len(links) < 3:
        decoded = safe_base64_decode(text)
        if decoded: links.extend(re.findall(regex, decoded))
    
    unique_links = []
    seen = set()
    for link in links:
        clean = link.split('#')[0]
        if clean not in seen:
            seen.add(clean)
            unique_links.append(link)
    return unique_links

def is_valid_ip_or_host(host):
    if not host or len(host) < 4: return False
    if host.startswith(('127.', '10.', '192.168.')) or host == 'localhost': return False
    return True

def has_bad_sni(sni):
    if not sni: return False
    sni_lower = sni.lower()
    for bad in BLOCKED_SNIS:
        if bad in sni_lower: return True
    return False

def parse_config_info(config_str, source_type):
    if not config_str or len(config_str) < 20: return None
    try:
        # VLESS
        if config_str.startswith("vless://"):
            part = config_str.split("@")[1].split("?")[0]
            if ":" not in part: return None
            host, port = part.rsplit(":", 1)
            if not is_valid_ip_or_host(host): return None
            
            uuid = config_str.split("@")[0].replace("vless://", "")
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            sni = params.get('sni', [''])[0]
            is_reality = params.get('security', [''])[0] == 'reality'
            
            # 🛡️ Фильтр SNI
            if is_reality and has_bad_sni(sni):
                return None
            
            remark = unquote(config_str.split("#")[-1]).strip() if "#" in config_str else ""

            return {
                "ip": host, "port": int(port), "uuid": uuid, 
                "original": config_str, "original_remark": remark,
                "latency": 9999, "speed_mbps": 0.0,
                "transport": params.get('type', ['tcp'])[0],
                "security": params.get('security', ['none'])[0],
                "parsed_params": params,
                "is_reality": is_reality,
                "is_hy2": False, "source_type": source_type
            }
            
        # HYSTERIA2
        if config_str.startswith(("hy2://", "hysteria2://")):
            prefix = "hy2://" if config_str.startswith("hy2://") else "hysteria2://"
            part = config_str.split("@")
            if len(part) < 2: return None
            
            password = part[0].replace(prefix, "")
            host_port_query = part[1]
            if "?" in host_port_query: host_port, query = host_port_query.split("?", 1)
            else: host_port, query = host_port_query, ""
                
            if "#" in query: query, remark = query.split("#", 1)
            elif "#" in host_port: host_port, remark = host_port.split("#", 1)
            else: remark = "Hy2"
            
            if ":" not in host_port: return None
            host, port = host_port.rsplit(":", 1)
            if not is_valid_ip_or_host(host): return None

            params = parse_qs(query)
            return {
                "ip": host, "port": int(port), "uuid": password,
                "original": config_str, "original_remark": unquote(remark).strip(),
                "latency": 9999, "speed_mbps": 0.0,
                "transport": "udp", "security": "tls",
                "parsed_params": params,
                "is_reality": False, "is_hy2": True, "source_type": source_type
            }

    except: pass
    return None

def is_warp_config(server):
    remark = server.get('original_remark', '').lower()
    sni = server.get('parsed_params', {}).get('sni', [''])[0].lower()
    for k in ['warp', 'wireguard', 'cloudflare', 'cf', 'clash']:
        if k in remark or k in sni: return True
    return False

# ═══════════════════════════════════════════════════════════════
# СЕТЕВЫЕ ФУНКЦИИ (ПОЛНЫЙ КОМПЛЕКТ)
# ═══════════════════════════════════════════════════════════════
def tcp_ping(host, port):
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter()
        if sock.connect_ex((host, port)) == 0:
            return (time.perf_counter() - start) * 1000
    except: pass
    finally:
        if sock: sock.close()
    return None

def generate_xray_config(server, local_port):
    try:
        if server.get('is_hy2'):
            outbound = {
                "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [{"password": server['uuid']}]}]
            }
            stream = {
                "network": "udp", "security": "tls", 
                "tlsSettings": {"serverName": server['parsed_params'].get('sni', [''])[0], "allowInsecure": True}
            }
            protocol = "hysteria2"
        else:
            params = server['parsed_params']
            user = {"id": server['uuid'], "encryption": "none"}
            if params.get('flow'): user["flow"] = params['flow'][0]
            
            outbound = {"vnext": [{"address": server['ip'], "port": int(server['port']), "users": [user]}]}
            stream = {"network": server['transport'], "security": server['security']}

            if server['transport'] == 'ws':
                ws = {"path": params.get('path', ['/'])[0]}
                if params.get('host'): ws["headers"] = {"Host": params['host'][0]}
                stream["wsSettings"] = ws
            elif server['transport'] == 'grpc':
                stream["grpcSettings"] = {"serviceName": params.get('serviceName', [''])[0]}

            if server['security'] == 'tls':
                stream["tlsSettings"] = {
                    "serverName": params.get('sni', [''])[0], "allowInsecure": False,
                    "fingerprint": params.get('fp', ['chrome'])[0]
                }
            elif server['security'] == 'reality':
                stream["realitySettings"] = {
                    "show": False, "fingerprint": params.get('fp', ['chrome'])[0],
                    "serverName": params.get('sni', [''])[0],
                    "publicKey": params.get('pbk', [''])[0],
                    "shortId": params.get('sid', [''])[0],
                    "spiderX": params.get('spx', ['/'])[0]
                }
            protocol = "vless"

        return {
            "log": {"loglevel": "error"},
            "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [{"tag": "proxy", "protocol": protocol, "settings": outbound, "streamSettings": stream}]
        }
    except: return None

def check_udp_dns(local_port):
    """⚡ ЧЕСТНАЯ ПРОВЕРКА UDP (Отправка DNS запроса через прокси)"""
    if not socks: return False
    s = None
    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
        s.set_proxy(socks.SOCKS5, "127.0.0.1", local_port)
        s.settimeout(2.5)
        # DNS запрос к 8.8.8.8 (google.com)
        dns_query = binascii.unhexlify("aaaa0100000100000000000006676f6f676c6503636f6d0000010001")
        s.sendto(dns_query, ("8.8.8.8", 53))
        data, addr = s.recvfrom(1024)
        return True
    except: return False
    finally:
        if s: s.close()

def measure_speed(local_port):
    """⚡ ТЕСТ СКОРОСТИ НА GOOGLE"""
    url = "https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe"
    proxies = {"http": f"socks5h://127.0.0.1:{local_port}", "https": f"socks5h://127.0.0.1:{local_port}"}
    start = time.time()
    try:
        with requests.get(url, proxies=proxies, timeout=SPEED_TEST_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_content(32768):
                if chunk: total += len(chunk)
                if total > 2 * 1024 * 1024: break # 2 MB limit
            dur = time.time() - start
            return round((total * 8) / (max(dur, 0.1) * 1_000_000), 2)
    except: pass
    return 0.0

def check_endpoints(local_port):
    """⚡ ТРОЙНАЯ ПРОВЕРКА (Google, CF, Gstatic)"""
    proxies = {'https': f'socks5://127.0.0.1:{local_port}'}
    endpoints = [
        ("https://www.google.com/generate_204", 204),
        ("https://cp.cloudflare.com/", 200),
        ("https://www.gstatic.com/generate_204", 204)
    ]
    success = 0
    total_lat = 0
    for url, code in endpoints:
        try:
            st = time.perf_counter()
            r = requests.get(url, proxies=proxies, timeout=5)
            if r.status_code == code or 200 <= r.status_code < 300:
                success += 1
                total_lat += (time.perf_counter() - st) * 1000
        except: pass
    
    if success >= 2: # Если хотя бы 2 из 3 работают
        return total_lat / success
    return None

def check_real_connection(server):
    local_port = random.randint(10000, 60000)
    conf = generate_xray_config(server, local_port)
    if not conf: return None, 0.0, False

    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
        json.dump(conf, f)
        cpath = f.name

    proc = subprocess.Popen([XRAY_BIN, "-config", cpath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    
    lat = None
    speed = 0.0
    udp = False
    
    try:
        # 1. Пинг (Тройной чек)
        lat = check_endpoints(local_port)
        
        if lat:
            # 2. UDP чек
            udp = check_udp_dns(local_port)
            
            # 3. Скорость
            speed = measure_speed(local_port)
            update_history(server['ip'], server['port'], True)
        else:
            update_history(server['ip'], server['port'], False)
            
    except:
        update_history(server['ip'], server['port'], False)
    finally:
        proc.terminate()
        proc.wait()
        try: os.remove(cpath)
        except: pass

    return lat, speed, udp

# ═══════════════════════════════════════════════════════════════
# ПРОВЕРКА И ОТБОР
# ═══════════════════════════════════════════════════════════════
def check_server_initial(server, progress):
    ip, port = server['ip'], server['port']
    if not should_check_server(ip, port):
        progress.increment(False); return None
        
    code = get_ip_country_local(ip)
    if code != 'XX' and code in BLACKLIST_COUNTRIES:
        progress.increment(False); return None

    p = tcp_ping(ip, port)
    if p is None:
        update_history(ip, port, False)
        progress.increment(False); return None
        
    if code == 'XX': # Если живой, но страна неизвестна - узнаем онлайн
        code = get_country_online_fallback(ip)
        if code in BLACKLIST_COUNTRIES:
            progress.increment(False); return None
            
    server['latency'] = int(p)
    server['info'] = {'countryCode': code}
    logger.debug(f"   🟢 {ip} ({code}) - {p:.0f}ms")
    progress.increment(True)
    return server

def check_full_server(server, progress):
    lat, speed, udp = check_real_connection(server)
    if lat is None:
        progress.increment(False); return None
        
    server['real_latency'] = lat
    server['speed_mbps'] = speed
    server['udp_enabled'] = udp
    
    name = RUS_NAMES.get(server['info']['countryCode'], server['info']['countryCode'])
    udp_str = "✅UDP" if udp else "❌UDP"
    logger.info(f"   🎯 {server['ip']} ({name}) - {speed:.1f} Mbps, {lat:.0f}ms, {udp_str}")
    progress.increment(True)
    return server

def select_final_servers(servers):
    final_list = []
    used_ips = set()
    reserve_pool = []
    
    ru_pool = [s for s in servers if s['info']['countryCode'] == 'RU']
    global_pool = [s for s in servers if s['info']['countryCode'] not in EXCLUDE_FROM_GLOBAL]
    
    logger.info(f"\n🧩 Распределение по категориям:")
    
    # 1. WHITELIST (2 servers)
    for i, s in enumerate(sorted(ru_pool, key=lambda x: -x['speed_mbps'])[:COUNT_WHITELIST]):
        s['final_name'] = format_server_name("WHITELIST", "RU", i+1)
        final_list.append(s); used_ips.add(s['ip'])
        logger.info(f"   ✅ WHITELIST #{i+1}: {s['ip']} (RU) {s['speed_mbps']} Mbps")

    # 2. WARP (2 servers)
    warps = [s for s in global_pool if is_warp_config(s) and s['ip'] not in used_ips]
    if len(warps) < COUNT_WARP: # Fallback
        warps.extend(sorted([s for s in global_pool if s['ip'] not in used_ips], key=lambda x: -x['speed_mbps']))
    
    for i, s in enumerate(sorted(warps, key=lambda x: -x['speed_mbps'])[:COUNT_WARP]):
        s['final_name'] = format_server_name("WARP", s['info']['countryCode'], i+1)
        final_list.append(s); used_ips.add(s['ip'])
        logger.info(f"   ✅ WARP #{i+1}: {s['ip']} ({s['info']['countryCode']}) {s['speed_mbps']} Mbps")

    # 3. GAME (2 servers - Приоритет пинг + соседи + UDP)
    gamers = [s for s in global_pool if s['ip'] not in used_ips and s['info']['countryCode'] in GAME_COUNTRIES and s['udp_enabled']]
    if len(gamers) < COUNT_GAME:
        gamers.extend([s for s in global_pool if s['ip'] not in used_ips and s['udp_enabled']])
    
    for i, s in enumerate(sorted(gamers, key=lambda x: x['real_latency'])[:COUNT_GAME]):
        s['final_name'] = format_server_name("GAME", s['info']['countryCode'], i+1)
        final_list.append(s); used_ips.add(s['ip'])
        logger.info(f"   ✅ GAME #{i+1}: {s['ip']} ({s['info']['countryCode']}) Ping: {s['real_latency']:.0f}ms")

    # 4. UNIVERSAL (3 servers - Max Speed)
    unis = sorted([s for s in global_pool if s['ip'] not in used_ips], key=lambda x: -x['speed_mbps'])
    for i, s in enumerate(unis[:COUNT_UNIVERSAL]):
        s['final_name'] = format_server_name("UNIVERSAL", s['info']['countryCode'], i+1)
        final_list.append(s); used_ips.add(s['ip'])
        logger.info(f"   ✅ UNIVERSAL #{i+1}: {s['ip']} ({s['info']['countryCode']}) {s['speed_mbps']} Mbps")

    # Остаток в резерв
    for s in servers:
        if s['ip'] not in used_ips and s['speed_mbps'] > 1.0:
            reserve_pool.append(s)
            
    return final_list, reserve_pool

# ═══════════════════════════════════════════════════════════════
# СБОР И ЗАПУСК
# ═══════════════════════════════════════════════════════════════
def fetch_url(url, stype):
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            return [p for link in extract_links(r.text) if (p := parse_config_info(link, stype))]
    except: pass
    return []

def fetch_tg(channel):
    try:
        r = requests.get(f"https://t.me/s/{channel}", timeout=FETCH_TIMEOUT)
        if r.status_code == 200:
            return [p for link in extract_links(r.text) if (p := parse_config_info(link, 'telegram'))]
    except: pass
    return []

def fetch_github(repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/issues?state=all", headers={'User-Agent': 'Bot'})
        configs = []
        if r.status_code == 200:
            for issue in r.json():
                text = (issue.get('body') or '') + (issue.get('title') or '')
                configs.extend([p for link in extract_links(text) if (p := parse_config_info(link, 'github_issues'))])
        return configs
    except: pass
    return []

def fetch_all():
    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_FETCH) as ex:
        for u in REALITY_URLS + PREMIUM_URLS + GENERAL_URLS: tasks.append(ex.submit(fetch_url, u, 'general'))
        for u in WHITELIST_URLS: tasks.append(ex.submit(fetch_url, u, 'whitelist'))
        for u in SUBSCRIPTION_URLS: tasks.append(ex.submit(fetch_url, u, 'subscription'))
        for c in TELEGRAM_CHANNELS: tasks.append(ex.submit(fetch_tg, c))
        for r in GITHUB_ISSUES_REPOS: tasks.append(ex.submit(fetch_github, r))
    
    unique = {}
    for f in concurrent.futures.as_completed(tasks):
        if res := f.result():
            for c in res: unique[f"{c['ip']}:{c['port']}"] = c
    return list(unique.values())

def main():
    start_ts = time.time()
    print("═" * 60)
    logger.info("🚀 FL1P VPN SCANNER V124 - ULTIMATE (FULL CHECKS)")
    logger.info(f"   🛡️ SNI FILTER: ON (Discord/Twitter blocked)")
    logger.info(f"   🎮 GAME: {COUNT_GAME} | 🌌 UNI: {COUNT_UNIVERSAL} | 🌀 WARP: {COUNT_WARP}")
    print("═" * 60)
    
    load_history()
    download_mmdb()
    init_geoip()
    
    if not os.path.exists(XRAY_BIN): logger.error("❌ Xray не найден!"); return

    # 1. Сбор
    logger.info("📥 Сбор конфигов...")
    candidates = fetch_all()
    logger.info(f"   🔍 Найдено уникальных: {len(candidates)}")
    
    # 2. TCP
    alive = []
    pc = ProgressCounter(len(candidates), "TCP")
    with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS_SCAN) as ex:
        futs = [ex.submit(check_server_initial, s, pc) for s in candidates]
        for f in concurrent.futures.as_completed(futs):
            if res := f.result(): alive.append(res)
            
    # 3. Отбор
    ru_only = [s for s in alive if s['info']['countryCode'] == 'RU']
    global_only = [s for s in alive if s['info']['countryCode'] not in EXCLUDE_FROM_GLOBAL]
    
    to_check = []
    to_check.extend(ru_only[:100]) 
    warps = [s for s in global_only if is_warp_config(s)]
    to_check.extend(warps[:50])
    gamers = [s for s in global_only if s['info']['countryCode'] in GAME_COUNTRIES and s not in to_check]
    gamers.sort(key=lambda x: x['latency'])
    to_check.extend(gamers[:300])
    others = [s for s in global_only if s not in to_check]
    to_check.extend(others[:600])
    
    logger.info(f"\n🧪 Глубокая проверка: {len(to_check)}")
    
    # 4. Full Check
    verified = []
    pc2 = ProgressCounter(len(to_check), "Full Check")
    with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS_CUP) as ex:
        futs = {ex.submit(check_full_server, s, pc2): s for s in to_check}
        for f in concurrent.futures.as_completed(futs):
            if res := f.result(): verified.append(res)
            
    # 5. Финал
    final_srv, reserve = select_final_servers(verified)
    
    # 6. Сохранение
    res_links = [f"{s['original'].split('#')[0]}#{quote(s['final_name'])}" for s in final_srv]
    with open(OUTPUT_FILE, 'w') as f:
        f.write(base64.b64encode("\n".join(res_links).encode()).decode())
        
    stats = {
        "updated": datetime.now().strftime('%H:%M:%S'),
        "servers": [{
            "name": s['final_name'], "ip": s['ip'], "country": s['info']['countryCode'],
            "speed": s['speed_mbps'], "ping": s['real_latency']
        } for s in final_srv]
    }
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    # 💾 СОХРАНЕНИЕ РЕЗЕРВА (ВЕРНУЛ)
    if reserve:
        res_pool_data = {"updated": datetime.now().isoformat(), "servers": reserve[:50]}
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(res_pool_data, f, default=str, indent=2)
        logger.info(f"💾 Резерв сохранен в {RESERVE_POOL_FILE}")
        
    save_history()
    close_geoip()
    logger.info(f"✅ Готово! Файл: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
