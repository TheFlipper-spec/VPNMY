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
#  FL1P VPN SCANNER V120 - PREMIUM EDITION
#  
#  Структура подписки:
#  🎮 GAME-1, GAME-2      - Минимальный пинг для игр (FI, EE, LV, LT)
#  🌐 UNIVERSAL-1,2,3     - Универсальные быстрые серверы
#  ☁️ WARP-1, WARP-2      - Cloudflare WARP (или резервные)
#  🇷🇺 WHITELIST-1,2      - Российские серверы для RU сайтов
#
# ═══════════════════════════════════════════════════════════════
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
# 🌍 GEO НАСТРОЙКИ - ТИРЫ СТРАН
# ═══════════════════════════════════════════════════════════════

# Тир 1: Ближайшие к России (пинг 10-30ms) - ИДЕАЛЬНО ДЛЯ ИГР
TIER_1_COUNTRIES = ['FI', 'EE', 'LV', 'LT']

# Тир 2: Близкие страны (пинг 30-60ms)
TIER_2_COUNTRIES = ['SE', 'NO', 'PL']

# Тир 3: Европа (пинг 50-100ms)
TIER_3_COUNTRIES = ['DE', 'NL', 'AT', 'CZ', 'DK', 'BE', 'CH']

# Тир 4: Дальняя Европа (пинг 80-150ms)
TIER_4_COUNTRIES = ['GB', 'FR', 'IT', 'ES', 'PT', 'IE', 'HU', 'RO', 'BG', 'SK']

# Все допустимые страны для глобальных серверов (БЕЗ RU и BY!)
ALLOWED_GLOBAL_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES + TIER_3_COUNTRIES + TIER_4_COUNTRIES

# Страны для WHITELIST (только RU)
WHITELIST_COUNTRIES = ['RU']

# Черный список (никогда не использовать)
BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP', 'US', 'BY']

# Названия стран на русском
RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция',
    'RU': 'Россия', 'UA': 'Украина', 'KZ': 'Казахстан', 'BY': 'Беларусь',
    'TR': 'Турция', 'MD': 'Молдова',
    'JP': 'Япония', 'SG': 'Сингапур', 'HK': 'Гонконг', 'KR': 'Корея',
    'CA': 'Канада', 'AU': 'Австралия', 'IN': 'Индия', 'BR': 'Бразилия',
}

# ═══════════════════════════════════════════════════════════════
# 🔥 ИСТОЧНИКИ КОНФИГОВ
# ═══════════════════════════════════════════════════════════════

# 🛡️ REALITY - Приоритетные источники (обход DPI)
REALITY_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/lagzian/SS-Collector/main/realitiy_api.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/reality.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/reality.txt",
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub/vless",
]

# 🥇 PREMIUM - Качественные агрегаторы
PREMIUM_URLS = [
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/Config/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/vless",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/hysteria2",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
]

# 📦 GENERAL - Общие источники
GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/master/collected-proxies/row-url/all.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/master/sub/share/vless",
]

# 🇷🇺 WHITELIST - Российские серверы для обхода блокировок RU сайтов
WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",
    "https://raw.githubusercontent.com/STARTER-X-0/STARTER-X-VPN/refs/heads/main/RU-WHITE-LIST",
]

# ☁️ WARP - Cloudflare WARP конфиги
WARP_URLS = [
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/warp",
    "https://raw.githubusercontent.com/NiREvil/vless/main/sub/warp",
    "https://raw.githubusercontent.com/ircfspace/warpsub/main/export/warp",
]

# 📱 TELEGRAM - Каналы с конфигами
TELEGRAM_CHANNELS = [
    # Reality-focused
    "PrivateVPNs", "iSegaro", "reality_daily", "RealityVpnChannel",
    # Общие качественные
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir",
    "v2ray_configs_pool", "VlessConfig", "v2ray1_ng",
    "DirectVPN", "v2ray_alpha", "customv2ray", 
    "ConfigsHUB", "freev2rayssr",
    # Дополнительные
    "proxy_mtm", "ShadowProxy66", "Proxy_PJ",
    "SafeNet_Server", "Awlix_ir", "VmessProtocol",
    "ServerNett", "V2RayTz", "VpnProSec",
]

# 🐙 GITHUB ISSUES - Парсинг Issues
GITHUB_ISSUES_REPOS = [
    "barry-far/V2ray-Configs",
    "Pawdroid/Free-servers", 
    "mahdibland/V2RayAggregator",
    "yebekhe/TelegramV2rayCollector",
    "NiREvil/vless",
]

# ═══════════════════════════════════════════════════════════════
# ⚙️ СИСТЕМНЫЕ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

# Воркеры
MAX_WORKERS_SCAN = 50
MAX_WORKERS_DEEP = 10
MAX_WORKERS_FETCH = 15

