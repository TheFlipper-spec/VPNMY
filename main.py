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
#  FL1P VPN SCANNER V2.1 - IGAR EDITION
# ═══════════════════════════════════════════════════════════════
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ
# ═══════════════════════════════════════════════════════════════
LOG_FILE = 'vpn_scanner.log'
logging.basicConfig(
    level=logging.INFO,
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
# 🌍 СТРАНЫ И ПРИОРИТЕТЫ
# ═══════════════════════════════════════════════════════════════
# 🔥 SUPER PRIORITY
PRIORITY_COUNTRIES = ['FI', 'EE', 'LV', 'SE'] 

TIER_1_COUNTRIES = ['FI', 'EE', 'LV', 'LT', 'SE'] 
TIER_2_COUNTRIES = ['NO', 'PL', 'DE', 'NL', 'DK']      
TIER_3_COUNTRIES = ['AT', 'CZ', 'BE', 'CH', 'GB', 'FR']  
TIER_4_COUNTRIES = ['IT', 'ES', 'PT', 'IE', 'HU', 'RO', 'BG', 'SK', 'GR', 'TR']

GAME_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES
WHITELIST_COUNTRIES = ['RU']
BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP', 'US', 'BY', 'XX']

RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция', 'TR': 'Турция',
    'RU': 'Россия', 'UA': 'Украина', 'MD': 'Молдова', 'CF': 'Cloudflare',
    'US': 'США', 'XX': 'Unknown'
}

# ═══════════════════════════════════════════════════════════════
# 🔥 ИСТОЧНИКИ
# ═══════════════════════════════════════════════════════════════
GLOBAL_URLS = [
    # --- ЗАПРОШЕННЫЕ ССЫЛКИ (IGARECK) ---
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_SS+All_RUS.txt",
    
    # --- РЕЗЕРВНЫЕ СТАБИЛЬНЫЕ (для гарантии) ---
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/mttsh/v2ray/main/vless.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt"
]

TELEGRAM_CHANNELS = [
    "PrivateVPNs", "iSegaro", "reality_daily", "RealityVpnChannel",
    "FarahVPN", "v2rayng_vpn", "v2ray_configs_pool", "VlessConfig",
    "DirectVPN", "v2ray_alpha", "ConfigsHUB", "freev2rayssr",
    "v2rayng_org", "v2ray_outline", "flyvless"
]

# ═══════════════════════════════════════════════════════════════
# ⚙️ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

MAX_WORKERS_SCAN = 60
MAX_WORKERS_DEEP = 15
MAX_WORKERS_FETCH = 15

TIMEOUT_TCP = 0.9
TIMEOUT_REAL = 10.0
TIMEOUT_SPEED = 7.0
TIMEOUT_FETCH = 10.0 # Увеличил таймаут для загрузки

MAX_DEEP_CHECK_GLOBAL = 450
MAX_DEEP_CHECK_WHITELIST = 80

MIN_SPEED_GAME = 2.0        
MIN_SPEED_UNIVERSAL = 3.0   
MAX_PING_GAME = 180         
MAX_PING_UNIVERSAL = 350    

OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

TIMEZONE_OFFSET = 3
CACHE_TTL_HOURS = 4
MAX_FAILURES = 2
RESERVE_POOL_SIZE = 40
UPDATE_INTERVAL_MINUTES = 20

# ═══════════════════════════════════════════════════════════════
# 🛡️ SNI ФИЛЬТРЫ
# ═══════════════════════════════════════════════════════════════
TRUSTED_SNIS = [
    'www.google.com', 'google.com', 'www.microsoft.com', 'microsoft.com', 
    'learn.microsoft.com', 'www.apple.com', 'apple.com', 'www.cloudflare.com', 
    'cloudflare.com', 'www.mozilla.org', 'mozilla.org', 'www.yahoo.com', 
    'yahoo.com', 'www.amazon.com', 'amazon.com', 'www.github.com', 'github.com',
    'www.samsung.com', 'samsung.com', 'www.nvidia.com', 'nvidia.com',
    'www.amd.com', 'amd.com', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com',
    'www.docker.com', 'docker.com', 'www.oracle.com', 'oracle.com',
    'www.ibm.com', 'ibm.com', 'www.cisco.com', 'cisco.com', 'www.dell.com', 
    'dell.com', 'www.hp.com', 'hp.com', 'www.lenovo.com', 'lenovo.com',
    'www.asus.com', 'asus.com', 'www.whatsapp.com', 'whatsapp.com',
    'www.twitch.tv', 'twitch.tv', 'www.steam.com', 'steampowered.com',
]

