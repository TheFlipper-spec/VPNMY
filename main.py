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

# --- V110: WATCHDOG + ROTATION SYSTEM ---
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

# 🛡️ REALITY-ONLY - максимальный приоритет (обходит DPI/ТСПУ)
REALITY_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/lagzian/SS-Collector/main/realitiy_api.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/reality.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/splitted/reality.txt",
]

# 🥇 PREMIUM - общие хорошие агрегаторы
PREMIUM_URLS = [
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/Config/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/vless",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/hysteria2",
]

# 📦 GENERAL - общие публичные списки
GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/master/collected-proxies/row-url/all.txt",
]

# 🇷🇺 WHITELIST - для обхода российских блокировок (RU серверы)
WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt",
]

# 🔄 SUBSCRIPTION AGGREGATORS
SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/master/sub/share/vless",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
]

# 📱 TELEGRAM CHANNELS
TELEGRAM_CHANNELS = [
    # Reality-focused каналы (приоритет)
    "PrivateVPNs", "iSegaro", "reality_daily",
    # Общие проверенные
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir",
    "v2ray_configs_pool", "VlessConfig", "v2ray1_ng",
    "DirectVPN", "v2ray_alpha", "customv2ray", 
    "ConfigsHUB", "freev2rayssr",
    "proxy_mtm", "ShadowProxy66",
    "Proxy_PJ", "SafeNet_Server", "Awlix_ir",
    "VmessProtocol", "ServerNett", "V2RayTz",
]

# 🐙 GITHUB ISSUES
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
REAL_TEST_TIMEOUT = 12.0
SPEED_TEST_TIMEOUT = 8.0 
FETCH_TIMEOUT = 8.0

# 🎯 КРИТЕРИИ ОТБОРА
MIN_SPEED_GOD = 5.0
MIN_SPEED_BACKUP = 2.0   
MIN_SPEED_RU = 0.5       

# 📁 ФАЙЛЫ
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json'
RESERVE_POOL_FILE = 'reserve_pool.json'  # 🆕 Резервный пул

TIMEZONE_OFFSET = 3 
CACHE_TTL_HOURS = 4      
MAX_FAILURES = 2

# 🔄 НАСТРОЙКИ РОТАЦИИ
RESERVE_POOL_SIZE = 20     # Сколько резервных серверов хранить
ACTIVE_SERVERS_COUNT = 4   # Сколько активных серверов в подписке

# ═══════════════════════════════════════════════════════════════
# 🛡️ REALITY-СПЕЦИФИЧНЫЕ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════

# Доверенные SNI для Reality (популярные сайты, не заблокированные в РФ)
TRUSTED_REALITY_SNIS = [
    'www.google.com', 'google.com',
    'www.microsoft.com', 'microsoft.com',
    'www.apple.com', 'apple.com',
    'www.yahoo.com', 'yahoo.com',
    'www.cloudflare.com', 'cloudflare.com',
    'www.mozilla.org', 'mozilla.org',
    'www.samsung.com', 'samsung.com',
    'www.nvidia.com', 'nvidia.com',
    'www.amd.com', 'amd.com',
    'www.cisco.com', 'cisco.com',
    'www.hp.com', 'hp.com',
    'www.dell.com', 'dell.com',
    'www.lenovo.com', 'lenovo.com',
    'www.asus.com', 'asus.com',
    'www.whatsapp.com', 'whatsapp.com',
    'cdn.jsdelivr.net',
    'ajax.googleapis.com',
    'fonts.googleapis.com',
    'www.docker.com',
    'www.github.com',
    'www.stackoverflow.com',
]

# SNI которые заблокированы в России
BLOCKED_SNIS = [
    'discord.com', 'www.discord.com', 'discordapp.com',
    'twitter.com', 'www.twitter.com', 'x.com',
    'facebook.com', 'www.facebook.com',
    'instagram.com', 'www.instagram.com',
    'linkedin.com', 'www.linkedin.com',
]

# ═══════════════════════════════════════════════════════════════
# GEO НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
RUS_NAMES = {
    'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'PL': 'Польша', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'NO': 'Норвегия', 'AT': 'Австрия', 'CZ': 'Чехия',
    'UA': 'Украина', 'KZ': 'Казахстан', 'MD': 'Молдова', 'BY': 'Беларусь',
    'BG': 'Болгария', 'RO': 'Румыния', 'HU': 'Венгрия', 'SK': 'Словакия',
    'CH': 'Швейцария', 'BE': 'Бельгия', 'DK': 'Дания', 'IE': 'Ирландия',
    'IT': 'Италия', 'ES': 'Испания', 'PT': 'Португалия', 'GR': 'Греция',
    'JP': 'Япония', 'SG': 'Сингапур', 'HK': 'Гонконг', 'KR': 'Корея',
    'CA': 'Канада', 'AU': 'Австралия', 'IN': 'Индия', 'BR': 'Бразилия',
}

BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP', 'US']

# 🎯 Приоритет стран для России (близость + надежность)
PRIORITY_COUNTRIES = [
    'FI',  # Финляндия - топ для РФ, близко
    'EE',  # Эстония - очень близко
    'LV',  # Латвия
    'LT',  # Литва
    'SE',  # Швеция
    'NO',  # Норвегия
    'PL',  # Польша
    'DE',  # Германия - много серверов
    'NL',  # Нидерланды - хорошие дата-центры
    'AT',  # Австрия
    'CZ',  # Чехия
]

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════
geo_reader = None
server_history = {} 

# ═══════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_beautiful_time():
    """Возвращает красиво отформатированное время обновления"""
    now_utc = datetime.now(timezone.utc)
    msk_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    time_str = msk_time.strftime('%H:%M')
    return f"🕐{time_str}"

def get_country_flag(country_code):
    """Преобразует код страны в флаг эмодзи"""
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def format_server_name(base_name, country_code, include_time=False):
    """Форматирует название сервера с флагом слева"""
    flag = get_country_flag(country_code)
    
    if include_time:
        time_str = get_beautiful_time()
        return f"{flag} {base_name} | {time_str}"
    else:
        return f"{flag} {base_name}"