# Таймауты (оптимизированные)
TIMEOUT_TCP = 0.6
TIMEOUT_REAL = 8.0
TIMEOUT_SPEED = 5.0
TIMEOUT_FETCH = 5.0

# Лимиты
MAX_DEEP_CHECK_GLOBAL = 400
MAX_DEEP_CHECK_WHITELIST = 100

# Критерии качества
MIN_SPEED_GAME = 3.0       # Mbps для GAME серверов (важнее пинг)
MIN_SPEED_UNIVERSAL = 5.0   # Mbps для UNIVERSAL
MIN_SPEED_WARP = 2.0        # Mbps для WARP
MIN_SPEED_WHITELIST = 0.5   # Mbps для WHITELIST

MAX_PING_GAME = 100         # ms для GAME серверов
MAX_PING_UNIVERSAL = 200    # ms для UNIVERSAL

# Файлы
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

TIMEZONE_OFFSET = 3
CACHE_TTL_HOURS = 4
MAX_FAILURES = 2
RESERVE_POOL_SIZE = 25

# ═══════════════════════════════════════════════════════════════
# 🛡️ REALITY НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
TRUSTED_REALITY_SNIS = [
    'www.google.com', 'google.com',
    'www.microsoft.com', 'microsoft.com',
    'www.apple.com', 'apple.com',
    'www.cloudflare.com', 'cloudflare.com',
    'www.mozilla.org', 'mozilla.org',
    'www.yahoo.com', 'yahoo.com',
    'www.amazon.com', 'amazon.com',
    'www.github.com', 'github.com',
    'www.samsung.com', 'samsung.com',
    'www.nvidia.com', 'nvidia.com',
    'cdn.jsdelivr.net', 'ajax.googleapis.com',
    'www.docker.com', 'www.oracle.com',
    'www.cisco.com', 'www.ibm.com',
    'www.dell.com', 'www.hp.com',
    'www.whatsapp.com', 'www.spotify.com',
]

BLOCKED_SNIS = [
    'discord.com', 'discordapp.com',
    'twitter.com', 'x.com',
    'facebook.com', 'instagram.com',
    'linkedin.com', 'tiktok.com',
]

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════
geo_reader = None
server_history = {}

# ═══════════════════════════════════════════════════════════════
# 🎨 УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_msk_time():
    """Возвращает текущее время MSK"""
    return datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)

def get_beautiful_time():
    """Красивое время для названия сервера"""
    return f"🕐{get_msk_time().strftime('%H:%M')}"

def get_timestamp():
    """Timestamp для логов"""
    return get_msk_time().strftime('%Y-%m-%d %H:%M:%S MSK')

def get_country_flag(country_code):
    """Преобразует код страны в эмодзи флаг"""
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def format_server_name(base_name, country_code, include_time=False):
    """Форматирует название сервера"""
    flag = get_country_flag(country_code)
    if include_time:
        return f"{flag} {base_name} | {get_beautiful_time()}"
    return f"{flag} {base_name}"

def get_country_tier(country_code):
    """Возвращает тир страны (1-4, 0 для запрещённых)"""
    if country_code in BLACKLIST_COUNTRIES:
        return 0
    if country_code in TIER_1_COUNTRIES:
        return 1
    if country_code in TIER_2_COUNTRIES:
        return 2
    if country_code in TIER_3_COUNTRIES:
        return 3
    if country_code in TIER_4_COUNTRIES:
        return 4
    return 5  # Неизвестные страны

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
    else:
        logger.info("📂 История не найдена, создаём новую")

def save_history():
    current_ts = time.time()
    clean = {k: v for k, v in server_history.items()
             if v.get('fails', 0) < MAX_FAILURES and current_ts - v.get('ts', 0) < 86400}
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2)
        logger.debug(f"💾 История сохранена: {len(clean)} записей")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения истории: {e}")

def update_history(ip, port, is_alive, is_reality=False):
    key = f"{ip}:{port}"
    current = server_history.get(key, {'fails': 0, 'ts': 0, 'streak': 0})
    if is_alive:
        current['fails'] = 0
        current['streak'] = current.get('streak', 0) + 1
        current['is_reality'] = is_reality
    else:
        current['fails'] = current.get('fails', 0) + 1
        current['streak'] = 0
    current['ts'] = time.time()
    server_history[key] = current

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
        logger.info("📥 Скачивание GeoIP базы...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=30)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                logger.info("✅ GeoIP база скачана")
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания GeoIP: {e}")

def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
        logger.info("🌍 GeoIP инициализирован")
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
def safe_b64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '')
    s += '=' * (4 - len(s) % 4) if len(s) % 4 else ''
    for decoder in [base64.urlsafe_b64decode, base64.b64decode]:
        try:
            return decoder(s).decode('utf-8', errors='ignore')
        except:
            pass
    return ""

