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

# ═══════════════════════════════════════════════════════════════
#  FL1P VPN SCANNER V122 - PERFECT 9 EDITION
#  
#  Структура (ВСЕГДА 9 серверов):
#  🎮 GAME ×2      - Игровые (Tier 1-2, низкий пинг)
#  ⚡ UNIVERSAL ×3 - Универсальные (высокая скорость)
#  🔄 WARP ×2      - Cloudflare WARP
#  ⚪ WHITELIST ×2 - Российские для РКН
#
#  Формат названий:
#  🎮🇫🇮 Финляндия | 📅15:30
#  🎮🇪🇪 Эстония | 📅15:50
#  ⚡🇩🇪 Германия
#  🔄🇳🇱 Нидерланды
#  ⚪🇷🇺 (РКН)
#
# ═══════════════════════════════════════════════════════════════
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ
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
# 🌍 ТИРЫ СТРАН
# ═══════════════════════════════════════════════════════════════
TIER_1_COUNTRIES = ['FI', 'EE', 'LV', 'LT']
TIER_2_COUNTRIES = ['SE', 'NO', 'PL']
TIER_3_COUNTRIES = ['DE', 'NL', 'AT', 'CZ', 'DK', 'BE', 'CH']
TIER_4_COUNTRIES = ['GB', 'FR', 'IT', 'ES', 'PT', 'IE', 'HU', 'RO', 'BG', 'SK', 'GR', 'TR']

GAME_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES
UNIVERSAL_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES + TIER_3_COUNTRIES + TIER_4_COUNTRIES
WHITELIST_COUNTRIES = ['RU']
BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP', 'US', 'BY']

RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция', 'TR': 'Турция',
    'RU': 'Россия', 'UA': 'Украина', 'MD': 'Молдова', 'CF': 'Cloudflare',
}

# ═══════════════════════════════════════════════════════════════
# 🔥 ИСТОЧНИКИ
# ═══════════════════════════════════════════════════════════════
REALITY_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/lagzian/SS-Collector/main/realitiy_api.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/reality.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/reality.txt",
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub/vless",
]

PREMIUM_URLS = [
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/vless",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
]

GENERAL_URLS = [
    "https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/master/collected-proxies/row-url/all.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",
    "https://raw.githubusercontent.com/STARTER-X-0/STARTER-X-VPN/refs/heads/main/RU-WHITE-LIST",
]

WARP_URLS = [
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/warp",
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub/warp",
    "https://raw.githubusercontent.com/ircfspace/warpsub/main/export/warp",
]

TELEGRAM_CHANNELS = [
    "PrivateVPNs", "iSegaro", "reality_daily", "RealityVpnChannel",
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir", "v2ray_configs_pool",
    "VlessConfig", "v2ray1_ng", "DirectVPN", "v2ray_alpha",
    "customv2ray", "ConfigsHUB", "freev2rayssr", "proxy_mtm",
    "ShadowProxy66", "Proxy_PJ", "SafeNet_Server", "VmessProtocol",
]

GITHUB_ISSUES_REPOS = [
    "barry-far/V2ray-Configs",
    "Pawdroid/Free-servers",
    "mahdibland/V2RayAggregator",
    "yebekhe/TelegramV2rayCollector",
]

# ═══════════════════════════════════════════════════════════════
# ⚙️ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

MAX_WORKERS_SCAN = 50
MAX_WORKERS_DEEP = 12
MAX_WORKERS_FETCH = 15

TIMEOUT_TCP = 0.7
TIMEOUT_REAL = 8.0
TIMEOUT_SPEED = 5.0
TIMEOUT_FETCH = 6.0

MAX_DEEP_CHECK_GLOBAL = 500
MAX_DEEP_CHECK_WHITELIST = 100

MIN_SPEED_GAME = 1.0
MIN_SPEED_UNIVERSAL = 2.0
MIN_SPEED_WHITELIST = 0.3

OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

TIMEZONE_OFFSET = 3
CACHE_TTL_HOURS = 4
MAX_FAILURES = 2
RESERVE_POOL_SIZE = 30
UPDATE_INTERVAL_MINUTES = 20

# ═══════════════════════════════════════════════════════════════
# 🛡️ REALITY
# ═══════════════════════════════════════════════════════════════
TRUSTED_SNIS = [
    'www.google.com', 'google.com', 'www.microsoft.com', 'microsoft.com',
    'www.apple.com', 'www.cloudflare.com', 'www.mozilla.org', 'www.yahoo.com',
    'www.amazon.com', 'www.github.com', 'www.samsung.com', 'cdn.jsdelivr.net',
    'www.nvidia.com', 'www.docker.com', 'www.oracle.com', 'www.cisco.com',
]

BLOCKED_SNIS = ['discord.com', 'twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'tiktok.com']

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════
geo_reader = None
server_history = {}

# ═══════════════════════════════════════════════════════════════
# 🎨 УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_msk_time():
    return datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)

def get_last_update_time():
    """Время последнего обновления"""
    return get_msk_time().strftime('%H:%M')