BLOCKED_SNIS = [
    'discord.com', 'discordapp.com', 'discord.gg',
    'twitter.com', 'x.com', 't.co',
    'facebook.com', 'fb.com', 'fbcdn.net',
    'instagram.com', 'cdninstagram.com',
    'linkedin.com', 'tiktok.com',
    'youtube.com', 'youtu.be', 'googlevideo.com',
    'bbc.com', 'dw.com', 'meduza.io', 'rferl.org'
]

geo_reader = None
server_history = {}

# ═══════════════════════════════════════════════════════════════
# 🎨 УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_msk_time():
    return datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)

def get_last_update_time():
    return get_msk_time().strftime('%H:%M')

def get_next_update_time():
    return (get_msk_time() + timedelta(minutes=UPDATE_INTERVAL_MINUTES)).strftime('%H:%M')

def get_timestamp():
    return get_msk_time().strftime('%Y-%m-%d %H:%M:%S MSK')

def get_flag(cc):
    if not cc or len(cc) != 2 or cc == 'XX':
        return "❓"
    return "".join([chr(127397 + ord(c)) for c in cc.upper()])

def get_country_name(cc):
    return RUS_NAMES.get(cc, cc)

def get_tier(cc):
    if cc in TIER_1_COUNTRIES: return 1
    if cc in TIER_2_COUNTRIES: return 2
    if cc in TIER_3_COUNTRIES: return 3
    if cc in TIER_4_COUNTRIES: return 4
    return 5

# ═══════════════════════════════════════════════════════════════
# 📂 ИСТОРИЯ
# ═══════════════════════════════════════════════════════════════
def load_history():
    global server_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                server_history = json.load(f)
        except:
            server_history = {}

def save_history():
    ts = time.time()
    clean = {k: v for k, v in server_history.items() if v.get('fails', 0) < MAX_FAILURES and ts - v.get('ts', 0) < 86400}
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(clean, f)
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
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=30)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
        except:
            pass

def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
    except:
        pass

def close_geoip():
    global geo_reader
    if geo_reader:
        try:
            geo_reader.close()
        except:
            pass

def get_country(ip):
    if not geo_reader: return 'XX'
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
    # Добавлена базовая поддержка ss:// для полноты, но фокус на vless
    regex = r"(vless://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+|hysteria2://[^\s\n<>\"']+|ss://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    if len(links) < 2:
        decoded = safe_b64(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(link.split('#')[0] for link in links))

def check_sni_quality(sni):
    if not sni: return False, False, 0
    sni_lower = sni.lower()
    for blocked in BLOCKED_SNIS:
        if blocked in sni_lower: return True, False, -100
    for trusted in TRUSTED_SNIS:
        if trusted in sni_lower or sni_lower in trusted: return False, True, 50
    if '.' in sni and not sni[0].isdigit(): return False, False, 20
    return False, False, 0

def get_reality_score(params):
    if params.get('security', [''])[0].lower() != 'reality': return 0
    score = 30
    sni = params.get('sni', [''])[0]
    is_blocked, is_trusted, sni_score = check_sni_quality(sni)
    if is_blocked: return -100
    score += sni_score
    if params.get('fp', [''])[0].lower() in ['chrome', 'firefox', 'safari']: score += 15
    if len(params.get('pbk', [''])[0]) == 43: score += 10
    return min(score, 100)