def extract_links(text):
    regex = r"(vless://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+|hysteria2://[^\s\n<>\"']+|warp://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    
    if len(links) < 3:
        decoded = safe_b64_decode(text)
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
    for blocked in BLOCKED_SNIS:
        if blocked in sni:
            return False
    for trusted in TRUSTED_REALITY_SNIS:
        if trusted in sni:
            return True
    return '.' in sni and not sni[0].isdigit()

def get_reality_score(params):
    if params.get('security', [''])[0].lower() != 'reality':
        return 0
    score = 50
    sni = params.get('sni', [''])[0].lower()
    
    for trusted in TRUSTED_REALITY_SNIS[:10]:
        if trusted in sni:
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
        # WARP
        if config_str.startswith("warp://"):
            # Простой парсинг WARP
            return {
                "ip": "warp", "port": 0, "uuid": "",
                "original": config_str, "original_remark": "WARP",
                "latency": 9999, "info": {'countryCode': 'CF'},
                "speed_mbps": 0.0, "transport": "warp", "security": "warp",
                "is_reality": False, "is_warp": True, "is_hy2": False,
                "source_type": source_type, "parsed_params": {},
                "reality_score": 0, "has_good_sni": False
            }
        
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
                "original": config_str, "original_remark": unquote(remark).strip(),
                "latency": 9999, "info": {}, "speed_mbps": 0.0,
                "transport": "udp", "security": "tls",
                "is_reality": False, "is_warp": False, "is_hy2": True,
                "source_type": source_type, "parsed_params": params,
                "sni": params.get('sni', [''])[0],
                "reality_score": 0, "has_good_sni": False
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
            
            # Валидация Reality
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) != 43:
                    return None
                sni = params.get('sni', [''])[0]
                if sni == host:
                    return None
                for blocked in BLOCKED_SNIS:
                    if blocked in sni.lower():
                        return None
            
            remark = unquote(config_str.split("#")[-1]).strip() if "#" in config_str else "VLESS"
            
            return {
                "ip": host, "port": int(port), "uuid": uuid,
                "original": config_str, "original_remark": remark,
                "latency": 9999, "info": {}, "speed_mbps": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_warp": False, "is_hy2": False,
                "source_type": source_type, "parsed_params": params,
                "reality_score": get_reality_score(params),
                "has_good_sni": has_good_sni(params) if is_reality else False
            }
    except Exception as e:
        logger.debug(f"Ошибка парсинга: {e}")
    
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

def generate_xray_config(server, local_port):
    try:
        if server.get('is_hy2'):
            return {
                "log": {"loglevel": "error"},
                "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [{
                    "protocol": "hysteria2",
                    "settings": {"vnext": [{"address": server['ip'], "port": server['port'], "users": [{"password": server['uuid']}]}]},
                    "streamSettings": {"network": "udp", "security": "tls", "tlsSettings": {"serverName": server.get('sni', ''), "allowInsecure": True}}
                }]
            }
        
        params = server['parsed_params']
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
            stream["tlsSettings"] = {
                "serverName": params.get('sni', [''])[0],
                "fingerprint": params.get('fp', ['chrome'])[0],
                "allowInsecure": False
            }
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
            "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": server['ip'], "port": server['port'], "users": [user]}]}, "streamSettings": stream}]
        }
    except:
        return None

def measure_speed(local_port):
    try:
        proxies = {"http": f"socks5h://127.0.0.1:{local_port}", "https": f"socks5h://127.0.0.1:{local_port}"}
        start = time.time()
        with requests.get("https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe",
                         proxies=proxies, timeout=TIMEOUT_SPEED, stream=True) as r:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_content(32768):
                total += len(chunk)
                if total > 1.5 * 1024 * 1024:  # 1.5 MB
                    break
            duration = max(0.1, time.time() - start)
            return round((total * 8) / (duration * 1_000_000), 2)
    except:
        return 0.0

def check_udp(local_port):
    if not socks:
        return False
    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
        s.set_proxy(socks.SOCKS5, "127.0.0.1", local_port)
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

def check_endpoints(local_port):
    """Проверка нескольких эндпоинтов"""
    endpoints = [
        ("https://www.google.com/generate_204", 204),
        ("https://cp.cloudflare.com/", 200),
        ("https://www.gstatic.com/generate_204", 204),
    ]
    
    proxies = {'http': f'socks5://127.0.0.1:{local_port}', 'https': f'socks5://127.0.0.1:{local_port}'}
    success = 0
    total_lat = 0
    
    for url, code in endpoints:
        try:
            start = time.perf_counter()
            r = requests.get(url, proxies=proxies, timeout=4, verify=False)
            if r.status_code == code or 200 <= r.status_code < 300:
                success += 1
                total_lat += (time.perf_counter() - start) * 1000
        except:
            pass
    
    return total_lat / success if success >= 2 else None