def get_next_update_time():
    """Время следующего обновления (+20 минут)"""
    next_time = get_msk_time() + timedelta(minutes=UPDATE_INTERVAL_MINUTES)
    return next_time.strftime('%H:%M')

def get_timestamp():
    return get_msk_time().strftime('%Y-%m-%d %H:%M:%S MSK')

def get_flag(cc):
    """Получить эмодзи флаг страны"""
    if not cc or len(cc) != 2:
        return ""
    return "".join([chr(127397 + ord(c)) for c in cc.upper()])

def get_country_name(cc):
    """Получить название страны на русском"""
    return RUS_NAMES.get(cc, cc)

# ═══════════════════════════════════════════════════════════════
# 📂 ИСТОРИЯ
# ═══════════════════════════════════════════════════════════════
def load_history():
    global server_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                server_history = json.load(f)
            logger.info(f"📂 История: {len(server_history)} записей")
        except:
            server_history = {}

def save_history():
    ts = time.time()
    clean = {k: v for k, v in server_history.items() if v.get('fails', 0) < MAX_FAILURES and ts - v.get('ts', 0) < 86400}
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2)
    except:
        pass

def update_history(ip, port, alive, is_reality=False):
    key = f"{ip}:{port}"
    cur = server_history.get(key, {'fails': 0, 'ts': 0, 'streak': 0})
    if alive:
        cur['fails'] = 0
        cur['streak'] = cur.get('streak', 0) + 1
        cur['is_reality'] = is_reality
    else:
        cur['fails'] = cur.get('fails', 0) + 1
        cur['streak'] = 0
    cur['ts'] = time.time()
    server_history[key] = cur

def get_streak(ip, port):
    return server_history.get(f"{ip}:{port}", {}).get('streak', 0)

def should_check(ip, port):
    key = f"{ip}:{port}"
    if key not in server_history:
        return True
    rec = server_history[key]
    if rec.get('fails', 0) >= MAX_FAILURES:
        if (time.time() - rec.get('ts', 0)) / 3600 < CACHE_TTL_HOURS:
            return False
    return True