# ═══════════════════════════════════════════════════════════════
# РАБОТА С ИСТОРИЕЙ
# ═══════════════════════════════════════════════════════════════
def load_history():
    global server_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                server_history = json.load(f)
            logger.info(f"📂 Загружена история: {len(server_history)} записей")
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Ошибка чтения истории: {e}")
            server_history = {}
        except Exception as e:
            logger.error(f"❌ Не удалось загрузить историю: {e}")
            server_history = {}
    else:
        logger.info("📂 Файл истории не найден, начинаем с чистого листа")

def save_history():
    current_ts = time.time()
    clean_history = {}
    expired_count = 0
    failed_count = 0
    
    for key, val in server_history.items():
        if val.get('fails', 0) >= MAX_FAILURES:
            failed_count += 1
            continue
        if current_ts - val.get('ts', 0) < (24 * 3600):
            clean_history[key] = val
        else:
            expired_count += 1
    
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(clean_history, f, indent=2)
        logger.debug(f"💾 История сохранена: {len(clean_history)} записей (удалено: {expired_count} устаревших, {failed_count} мёртвых)")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения истории: {e}")

def update_history(ip, port, is_alive, is_reality=False):
    key = f"{ip}:{port}"
    current = server_history.get(key, {'fails': 0, 'ts': 0, 'success_streak': 0})
    
    if is_alive:
        current['fails'] = 0
        current['success_streak'] = current.get('success_streak', 0) + 1
        current['is_reality'] = is_reality
        logger.debug(f"   ✅ {key} - alive (streak: {current['success_streak']})")
    else:
        current['fails'] = current.get('fails', 0) + 1
        current['success_streak'] = 0
        logger.debug(f"   ❌ {key} - dead (fails: {current['fails']})")
    
    current['ts'] = time.time()
    server_history[key] = current

def get_streak(ip, port):
    key = f"{ip}:{port}"
    return server_history.get(key, {}).get('success_streak', 0)

def should_check_server(ip, port):
    key = f"{ip}:{port}"
    if key not in server_history:
        return True
    
    rec = server_history[key]
    if rec.get('fails', 0) >= MAX_FAILURES:
        age_hours = (time.time() - rec.get('ts', 0)) / 3600
        if age_hours < CACHE_TTL_HOURS:
            logger.debug(f"   ⏭️ {key} - пропущен (в кеше мёртвых)")
            return False
    return True

# ═══════════════════════════════════════════════════════════════
# GEOIP
# ═══════════════════════════════════════════════════════════════
def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        logger.info("📥 Скачивание GeoIP базы...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=30)
            if r.status_code == 200:
                downloaded = 0
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                logger.info(f"✅ GeoIP база скачана: {downloaded / 1024 / 1024:.1f} MB")
            else:
                logger.error(f"❌ Не удалось скачать GeoIP: HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания GeoIP: {e}")
    else:
        logger.debug(f"📁 GeoIP база найдена: {MMDB_FILE}")

def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
        logger.info("🌍 GeoIP инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации GeoIP: {e}")
        geo_reader = None

def close_geoip():
    global geo_reader
    if geo_reader:
        try:
            geo_reader.close()
            logger.debug("🌍 GeoIP закрыт")
        except:
            pass

def get_ip_country_local(ip):
    if not geo_reader:
        return 'XX'
    try:
        return geo_reader.country(ip).country.iso_code
    except geoip2.errors.AddressNotFoundError:
        logger.debug(f"   ⚠️ IP не найден в GeoIP: {ip}")
        return 'XX'
    except Exception as e:
        logger.debug(f"   ⚠️ Ошибка GeoIP для {ip}: {e}")
        return 'XX'

# ═══════════════════════════════════════════════════════════════
# ПАРСИНГ
# ═══════════════════════════════════════════════════════════════
def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '')
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    
    for decoder in [base64.urlsafe_b64decode, base64.b64decode]:
        try:
            return decoder(s).decode('utf-8', errors='ignore')
        except Exception:
            continue
    return ""

def extract_links(text):
    """Извлекает VPN ссылки из текста"""
    regex = r"(vless://[^\s\n<>\"']+|ss://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+|hysteria2://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    
    # Пробуем декодировать base64
    if len(links) < 3:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    
    # Дедупликация
    seen = set()
    unique_links = []
    for link in links:
        clean_link = link.split('#')[0]
        if clean_link not in seen:
            seen.add(clean_link)
            unique_links.append(link)
    
    return unique_links

def is_valid_uuid(uuid_str):
    """Проверка валидности UUID"""
    uuid_pattern = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)
    return bool(uuid_pattern.match(uuid_str))

def is_valid_port(port):
    """Проверка валидности порта"""
    try:
        p = int(port)
        return 1 <= p <= 65535
    except:
        return False

def is_valid_ip_or_host(host):
    """Проверка что хост валидный"""
    if not host or len(host) < 4:
        return False
    if host.startswith('127.') or host.startswith('192.168.') or host.startswith('10.'):
        return False
    if host in ['localhost', '0.0.0.0']:
        return False
    return True

def is_reality_config(params):
    """Проверяет, является ли конфиг Reality"""
    security = params.get('security', ['none'])[0].lower()
    return security == 'reality'

def has_trusted_sni(params):
    """Проверяет, использует ли конфиг доверенный SNI"""
    sni = params.get('sni', [''])[0].lower()
    
    # Проверяем на заблокированные SNI
    for blocked in BLOCKED_SNIS:
        if blocked in sni:
            return False
    
    # Для Reality важно иметь хороший SNI
    for trusted in TRUSTED_REALITY_SNIS:
        if trusted in sni or sni in trusted:
            return True
    
    # Если SNI похож на домен (а не IP), это уже неплохо
    if '.' in sni and not sni[0].isdigit():
        return True
    
    return False