def parse_config(config_str, source_type):
    if not config_str or len(config_str) < 15: return None
    
    try:
        # VLESS
        if config_str.startswith("vless://"):
            if "@" not in config_str or "?" not in config_str: return None
            uuid = config_str.split("@")[0].replace("vless://", "")
            rest = config_str.split("@")[1]
            host_port = rest.split("?")[0]
            if ":" not in host_port: return None
            host, port_str = host_port.rsplit(":", 1)
            try: port = int(port_str)
            except: return None
            
            query = rest.split("?")[1].split("#")[0]
            params = parse_qs(query)
            security = params.get('security', ['none'])[0].lower()
            transport = params.get('type', ['tcp'])[0].lower()
            remark = unquote(config_str.split("#")[-1]).strip() if "#" in config_str else "VLESS"
            remark_lower = remark.lower()
            
            is_reality = (security == 'reality')
            is_warp = any(k in remark_lower for k in ['warp', 'cloudflare', 'cf', 'cloud'])
            is_whitelist = (source_type == 'whitelist')
            
            valid = False
            if is_whitelist:
                valid = True
            elif is_reality:
                pbk = params.get('pbk', [''])[0]
                sni = params.get('sni', [''])[0]
                if len(pbk) == 43 and sni != host:
                    is_blocked, _, _ = check_sni_quality(sni)
                    if not is_blocked:
                        valid = True
            elif is_warp:
                if transport in ['ws', 'grpc']:
                    valid = True
            
            if not valid: return None
            
            reality_score = get_reality_score(params) if is_reality else 0
            
            return {
                "ip": host, "port": port, "uuid": uuid,
                "original": config_str, "remark": remark,
                "latency": 9999, "speed": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality, "is_warp": is_warp,
                "source": source_type, "params": params,
                "reality_score": reality_score,
                "sni": params.get('sni', [''])[0] if is_reality else ""
            }
    except:
        pass
    return None

# ═══════════════════════════════════════════════════════════════
# 🌐 ПРОВЕРКИ
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
        try: sock.close()
        except: pass
    return None

def gen_xray_config(server, port):
    try:
        params = server['params']
        user = {"id": server['uuid'], "encryption": "none"}
        if params.get('flow'): user["flow"] = params['flow'][0]
        
        stream = {"network": server['transport'], "security": server['security']}
        
        if server['transport'] == 'ws':
            stream["wsSettings"] = {"path": params.get('path', ['/'])[0]}
            if params.get('host'): stream["wsSettings"]["headers"] = {"Host": params['host'][0]}
        elif server['transport'] == 'grpc' and params.get('serviceName'):
            stream["grpcSettings"] = {"serviceName": params['serviceName'][0]}
        
        if server['security'] == 'tls':
            stream["tlsSettings"] = {
                "serverName": params.get('sni', [''])[0],
                "fingerprint": params.get('fp', ['chrome'])[0]
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
            "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": server['ip'], "port": server['port'], "users": [user]}]}, "streamSettings": stream}]
        }
    except:
        return None

def measure_speed(port):
    try:
        proxies = {"http": f"socks5h://127.0.0.1:{port}", "https": f"socks5h://127.0.0.1:{port}"}
        start = time.time()
        url = "https://dl.google.com/dl/android/studio/install/3.4.1.0/android-studio-ide-183.5522156-windows.exe"
        with requests.get(url, proxies=proxies, timeout=TIMEOUT_SPEED, stream=True) as r:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_content(32768):
                total += len(chunk)
                if total > 1.5 * 1024 * 1024: break
            return round((total * 8) / (max(0.1, time.time() - start) * 1_000_000), 2)
    except:
        return 0.0

def check_endpoints(port):
    endpoints = [
        ("https://www.google.com/generate_204", 204),
        ("https://cp.cloudflare.com/", 200),
        ("https://www.gstatic.com/generate_204", 204)
    ]
    proxies = {'http': f'socks5://127.0.0.1:{port}', 'https': f'socks5://127.0.0.1:{port}'}
    success, total_lat = 0, 0
    for url, expected in endpoints:
        try:
            start = time.perf_counter()
            r = requests.get(url, proxies=proxies, timeout=5, verify=False)
            if r.status_code == expected or 200 <= r.status_code < 300:
                success += 1
                total_lat += (time.perf_counter() - start) * 1000
        except: pass
    return total_lat / success if success >= 2 else None