# ═══════════════════════════════════════════════════════════════
# 🌍 GEOIP
# ═══════════════════════════════════════════════════════════════
def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        logger.info("📥 Скачивание GeoIP...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=30)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                logger.info("✅ GeoIP скачан")
        except Exception as e:
            logger.error(f"❌ Ошибка GeoIP: {e}")

def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
        logger.info("🌍 GeoIP OK")
    except Exception as e:
        logger.error(f"❌ GeoIP ошибка: {e}")

def close_geoip():
    global geo_reader
    if geo_reader:
        try:
            geo_reader.close()
        except:
            pass

def get_country(ip):
    if not geo_reader:
        return 'XX'
    try:
        return geo_reader.country(ip).country.iso_code or 'XX'
    except:
        return 'XX'

# ═══════════════════════════════════════════════════════════════
# 🔍 ПАРСИНГ
# ═══════════════════════════════════════════════════════════════
def safe_b64(s):
    s = s.strip().replace('\n', '').replace('\r', '')
    s += '=' * (4 - len(s) % 4) if len(s) % 4 else ''
    for dec in [base64.urlsafe_b64decode, base64.b64decode]:
        try:
            return dec(s).decode('utf-8', errors='ignore')
        except:
            pass
    return ""

def extract_links(text):
    regex = r"(vless://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+|hysteria2://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    if len(links) < 3:
        decoded = safe_b64(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    seen = set()
    unique = []
    for link in links:
        clean = link.split('#')[0]
        if clean not in seen:
            seen.add(clean)
            unique.append(link)
    return unique

def is_valid_uuid(s):
    return bool(re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', s, re.I))

def is_valid_port(p):
    try:
        return 1 <= int(p) <= 65535
    except:
        return False

def is_valid_host(h):
    if not h or len(h) < 4:
        return False
    if h.startswith(('127.', '192.168.', '10.', '0.')) or h == 'localhost':
        return False
    return True

def has_good_sni(params):
    sni = params.get('sni', [''])[0].lower()
    for b in BLOCKED_SNIS:
        if b in sni:
            return False
    for t in TRUSTED_SNIS:
        if t in sni:
            return True
    return '.' in sni and not sni[0].isdigit()

def get_reality_score(params):
    if params.get('security', [''])[0].lower() != 'reality':
        return 0
    score = 50
    sni = params.get('sni', [''])[0].lower()
    for t in TRUSTED_SNIS[:10]:
        if t in sni:
            score += 30
            break
    else:
        if has_good_sni(params):
            score += 15
    if params.get('fp', [''])[0].lower() in ['chrome', 'firefox', 'safari', 'edge']:
        score += 10
    if len(params.get('pbk', [''])[0]) == 43:
        score += 10
    return min(score, 100)

def parse_config(config_str, source_type):
    if not config_str or len(config_str) < 20:
        return None
    
    try:
        # HYSTERIA2
        if config_str.startswith(("hy2://", "hysteria2://")):
            prefix = "hy2://" if config_str.startswith("hy2://") else "hysteria2://"
            parts = config_str.split("@")
            if len(parts) < 2:
                return None
            
            password = parts[0].replace(prefix, "")
            rest = parts[1]
            
            if "?" in rest:
                host_port, query = rest.split("?", 1)
            else:
                host_port, query = rest.split("#")[0] if "#" in rest else rest, ""
            
            if "#" in query:
                query, remark = query.split("#", 1)
            elif "#" in host_port:
                host_port, remark = host_port.split("#", 1)
            else:
                remark = "Hy2"
            
            if ":" not in host_port:
                return None
            
            host, port = host_port.rsplit(":", 1)
            if not is_valid_host(host) or not is_valid_port(port):
                return None
            
            params = parse_qs(query) if query else {}
            
            return {
                "ip": host, "port": int(port), "uuid": password,
                "original": config_str, "remark": unquote(remark).strip(),
                "latency": 9999, "info": {}, "speed": 0.0,
                "transport": "udp", "security": "tls",
                "is_reality": False, "is_hy2": True,
                "source": source_type, "params": params,
                "sni": params.get('sni', [''])[0],
                "reality_score": 0, "good_sni": False
            }
        
        # VLESS
        if config_str.startswith("vless://"):
            if "@" not in config_str or "?" not in config_str:
                return None
            
            uuid = config_str.split("@")[0].replace("vless://", "")
            if not is_valid_uuid(uuid):
                return None
            
            rest = config_str.split("@")[1]
            host_port = rest.split("?")[0]
            
            if ":" not in host_port:
                return None
            
            host, port = host_port.rsplit(":", 1)
            if not is_valid_host(host) or not is_valid_port(port):
                return None
            
            query = rest.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            is_reality = security == 'reality'
            
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) != 43:
                    return None
                sni = params.get('sni', [''])[0]
                if sni == host:
                    return None
                for b in BLOCKED_SNIS:
                    if b in sni.lower():
                        return None
            
            remark = unquote(config_str.split("#")[-1]).strip() if "#" in config_str else "VLESS"
            
            return {
                "ip": host, "port": int(port), "uuid": uuid,
                "original": config_str, "remark": remark,
                "latency": 9999, "info": {}, "speed": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_hy2": False,
                "source": source_type, "params": params,
                "reality_score": get_reality_score(params),
                "good_sni": has_good_sni(params) if is_reality else False
            }
    except:
        pass
    
    return None

# ═══════════════════════════════════════════════════════════════
# 🌐 СЕТЕВЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def tcp_ping(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT_TCP)
        start = time.perf_counter()
        if sock.connect_ex((host, port)) == 0:
            return (time.perf_counter() - start) * 1000
    except:
        pass
    finally:
        try:
            sock.close()
        except:
            pass
    return None

def gen_xray_config(server, port):
    try:
        if server.get('is_hy2'):
            return {
                "log": {"loglevel": "error"},
                "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [{
                    "protocol": "hysteria2",
                    "settings": {"vnext": [{"address": server['ip'], "port": server['port'], "users": [{"password": server['uuid']}]}]},
                    "streamSettings": {"network": "udp", "security": "tls", "tlsSettings": {"serverName": server.get('sni', ''), "allowInsecure": True}}
                }]
            }
        
        params = server['params']
        user = {"id": server['uuid'], "encryption": "none"}
        flow = params.get('flow', [''])[0]
        if flow:
            user["flow"] = flow
        
        stream = {"network": server['transport'], "security": server['security']}
        
        if server['transport'] == 'ws':
            stream["wsSettings"] = {"path": params.get('path', ['/'])[0]}
            if params.get('host'):
                stream["wsSettings"]["headers"] = {"Host": params['host'][0]}
        elif server['transport'] == 'grpc' and params.get('serviceName'):
            stream["grpcSettings"] = {"serviceName": params['serviceName'][0]}
        
        if server['security'] == 'tls':
            stream["tlsSettings"] = {"serverName": params.get('sni', [''])[0], "fingerprint": params.get('fp', ['chrome'])[0]}
        elif server['security'] == 'reality':
            stream["realitySettings"] = {
                "fingerprint": params.get('fp', ['chrome'])[0],
                "serverName": params.get('sni', [''])[0],
                "publicKey": params.get('pbk', [''])[0],
                "shortId": params.get('sid', [''])[0],
                "spiderX": params.get('spx', ['/'])[0]
            }
        
        return {
            "log": {"loglevel": "error"},
            "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": server['ip'], "port": server['port'], "users": [user]}]}, "streamSettings": stream}]
        }
    except:
        return None

def measure_speed(port):
    try:
        proxies = {"http": f"socks5h://127.0.0.1:{port}", "https": f"socks5h://127.0.0.1:{port}"}
        start = time.time()
        with requests.get("https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe",
                         proxies=proxies, timeout=TIMEOUT_SPEED, stream=True) as r:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_content(32768):
                total += len(chunk)
                if total > 1.5 * 1024 * 1024:
                    break
            return round((total * 8) / (max(0.1, time.time() - start) * 1_000_000), 2)
    except:
        return 0.0