def get_reality_score(params):
    """Возвращает оценку качества Reality конфига (0-100)"""
    score = 0
    
    # Базовый балл за Reality
    if is_reality_config(params):
        score += 50
    else:
        return 0
    
    # Бонус за доверенный SNI
    sni = params.get('sni', [''])[0].lower()
    for trusted in TRUSTED_REALITY_SNIS[:10]:
        if trusted in sni:
            score += 30
            break
    else:
        if has_trusted_sni(params):
            score += 15
    
    # Бонус за fingerprint
    fp = params.get('fp', [''])[0].lower()
    if fp in ['chrome', 'firefox', 'safari', 'edge']:
        score += 10
    
    # Бонус за правильный public key
    pbk = params.get('pbk', [''])[0]
    if len(pbk) == 43:
        score += 10
    
    return min(score, 100)

def parse_config_info(config_str, source_type):
    if not config_str or len(config_str) < 20:
        return None
    
    try:
        # ═══════ HYSTERIA2 ═══════
        if config_str.startswith("hy2://") or config_str.startswith("hysteria2://"):
            prefix = "hy2://" if config_str.startswith("hy2://") else "hysteria2://"
            part = config_str.split("@")
            if len(part) < 2:
                return None
            
            password = part[0].replace(prefix, "")
            host_port_query = part[1]
            
            if "?" in host_port_query:
                host_port, query = host_port_query.split("?", 1)
            else:
                host_port = host_port_query
                query = ""
            
            if "#" in query:
                query, remark = query.split("#", 1)
            elif "#" in host_port:
                host_port, remark = host_port.split("#", 1)
            else:
                remark = "Hy2"

            if ":" not in host_port:
                return None
            
            host, port = host_port.rsplit(":", 1)
            
            if not is_valid_ip_or_host(host) or not is_valid_port(port):
                return None
            
            params = parse_qs(query)
            sni = params.get('sni', [''])[0]
            
            return {
                "ip": host, "port": int(port), "uuid": password, "original": config_str,
                "original_remark": unquote(remark).strip(), "latency": 9999, "jitter": 0,
                "final_score": 9999, "info": {}, "speed_mbps": 0.0,
                "transport": "udp", "security": "tls",
                "is_reality": False, "source_type": source_type,
                "parsed_params": params, "sni": sni, "is_hy2": True,
                "reality_score": 0
            }

        # ═══════ VLESS ═══════
        if config_str.startswith("vless://"):
            if "@" not in config_str or "?" not in config_str:
                return None
            
            part = config_str.split("@")[1].split("?")[0]
            if ":" not in part:
                return None
            
            host, port = part.rsplit(":", 1)
            
            if not is_valid_ip_or_host(host) or not is_valid_port(port):
                return None
            
            _uuid = config_str.split("@")[0].replace("vless://", "")
            if not is_valid_uuid(_uuid):
                logger.debug(f"   ⚠️ Невалидный UUID: {_uuid[:20]}...")
                return None
            
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            is_reality = (security == 'reality')
            
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) != 43:
                    logger.debug(f"   ⚠️ Невалидный pbk для Reality: {len(pbk)} символов")
                    return None
                sni = params.get('sni', [''])[0]
                if sni == host:
                    logger.debug(f"   ⚠️ SNI совпадает с хостом: {sni}")
                    return None
                # Проверяем на заблокированные SNI
                for blocked in BLOCKED_SNIS:
                    if blocked in sni.lower():
                        logger.debug(f"   🚫 Заблокированный SNI: {sni}")
                        return None
            
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            reality_score = get_reality_score(params)

            return {
                "ip": host, "port": int(port), "uuid": _uuid, "original": config_str, 
                "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                "final_score": 9999, "info": {},
                "speed_mbps": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality,
                "is_hy2": False,
                "source_type": source_type,
                "parsed_params": params,
                "reality_score": reality_score,
                "has_trusted_sni": has_trusted_sni(params) if is_reality else False
            }
            
    except Exception as e:
        logger.debug(f"   ⚠️ Ошибка парсинга конфига: {e}")
    
    return None

# ═══════════════════════════════════════════════════════════════
# СЕТЕВЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def tcp_ping(host, port):
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter()
        res = sock.connect_ex((host, port))
        end = time.perf_counter()
        if res == 0:
            return (end - start) * 1000
    except socket.gaierror as e:
        logger.debug(f"   ⚠️ DNS ошибка для {host}: {e}")
    except socket.timeout:
        pass
    except Exception as e:
        logger.debug(f"   ⚠️ Ошибка TCP ping {host}:{port}: {e}")
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass
    return None

def generate_xray_config(server, local_port):
    try:
        if server.get('is_hy2'):
            outbound_settings = {
                "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [{"password": server['uuid']}]}]
            }
            stream_settings = {
                "network": "udp", "security": "tls", 
                "tlsSettings": {"serverName": server.get('sni', ''), "allowInsecure": True}
            }
            protocol = "hysteria2"
        else:
            params = server['parsed_params']
            user_obj = {"id": server['uuid'], "encryption": "none"}
            flow = params.get('flow', [''])[0]
            if flow:
                user_obj["flow"] = flow
            
            outbound_settings = {
                "vnext": [{"address": server['ip'], "port": int(server['port']), "users": [user_obj]}]
            }
            stream_settings = {"network": server['transport'], "security": server['security']}

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
                    "allowInsecure": False,
                    "fingerprint": params.get('fp', ['chrome'])[0]
                }
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
            
            protocol = "vless"

        config = {
            "log": {"loglevel": "error"},
            "inbounds": [{
                "port": local_port, "listen": "127.0.0.1", "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"}
            }],
            "outbounds": [{
                "tag": "proxy", "protocol": protocol,
                "settings": outbound_settings, "streamSettings": stream_settings
            }]
        }
        return config
    except Exception as e:
        logger.debug(f"   ⚠️ Ошибка генерации конфига Xray: {e}")
        return None