def deep_check_server(server):
    """Глубокая проверка сервера"""
    if server.get('is_warp'):
        return None, 0.0, False  # WARP проверяем отдельно
    
    local_port = random.randint(10000, 60000)
    config = generate_xray_config(server, local_port)
    if not config:
        return None, 0.0, False
    
    config_path = None
    proc = None
    latency, speed, udp = None, 0.0, False
    
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
            json.dump(config, f)
            config_path = f.name
        
        proc = subprocess.Popen([XRAY_BIN, "-config", config_path], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        
        if proc.poll() is not None:
            raise Exception("Xray died")
        
        latency = check_endpoints(local_port)
        if latency:
            udp = check_udp(local_port)
            speed = measure_speed(local_port)
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
        if config_path and os.path.exists(config_path):
            try:
                os.remove(config_path)
            except:
                pass
    
    return latency, speed, udp

# ═══════════════════════════════════════════════════════════════
# ✅ ПРОВЕРКА СЕРВЕРОВ
# ═══════════════════════════════════════════════════════════════
def initial_check(server, progress=None):
    """Быстрая TCP проверка"""
    if server.get('is_warp'):
        # WARP не проверяем TCP
        server['latency'] = 50
        server['info'] = {'countryCode': 'CF'}
        if progress:
            progress.increment(True)
        return server
    
    ip, port = server['ip'], server['port']
    
    if not should_check(ip, port):
        if progress:
            progress.increment(False)
        return None
    
    country = get_country(ip)
    server['info'] = {'countryCode': country}
    
    # Проверка страны (для глобальных)
    if server['source_type'] != 'whitelist':
        if country in BLACKLIST_COUNTRIES or country in WHITELIST_COUNTRIES:
            if progress:
                progress.increment(False)
            return None
    else:
        # Для whitelist нужен RU
        if country not in WHITELIST_COUNTRIES:
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
    """Полная глубокая проверка"""
    lat, speed, udp = deep_check_server(server)
    
    if lat is None:
        if progress:
            progress.increment(False)
        return None
    
    server['real_latency'] = lat
    server['speed_mbps'] = speed
    server['udp'] = udp
    
    cc = server['info']['countryCode']
    name = RUS_NAMES.get(cc, cc)
    reality = "🛡️" if server.get('is_reality') else ""
    udp_str = "UDP✅" if udp else "UDP❌"
    
    logger.info(f"   🎯 {server['ip']} ({name}) - {speed:.1f}Mbps, {lat:.0f}ms {udp_str} {reality}")
    
    if progress:
        progress.increment(True)
    
    return server

# ═══════════════════════════════════════════════════════════════
# 📥 СБОР КОНФИГОВ
# ═══════════════════════════════════════════════════════════════
def fetch_url(url, source_type):
    try:
        r = requests.get(url, timeout=TIMEOUT_FETCH, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            configs = [parse_config(link, source_type) for link in extract_links(r.text)]
            configs = [c for c in configs if c]
            if configs:
                logger.debug(f"   ✅ {url.split('/')[-1][:25]}: {len(configs)}")
            return configs
    except:
        pass
    return []

def fetch_telegram(channel):
    try:
        r = requests.get(f"https://t.me/s/{channel}", timeout=TIMEOUT_FETCH)
        if r.status_code == 200:
            configs = [parse_config(link, 'telegram') for link in extract_links(r.text)]
            configs = [c for c in configs if c]
            if configs:
                logger.debug(f"   📱 {channel}: {len(configs)}")
            return configs
    except:
        pass
    return []

def fetch_issues(repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/issues?state=all&per_page=10",
                        timeout=TIMEOUT_FETCH, headers={'User-Agent': 'VPN-Scanner'})
        if r.status_code == 200:
            configs = []
            for issue in r.json():
                text = f"{issue.get('title', '')}\n{issue.get('body', '') or ''}"
                for link in extract_links(text):
                    c = parse_config(link, 'github')
                    if c:
                        configs.append(c)
            if configs:
                logger.debug(f"   🐙 {repo.split('/')[-1]}: {len(configs)}")
            return configs
    except:
        pass
    return []

def collect_all_configs():
    """Собираем все конфиги параллельно"""
    all_configs = []
    warp_configs = []
    whitelist_configs = []
    
    stats = {'reality': 0, 'premium': 0, 'general': 0, 'whitelist': 0, 'warp': 0, 'telegram': 0, 'github': 0}
    
    logger.info("📥 Сбор конфигов из всех источников...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_FETCH) as ex:
        futures = {}
        
        for url in REALITY_URLS:
            futures[ex.submit(fetch_url, url, 'reality')] = ('reality', url)
        for url in PREMIUM_URLS:
            futures[ex.submit(fetch_url, url, 'premium')] = ('premium', url)
        for url in GENERAL_URLS:
            futures[ex.submit(fetch_url, url, 'general')] = ('general', url)
        for url in WHITELIST_URLS:
            futures[ex.submit(fetch_url, url, 'whitelist')] = ('whitelist', url)
        for url in WARP_URLS:
            futures[ex.submit(fetch_url, url, 'warp')] = ('warp', url)
        for ch in TELEGRAM_CHANNELS:
            futures[ex.submit(fetch_telegram, ch)] = ('telegram', ch)
        for repo in GITHUB_ISSUES_REPOS:
            futures[ex.submit(fetch_issues, repo)] = ('github', repo)
        
        for future in concurrent.futures.as_completed(futures):
            src_type, _ = futures[future]
            try:
                configs = future.result()
                for c in configs:
                    if c.get('is_warp'):
                        warp_configs.append(c)
                    elif c['source_type'] == 'whitelist':
                        whitelist_configs.append(c)
                    else:
                        all_configs.append(c)
                stats[src_type] += len(configs)
            except:
                pass
    
    # Статистика
    reality_count = sum(1 for c in all_configs if c.get('is_reality'))
    
    logger.info(f"\n📊 Источники:")
    logger.info(f"   🛡️ Reality: {stats['reality']} | 🥇 Premium: {stats['premium']}")
    logger.info(f"   📦 General: {stats['general']} | 📱 Telegram: {stats['telegram']}")
    logger.info(f"   🇷🇺 Whitelist: {stats['whitelist']} | ☁️ WARP: {stats['warp']}")
    logger.info(f"   🐙 GitHub: {stats['github']}")
    logger.info(f"   ═══════════════════════════")
    logger.info(f"   📈 Всего: {len(all_configs)} глобальных ({reality_count} Reality)")
    logger.info(f"   🇷🇺 Whitelist: {len(whitelist_configs)} | ☁️ WARP: {len(warp_configs)}")
    
    return all_configs, whitelist_configs, warp_configs

# ═══════════════════════════════════════════════════════════════
# 🏆 ОТБОР ЛУЧШИХ СЕРВЕРОВ
# ═══════════════════════════════════════════════════════════════
def sort_for_games(servers):
    """Сортировка для игровых серверов (минимальный пинг, Tier 1-2)"""
    def key(s):
        tier = get_country_tier(s['info']['countryCode'])
        is_reality = 1 if s.get('is_reality') else 0
        return (tier, -is_reality, s['latency'])
    return sorted(servers, key=key)

def sort_for_universal(servers):
    """Сортировка для универсальных (баланс скорости и пинга)"""
    def key(s):
        tier = get_country_tier(s['info']['countryCode'])
        is_reality = 1 if s.get('is_reality') else 0
        score = s.get('reality_score', 0)
        # Баланс: скорость важнее пинга
        return (-is_reality, -score, tier, -s['speed_mbps'], s['latency'])
    return sorted(servers, key=key)

def select_best_candidates(servers, limit):
    """Отбор лучших кандидатов с приоритетом Reality и близких стран"""
    def key(s):
        tier = get_country_tier(s['info']['countryCode'])
        reality_bonus = -20 if s.get('has_good_sni') else (-10 if s.get('is_reality') else 0)
        return (reality_bonus, tier, s['latency'])
    return sorted(servers, key=key)[:limit]

def select_final_9(verified_global, verified_whitelist, warp_configs):
    """
    Финальный отбор 9 серверов:
    - 🎮 GAME-1, GAME-2 (Tier 1-2, минимальный пинг)
    - 🌐 UNIVERSAL-1,2,3 (лучшая скорость)
    - ☁️ WARP-1, WARP-2 (или резервные)
    - 🇷🇺 WHITELIST-1, WHITELIST-2
    """
    final = []
    reserve = []
    used_ips = set()
    
    # Фильтруем по качеству
    game_pool = [s for s in verified_global 
                 if s['info']['countryCode'] in (TIER_1_COUNTRIES + TIER_2_COUNTRIES)
                 and s['real_latency'] <= MAX_PING_GAME
                 and s['speed_mbps'] >= MIN_SPEED_GAME]
    
    universal_pool = [s for s in verified_global 
                      if s['speed_mbps'] >= MIN_SPEED_UNIVERSAL
                      and s['real_latency'] <= MAX_PING_UNIVERSAL]
    
    whitelist_pool = [s for s in verified_whitelist if s['speed_mbps'] >= MIN_SPEED_WHITELIST]
    
    logger.info(f"\n📊 Пулы после фильтрации:")
    logger.info(f"   🎮 GAME: {len(game_pool)} серверов")
    logger.info(f"   🌐 UNIVERSAL: {len(universal_pool)} серверов")
    logger.info(f"   ☁️ WARP: {len(warp_configs)} конфигов")
    logger.info(f"   🇷🇺 WHITELIST: {len(whitelist_pool)} серверов")
    
    # ═══════ 🎮 GAME SERVERS (2 штуки) ═══════
    logger.info(f"\n🎮 Выбор GAME серверов...")
    game_sorted = sort_for_games(game_pool)
    
    for i, role in enumerate(["GAME-1", "GAME-2"]):
        candidates = [s for s in game_sorted if s['ip'] not in used_ips]
        if candidates:
            server = candidates[0]
            used_ips.add(server['ip'])
            reality_tag = "🛡️" if server.get('is_reality') else ""
            server['final_name'] = format_server_name(
                f"🎮{role}{reality_tag}",
                server['info']['countryCode'],
                include_time=(i == 0)
            )
            final.append(server)
            cc = server['info']['countryCode']
            logger.info(f"   {role}: {server['ip']} ({RUS_NAMES.get(cc, cc)}) - {server['real_latency']:.0f}ms, {server['speed_mbps']:.1f}Mbps")
        else:
            logger.warning(f"   ⚠️ Не найден сервер для {role}")
    
    # ═══════ 🌐 UNIVERSAL SERVERS (3 штуки) ═══════
    logger.info(f"\n🌐 Выбор UNIVERSAL серверов...")
    universal_sorted = sort_for_universal(universal_pool)
    
    for i, role in enumerate(["UNIVERSAL-1", "UNIVERSAL-2", "UNIVERSAL-3"]):
        candidates = [s for s in universal_sorted if s['ip'] not in used_ips]
        if candidates:
            server = candidates[0]
            used_ips.add(server['ip'])
            reality_tag = "🛡️" if server.get('is_reality') else ""
            server['final_name'] = format_server_name(
                f"🌐{role}{reality_tag}",
                server['info']['countryCode']
            )
            final.append(server)
            cc = server['info']['countryCode']
            logger.info(f"   {role}: {server['ip']} ({RUS_NAMES.get(cc, cc)}) - {server['speed_mbps']:.1f}Mbps, {server['real_latency']:.0f}ms")
        else:
            logger.warning(f"   ⚠️ Не найден сервер для {role}")
    
    # ═══════ ☁️ WARP SERVERS (2 штуки) ═══════
    logger.info(f"\n☁️ Выбор WARP серверов...")
    
    # Если есть WARP конфиги - используем их
    warp_added = 0
    for i, role in enumerate(["WARP-1", "WARP-2"]):
        if warp_configs and warp_added < len(warp_configs):
            server = warp_configs[warp_added]
            server['final_name'] = f"☁️ {role}"
            server['real_latency'] = 50
            server['speed_mbps'] = 10.0
            server['udp'] = True
            final.append(server)
            warp_added += 1
            logger.info(f"   {role}: Cloudflare WARP")
        else:
            # Используем обычные серверы как замену WARP
            candidates = [s for s in universal_sorted if s['ip'] not in used_ips]
            if candidates:
                server = candidates[0]
                used_ips.add(server['ip'])
                server['final_name'] = format_server_name(f"☁️{role}", server['info']['countryCode'])
                final.append(server)
                cc = server['info']['countryCode']
                logger.info(f"   {role}: {server['ip']} ({RUS_NAMES.get(cc, cc)}) [резерв]")
            else:
                logger.warning(f"   ⚠️ Не найден сервер для {role}")
    
    # ═══════ 🇷🇺 WHITELIST SERVERS (2 штуки) ═══════
    logger.info(f"\n🇷🇺 Выбор WHITELIST серверов...")
    whitelist_sorted = sorted(whitelist_pool, key=lambda x: (-x['speed_mbps'], x['real_latency']))
    
    for i, role in enumerate(["WHITELIST-1", "WHITELIST-2"]):
        if i < len(whitelist_sorted):
            server = whitelist_sorted[i]
            server['final_name'] = format_server_name(f"🇷🇺{role}", server['info']['countryCode'])
            final.append(server)
            logger.info(f"   {role}: {server['ip']} (Россия) - {server['speed_mbps']:.1f}Mbps")
        else:
            logger.warning(f"   ⚠️ Не найден сервер для {role}")
    
    # ═══════ 📦 RESERVE POOL ═══════
    all_remaining = [s for s in verified_global if s['ip'] not in used_ips]
    reserve_sorted = sorted(all_remaining, 
                           key=lambda x: (-x.get('is_reality', False), -x.get('reality_score', 0), -x['speed_mbps']))
    reserve = reserve_sorted[:RESERVE_POOL_SIZE]
    
    logger.info(f"\n📦 Резервный пул: {len(reserve)} серверов")
    
    return final, reserve

# ═══════════════════════════════════════════════════════════════
# 💾 СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
# ═══════════════════════════════════════════════════════════════
def save_results(final_servers, reserve_pool, stats_info):
    """Сохранение подписки, статистики и резервного пула"""
    
    # 1. Подписка (base64)
    links = []
    for s in final_servers:
        if s.get('is_warp'):
            links.append(s['original'])
        else:
            base = s['original'].split('#')[0]
            links.append(f"{base}#{quote(s['final_name'])}")
    
    try:
        with open(OUTPUT_FILE, 'w') as f:
            f.write(base64.b64encode("\n".join(links).encode()).decode())
        logger.info(f"💾 Подписка: {OUTPUT_FILE} ({len(links)} серверов)")
    except Exception as e:
        logger.error(f"❌ Ошибка записи подписки: {e}")
    
    # 2. Статистика JSON
    json_data = {
        "servers": [],
        "updated": datetime.now(timezone.utc).isoformat(),
        "updated_msk": get_timestamp(),
        "stats": stats_info,
        "version": "V120-Premium"
    }
    
    for s in final_servers:
        cc = s.get('info', {}).get('countryCode', 'XX')
        json_data["servers"].append({
            "name": s.get('final_name', 'Unknown'),
            "ip": s.get('ip', ''),
            "port": s.get('port', 0),
            "country": cc,
            "country_name": RUS_NAMES.get(cc, cc),
            "country_flag": get_country_flag(cc),
            "speed_mbps": s.get('speed_mbps', 0),
            "latency_ms": s.get('real_latency', 0),
            "udp": s.get('udp', False),
            "is_reality": s.get('is_reality', False),
            "is_warp": s.get('is_warp', False),
            "reality_score": s.get('reality_score', 0),
            "streak": s.get('streak', 0),
            "original": s.get('original', '')
        })
    
    try:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Статистика: {JSON_FILE}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи статистики: {e}")
    
    # 3. Резервный пул
    pool_data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "updated_msk": get_timestamp(),
        "servers": []
    }
    
    for s in reserve_pool:
        cc = s.get('info', {}).get('countryCode', 'XX')
        pool_data["servers"].append({
            "ip": s['ip'],
            "port": s['port'],
            "country": cc,
            "country_name": RUS_NAMES.get(cc, cc),
            "speed_mbps": s.get('speed_mbps', 0),
            "latency_ms": s.get('real_latency', 0),
            "udp": s.get('udp', False),
            "is_reality": s.get('is_reality', False),
            "reality_score": s.get('reality_score', 0),
            "streak": s.get('streak', 0),
            "original": s['original']
        })
    
    try:
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(pool_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Резерв: {RESERVE_POOL_FILE} ({len(reserve_pool)} серверов)")
    except Exception as e:
        logger.error(f"❌ Ошибка записи резерва: {e}")

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    
    print("═" * 70)
    logger.info("🚀 FL1P VPN SCANNER V120 - PREMIUM EDITION")
    logger.info(f"   ⏰ Запуск: {get_timestamp()}")
    logger.info("   📋 Структура: 2 GAME + 3 UNIVERSAL + 2 WARP + 2 WHITELIST")
    logger.info(f"   🌍 Приоритет: {', '.join(TIER_1_COUNTRIES)} (Tier 1)")
    print("═" * 70)
    
    # Инициализация
    load_history()
    
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ Xray не найден: {XRAY_BIN}")
        return
    os.chmod(XRAY_BIN, 0o755)
    logger.info(f"✅ Xray: {XRAY_BIN}")
    
    download_mmdb()
    init_geoip()
    
    # ═══════ ЭТАП 1: СБОР ═══════
    logger.info("\n" + "═" * 50)
    logger.info("📥 ЭТАП 1: СБОР КОНФИГОВ")
    logger.info("═" * 50)
    
    global_configs, whitelist_configs, warp_configs = collect_all_configs()
    
    # Дедупликация
    unique_global = {}
    for c in global_configs:
        key = f"{c['ip']}:{c['port']}"
        if key not in unique_global or (c.get('is_reality') and not unique_global[key].get('is_reality')):
            unique_global[key] = c
    global_list = list(unique_global.values())
    
    unique_whitelist = {}
    for c in whitelist_configs:
        key = f"{c['ip']}:{c['port']}"
        if key not in unique_whitelist:
            unique_whitelist[key] = c
    whitelist_list = list(unique_whitelist.values())
    
    logger.info(f"\n🔍 Уникальных: {len(global_list)} глобальных, {len(whitelist_list)} whitelist")
    
    # ═══════ ЭТАП 2: TCP ПРОВЕРКА ═══════
    logger.info("\n" + "═" * 50)
    logger.info("⚡ ЭТАП 2: TCP ПРОВЕРКА")
    logger.info("═" * 50)
    
    alive_global = []
    progress = ProgressCounter(len(global_list), "Глобальные")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, progress) for s in global_list])]:
            if r:
                alive_global.append(r)
    
    alive_whitelist = []
    progress = ProgressCounter(len(whitelist_list), "Whitelist")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, progress) for s in whitelist_list])]:
            if r:
                alive_whitelist.append(r)
    
    reality_alive = sum(1 for s in alive_global if s.get('is_reality'))
    logger.info(f"\n✅ Живых: {len(alive_global)} глобальных ({reality_alive} Reality), {len(alive_whitelist)} whitelist")
    
    # Статистика по странам
    country_stats = {}
    for s in alive_global:
        cc = s['info']['countryCode']
        country_stats[cc] = country_stats.get(cc, 0) + 1
    
    logger.info("\n📊 Топ стран:")
    for cc, count in sorted(country_stats.items(), key=lambda x: -x[1])[:8]:
        tier = get_country_tier(cc)
        logger.info(f"   {get_country_flag(cc)} {cc} ({RUS_NAMES.get(cc, cc)}): {count} [Tier {tier}]")
    
    # ═══════ ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА ═══════
    logger.info("\n" + "═" * 50)
    logger.info("🧪 ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА")
    logger.info("═" * 50)
    
    # Отбираем лучших кандидатов
    global_candidates = select_best_candidates(alive_global, MAX_DEEP_CHECK_GLOBAL)
    whitelist_candidates = alive_whitelist[:MAX_DEEP_CHECK_WHITELIST]
    
    logger.info(f"   🌍 Глобальных к проверке: {len(global_candidates)}")
    logger.info(f"   🇷🇺 Whitelist к проверке: {len(whitelist_candidates)}")
    
    verified_global = []
    progress = ProgressCounter(len(global_candidates), "Глобальные")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, progress): s for s in global_candidates})]:
            if r:
                verified_global.append(r)
    
    verified_whitelist = []
    progress = ProgressCounter(len(whitelist_candidates), "Whitelist")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, progress): s for s in whitelist_candidates})]:
            if r:
                verified_whitelist.append(r)
    
    reality_verified = sum(1 for s in verified_global if s.get('is_reality'))
    logger.info(f"\n✅ Прошли проверку: {len(verified_global)} глобальных ({reality_verified} Reality), {len(verified_whitelist)} whitelist")
    
    # ═══════ ЭТАП 4: ФИНАЛЬНЫЙ ОТБОР ═══════
    logger.info("\n" + "═" * 50)
    logger.info("🏆 ЭТАП 4: ФИНАЛЬНЫЙ ОТБОР")
    logger.info("═" * 50)
    
    final_9, reserve_pool = select_final_9(verified_global, verified_whitelist, warp_configs)
    
    # ═══════ ВЫВОД РЕЗУЛЬТАТОВ ═══════
    print("\n" + "═" * 70)
    logger.info("🏆 THE FINAL 9:")
    print("═" * 70)
    
    for s in final_9:
        cc = s.get('info', {}).get('countryCode', 'CF')
        name = RUS_NAMES.get(cc, cc)
        udp = "UDP✅" if s.get('udp') else "UDP❌"
        reality = "🛡️Reality" if s.get('is_reality') else ""
        warp = "☁️WARP" if s.get('is_warp') else ""
        
        print(f"\n   🌟 {s['final_name']}")
        if not s.get('is_warp'):
            print(f"      {s['ip']} | {s.get('speed_mbps', 0):.1f}Mbps | {s.get('real_latency', 0):.0f}ms | {udp} {reality}")
        else:
            print(f"      Cloudflare WARP | Глобальная CDN {warp}")
    
    print()
    
    # ═══════ СОХРАНЕНИЕ ═══════
    stats_info = {
        "total_found": len(global_configs) + len(whitelist_configs),
        "unique_global": len(global_list),
        "unique_whitelist": len(whitelist_list),
        "alive_global": len(alive_global),
        "alive_whitelist": len(alive_whitelist),
        "verified_global": len(verified_global),
        "verified_whitelist": len(verified_whitelist),
        "reality_count": reality_verified,
        "reserve_pool": len(reserve_pool),
        "warp_available": len(warp_configs)
    }
    
    save_results(final_9, reserve_pool, stats_info)
    save_history()
    close_geoip()
    
    elapsed = time.time() - start_time
    print("═" * 70)
    logger.info(f"✅ ГОТОВО за {elapsed:.1f} секунд")
    logger.info(f"📊 Pipeline: {len(global_configs)}→{len(global_list)}→{len(alive_global)}→{len(verified_global)}→{len(final_9)}")
    logger.info(f"📄 Лог: {LOG_FILE}")
    print("═" * 70)

if __name__ == "__main__":
    main()