def check_udp(port):
    if not socks:
        return False
    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
        s.set_proxy(socks.SOCKS5, "127.0.0.1", port)
        s.settimeout(3.0)
        s.sendto(binascii.unhexlify("aaaa0100000100000000000006676f6f676c6503636f6d0000010001"), ("8.8.8.8", 53))
        s.recvfrom(512)
        return True
    except:
        return False
    finally:
        try:
            s.close()
        except:
            pass

def check_endpoints(port):
    endpoints = [
        ("https://www.google.com/generate_204", 204),
        ("https://cp.cloudflare.com/", 200),
        ("https://www.gstatic.com/generate_204", 204),
    ]
    proxies = {'http': f'socks5://127.0.0.1:{port}', 'https': f'socks5://127.0.0.1:{port}'}
    ok = 0
    lat = 0
    for url, code in endpoints:
        try:
            start = time.perf_counter()
            r = requests.get(url, proxies=proxies, timeout=4, verify=False)
            if r.status_code == code or 200 <= r.status_code < 300:
                ok += 1
                lat += (time.perf_counter() - start) * 1000
        except:
            pass
    return lat / ok if ok >= 2 else None

def deep_check(server):
    port = random.randint(10000, 60000)
    config = gen_xray_config(server, port)
    if not config:
        return None, 0.0, False
    
    path = None
    proc = None
    lat, speed, udp = None, 0.0, False
    
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
            json.dump(config, f)
            path = f.name
        
        proc = subprocess.Popen([XRAY_BIN, "-config", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        
        if proc.poll() is not None:
            raise Exception("Xray died")
        
        lat = check_endpoints(port)
        if lat:
            udp = check_udp(port)
            speed = measure_speed(port)
            update_history(server['ip'], server['port'], True, server.get('is_reality', False))
        else:
            update_history(server['ip'], server['port'], False)
    except:
        update_history(server['ip'], server['port'], False)
    finally:
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except:
                try:
                    proc.kill()
                except:
                    pass
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
    
    return lat, speed, udp

# ═══════════════════════════════════════════════════════════════
# ✅ ПРОВЕРКИ
# ═══════════════════════════════════════════════════════════════
def initial_check(server, progress=None):
    ip, port = server['ip'], server['port']
    
    if not should_check(ip, port):
        if progress:
            progress.increment(False)
        return None
    
    cc = get_country(ip)
    server['info'] = {'cc': cc}
    
    if server['source'] == 'whitelist':
        if cc not in WHITELIST_COUNTRIES:
            if progress:
                progress.increment(False)
            return None
    else:
        if cc in BLACKLIST_COUNTRIES or cc in WHITELIST_COUNTRIES:
            if progress:
                progress.increment(False)
            return None
    
    ping = tcp_ping(ip, port)
    if ping is None:
        update_history(ip, port, False)
        if progress:
            progress.increment(False)
        return None
    
    server['latency'] = int(ping)
    server['streak'] = get_streak(ip, port)
    
    if progress:
        progress.increment(True)
    
    return server

def full_check(server, progress=None):
    lat, speed, udp = deep_check(server)
    
    if lat is None:
        if progress:
            progress.increment(False)
        return None
    
    server['real_lat'] = lat
    server['speed'] = speed
    server['udp'] = udp
    
    cc = server['info']['cc']
    name = get_country_name(cc)
    udp_str = "UDP✅" if udp else "UDP❌"
    reality_str = "Reality" if server.get('is_reality') else ""
    
    logger.info(f"   🎯 {server['ip']} ({name}) - {speed:.1f}Mbps, {lat:.0f}ms {udp_str} {reality_str}")
    
    if progress:
        progress.increment(True)
    
    return server

# ═══════════════════════════════════════════════════════════════
# 📥 СБОР КОНФИГОВ
# ═══════════════════════════════════════════════════════════════
def fetch_url(url, src):
    try:
        r = requests.get(url, timeout=TIMEOUT_FETCH, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            configs = [parse_config(link, src) for link in extract_links(r.text)]
            return [c for c in configs if c]
    except:
        pass
    return []

def fetch_tg(channel):
    try:
        r = requests.get(f"https://t.me/s/{channel}", timeout=TIMEOUT_FETCH)
        if r.status_code == 200:
            configs = [parse_config(link, 'telegram') for link in extract_links(r.text)]
            return [c for c in configs if c]
    except:
        pass
    return []

def fetch_issues(repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/issues?state=all&per_page=10",
                        timeout=TIMEOUT_FETCH, headers={'User-Agent': 'VPN'})
        if r.status_code == 200:
            configs = []
            for issue in r.json():
                text = f"{issue.get('title', '')}\n{issue.get('body', '') or ''}"
                for link in extract_links(text):
                    c = parse_config(link, 'github')
                    if c:
                        configs.append(c)
            return configs
    except:
        pass
    return []

def collect_all():
    global_cfgs = []
    whitelist_cfgs = []
    
    logger.info("📥 Сбор конфигов...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_FETCH) as ex:
        futures = {}
        for url in REALITY_URLS:
            futures[ex.submit(fetch_url, url, 'reality')] = 'reality'
        for url in PREMIUM_URLS:
            futures[ex.submit(fetch_url, url, 'premium')] = 'premium'
        for url in GENERAL_URLS:
            futures[ex.submit(fetch_url, url, 'general')] = 'general'
        for url in WHITELIST_URLS:
            futures[ex.submit(fetch_url, url, 'whitelist')] = 'whitelist'
        for ch in TELEGRAM_CHANNELS:
            futures[ex.submit(fetch_tg, ch)] = 'telegram'
        for repo in GITHUB_ISSUES_REPOS:
            futures[ex.submit(fetch_issues, repo)] = 'github'
        
        for future in concurrent.futures.as_completed(futures):
            try:
                configs = future.result()
                for c in configs:
                    if c['source'] == 'whitelist':
                        whitelist_cfgs.append(c)
                    else:
                        global_cfgs.append(c)
            except:
                pass
    
    reality_count = sum(1 for c in global_cfgs if c.get('is_reality'))
    logger.info(f"\n📊 Собрано: {len(global_cfgs)} глобальных ({reality_count} Reality), {len(whitelist_cfgs)} whitelist")
    
    return global_cfgs, whitelist_cfgs

def fetch_warp_configs():
    """Сбор WARP конфигов"""
    warp_list = []
    
    logger.info("🔄 Сбор WARP конфигов...")
    
    for url in WARP_URLS:
        try:
            r = requests.get(url, timeout=TIMEOUT_FETCH)
            if r.status_code == 200:
                text = r.text
                decoded = safe_b64(text)
                if decoded:
                    text = decoded
                
                # Ищем warp:// ссылки
                warp_regex = r"(warp://[^\s\n<>\"']+)"
                links = re.findall(warp_regex, text)
                warp_list.extend(links)
                
                # Ищем vless/hy2 с пометкой warp в названии
                for link in extract_links(text):
                    lower_link = link.lower()
                    if 'warp' in lower_link or 'cloudflare' in lower_link or 'cf-' in lower_link:
                        if link not in warp_list:
                            warp_list.append(link)
        except:
            pass
    
    warp_list = list(set(warp_list))
    logger.info(f"   🔄 Найдено WARP: {len(warp_list)}")
    
    return warp_list

# ═══════════════════════════════════════════════════════════════
# 🏆 ФИНАЛЬНЫЙ ОТБОР - 9 СЕРВЕРОВ
# ═══════════════════════════════════════════════════════════════
def select_final_9(verified_global, verified_whitelist, warp_links):
    """
    Выбирает РОВНО 9 серверов:
    
    🎮🇫🇮 Финляндия | 📅15:30      ← GAME-1 с временем последнего обновления
    🎮🇪🇪 Эстония | 📅15:50        ← GAME-2 с временем следующего обновления
    ⚡🇩🇪 Германия                  ← UNIVERSAL-1
    ⚡🇳🇱 Нидерланды                ← UNIVERSAL-2
    ⚡🇵🇱 Польша                    ← UNIVERSAL-3
    🔄🇫🇮 Финляндия                 ← WARP-1
    🔄🇳🇱 Нидерланды                ← WARP-2
    ⚪🇷🇺 (РКН)                     ← WHITELIST-1
    ⚪🇷🇺 (РКН)                     ← WHITELIST-2
    """
    
    final = []
    reserve = []
    used_ips = set()
    
    last_update = get_last_update_time()
    next_update = get_next_update_time()
    
    # ═══════ ПОДГОТОВКА ПУЛОВ ═══════
    
    # GAME: Tier 1-2, сортировка по пингу
    game_pool = [s for s in verified_global 
                 if s['info']['cc'] in GAME_COUNTRIES and s['speed'] >= MIN_SPEED_GAME]
    game_pool = sorted(game_pool, key=lambda x: (x['real_lat'], -x['speed']))
    
    # Если мало GAME кандидатов, добавляем из других стран
    if len(game_pool) < 2:
        extra = [s for s in verified_global if s['info']['cc'] not in GAME_COUNTRIES and s['speed'] >= MIN_SPEED_GAME]
        extra = sorted(extra, key=lambda x: x['real_lat'])
        game_pool.extend(extra)
    
    # UNIVERSAL: все страны, сортировка по скорости
    univ_pool = sorted(verified_global, key=lambda x: (-x.get('is_reality', False), -x['speed']))
    
    # WHITELIST: RU, сортировка по скорости
    wl_pool = sorted(verified_whitelist, key=lambda x: -x['speed'])
    
    logger.info(f"\n📊 Пулы: GAME={len(game_pool)}, UNIVERSAL={len(univ_pool)}, WHITELIST={len(wl_pool)}, WARP={len(warp_links)}")
    
    # ═══════ 🎮 GAME-1 (с временем последнего обновления) ═══════
    logger.info(f"\n🎮 Выбор GAME серверов...")
    
    candidates = [s for s in game_pool if s['ip'] not in used_ips]
    if candidates:
        s = candidates[0]
        used_ips.add(s['ip'])
        cc = s['info']['cc']
        # Формат: 🎮🇫🇮 Финляндия | 📅15:30
        s['final_name'] = f"🎮{get_flag(cc)} {get_country_name(cc)} | 📅{last_update}"
        s['role'] = 'GAME'
        final.append(s)
        logger.info(f"   GAME-1: {s['ip']} ({get_country_name(cc)}) - {s['real_lat']:.0f}ms, {s['speed']:.1f}Mbps")
    else:
        logger.warning("   ⚠️ GAME-1 не найден, используем fallback")
        if univ_pool:
            s = univ_pool[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            s['final_name'] = f"🎮{get_flag(cc)} {get_country_name(cc)} | 📅{last_update}"
            s['role'] = 'GAME'
            final.append(s)
    
    # ═══════ 🎮 GAME-2 (с временем следующего обновления) ═══════
    candidates = [s for s in game_pool if s['ip'] not in used_ips]
    if candidates:
        s = candidates[0]
        used_ips.add(s['ip'])
        cc = s['info']['cc']
        # Формат: 🎮🇪🇪 Эстония | 📅15:50
        s['final_name'] = f"🎮{get_flag(cc)} {get_country_name(cc)} | 📅{next_update}"
        s['role'] = 'GAME'
        final.append(s)
        logger.info(f"   GAME-2: {s['ip']} ({get_country_name(cc)}) - {s['real_lat']:.0f}ms, {s['speed']:.1f}Mbps")
    else:
        logger.warning("   ⚠️ GAME-2 не найден, используем fallback")
        candidates = [s for s in univ_pool if s['ip'] not in used_ips]
        if candidates:
            s = candidates[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            s['final_name'] = f"🎮{get_flag(cc)} {get_country_name(cc)} | 📅{next_update}"
            s['role'] = 'GAME'
            final.append(s)
    
    # ═══════ ⚡ UNIVERSAL ×3 ═══════
    logger.info(f"\n⚡ Выбор UNIVERSAL серверов...")
    
    for i in range(3):
        candidates = [s for s in univ_pool if s['ip'] not in used_ips]
        if candidates:
            s = candidates[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            # Формат: ⚡🇩🇪 Германия
            s['final_name'] = f"⚡{get_flag(cc)} {get_country_name(cc)}"
            s['role'] = 'UNIVERSAL'
            final.append(s)
            logger.info(f"   UNIVERSAL-{i+1}: {s['ip']} ({get_country_name(cc)}) - {s['speed']:.1f}Mbps")
        else:
            logger.warning(f"   ⚠️ UNIVERSAL-{i+1} не найден")
    
    # ═══════ 🔄 WARP ×2 ═══════
    logger.info(f"\n🔄 Выбор WARP серверов...")
    
    warp_added = 0
    
    # Пробуем найти WARP-подобные конфиги с известной страной
    for warp_link in warp_links[:5]:
        if warp_added >= 2:
            break
        
        # Парсим WARP конфиг
        parsed = parse_config(warp_link, 'warp')
        if parsed and parsed['ip'] not in used_ips:
            cc = get_country(parsed['ip']) if parsed['ip'] else 'CF'
            if cc == 'XX':
                cc = 'CF'
            
            parsed['info'] = {'cc': cc}
            parsed['real_lat'] = 30
            parsed['speed'] = 50.0
            parsed['udp'] = True
            parsed['is_warp'] = True
            # Формат: 🔄🇫🇮 Финляндия или 🔄 WARP
            if cc != 'CF':
                parsed['final_name'] = f"🔄{get_flag(cc)} {get_country_name(cc)}"
            else:
                parsed['final_name'] = f"🔄 WARP-{warp_added + 1}"
            parsed['role'] = 'WARP'
            
            used_ips.add(parsed['ip'])
            final.append(parsed)
            warp_added += 1
            logger.info(f"   WARP-{warp_added}: {parsed.get('final_name')}")
    
    # Если WARP конфигов не хватает, используем обычные серверы как fallback
    while warp_added < 2:
        candidates = [s for s in univ_pool if s['ip'] not in used_ips]
        if candidates:
            s = candidates[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            s['final_name'] = f"🔄{get_flag(cc)} {get_country_name(cc)}"
            s['role'] = 'WARP'
            s['is_warp'] = False
            final.append(s)
            warp_added += 1
            logger.info(f"   WARP-{warp_added}: {s['ip']} ({get_country_name(cc)}) [fallback]")
        else:
            logger.warning(f"   ⚠️ WARP-{warp_added + 1} не найден")
            break
    
    # ═══════ ⚪ WHITELIST ×2 ═══════
    logger.info(f"\n⚪ Выбор WHITELIST серверов...")
    
    for i in range(2):
        if i < len(wl_pool):
            s = wl_pool[i]
            cc = s['info']['cc']
            # Формат: ⚪🇷🇺 (РКН)
            s['final_name'] = f"⚪{get_flag(cc)} (РКН)"
            s['role'] = 'WHITELIST'
            final.append(s)
            logger.info(f"   WHITELIST-{i+1}: {s['ip']} - {s['speed']:.1f}Mbps")
        else:
            logger.warning(f"   ⚠️ WHITELIST-{i+1} не найден в пуле")
    
    # ═══════ 📦 РЕЗЕРВНЫЙ ПУЛ ═══════
    remaining = [s for s in verified_global if s['ip'] not in used_ips]
    reserve = sorted(remaining, key=lambda x: (-x.get('is_reality', False), -x['speed']))[:RESERVE_POOL_SIZE]
    
    # ═══════ ПРОВЕРКА 9 СЕРВЕРОВ ═══════
    logger.info(f"\n✅ Итого в подписке: {len(final)} серверов")
    
    if len(final) < 9:
        logger.warning(f"⚠️ Только {len(final)} серверов! Добавляем резервные...")
        while len(final) < 9 and reserve:
            s = reserve.pop(0)
            cc = s['info']['cc']
            s['final_name'] = f"⚡{get_flag(cc)} {get_country_name(cc)}"
            s['role'] = 'RESERVE'
            final.append(s)
            logger.info(f"   Добавлен резерв: {s['ip']} ({get_country_name(cc)})")
    
    logger.info(f"📦 Резервный пул: {len(reserve)} серверов")
    
    return final, reserve

# ═══════════════════════════════════════════════════════════════
# 💾 СОХРАНЕНИЕ
# ═══════════════════════════════════════════════════════════════
def save_results(final, reserve, stats):
    # 1. Подписка (base64)
    links = []
    for s in final:
        base = s['original'].split('#')[0]
        links.append(f"{base}#{quote(s['final_name'])}")
    
    try:
        with open(OUTPUT_FILE, 'w') as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        logger.info(f"💾 Подписка: {OUTPUT_FILE} ({len(links)} серверов)")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    
    # 2. JSON статистика
    json_data = {
        "servers": [],
        "updated": datetime.now(timezone.utc).isoformat(),
        "updated_msk": get_timestamp(),
        "next_update_msk": get_next_update_time(),
        "stats": stats,
        "version": "V122"
    }
    
    for s in final:
        cc = s.get('info', {}).get('cc', 'XX')
        json_data["servers"].append({
            "name": s.get('final_name', ''),
            "role": s.get('role', 'UNKNOWN'),
            "ip": s.get('ip', ''),
            "port": s.get('port', 0),
            "country": cc,
            "country_name": get_country_name(cc),
            "speed_mbps": s.get('speed', 0),
            "latency_ms": s.get('real_lat', 0),
            "udp": s.get('udp', False),
            "is_reality": s.get('is_reality', False),
            "is_warp": s.get('is_warp', False),
            "original": s.get('original', '')
        })
    
    try:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
    except:
        pass
    
    # 3. Резервный пул
    pool = {"updated": get_timestamp(), "servers": []}
    for s in reserve:
        cc = s.get('info', {}).get('cc', 'XX')
        pool["servers"].append({
            "ip": s['ip'], "port": s['port'], "country": cc,
            "country_name": get_country_name(cc),
            "speed_mbps": s.get('speed', 0), "latency_ms": s.get('real_lat', 0),
            "is_reality": s.get('is_reality', False), "original": s['original']
        })
    
    try:
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Резерв: {len(reserve)} серверов")
    except:
        pass

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start = time.time()
    
    print("═" * 70)
    logger.info("🚀 FL1P VPN V122 - PERFECT 9 EDITION")
    logger.info(f"   ⏰ {get_timestamp()}")
    logger.info("   📋 Структура: 2×GAME + 3×UNIVERSAL + 2×WARP + 2×WHITELIST = 9")
    logger.info("   🎨 Формат: 🎮🇫🇮 Финляндия | 📅15:30")
    print("═" * 70)
    
    load_history()
    
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ Xray не найден: {XRAY_BIN}")
        return
    os.chmod(XRAY_BIN, 0o755)
    
    download_mmdb()
    init_geoip()
    
    # ═══ ЭТАП 1: СБОР ═══
    logger.info("\n" + "═" * 50)
    logger.info("📥 ЭТАП 1: СБОР КОНФИГОВ")
    logger.info("═" * 50)
    
    global_cfgs, whitelist_cfgs = collect_all()
    warp_links = fetch_warp_configs()
    
    # Дедупликация
    unique_global = {}
    for c in global_cfgs:
        key = f"{c['ip']}:{c['port']}"
        if key not in unique_global or (c.get('is_reality') and not unique_global[key].get('is_reality')):
            unique_global[key] = c
    global_list = list(unique_global.values())
    
    unique_wl = {}
    for c in whitelist_cfgs:
        key = f"{c['ip']}:{c['port']}"
        if key not in unique_wl:
            unique_wl[key] = c
    wl_list = list(unique_wl.values())
    
    logger.info(f"🔍 Уникальных: {len(global_list)} глобальных, {len(wl_list)} whitelist")
    
    # ═══ ЭТАП 2: TCP ═══
    logger.info("\n" + "═" * 50)
    logger.info("⚡ ЭТАП 2: TCP ПРОВЕРКА")
    logger.info("═" * 50)
    
    alive_global = []
    progress = ProgressCounter(len(global_list), "Глобальные")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, progress) for s in global_list])]:
            if r:
                alive_global.append(r)
    
    alive_wl = []
    progress = ProgressCounter(len(wl_list), "Whitelist")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, progress) for s in wl_list])]:
            if r:
                alive_wl.append(r)
    
    logger.info(f"\n✅ Живых: {len(alive_global)} глобальных, {len(alive_wl)} whitelist")
    
    # Статистика по странам
    cc_stats = {}
    for s in alive_global:
        cc = s['info']['cc']
        cc_stats[cc] = cc_stats.get(cc, 0) + 1
    
    logger.info("\n📊 Топ стран:")
    for cc, cnt in sorted(cc_stats.items(), key=lambda x: -x[1])[:10]:
        tier = "T1" if cc in TIER_1_COUNTRIES else ("T2" if cc in TIER_2_COUNTRIES else ("T3" if cc in TIER_3_COUNTRIES else "T4"))
        logger.info(f"   {get_flag(cc)} {cc} ({get_country_name(cc)}): {cnt} [{tier}]")
    
    # ═══ ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА ═══
    logger.info("\n" + "═" * 50)
    logger.info("🧪 ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА")
    logger.info("═" * 50)
    
    def sort_key(s):
        tier = 1 if s['info']['cc'] in TIER_1_COUNTRIES else (2 if s['info']['cc'] in TIER_2_COUNTRIES else (3 if s['info']['cc'] in TIER_3_COUNTRIES else 4))
        reality = -20 if s.get('good_sni') else (-10 if s.get('is_reality') else 0)
        return (reality, tier, s['latency'])
    
    candidates_global = sorted(alive_global, key=sort_key)[:MAX_DEEP_CHECK_GLOBAL]
    candidates_wl = alive_wl[:MAX_DEEP_CHECK_WHITELIST]
    
    logger.info(f"   К проверке: {len(candidates_global)} глобальных, {len(candidates_wl)} whitelist")
    
    verified_global = []
    progress = ProgressCounter(len(candidates_global), "Глобальные")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, progress): s for s in candidates_global})]:
            if r:
                verified_global.append(r)
    
    verified_wl = []
    progress = ProgressCounter(len(candidates_wl), "Whitelist")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, progress): s for s in candidates_wl})]:
            if r:
                verified_wl.append(r)
    
    logger.info(f"\n✅ Прошли: {len(verified_global)} глобальных, {len(verified_wl)} whitelist")
    
    # ═══ ЭТАП 4: ФИНАЛ ═══
    logger.info("\n" + "═" * 50)
    logger.info("🏆 ЭТАП 4: ФИНАЛЬНЫЙ ОТБОР")
    logger.info("═" * 50)
    
    final_9, reserve = select_final_9(verified_global, verified_wl, warp_links)
    
    # ═══ ВЫВОД ═══
    print("\n" + "═" * 70)
    logger.info("🏆 THE FINAL 9:")
    print("═" * 70)
    
    for i, s in enumerate(final_9):
        role = s.get('role', 'UNKNOWN')
        cc = s.get('info', {}).get('cc', 'XX')
        
        if s.get('is_warp') and 'WARP' in s.get('final_name', ''):
            print(f"\n   {i+1}. {s['final_name']}")
            print(f"      Cloudflare WARP")
        else:
            udp = "UDP✅" if s.get('udp') else "UDP❌"
            print(f"\n   {i+1}. {s['final_name']}")
            print(f"      {s['ip']} | {s.get('speed', 0):.1f}Mbps | {s.get('real_lat', 0):.0f}ms | {udp}")
    
    print()
    
    # ═══ СОХРАНЕНИЕ ═══
    stats = {
        "total": len(global_cfgs) + len(whitelist_cfgs),
        "unique_global": len(global_list),
        "unique_whitelist": len(wl_list),
        "alive_global": len(alive_global),
        "alive_whitelist": len(alive_wl),
        "verified_global": len(verified_global),
        "verified_whitelist": len(verified_wl),
        "warp_found": len(warp_links),
        "reserve": len(reserve),
        "final_count": len(final_9)
    }
    
    save_results(final_9, reserve, stats)
    save_history()
    close_geoip()
    
    elapsed = time.time() - start
    print("═" * 70)
    logger.info(f"✅ ГОТОВО за {elapsed:.1f} сек")
    logger.info(f"📊 {len(global_cfgs)}→{len(alive_global)}→{len(verified_global)}→{len(final_9)} серверов")
    print("═" * 70)

if __name__ == "__main__":
    main()