def measure_speed(local_port):
    url = "https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe"
    proxies = {
        "http": f"socks5h://127.0.0.1:{local_port}",
        "https": f"socks5h://127.0.0.1:{local_port}"
    }
    start_time = time.time()
    
    try:
        with requests.get(url, proxies=proxies, timeout=SPEED_TEST_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            total_bytes = 0
            for chunk in r.iter_content(chunk_size=32768):
                if chunk:
                    total_bytes += len(chunk)
                if total_bytes > 2 * 1024 * 1024:
                    break
            
            duration = time.time() - start_time
            if duration <= 0.1:
                duration = 0.1
            
            speed = round((total_bytes * 8) / (duration * 1_000_000), 2)
            logger.debug(f"      📶 Скорость: {speed} Mbps ({total_bytes/1024:.0f} KB за {duration:.1f}s)")
            return speed
    except requests.exceptions.Timeout:
        logger.debug(f"      ⏰ Таймаут теста скорости")
    except Exception as e:
        logger.debug(f"      ⚠️ Ошибка теста скорости: {e}")
    return 0.0

def check_udp_dns(local_port):
    if not socks:
        return False
    
    s = None
    try:
        s = socks.socksocket(socket.AF_INET, socket.SOCK_DGRAM)
        s.set_proxy(socks.SOCKS5, "127.0.0.1", local_port)
        s.settimeout(3.0)
        dns_query = binascii.unhexlify("aaaa0100000100000000000006676f6f676c6503636f6d0000010001")
        s.sendto(dns_query, ("8.8.8.8", 53))
        data, addr = s.recvfrom(1024)
        logger.debug(f"      🔌 UDP работает")
        return True
    except Exception as e:
        logger.debug(f"      ⚠️ UDP не работает: {e}")
        return False
    finally:
        if s:
            try:
                s.close()
            except:
                pass

def check_multiple_endpoints(local_port):
    """Проверяет несколько эндпоинтов для надежности"""
    endpoints = [
        ("https://www.google.com/generate_204", 204),
        ("https://cp.cloudflare.com/", 200),
        ("https://www.gstatic.com/generate_204", 204),
    ]
    
    proxies = {
        'http': f'socks5://127.0.0.1:{local_port}',
        'https': f'socks5://127.0.0.1:{local_port}'
    }
    
    success_count = 0
    total_latency = 0
    
    for url, expected_code in endpoints:
        try:
            start = time.perf_counter()
            resp = requests.get(url, proxies=proxies, timeout=5, verify=False)
            end = time.perf_counter()
            
            if resp.status_code == expected_code or 200 <= resp.status_code < 300:
                success_count += 1
                total_latency += (end - start) * 1000
        except:
            pass
    
    if success_count >= 2:
        return total_latency / success_count
    return None

def check_real_connection(server):
    local_port = random.randint(10000, 60000)
    config_data = generate_xray_config(server, local_port)
    
    if not config_data:
        return None, 0.0, False

    config_path = None
    xray_process = None
    result_latency = None
    result_speed = 0.0
    udp_success = False

    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
            json.dump(config_data, tmp_conf)
            config_path = tmp_conf.name

        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(1.2)
        
        if xray_process.poll() is not None:
            logger.debug(f"   ❌ Xray умер сразу после запуска для {server['ip']}")
            raise Exception("Xray died")

        # Проверяем несколько эндпоинтов
        result_latency = check_multiple_endpoints(local_port)
        
        if result_latency is not None:
            logger.debug(f"   🟢 {server['ip']}:{server['port']} - реальный пинг {result_latency:.0f}ms")
            udp_success = check_udp_dns(local_port)
            result_speed = measure_speed(local_port)
            update_history(server['ip'], server['port'], True, server.get('is_reality', False))
        else:
            logger.debug(f"   🔴 {server['ip']}:{server['port']} - не прошел проверку эндпоинтов")
            update_history(server['ip'], server['port'], False)
            
    except requests.exceptions.Timeout:
        logger.debug(f"   ⏰ {server['ip']}:{server['port']} - таймаут")
        update_history(server['ip'], server['port'], False)
    except Exception as e:
        logger.debug(f"   ❌ {server['ip']}:{server['port']} - ошибка: {e}")
        update_history(server['ip'], server['port'], False)
    finally:
        if xray_process:
            try:
                xray_process.terminate()
                xray_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                xray_process.kill()
                xray_process.wait()
            except:
                pass
        
        if config_path and os.path.exists(config_path):
            try:
                os.remove(config_path)
            except:
                pass

    return result_latency, result_speed, udp_success

# ═══════════════════════════════════════════════════════════════
# ПРОВЕРКА СЕРВЕРОВ
# ═══════════════════════════════════════════════════════════════
def check_server_initial(server, progress=None):
    ip = server['ip']
    port = server['port']
    
    if not should_check_server(ip, port):
        if progress:
            progress.increment(success=False)
        return None
    
    code = get_ip_country_local(ip)
    
    if code in BLACKLIST_COUNTRIES:
        logger.debug(f"   🚫 {ip} - страна в черном списке: {code}")
        if progress:
            progress.increment(success=False)
        return None

    p = tcp_ping(ip, port)
    if p is None:
        update_history(ip, port, False)
        if progress:
            progress.increment(success=False)
        return None
    
    server['latency'] = int(p)
    server['info'] = {'countryCode': code}
    server['streak'] = get_streak(ip, port)
    
    country_name = RUS_NAMES.get(code, code)
    logger.debug(f"   🟢 {ip}:{port} ({country_name}) - TCP пинг {p:.0f}ms")
    
    if progress:
        progress.increment(success=True)
    
    return server

def check_full_server(server, progress=None):
    lat, speed, udp = check_real_connection(server)
    
    if lat is None:
        if progress:
            progress.increment(success=False)
        return None
    
    server['real_latency'] = lat
    server['speed_mbps'] = speed
    server['udp_enabled'] = udp
    
    # Корректировка пинга для отдаленных стран
    display_ping = lat
    if server['info']['countryCode'] in ['DE', 'NL', 'GB', 'FR']:
        display_ping += 35
    server['display_ping'] = int(display_ping)
    
    country_name = RUS_NAMES.get(server['info']['countryCode'], server['info']['countryCode'])
    udp_status = "UDP✅" if udp else "UDP❌"
    reality_status = "🛡️Reality" if server.get('is_reality') else ""
    logger.info(f"   🎯 {server['ip']} ({country_name}) - {speed:.1f} Mbps, {lat:.0f}ms, {udp_status} {reality_status}")
    
    if progress:
        progress.increment(success=True)
    
    return server

# ═══════════════════════════════════════════════════════════════
# 🏆 ВЫБОР ЛУЧШИХ (ПРИОРИТЕТ REALITY)
# ═══════════════════════════════════════════════════════════════
def get_best_candidates(servers, limit=100):
    """Сортировка с приоритетом Reality"""
    def sort_key(s):
        cc = s['info']['countryCode']
        
        # Приоритет страны
        country_prio = 0
        if cc in PRIORITY_COUNTRIES[:4]:  # FI, EE, LV, LT
            country_prio = -3
        elif cc in PRIORITY_COUNTRIES[4:8]:  # SE, NO, PL, DE
            country_prio = -2
        elif cc in PRIORITY_COUNTRIES[8:]:  # NL, AT, CZ
            country_prio = -1
        
        # БОНУС ЗА REALITY
        reality_bonus = 0
        if s.get('is_reality'):
            reality_bonus = -10
            if s.get('has_trusted_sni'):
                reality_bonus = -15
        
        return (reality_bonus, country_prio, s['latency'])
    
    return sorted(servers, key=sort_key)[:limit]

def select_final_servers(verified_servers):
    """🏆 Выбирает 4 активных + 20 резервных серверов"""
    final_4 = []
    reserve_pool = []
    used_ips = set()
    
    verified_ru = [s for s in verified_servers if s['info']['countryCode'] == 'RU']
    verified_global = [s for s in verified_servers if s['info']['countryCode'] != 'RU']
    
    # Reality серверы
    reality_servers = [s for s in verified_global if s.get('is_reality')]
    reality_trusted = [s for s in reality_servers if s.get('has_trusted_sni')]
    non_reality = [s for s in verified_global if not s.get('is_reality')]
    
    logger.info(f"\n📊 Статистика после проверки:")
    logger.info(f"   🌍 Глобальных: {len(verified_global)}")
    logger.info(f"   🛡️ Reality: {len(reality_servers)} (с доверенным SNI: {len(reality_trusted)})")
    logger.info(f"   📡 Обычных: {len(non_reality)}")
    logger.info(f"   🇷🇺 Российских: {len(verified_ru)}")
    
    # ═══════ 1. ОСНОВНОЙ - ЛУЧШИЙ REALITY ═══════
    god_candidates = sorted(
        [s for s in reality_trusted if s['speed_mbps'] > MIN_SPEED_GOD],
        key=lambda x: (-x.get('reality_score', 0), -x['speed_mbps'])
    )
    
    if not god_candidates:
        god_candidates = sorted(
            [s for s in reality_servers if s['speed_mbps'] > MIN_SPEED_GOD],
            key=lambda x: (-x.get('reality_score', 0), -x['speed_mbps'])
        )
        if god_candidates:
            logger.warning("   ⚠️ Нет Reality с доверенным SNI, берем любой Reality")
    
    if not god_candidates:
        god_candidates = sorted(verified_global, key=lambda x: -x['speed_mbps'])
        logger.warning("   ⚠️ Нет быстрых Reality серверов, берем обычный")

    if god_candidates:
        server_god = god_candidates[0]
        used_ips.add(server_god['ip'])
        
        reality_tag = "🛡️" if server_god.get('is_reality') else ""
        server_god['final_name'] = format_server_name(
            f"ОСНОВНОЙ{reality_tag}", 
            server_god['info']['countryCode'], 
            include_time=True
        )
        final_4.append(server_god)
        
        country_name = RUS_NAMES.get(server_god['info']['countryCode'], server_god['info']['countryCode'])
        sni = server_god.get('parsed_params', {}).get('sni', [''])[0][:30]
        logger.info(f"   1️⃣ ОСНОВНОЙ: {server_god['ip']} ({country_name}) - {server_god['speed_mbps']:.1f} Mbps | Reality: {server_god.get('is_reality')} | SNI: {sni}")
    
    # ═══════ 2. ЗАПАСНОЙ - ДРУГОЙ REALITY ═══════
    backup_candidates = sorted(
        [s for s in reality_servers if s['ip'] not in used_ips and s['speed_mbps'] > MIN_SPEED_BACKUP],
        key=lambda x: (-x.get('reality_score', 0), -x['speed_mbps'])
    )
    
    if not backup_candidates:
        backup_candidates = sorted(
            [s for s in verified_global if s['ip'] not in used_ips],
            key=lambda x: -x['speed_mbps']
        )
    
    if backup_candidates:
        server_backup = backup_candidates[0]
        used_ips.add(server_backup['ip'])
        
        reality_tag = "🛡️" if server_backup.get('is_reality') else ""
        server_backup['final_name'] = format_server_name(
            f"ЗАПАСНОЙ{reality_tag}", 
            server_backup['info']['countryCode']
        )
        final_4.append(server_backup)
        
        country_name = RUS_NAMES.get(server_backup['info']['countryCode'], server_backup['info']['countryCode'])
        logger.info(f"   2️⃣ ЗАПАСНОЙ: {server_backup['ip']} ({country_name}) - {server_backup['speed_mbps']:.1f} Mbps | Reality: {server_backup.get('is_reality')}")
        
    # ═══════ 3. РЕЗЕРВНЫЙ - СТАБИЛЬНЫЙ ═══════
    stable_candidates = sorted(
        [s for s in verified_global if s['ip'] not in used_ips],
        key=lambda x: (-x.get('is_reality', False), -x['streak'], -x['speed_mbps'])
    )
    
    if stable_candidates:
        server_stable = stable_candidates[0]
        used_ips.add(server_stable['ip'])
        
        reality_tag = "🛡️" if server_stable.get('is_reality') else ""
        server_stable['final_name'] = format_server_name(
            f"РЕЗЕРВНЫЙ{reality_tag}", 
            server_stable['info']['countryCode']
        )
        final_4.append(server_stable)
        
        country_name = RUS_NAMES.get(server_stable['info']['countryCode'], server_stable['info']['countryCode'])
        logger.info(f"   3️⃣ РЕЗЕРВНЫЙ: {server_stable['ip']} ({country_name}) - streak: {server_stable['streak']}, {server_stable['speed_mbps']:.1f} Mbps")
        
    # ═══════ 4. WHITELIST (RU) ═══════
    ru_final = sorted(
        [s for s in verified_ru if s['speed_mbps'] > MIN_SPEED_RU],
        key=lambda x: -x['speed_mbps']
    )
    if not ru_final:
        ru_final = sorted(verified_ru, key=lambda x: x['speed_mbps'], reverse=True)
    
    if ru_final:
        server_ru = ru_final[0]
        server_ru['final_name'] = format_server_name(
            "WHITELIST", 
            server_ru['info']['countryCode']
        )
        final_4.append(server_ru)
        logger.info(f"   4️⃣ WHITELIST: {server_ru['ip']} (Россия) - {server_ru['speed_mbps']:.1f} Mbps")
    else:
        logger.warning("   ⚠️ Нет рабочих серверов из России для WHITELIST")

    # ═══════ 🔄 РЕЗЕРВНЫЙ ПУЛ ═══════
    all_remaining = sorted(
        [s for s in verified_global if s['ip'] not in used_ips],
        key=lambda x: (-x.get('is_reality', False), -x.get('reality_score', 0), -x['speed_mbps'])
    )
    
    for s in all_remaining[:RESERVE_POOL_SIZE]:
        s['pool_name'] = f"RESERVE_{len(reserve_pool)+1}"
        reserve_pool.append(s)
    
    logger.info(f"\n🔄 Резервный пул: {len(reserve_pool)} серверов")
    
    # Показываем топ-5 резервных
    for i, s in enumerate(reserve_pool[:5]):
        cc = s['info']['countryCode']
        reality = "🛡️" if s.get('is_reality') else ""
        logger.info(f"      {i+1}. {s['ip']} ({RUS_NAMES.get(cc, cc)}) - {s['speed_mbps']:.1f} Mbps {reality}")

    return final_4, reserve_pool

# ═══════════════════════════════════════════════════════════════
# СБОР КОНФИГОВ
# ═══════════════════════════════════════════════════════════════
def fetch_url(url, source_type, timeout=FETCH_TIMEOUT):
    """Загружает конфиги из одного URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, timeout=timeout, headers=headers)
        if resp.status_code == 200:
            found = extract_links(resp.text)
            configs = []
            for link in found:
                p = parse_config_info(link, source_type)
                if p:
                    configs.append(p)
            
            source_name = url.split('/')[-1][:30] if '/' in url else url[:30]
            if configs:
                logger.debug(f"   ✅ {source_name}: {len(configs)} конфигов")
            return configs
        else:
            logger.debug(f"   ⚠️ {url.split('/')[-1][:30]}: HTTP {resp.status_code}")
    except requests.exceptions.Timeout:
        logger.debug(f"   ⏰ {url.split('/')[-1][:30]}: timeout")
    except Exception as e:
        logger.debug(f"   ❌ {url.split('/')[-1][:30]}: {str(e)[:50]}")
    return []

def fetch_telegram_channel(channel):
    """Загружает конфиги из одного Telegram канала"""
    try:
        url = f"https://t.me/s/{channel}"
        resp = requests.get(url, timeout=FETCH_TIMEOUT)
        if resp.status_code == 200:
            found = extract_links(resp.text)
            configs = []
            for link in found:
                p = parse_config_info(link, 'telegram')
                if p:
                    configs.append(p)
            if configs:
                logger.debug(f"   📱 {channel}: {len(configs)} конфигов")
            return configs
    except Exception as e:
        logger.debug(f"   ❌ {channel}: {str(e)[:30]}")
    return []

def fetch_github_issues(repo):
    """Парсит конфиги из GitHub Issues"""
    configs = []
    try:
        api_url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=10"
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'VPN-Scanner/1.0'
        }
        
        resp = requests.get(api_url, timeout=FETCH_TIMEOUT, headers=headers)
        if resp.status_code == 200:
            issues = resp.json()
            for issue in issues:
                body = issue.get('body', '') or ''
                title = issue.get('title', '') or ''
                full_text = f"{title}\n{body}"
                
                found = extract_links(full_text)
                for link in found:
                    p = parse_config_info(link, 'github_issues')
                    if p:
                        configs.append(p)
            
            if configs:
                logger.debug(f"   🐙 {repo.split('/')[-1]}: {len(configs)} из Issues")
        elif resp.status_code == 403:
            logger.debug(f"   ⚠️ {repo}: Rate limit exceeded")
        else:
            logger.debug(f"   ⚠️ {repo}: HTTP {resp.status_code}")
            
    except Exception as e:
        logger.debug(f"   ❌ {repo}: {str(e)[:30]}")
    
    return configs

def fetch_all_sources():
    """Параллельно загружает конфиги из всех источников"""
    all_configs = []
    stats = {
        'reality': 0,
        'premium': 0,
        'general': 0,
        'whitelist': 0,
        'subscription': 0,
        'telegram': 0,
        'github_issues': 0,
    }
    
    logger.info("📥 Загрузка из всех источников...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_FETCH) as executor:
        futures = {}
        
        # Reality URLs
        for url in REALITY_URLS:
            futures[executor.submit(fetch_url, url, 'reality')] = ('reality', url)
        
        # Premium URLs
        for url in PREMIUM_URLS:
            futures[executor.submit(fetch_url, url, 'premium')] = ('premium', url)
        
        # General URLs
        for url in GENERAL_URLS:
            futures[executor.submit(fetch_url, url, 'general')] = ('general', url)
        
        # Whitelist URLs
        for url in WHITELIST_URLS:
            futures[executor.submit(fetch_url, url, 'whitelist')] = ('whitelist', url)
        
        # Subscription URLs
        for url in SUBSCRIPTION_URLS:
            futures[executor.submit(fetch_url, url, 'subscription')] = ('subscription', url)
        
        # Telegram channels
        for channel in TELEGRAM_CHANNELS:
            futures[executor.submit(fetch_telegram_channel, channel)] = ('telegram', channel)
        
        # GitHub Issues
        for repo in GITHUB_ISSUES_REPOS:
            futures[executor.submit(fetch_github_issues, repo)] = ('github_issues', repo)
        
        # Собираем результаты
        for future in concurrent.futures.as_completed(futures):
            source_type, source_name = futures[future]
            try:
                configs = future.result()
                if configs:
                    all_configs.extend(configs)
                    stats[source_type] += len(configs)
            except Exception as e:
                logger.debug(f"   ❌ Ошибка {source_name}: {e}")
    
    # Подсчет Reality
    reality_count = sum(1 for c in all_configs if c.get('is_reality'))
    trusted_sni_count = sum(1 for c in all_configs if c.get('has_trusted_sni'))
    
    # Выводим статистику
    logger.info(f"\n📊 Статистика источников:")
    logger.info(f"   🛡️ Reality:      {stats['reality']}")
    logger.info(f"   🥇 Premium:      {stats['premium']}")
    logger.info(f"   📦 General:      {stats['general']}")
    logger.info(f"   🇷🇺 Whitelist:    {stats['whitelist']}")
    logger.info(f"   🔄 Subscription: {stats['subscription']}")
    logger.info(f"   📱 Telegram:     {stats['telegram']}")
    logger.info(f"   🐙 GitHub Issues: {stats['github_issues']}")
    logger.info(f"   ═══════════════════════")
    logger.info(f"   📈 ВСЕГО:        {len(all_configs)}")
    logger.info(f"   🛡️ Из них Reality: {reality_count} (с довер. SNI: {trusted_sni_count})")
    
    return all_configs

# ═══════════════════════════════════════════════════════════════
# СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
# ═══════════════════════════════════════════════════════════════
def save_results(final_4, reserve_pool, stats_data):
    """Сохраняет подписку, статистику и резервный пул"""
    
    # 1. Подписка (base64)
    result_links = []
    for s in final_4:
        base = s['original'].split('#')[0]
        link = f"{base}#{quote(s['final_name'])}"
        result_links.append(link)
    
    try:
        with open(OUTPUT_FILE, 'w') as f:
            f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        logger.info(f"💾 Подписка сохранена: {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи {OUTPUT_FILE}: {e}")
    
    # 2. Статистика (JSON)
    json_data = {
        "servers": [],
        "updated": datetime.now(timezone.utc).isoformat(),
        "updated_msk": (datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)).strftime('%Y-%m-%d %H:%M:%S MSK'),
        "stats": stats_data
    }
    
    for s in final_4:
        country_name = RUS_NAMES.get(s['info']['countryCode'], s['info']['countryCode'])
        flag = get_country_flag(s['info']['countryCode'])
        sni = s.get('parsed_params', {}).get('sni', ['N/A'])[0][:40]
        
        json_data["servers"].append({
            "name": s['final_name'],
            "ip": s['ip'],
            "port": s['port'],
            "country": s['info']['countryCode'],
            "country_name": country_name,
            "country_flag": flag,
            "speed_mbps": s['speed_mbps'],
            "latency_ms": s['real_latency'],
            "udp": s.get('udp_enabled', False),
            "is_reality": s.get('is_reality', False),
            "reality_score": s.get('reality_score', 0),
            "sni": sni,
            "streak": s.get('streak', 0),
            "source_type": s.get('source_type', 'unknown'),
            "original": s['original']
        })
    
    try:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 JSON сохранён: {JSON_FILE}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи {JSON_FILE}: {e}")
    
    # 3. Резервный пул
    pool_data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "updated_msk": (datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)).strftime('%Y-%m-%d %H:%M:%S MSK'),
        "servers": []
    }
    
    for s in reserve_pool:
        country_name = RUS_NAMES.get(s['info']['countryCode'], s['info']['countryCode'])
        sni = s.get('parsed_params', {}).get('sni', ['N/A'])[0][:40]
        
        pool_data["servers"].append({
            "ip": s['ip'],
            "port": s['port'],
            "country": s['info']['countryCode'],
            "country_name": country_name,
            "speed_mbps": s['speed_mbps'],
            "latency_ms": s['real_latency'],
            "udp": s.get('udp_enabled', False),
            "is_reality": s.get('is_reality', False),
            "reality_score": s.get('reality_score', 0),
            "sni": sni,
            "streak": s.get('streak', 0),
            "original": s['original']
        })
    
    try:
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(pool_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Резервный пул: {RESERVE_POOL_FILE} ({len(reserve_pool)} серверов)")
    except Exception as e:
        logger.error(f"❌ Ошибка записи {RESERVE_POOL_FILE}: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    
    print("═" * 60)
    logger.info("🚀 FL1P VPN SCANNER V110 - WATCHDOG + ROTATION SYSTEM")
    logger.info(f"   🛡️ Приоритет: Reality с доверенным SNI")
    logger.info(f"   🔄 Резервный пул: {RESERVE_POOL_SIZE} серверов")
    logger.info(f"   🌐 Источников Reality: {len(REALITY_URLS)}")
    logger.info(f"   📱 Telegram каналов: {len(TELEGRAM_CHANNELS)}")
    logger.info(f"   🚫 Черный список: {', '.join(BLACKLIST_COUNTRIES)}")
    print("═" * 60)
    
    load_history()
    
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
        logger.info(f"✅ Xray найден: {XRAY_BIN}")
    else:
        logger.error(f"❌ Xray не найден: {XRAY_BIN}")
        return
    
    download_mmdb()
    init_geoip()
    
    # ═══════ 1. СБОР КОНФИГОВ ═══════
    logger.info("\n" + "═" * 40)
    logger.info("📥 ЭТАП 1: СБОР КОНФИГОВ")
    logger.info("═" * 40)
    
    all_servers = fetch_all_sources()
    
    # Дедупликация (приоритет Reality)
    unique_servers = {}
    for s in all_servers:
        key = f"{s['ip']}:{s['port']}"
        if key not in unique_servers:
            unique_servers[key] = s
        elif s.get('is_reality') and not unique_servers[key].get('is_reality'):
            unique_servers[key] = s
    
    candidates = list(unique_servers.values())
    reality_unique = sum(1 for s in candidates if s.get('is_reality'))
    logger.info(f"\n🔍 Уникальных серверов: {len(candidates)} (Reality: {reality_unique})")

    # ═══════ 2. TCP ПРОВЕРКА ═══════
    logger.info("\n" + "═" * 40)
    logger.info("⚡ ЭТАП 2: TCP ПРОВЕРКА")
    logger.info("═" * 40)
    
    alive_servers = []
    progress_tcp = ProgressCounter(len(candidates), "TCP-пинг")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as executor:
        futures = [executor.submit(check_server_initial, s, progress_tcp) for s in candidates]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                alive_servers.append(res)
    
    reality_alive = sum(1 for s in alive_servers if s.get('is_reality'))
    logger.info(f"\n✅ Живых TCP: {len(alive_servers)} (Reality: {reality_alive})")
    
    # Статистика по странам
    country_stats = {}
    for s in alive_servers:
        cc = s['info']['countryCode']
        country_stats[cc] = country_stats.get(cc, 0) + 1
    
    logger.info("📊 Топ стран:")
    for cc, count in sorted(country_stats.items(), key=lambda x: -x[1])[:10]:
        name = RUS_NAMES.get(cc, cc)
        flag = get_country_flag(cc)
        logger.info(f"   {flag} {cc} ({name}): {count}")
    
    # ═══════ 3. ОТБОР КАНДИДАТОВ ═══════
    ru_candidates = [s for s in alive_servers if s['info']['countryCode'] == 'RU']
    global_candidates = [s for s in alive_servers if s['info']['countryCode'] != 'RU']
    
    top_global = get_best_candidates(global_candidates, 1500)
    top_ru = ru_candidates
    
    full_check_list = top_global + top_ru
    
    # ═══════ 4. ГЛУБОКАЯ ПРОВЕРКА ═══════
    logger.info("\n" + "═" * 40)
    logger.info(f"🧪 ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА ({len(full_check_list)} серверов)")
    logger.info("═" * 40)
    
    verified_servers = []
    progress_deep = ProgressCounter(len(full_check_list), "Глубокая проверка")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_CUP) as executor:
        futures = {executor.submit(check_full_server, s, progress_deep): s for s in full_check_list}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                verified_servers.append(res)
    
    reality_verified = sum(1 for s in verified_servers if s.get('is_reality'))
    logger.info(f"\n✅ Проверку прошли: {len(verified_servers)} (Reality: {reality_verified})")
            
    # ═══════ 5. ФИНАЛЬНЫЙ ОТБОР ═══════
    logger.info("\n" + "═" * 40)
    logger.info("🏆 ЭТАП 4: ФИНАЛЬНЫЙ ОТБОР")
    logger.info("═" * 40)
    
    final_4, reserve_pool = select_final_servers(verified_servers)

    # ═══════ 6. ВЫВОД РЕЗУЛЬТАТОВ ═══════
    print("\n" + "═" * 60)
    logger.info("🏆 THE CHOSEN FOUR:")
    print("═" * 60)
    
    for s in final_4:
        country_name = RUS_NAMES.get(s['info']['countryCode'], s['info']['countryCode'])
        flag = get_country_flag(s['info']['countryCode'])
        udp_status = "✅UDP" if s.get('udp_enabled') else "❌UDP"
        reality_status = "🛡️Reality" if s.get('is_reality') else "📡Standard"
        
        sni = s.get('parsed_params', {}).get('sni', ['N/A'])[0][:40]
        
        print(f"   🌟 {s['final_name']}")
        print(f"      IP: {s['ip']} | {s['speed_mbps']:.1f} Mbps | {s['real_latency']:.0f}ms")
        print(f"      {udp_status} | {reality_status} | SNI: {sni}")
        print()

    # ═══════ 7. СОХРАНЕНИЕ ═══════
    stats_data = {
        "total_found": len(all_servers),
        "unique": len(candidates),
        "reality_unique": reality_unique,
        "alive_tcp": len(alive_servers),
        "reality_alive": reality_alive,
        "verified": len(verified_servers),
        "reality_verified": reality_verified,
        "reserve_pool_size": len(reserve_pool)
    }
    
    save_results(final_4, reserve_pool, stats_data)
    
    save_history()
    close_geoip()
    
    elapsed = time.time() - start_time
    print("═" * 60)
    logger.info(f"✅ ГОТОВО за {elapsed:.1f} секунд")
    logger.info(f"📊 Найдено {len(all_servers)} → Уникальных {len(candidates)} → Reality {reality_unique} → Финал {len(final_4)} + {len(reserve_pool)} резерв")
    logger.info(f"📄 Лог сохранён: {LOG_FILE}")
    print("═" * 60)

if __name__ == "__main__":
    main()
