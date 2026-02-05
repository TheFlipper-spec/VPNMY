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

# --- V106: IMPROVED LOGGING & NO-USA EDITION ---
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

# Счётчики для прогресса
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
            
            # Показываем прогресс каждые 10%
            if self.total > 0 and self.current % max(1, self.total // 10) == 0:
                pct = (self.current / self.total) * 100
                logger.info(f"   📊 {self.name}: {self.current}/{self.total} ({pct:.0f}%) | ✅{self.success} ❌{self.failed}")

# ═══════════════════════════════════════════════════════════════
# ИСТОЧНИКИ
# ═══════════════════════════════════════════════════════════════
PREMIUM_URLS = [
    "https://raw.githubusercontent.com/Yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/w1770946466/Auto_proxy/main/Long_term_subscription_num",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/main/Config/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/hysteria2"
]

GENERAL_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/main/configs/vless.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

TELEGRAM_CHANNELS = [
    "FarahVPN", "v2rayng_vpn", "v2ray_outlineir",
    "v2ray_configs_pool", "VlessConfig", "v2ray1_ng"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
MAX_WORKERS_SCAN = 60
MAX_WORKERS_CUP = 15
TIMEOUT = 0.8            
REAL_TEST_TIMEOUT = 10.0 
SPEED_TEST_TIMEOUT = 7.0 

MIN_SPEED_GOD = 10.0     
MIN_SPEED_BACKUP = 3.0   
MIN_SPEED_RU = 0.5       

OUTPUT_FILE = 'FL1PVPN' 
JSON_FILE = 'stats.json'
HISTORY_FILE = 'history.json' 

TIMEZONE_OFFSET = 3 
CACHE_TTL_HOURS = 4      
MAX_FAILURES = 2         

RUS_NAMES = {
    'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'PL': 'Польша', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'NO': 'Норвегия', 'AT': 'Австрия', 'CZ': 'Чехия',
    'UA': 'Украина', 'KZ': 'Казахстан', 'MD': 'Молдова', 'BY': 'Беларусь',
    'BG': 'Болгария', 'RO': 'Румыния', 'HU': 'Венгрия', 'SK': 'Словакия'
}

# ⚠️ ИСПРАВЛЕНО: США добавлены в черный список!
BLACKLIST_COUNTRIES = ['CN', 'IR', 'KP', 'US']

# Приоритетные страны (ближе к РФ = лучше пинг)
PRIORITY_COUNTRIES = ['FI', 'EE', 'LV', 'LT', 'SE', 'NO', 'PL', 'DE', 'NL']

# ═══════════════════════════════════════════════════════════════
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════════════════════
geo_reader = None
server_history = {} 

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
        # Пропускаем серверы с MAX_FAILURES
        if val.get('fails', 0) >= MAX_FAILURES:
            failed_count += 1
            continue
        # Храним только последние 24 часа
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

def update_history(ip, port, is_alive):
    key = f"{ip}:{port}"
    current = server_history.get(key, {'fails': 0, 'ts': 0, 'success_streak': 0})
    
    if is_alive:
        current['fails'] = 0
        current['success_streak'] = current.get('success_streak', 0) + 1
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
                total_size = int(r.headers.get('content-length', 0))
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
    regex = r"(vless://[^\s\n<>\"']+|ss://[^\s\n<>\"']+|hy2://[^\s\n<>\"']+)"
    links = re.findall(regex, text)
    
    if len(links) < 3:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    
    # Удаляем дубликаты, сохраняя порядок
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
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
    # Проверка на локальные адреса
    if host.startswith('127.') or host.startswith('192.168.') or host.startswith('10.'):
        return False
    if host in ['localhost', '0.0.0.0']:
        return False
    return True

def parse_config_info(config_str, source_type):
    if not config_str or len(config_str) < 20:
        return None
    
    try:
        # ═══════ HYSTERIA2 ═══════
        if config_str.startswith("hy2://"):
            part = config_str.split("@")
            if len(part) < 2:
                return None
            
            password = part[0].replace("hy2://", "")
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
                "parsed_params": params, "sni": sni, "is_hy2": True
            }

        # ═══════ VLESS ═══════
        if config_str.startswith("vless://"):
            if "@" not in config_str or "?" not in config_str:
                return None
            
            part = config_str.split("@")[1].split("?")[0]
            if ":" not in part:
                return None
            
            # Извлекаем хост и порт
            host, port = part.rsplit(":", 1)
            
            if not is_valid_ip_or_host(host) or not is_valid_port(port):
                return None
            
            # Извлекаем UUID
            _uuid = config_str.split("@")[0].replace("vless://", "")
            if not is_valid_uuid(_uuid):
                logger.debug(f"   ⚠️ Невалидный UUID: {_uuid[:20]}...")
                return None
            
            # Парсим параметры
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            is_reality = (security == 'reality')
            
            # Проверки для Reality
            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) != 43:
                    logger.debug(f"   ⚠️ Невалидный pbk для Reality: {len(pbk)} символов")
                    return None
                sni = params.get('sni', [''])[0]
                if sni == host:
                    logger.debug(f"   ⚠️ SNI совпадает с хостом: {sni}")
                    return None
            
            # Remark
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, "port": int(port), "uuid": _uuid, "original": config_str, 
                "original_remark": original_remark, "latency": 9999, "jitter": 0, 
                "final_score": 9999, "info": {},
                "speed_mbps": 0.0,
                "transport": transport, "security": security,
                "is_reality": is_reality,
                "is_hy2": False,
                "source_type": source_type,
                "parsed_params": params
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

            # WebSocket
            if server['transport'] == 'ws':
                ws_settings = {"path": params.get('path', ['/'])[0]}
                host_val = params.get('host', [''])[0]
                if host_val:
                    ws_settings["headers"] = {"Host": host_val}
                stream_settings["wsSettings"] = ws_settings
            
            # gRPC
            elif server['transport'] == 'grpc':
                service_name = params.get('serviceName', [''])[0]
                if service_name:
                    stream_settings["grpcSettings"] = {"serviceName": service_name}

            # TLS
            if server['security'] == 'tls':
                tls_settings = {
                    "serverName": params.get('sni', [''])[0],
                    "allowInsecure": False,
                    "fingerprint": params.get('fp', ['chrome'])[0]
                }
                stream_settings["tlsSettings"] = tls_settings
            
            # Reality
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
                if total_bytes > 2 * 1024 * 1024:  # 2MB limit
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
        # Создаём временный конфиг
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
            json.dump(config_data, tmp_conf)
            config_path = tmp_conf.name

        # Запускаем Xray
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL  # Изменено: не используем PIPE
        )
        
        time.sleep(1.0)
        
        if xray_process.poll() is not None:
            logger.debug(f"   ❌ Xray умер сразу после запуска для {server['ip']}")
            raise Exception("Xray died")

        # Тестируем подключение
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        
        start_time = time.perf_counter()
        resp = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=REAL_TEST_TIMEOUT, verify=False)
        end_time = time.perf_counter()
        
        if 200 <= resp.status_code < 300:
            result_latency = (end_time - start_time) * 1000
            logger.debug(f"   🟢 {server['ip']}:{server['port']} - реальный пинг {result_latency:.0f}ms")
            
            udp_success = check_udp_dns(local_port)
            result_speed = measure_speed(local_port)
            update_history(server['ip'], server['port'], True)
        else:
            logger.debug(f"   🔴 {server['ip']}:{server['port']} - HTTP {resp.status_code}")
            update_history(server['ip'], server['port'], False)
            
    except requests.exceptions.Timeout:
        logger.debug(f"   ⏰ {server['ip']}:{server['port']} - таймаут")
        update_history(server['ip'], server['port'], False)
    except Exception as e:
        logger.debug(f"   ❌ {server['ip']}:{server['port']} - ошибка: {e}")
        update_history(server['ip'], server['port'], False)
    finally:
        # Корректно завершаем Xray
        if xray_process:
            try:
                xray_process.terminate()
                xray_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                xray_process.kill()
                xray_process.wait()
            except:
                pass
        
        # Удаляем временный файл
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
    
    # Проверяем кеш
    if not should_check_server(ip, port):
        if progress:
            progress.increment(success=False)
        return None
    
    # Получаем страну
    code = get_ip_country_local(ip)
    
    # ⚠️ ПРОВЕРКА НА BLACKLIST (включая США)
    if code in BLACKLIST_COUNTRIES:
        logger.debug(f"   🚫 {ip} - страна в черном списке: {code}")
        if progress:
            progress.increment(success=False)
        return None

    # TCP пинг
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
    logger.info(f"   🎯 {server['ip']} ({country_name}) - {speed:.1f} Mbps, {lat:.0f}ms, {udp_status}")
    
    if progress:
        progress.increment(success=True)
    
    return server