def deep_check(server):
    port = random.randint(10000, 60000)
    config = gen_xray_config(server, port)
    if not config: return None, 0.0, False
    
    path, proc = None, None
    lat, speed, udp = None, 0.0, False
    
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
            json.dump(config, f)
            path = f.name
        
        proc = subprocess.Popen([XRAY_BIN, "-config", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        
        if proc.poll() is None:
            lat = check_endpoints(port)
            if lat:
                speed = measure_speed(port)
                udp = True 
                update_history(server['ip'], server['port'], True, server.get('is_reality', False))
            else:
                update_history(server['ip'], server['port'], False)
    except:
        update_history(server['ip'], server['port'], False)
    finally:
        if proc:
            try: proc.terminate(); proc.wait(timeout=2)
            except: 
                try: proc.kill()
                except: pass
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass
            
    return lat, speed, udp

def initial_check(server, progress=None):
    ip, port = server['ip'], server['port']
    
    if not should_check(ip, port):
        if progress: progress.increment(False)
        return None
    
    cc = get_country(ip)
    
    if cc == 'XX':
        if progress: progress.increment(False)
        return None
        
    server['info'] = {'cc': cc}
    
    if server['source'] == 'whitelist':
        if cc not in WHITELIST_COUNTRIES:
            if progress: progress.increment(False)
            return None
    else:
        if cc in BLACKLIST_COUNTRIES or cc in WHITELIST_COUNTRIES:
            if progress: progress.increment(False)
            return None
            
    ping = tcp_ping(ip, port)
    if ping is None:
        update_history(ip, port, False)
        if progress: progress.increment(False)
        return None
        
    server['latency'] = int(ping)
    if progress: progress.increment(True)
    return server

def full_check(server, progress=None):
    lat, speed, udp = deep_check(server)
    if lat is None:
        if progress: progress.increment(False)
        return None
    
    server['real_lat'] = lat
    server['speed'] = speed
    server['udp'] = udp
    
    name = get_country_name(server['info']['cc'])
    mode = "Reality" if server.get('is_reality') else ("WARP" if server.get('is_warp') else "TCP")
    logger.info(f"   🎯 {server['ip']} ({name}) - {speed:.1f}Mbps, {lat:.0f}ms [{mode}]")
    
    if progress: progress.increment(True)
    return server

# ═══════════════════════════════════════════════════════════════
# 📥 СБОР
# ═══════════════════════════════════════════════════════════════
def fetch_url(url, src):
    try:
        r = requests.get(url, timeout=TIMEOUT_FETCH, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            text = r.text
            try:
                decoded = base64.b64decode(text).decode('utf-8')
                if "vless://" in decoded:
                    text = decoded
            except:
                pass
            
            configs = [parse_config(link, src) for link in extract_links(text)]
            return [c for c in configs if c]
    except Exception as e:
        # Логируем ошибку только если это наши критические ссылки
        if "igareck" in url:
            logger.warning(f"⚠️ Ошибка загрузки {url}: {e}")
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

def collect_all():
    global_cfgs = []
    whitelist_cfgs = []
    
    logger.info("📥 Сбор конфигов...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_FETCH) as ex:
        futures = {}
        for url in GLOBAL_URLS:
            futures[ex.submit(fetch_url, url, 'general')] = 'general'
        for url in WHITELIST_URLS:
            futures[ex.submit(fetch_url, url, 'whitelist')] = 'whitelist'
        for ch in TELEGRAM_CHANNELS:
            futures[ex.submit(fetch_tg, ch)] = 'telegram'
            
        for future in concurrent.futures.as_completed(futures):
            try:
                configs = future.result()
                for c in configs:
                    if c['source'] == 'whitelist': whitelist_cfgs.append(c)
                    else: global_cfgs.append(c)
            except: pass
            
    logger.info(f"\n📊 Собрано: {len(global_cfgs)} глобальных, {len(whitelist_cfgs)} WL")
    return global_cfgs, whitelist_cfgs

# ═══════════════════════════════════════════════════════════════
# 🏆 ФИНАЛЬНЫЙ ОТБОР
# ═══════════════════════════════════════════════════════════════
def select_final_9(verified_global, verified_whitelist):
    final = []
    used_ips = set()
    last_update = get_last_update_time()
    next_update = get_next_update_time()
    
    # 1. GAME POOL
    game_pool = [s for s in verified_global 
                 if s.get('is_reality') 
                 and s['info']['cc'] in GAME_COUNTRIES
                 and s['real_lat'] <= MAX_PING_GAME
                 and s['speed'] >= MIN_SPEED_GAME]
    
    game_pool = sorted(game_pool, key=lambda x: (
        x['info']['cc'] not in PRIORITY_COUNTRIES, 
        x['real_lat']
    ))
    
    # 2. UNIVERSAL POOL
    univ_pool = [s for s in verified_global 
                 if s.get('is_reality')
                 and s['speed'] >= MIN_SPEED_UNIVERSAL
                 and s['real_lat'] <= MAX_PING_UNIVERSAL]
                 
    univ_pool = sorted(univ_pool, key=lambda x: (
        x['info']['cc'] not in PRIORITY_COUNTRIES,
        -x.get('reality_score', 0),
        -x['speed']
    ))
    
    # 3. WARP POOL
    warp_pool = [s for s in verified_global
                 if (s.get('is_reality') and s.get('reality_score', 0) >= 50) 
                 or (s.get('is_warp') and s['speed'] >= 3.0)]
    warp_pool = sorted(warp_pool, key=lambda x: (-x.get('reality_score', 0), -x['speed']))
    
    # 4. WHITELIST POOL
    wl_pool = sorted(verified_whitelist, key=lambda x: (-x['speed'], x['real_lat']))
    
    logger.info(f"\n📊 Пулы (С учетом приоритета {PRIORITY_COUNTRIES}):")
    logger.info(f"   🎮 GAME: {len(game_pool)}")
    logger.info(f"   ⚡ UNIVERSAL: {len(univ_pool)}")
    logger.info(f"   🔄 WARP: {len(warp_pool)}")
    
    # GAME-1
    if game_pool:
        s = game_pool[0]
        used_ips.add(s['ip'])
        cc = s['info']['cc']
        flag = get_flag(cc)
        prio_icon = "⭐" if cc in PRIORITY_COUNTRIES else ""
        s['final_name'] = f"🎮{flag}{prio_icon} {get_country_name(cc)} | 📅{last_update}"
        s['role'] = 'GAME'
        final.append(s)
    
    # GAME-2
    cands = [s for s in game_pool if s['ip'] not in used_ips]
    if cands:
        s = cands[0]
        used_ips.add(s['ip'])
        cc = s['info']['cc']
        flag = get_flag(cc)
        prio_icon = "⭐" if cc in PRIORITY_COUNTRIES else ""
        s['final_name'] = f"🎮{flag}{prio_icon} {get_country_name(cc)} | 📅{next_update}"
        s['role'] = 'GAME'
        final.append(s)
        
    # UNIVERSAL x3
    for i in range(3):
        cands = [s for s in univ_pool if s['ip'] not in used_ips]
        if cands:
            s = cands[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            flag = get_flag(cc)
            prio_icon = "⭐" if cc in PRIORITY_COUNTRIES else ""
            s['final_name'] = f"⚡{flag}{prio_icon} {get_country_name(cc)}"
            s['role'] = 'UNIVERSAL'
            final.append(s)
            
    # WARP x2
    for i in range(2):
        cands = [s for s in warp_pool if s['ip'] not in used_ips]
        if cands:
            s = cands[0]
            used_ips.add(s['ip'])
            cc = s['info']['cc']
            mode = "WARP" if s.get('is_warp') else "REALITY"
            s['final_name'] = f"🔄{get_flag(cc)} {get_country_name(cc)} ({mode})"
            s['role'] = 'WARP'
            final.append(s)

    # WHITELIST x2
    for i in range(2):
        if i < len(wl_pool):
            s = wl_pool[i]
            cc = s['info']['cc']
            s['final_name'] = f"⚪{get_flag(cc)} (РКН)"
            s['role'] = 'WHITELIST'
            final.append(s)
            
    # FILLER
    while len(final) < 9:
        rem = [s for s in verified_global if s['ip'] not in used_ips]
        if not rem: break
        s = rem[0]
        used_ips.add(s['ip'])
        cc = s['info']['cc']
        s['final_name'] = f"⚡{get_flag(cc)} {get_country_name(cc)}"
        final.append(s)

    reserve = [s for s in verified_global if s['ip'] not in used_ips][:RESERVE_POOL_SIZE]
    return final, reserve

# ═══════════════════════════════════════════════════════════════
# 💾 СОХРАНЕНИЕ
# ═══════════════════════════════════════════════════════════════
def save_results(final, reserve, stats):
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
        
    json_data = {
        "updated_msk": get_timestamp(),
        "stats": stats,
        "servers": []
    }
    for s in final:
        json_data["servers"].append({
            "name": s['final_name'],
            "ip": s['ip'],
            "cc": s['info']['cc'],
            "speed": s['speed'],
            "ping": s['real_lat'],
            "type": "Reality" if s.get('is_reality') else "Warp/Other"
        })
    try:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
    except: pass

    pool = {"updated": get_timestamp(), "servers": []}
    for s in reserve:
         pool["servers"].append({"ip": s['ip'], "cc": s['info']['cc'], "link": s['original']})
    try:
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(pool, f, ensure_ascii=False, indent=2)
    except: pass

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start = time.time()
    print("═" * 70)
    logger.info("🚀 FL1P VPN V2.1 - IGAR EDITION")
    logger.info(f"   🔥 Priority Countries: {', '.join(PRIORITY_COUNTRIES)}")
    print("═" * 70)
    
    load_history()
    if not os.path.exists(XRAY_BIN): return
    os.chmod(XRAY_BIN, 0o755)
    download_mmdb()
    init_geoip()
    
    global_cfgs, whitelist_cfgs = collect_all()
    
    unique = {}
    for c in global_cfgs:
        key = f"{c['ip']}:{c['port']}"
        score = (2 if c.get('is_reality') else (1 if c.get('is_warp') else 0))
        if key not in unique or score > unique[key].get('score', -1):
            c['score'] = score
            unique[key] = c
    global_list = list(unique.values())
    
    logger.info(f"⚡ Проверка TCP ({len(global_list)})...")
    
    alive_global = []
    prog = ProgressCounter(len(global_list), "TCP")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, prog) for s in global_list])]:
            if r: alive_global.append(r)
            
    alive_wl = []
    prog = ProgressCounter(len(whitelist_cfgs), "TCP WL")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed([ex.submit(initial_check, s, prog) for s in whitelist_cfgs])]:
            if r: alive_wl.append(r)
            
    logger.info(f"\n🧪 Глубокая проверка ({len(alive_global)} живых)...")
    alive_global.sort(key=lambda x: (x['info']['cc'] not in PRIORITY_COUNTRIES, x['latency']))
    
    candidates = alive_global[:MAX_DEEP_CHECK_GLOBAL]
    verified_global = []
    prog = ProgressCounter(len(candidates), "Deep")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, prog): s for s in candidates})]:
            if r: verified_global.append(r)
            
    verified_wl = []
    prog = ProgressCounter(len(alive_wl), "Deep WL")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DEEP) as ex:
        for r in [f.result() for f in concurrent.futures.as_completed({ex.submit(full_check, s, prog): s for s in alive_wl})]:
            if r: verified_wl.append(r)
            
    final_9, reserve = select_final_9(verified_global, verified_wl)
    
    print("\n" + "═" * 70)
    logger.info("🏆 THE FINAL 9:")
    for i, s in enumerate(final_9):
        print(f"   {i+1}. {s['final_name']} ({s['speed']} Mbps)")
    
    stats = {"final": len(final_9), "reserve": len(reserve)}
    save_results(final_9, reserve, stats)
    save_history()
    close_geoip()
    
    print("═" * 70)
    logger.info(f"✅ DONE in {time.time()-start:.1f}s")

if __name__ == "__main__":
    main()