# ═══════════════════════════════════════════════════════════════
# ВЫБОР ЛУЧШИХ
# ═══════════════════════════════════════════════════════════════
def get_best_candidates(servers, limit=100):
    def sort_key(s):
        cc = s['info']['countryCode']
        prio = 0
        if cc in PRIORITY_COUNTRIES[:4]:  # FI, EE, LV, LT
            prio = -2
        elif cc in PRIORITY_COUNTRIES[4:]:  # SE, NO, PL, DE, NL
            prio = -1
        return (prio, s['latency'])
    
    return sorted(servers, key=sort_key)[:limit]

def select_final_servers(verified_servers):
    """Выбирает финальные 4 сервера"""
    final_4 = []
    used_ips = set()
    
    verified_ru = [s for s in verified_servers if s['info']['countryCode'] == 'RU']
    verified_global = [s for s in verified_servers if s['info']['countryCode'] != 'RU']
    
    logger.info(f"\n📊 Статистика после проверки:")
    logger.info(f"   🌍 Глобальных: {len(verified_global)}")
    logger.info(f"   🇷🇺 Российских: {len(verified_ru)}")
    
    # ═══════ 1. ОСНОВНОЙ ═══════
    god_candidates = sorted(
        [s for s in verified_global if s['speed_mbps'] > MIN_SPEED_GOD and s['udp_enabled']],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not god_candidates:
        god_candidates = sorted(verified_global, key=lambda x: x['speed_mbps'], reverse=True)
        logger.warning("   ⚠️ Нет серверов с UDP и >10 Mbps, берём лучший по скорости")

    if god_candidates:
        server_god = god_candidates[0]
        used_ips.add(server_god['ip'])
        msk_time = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime('%H:%M')
        flag = "".join([chr(127397 + ord(c)) for c in server_god['info']['countryCode'].upper()])
        server_god['final_name'] = f"ОСНОВНОЙ {flag} (Обн. {msk_time})"
        final_4.append(server_god)
        
        country_name = RUS_NAMES.get(server_god['info']['countryCode'], server_god['info']['countryCode'])
        logger.info(f"   1️⃣ ОСНОВНОЙ: {server_god['ip']} ({country_name}) - {server_god['speed_mbps']:.1f} Mbps")
    
    # ═══════ 2. ЗАПАСНОЙ ═══════
    backup_candidates = sorted(
        [s for s in verified_global if s['ip'] not in used_ips and s['speed_mbps'] > MIN_SPEED_BACKUP],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not backup_candidates:
        backup_candidates = sorted(
            [s for s in verified_global if s['ip'] not in used_ips],
            key=lambda x: x['speed_mbps'], reverse=True
        )
    
    if backup_candidates:
        server_backup = backup_candidates[0]
        used_ips.add(server_backup['ip'])
        flag = "".join([chr(127397 + ord(c)) for c in server_backup['info']['countryCode'].upper()])
        server_backup['final_name'] = f"ЗАПАСНОЙ {flag}"
        final_4.append(server_backup)
        
        country_name = RUS_NAMES.get(server_backup['info']['countryCode'], server_backup['info']['countryCode'])
        logger.info(f"   2️⃣ ЗАПАСНОЙ: {server_backup['ip']} ({country_name}) - {server_backup['speed_mbps']:.1f} Mbps")
        
    # ═══════ 3. РЕЗЕРВНЫЙ ═══════
    stable_candidates = sorted(
        [s for s in verified_global if s['ip'] not in used_ips],
        key=lambda x: (x['streak'], x['speed_mbps']), reverse=True
    )
    
    if stable_candidates:
        server_stable = stable_candidates[0]
        used_ips.add(server_stable['ip'])
        flag = "".join([chr(127397 + ord(c)) for c in server_stable['info']['countryCode'].upper()])
        server_stable['final_name'] = f"РЕЗЕРВНЫЙ {flag}"
        final_4.append(server_stable)
        
        country_name = RUS_NAMES.get(server_stable['info']['countryCode'], server_stable['info']['countryCode'])
        logger.info(f"   3️⃣ РЕЗЕРВНЫЙ: {server_stable['ip']} ({country_name}) - streak: {server_stable['streak']}, {server_stable['speed_mbps']:.1f} Mbps")
        
    # ═══════ 4. WHITELIST (RU) ═══════
    ru_final = sorted(
        [s for s in verified_ru if s['speed_mbps'] > MIN_SPEED_RU],
        key=lambda x: x['speed_mbps'], reverse=True
    )
    if not ru_final:
        ru_final = sorted(verified_ru, key=lambda x: x['speed_mbps'], reverse=True)
    
    if ru_final:
        server_ru = ru_final[0]
        flag = "".join([chr(127397 + ord(c)) for c in server_ru['info']['countryCode'].upper()])
        server_ru['final_name'] = f"WHITELIST {flag}"
        final_4.append(server_ru)
        logger.info(f"   4️⃣ WHITELIST: {server_ru['ip']} (Россия) - {server_ru['speed_mbps']:.1f} Mbps")
    else:
        logger.warning("   ⚠️ Нет рабочих серверов из России для WHITELIST")

    return final_4

# ═══════════════════════════════════════════════════════════════
# СБОР КОНФИГОВ
# ═══════════════════════════════════════════════════════════════
def fetch_telegram_channels():
    logger.info(f"✈️ Сканирование Telegram каналов...")
    links = []
    for channel in TELEGRAM_CHANNELS:
        try:
            resp = requests.get(f"https://t.me/s/{channel}", timeout=5)
            if resp.status_code == 200:
                found = extract_links(resp.text)
                parsed_count = 0
                for link in found:
                    p = parse_config_info(link, 'telegram')
                    if p:
                        links.append(p)
                        parsed_count += 1
                logger.debug(f"   📱 {channel}: {parsed_count} конфигов")
        except Exception as e:
            logger.debug(f"   ⚠️ {channel}: ошибка - {e}")
    
    logger.info(f"   📱 Telegram: найдено {len(links)} конфигов")
    return links

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                found = extract_links(resp.text)
                parsed_count = 0
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p:
                        links.append(p)
                        parsed_count += 1
                logger.debug(f"   🔗 {url.split('/')[-1][:30]}: {parsed_count} конфигов")
        except Exception as e:
            logger.debug(f"   ⚠️ {url.split('/')[-1][:30]}: ошибка - {e}")
    
    logger.info(f"   📦 {source_type}: найдено {len(links)} конфигов")
    return links

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    
    print("=" * 60)
    logger.info("🚀 ЗАПУСК V106 (IMPROVED LOGGING & NO-USA)")
    logger.info(f"   🚫 Черный список стран: {', '.join(BLACKLIST_COUNTRIES)}")
    print("=" * 60)
    
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
    logger.info("\n" + "=" * 40)
    logger.info("📥 ЭТАП 1: СБОР КОНФИГОВ")
    logger.info("=" * 40)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as executor:
        f1 = executor.submit(process_urls, GENERAL_URLS, 'static')
        f3 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        f4 = executor.submit(process_urls, PREMIUM_URLS, 'premium') 
        f_tg = executor.submit(fetch_telegram_channels)
        all_servers = f1.result() + f3.result() + f4.result() + f_tg.result()
    
    # Дедупликация
    unique_servers = {}
    for s in all_servers:
        key = f"{s['ip']}:{s['port']}"
        if key not in unique_servers:
            unique_servers[key] = s
    
    candidates = list(unique_servers.values())
    logger.info(f"\n🔍 Всего найдено: {len(all_servers)} конфигов")
    logger.info(f"🔍 Уникальных: {len(candidates)} серверов")

    # ═══════ 2. TCP ПРОВЕРКА ═══════
    logger.info("\n" + "=" * 40)
    logger.info("⚡ ЭТАП 2: TCP ПРОВЕРКА")
    logger.info("=" * 40)
    
    alive_servers = []
    progress_tcp = ProgressCounter(len(candidates), "TCP-пинг")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_SCAN) as executor:
        futures = [executor.submit(check_server_initial, s, progress_tcp) for s in candidates]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                alive_servers.append(res)
    
    logger.info(f"\n✅ Живых TCP: {len(alive_servers)}")
    
    # Статистика по странам
    country_stats = {}
    for s in alive_servers:
        cc = s['info']['countryCode']
        country_stats[cc] = country_stats.get(cc, 0) + 1
    
    logger.info("📊 Распределение по странам:")
    for cc, count in sorted(country_stats.items(), key=lambda x: -x[1])[:10]:
        name = RUS_NAMES.get(cc, cc)
        logger.info(f"   {cc} ({name}): {count}")
    
    # ═══════ 3. ОТБОР КАНДИДАТОВ ═══════
    ru_candidates = [s for s in alive_servers if s['info']['countryCode'] == 'RU']
    global_candidates = [s for s in alive_servers if s['info']['countryCode'] != 'RU']
    
    top_global = get_best_candidates(global_candidates, 1500)
    top_ru = ru_candidates
    
    full_check_list = top_global + top_ru
    
    # ═══════ 4. ГЛУБОКАЯ ПРОВЕРКА ═══════
    logger.info("\n" + "=" * 40)
    logger.info(f"🧪 ЭТАП 3: ГЛУБОКАЯ ПРОВЕРКА ({len(full_check_list)} серверов)")
    logger.info("=" * 40)
    
    verified_servers = []
    progress_deep = ProgressCounter(len(full_check_list), "Глубокая проверка")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_CUP) as executor:
        futures = {executor.submit(check_full_server, s, progress_deep): s for s in full_check_list}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                verified_servers.append(res)
    
    logger.info(f"\n✅ Проверку прошли: {len(verified_servers)}")
            
    # ═══════ 5. ФИНАЛЬНЫЙ ОТБОР ═══════
    logger.info("\n" + "=" * 40)
    logger.info("🏆 ЭТАП 4: ФИНАЛЬНЫЙ ОТБОР")
    logger.info("=" * 40)
    
    final_4 = select_final_servers(verified_servers)

    # ═══════ 6. ЗАПИСЬ РЕЗУЛЬТАТОВ ═══════
    result_links = []
    json_data = {"servers": [], "updated": datetime.now(timezone.utc).isoformat()}
    
    print("\n" + "=" * 60)
    logger.info("🏆 THE CHOSEN FOUR:")
    print("=" * 60)
    
    for s in final_4:
        country_name = RUS_NAMES.get(s['info']['countryCode'], s['info']['countryCode'])
        udp_status = "✅UDP" if s.get('udp_enabled') else "❌UDP"
        
        print(f"   🌟 {s['final_name']}")
        print(f"      IP: {s['ip']} | {s['speed_mbps']:.1f} Mbps | {s['real_latency']:.0f}ms | {udp_status}")
        print()
        
        base = s['original'].split('#')[0]
        link = f"{base}#{quote(s['final_name'])}"
        result_links.append(link)
        
        json_data["servers"].append({
            "name": s['final_name'],
            "ip": s['ip'],
            "country": s['info']['countryCode'],
            "country_name": country_name,
            "speed_mbps": s['speed_mbps'],
            "latency_ms": s['real_latency'],
            "udp": s.get('udp_enabled', False),
            "streak": s.get('streak', 0)
        })

    # Запись файлов
    try:
        with open(OUTPUT_FILE, 'w') as f:
            f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        logger.info(f"💾 Подписка сохранена: {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи {OUTPUT_FILE}: {e}")
    
    try:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 JSON сохранён: {JSON_FILE}")
    except Exception as e:
        logger.error(f"❌ Ошибка записи {JSON_FILE}: {e}")
    
    save_history()
    close_geoip()
    
    elapsed = time.time() - start_time
    print("=" * 60)
    logger.info(f"✅ ГОТОВО за {elapsed:.1f} секунд")
    logger.info(f"📄 Лог сохранён: {LOG_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
