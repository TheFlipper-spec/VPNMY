import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import requests
import base64
import socket
import time
import os
import json
import subprocess
import tempfile
import random
import urllib3
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, parse_qs, unquote

# --- WATCHDOG V1.0: Quick Health Check & Rotation ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ═══════════════════════════════════════════════════════════════
LOG_FILE = 'watchdog.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'),  # Append mode!
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
XRAY_BIN = "./xray"

# Файлы
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

# Таймауты
HEALTH_CHECK_TIMEOUT = 8.0      # Секунд на проверку одного сервера
XRAY_STARTUP_DELAY = 1.0        # Секунд на запуск Xray
CONNECTION_TIMEOUT = 5.0         # Таймаут HTTP запроса

TIMEZONE_OFFSET = 3  # MSK

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

# ═══════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_beautiful_time():
    """Возвращает красиво отформатированное время (MSK)"""
    now_utc = datetime.now(timezone.utc)
    msk_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    return f"🕐{msk_time.strftime('%H:%M')}"

def get_timestamp():
    """Возвращает timestamp для логов"""
    now_utc = datetime.now(timezone.utc)
    msk_time = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    return msk_time.strftime('%Y-%m-%d %H:%M:%S MSK')

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
# ЗАГРУЗКА ДАННЫХ
# ═══════════════════════════════════════════════════════════════
def load_current_servers():
    """Загружает текущие активные серверы из stats.json"""
    if not os.path.exists(JSON_FILE):
        logger.error(f"❌ Файл {JSON_FILE} не найден!")
        return None, None
    
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        servers = data.get('servers', [])
        logger.info(f"📂 Загружено {len(servers)} активных серверов из {JSON_FILE}")
        return servers, data
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга {JSON_FILE}: {e}")
        return None, None
    except Exception as e:
        logger.error(f"❌ Ошибка чтения {JSON_FILE}: {e}")
        return None, None

def load_reserve_pool():
    """Загружает резервный пул из reserve_pool.json"""
    if not os.path.exists(RESERVE_POOL_FILE):
        logger.warning(f"⚠️ Файл {RESERVE_POOL_FILE} не найден")
        return []
    
    try:
        with open(RESERVE_POOL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        servers = data.get('servers', [])
        logger.info(f"📂 Загружено {len(servers)} резервных серверов из {RESERVE_POOL_FILE}")
        return servers
    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга {RESERVE_POOL_FILE}: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Ошибка чтения {RESERVE_POOL_FILE}: {e}")
        return []

def save_reserve_pool(servers):
    """Сохраняет обновлённый резервный пул"""
    try:
        data = {
            "updated": datetime.now(timezone.utc).isoformat(),
            "updated_msk": get_timestamp(),
            "servers": servers
        }
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Резервный пул сохранён: {len(servers)} серверов")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения {RESERVE_POOL_FILE}: {e}")
        return False

def save_updated_stats(servers, original_data):
    """Сохраняет обновлённую статистику"""
    try:
        original_data['servers'] = servers
        original_data['updated'] = datetime.now(timezone.utc).isoformat()
        original_data['updated_msk'] = get_timestamp()
        original_data['last_watchdog'] = datetime.now(timezone.utc).isoformat()
        original_data['watchdog_rotations'] = original_data.get('watchdog_rotations', 0) + 1
        
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Статистика обновлена: {JSON_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения {JSON_FILE}: {e}")
        return False

def save_updated_subscription(servers):
    """Сохраняет обновлённую подписку в base64"""
    links = []
    
    for server in servers:
        original = server.get('original', '')
        if not original:
            logger.warning(f"⚠️ Сервер {server.get('ip', 'unknown')} без original ссылки")
            continue
        
        # Убираем старый remark и добавляем новый
        base = original.split('#')[0]
        name = server.get('name', 'Unknown')
        link = f"{base}#{quote(name)}"
        links.append(link)
    
    if not links:
        logger.error("❌ Нет ссылок для сохранения!")
        return False
    
    try:
        content = "\n".join(links)
        encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(encoded)
        
        logger.info(f"💾 Подписка обновлена: {OUTPUT_FILE} ({len(links)} серверов)")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения {OUTPUT_FILE}: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ КОНФИГА XRAY
# ═══════════════════════════════════════════════════════════════
def generate_xray_config_from_original(original, local_port):
    """Генерирует конфиг Xray из оригинальной ссылки vless:// или hy2://"""
    
    if not original:
        return None
    
    try:
        # ═══════ HYSTERIA2 ═══════
        if original.startswith("hy2://") or original.startswith("hysteria2://"):
            prefix = "hy2://" if original.startswith("hy2://") else "hysteria2://"
            
            parts = original.split("@")
            if len(parts) < 2:
                return None
            
            password = parts[0].replace(prefix, "")
            rest = parts[1]
            
            # Извлекаем host:port
            if "?" in rest:
                host_port = rest.split("?")[0]
                query = rest.split("?")[1].split("#")[0]
            else:
                host_port = rest.split("#")[0]
                query = ""
            
            if ":" not in host_port:
                return None
            
            host, port = host_port.rsplit(":", 1)
            params = parse_qs(query) if query else {}
            sni = params.get('sni', [''])[0]
            
            config = {
                "log": {"loglevel": "error"},
                "inbounds": [{
                    "port": local_port,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {"udp": True, "auth": "noauth"}
                }],
                "outbounds": [{
                    "protocol": "hysteria2",
                    "settings": {
                        "vnext": [{
                            "address": host,
                            "port": int(port),
                            "users": [{"password": password}]
                        }]
                    },
                    "streamSettings": {
                        "network": "udp",
                        "security": "tls",
                        "tlsSettings": {
                            "serverName": sni,
                            "allowInsecure": True
                        }
                    }
                }]
            }
            return config
        
        # ═══════ VLESS ═══════
        if original.startswith("vless://"):
            parts = original.split("@")
            if len(parts) < 2:
                return None
            
            uuid = parts[0].replace("vless://", "")
            rest = parts[1]
            
            # Извлекаем host:port
            if "?" not in rest:
                return None
            
            host_port = rest.split("?")[0]
            query = rest.split("?")[1].split("#")[0]
            
            if ":" not in host_port:
                return None
            
            host, port = host_port.rsplit(":", 1)
            params = parse_qs(query)
            
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            
            # User object
            user_obj = {"id": uuid, "encryption": "none"}
            flow = params.get('flow', [''])[0]
            if flow:
                user_obj["flow"] = flow
            
            # Stream settings
            stream_settings = {
                "network": transport,
                "security": security
            }
            
            # WebSocket
            if transport == 'ws':
                ws_settings = {"path": params.get('path', ['/'])[0]}
                host_val = params.get('host', [''])[0]
                if host_val:
                    ws_settings["headers"] = {"Host": host_val}
                stream_settings["wsSettings"] = ws_settings
            
            # gRPC
            elif transport == 'grpc':
                service_name = params.get('serviceName', [''])[0]
                if service_name:
                    stream_settings["grpcSettings"] = {"serviceName": service_name}
            
            # TLS
            if security == 'tls':
                tls_settings = {
                    "serverName": params.get('sni', [''])[0],
                    "allowInsecure": False,
                    "fingerprint": params.get('fp', ['chrome'])[0]
                }
                stream_settings["tlsSettings"] = tls_settings
            
            # Reality
            elif security == 'reality':
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
                    "settings": {"udp": True, "auth": "noauth"}
                }],
                "outbounds": [{
                    "protocol": "vless",
                    "settings": {
                        "vnext": [{
                            "address": host,
                            "port": int(port),
                            "users": [user_obj]
                        }]
                    },
                    "streamSettings": stream_settings
                }]
            }
            return config
            
    except Exception as e:
        logger.debug(f"Ошибка генерации конфига: {e}")
    
    return None

# ═══════════════════════════════════════════════════════════════
# ПРОВЕРКА ЗДОРОВЬЯ СЕРВЕРА
# ═══════════════════════════════════════════════════════════════
def quick_health_check(server):
    """
    Быстрая проверка работоспособности сервера.
    Возвращает True если сервер жив, False если мёртв.
    """
    original = server.get('original', '')
    ip = server.get('ip', 'unknown')
    
    if not original:
        logger.warning(f"   ⚠️ {ip}: нет original ссылки")
        return False
    
    local_port = random.randint(20000, 50000)
    config = generate_xray_config_from_original(original, local_port)
    
    if not config:
        logger.warning(f"   ⚠️ {ip}: не удалось сгенерировать конфиг")
        return False
    
    config_path = None
    xray_process = None
    is_alive = False
    latency = None
    
    try:
        # Создаём временный конфиг
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
            json.dump(config, f)
            config_path = f.name
        
        # Запускаем Xray
        xray_process = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Ждём запуска
        time.sleep(XRAY_STARTUP_DELAY)
        
        # Проверяем что Xray не упал
        if xray_process.poll() is not None:
            logger.debug(f"   ❌ {ip}: Xray умер при запуске")
            return False
        
        # Настраиваем прокси
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        
        # Проверяем первый эндпоинт
        try:
            start = time.perf_counter()
            resp = requests.get(
                "https://www.google.com/generate_204",
                proxies=proxies,
                timeout=CONNECTION_TIMEOUT,
                verify=False
            )
            end = time.perf_counter()
            
            if resp.status_code == 204 or (200 <= resp.status_code < 300):
                is_alive = True
                latency = (end - start) * 1000
        except requests.exceptions.Timeout:
            logger.debug(f"   ⏰ {ip}: таймаут google.com")
        except Exception as e:
            logger.debug(f"   ❌ {ip}: ошибка google.com - {e}")
        
        # Если первый не сработал, пробуем второй
        if not is_alive:
            try:
                start = time.perf_counter()
                resp = requests.get(
                    "https://cp.cloudflare.com/",
                    proxies=proxies,
                    timeout=CONNECTION_TIMEOUT,
                    verify=False
                )
                end = time.perf_counter()
                
                if 200 <= resp.status_code < 300:
                    is_alive = True
                    latency = (end - start) * 1000
            except requests.exceptions.Timeout:
                logger.debug(f"   ⏰ {ip}: таймаут cloudflare.com")
            except Exception as e:
                logger.debug(f"   ❌ {ip}: ошибка cloudflare.com - {e}")
        
        # Если и второй не сработал, пробуем третий
        if not is_alive:
            try:
                start = time.perf_counter()
                resp = requests.get(
                    "https://www.gstatic.com/generate_204",
                    proxies=proxies,
                    timeout=CONNECTION_TIMEOUT,
                    verify=False
                )
                end = time.perf_counter()
                
                if resp.status_code == 204 or (200 <= resp.status_code < 300):
                    is_alive = True
                    latency = (end - start) * 1000
            except:
                pass
        
    except Exception as e:
        logger.debug(f"   ❌ {ip}: общая ошибка - {e}")
    
    finally:
        # Убиваем Xray
        if xray_process:
            try:
                xray_process.terminate()
                xray_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    xray_process.kill()
                    xray_process.wait()
                except:
                    pass
            except:
                pass
        
        # Удаляем временный конфиг
        if config_path and os.path.exists(config_path):
            try:
                os.remove(config_path)
            except:
                pass
    
    if is_alive and latency:
        logger.debug(f"   ✅ {ip}: жив ({latency:.0f}ms)")
    
    return is_alive

# ═══════════════════════════════════════════════════════════════
# ПОИСК ЗАМЕНЫ
# ═══════════════════════════════════════════════════════════════
def find_replacement(reserve_pool, used_ips, server_role, max_attempts=5):
    """
    Ищет работающую замену в резервном пуле.
    
    Args:
        reserve_pool: список резервных серверов
        used_ips: set уже используемых IP
        server_role: роль сервера для лога
        max_attempts: максимум попыток
    
    Returns:
        (replacement_server, updated_reserve_pool) или (None, reserve_pool)
    """
    attempts = 0
    checked_indices = []
    
    for i, server in enumerate(reserve_pool):
        if attempts >= max_attempts:
            logger.warning(f"   ⚠️ Достигнут лимит попыток ({max_attempts})")
            break
        
        ip = server.get('ip', 'unknown')
        
        # Пропускаем уже используемые IP
        if ip in used_ips:
            continue
        
        attempts += 1
        checked_indices.append(i)
        
        country = server.get('country', 'XX')
        country_name = RUS_NAMES.get(country, country)
        is_reality = server.get('is_reality', False)
        reality_tag = "🛡️" if is_reality else ""
        
        logger.info(f"   🔄 Проверяем резерв #{i+1}: {ip} ({country_name}) {reality_tag}")
        
        if quick_health_check(server):
            logger.info(f"   ✅ Найдена замена: {ip} ({country_name})")
            
            # Удаляем из резервного пула
            updated_pool = [s for j, s in enumerate(reserve_pool) if j != i]
            
            return server, updated_pool
        else:
            logger.info(f"   ❌ Резерв #{i+1} тоже мёртв")
    
    logger.warning(f"   ⚠️ Не удалось найти замену после {attempts} попыток")
    return None, reserve_pool

# ═══════════════════════════════════════════════════════════════
# ОПРЕДЕЛЕНИЕ РОЛИ СЕРВЕРА
# ═══════════════════════════════════════════════════════════════
def determine_server_role(index, server_name):
    """Определяет роль сервера по индексу и имени"""
    name_lower = server_name.lower() if server_name else ""
    
    if "основной" in name_lower or index == 0:
        return "ОСНОВНОЙ", True  # include_time = True
    elif "запасной" in name_lower or index == 1:
        return "ЗАПАСНОЙ", False
    elif "резервный" in name_lower or index == 2:
        return "РЕЗЕРВНЫЙ", False
    elif "whitelist" in name_lower or index == 3:
        return "WHITELIST", False
    else:
        return f"SERVER_{index+1}", False

# ═══════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ РОТАЦИИ
# ═══════════════════════════════════════════════════════════════
def perform_rotation(current_servers, reserve_pool, original_stats):
    """
    Выполняет проверку и ротацию серверов.
    
    Returns:
        (updated_servers, updated_reserve_pool, changes_made)
    """
    alive_servers = []
    dead_servers = []
    dead_indices = []
    
    logger.info(f"\n🔍 Проверка {len(current_servers)} активных серверов...")
    logger.info("─" * 50)
    
    # Проверяем каждый сервер
    for i, server in enumerate(current_servers):
        ip = server.get('ip', 'unknown')
        name = server.get('name', 'Unknown')
        country = server.get('country', 'XX')
        country_name = RUS_NAMES.get(country, country)
        is_reality = server.get('is_reality', False)
        
        reality_tag = "🛡️" if is_reality else ""
        
        logger.info(f"\n   [{i+1}/{len(current_servers)}] {name}")
        logger.info(f"       IP: {ip} | {country_name} {reality_tag}")
        
        if quick_health_check(server):
            logger.info(f"       ✅ ЖИВОЙ")
            alive_servers.append(server)
        else:
            logger.warning(f"       ❌ МЁРТВ!")
            dead_servers.append(server)
            dead_indices.append(i)
    
    logger.info("\n" + "─" * 50)
    logger.info(f"📊 Результат проверки: ✅ {len(alive_servers)} живых | ❌ {len(dead_servers)} мёртвых")
    
    # Если все живы - ничего не делаем
    if not dead_servers:
        logger.info("\n✅ Все серверы работают! Ротация не требуется.")
        return current_servers, reserve_pool, False
    
    # Если есть мёртвые - ищем замены
    logger.info(f"\n⚠️ Обнаружено {len(dead_servers)} мёртвых серверов. Начинаем ротацию...")
    logger.info("─" * 50)
    
    used_ips = {s.get('ip') for s in alive_servers}
    updated_servers = list(current_servers)  # Копия для модификации
    updated_pool = list(reserve_pool)
    replacements_made = 0
    
    for dead_index in dead_indices:
        dead_server = current_servers[dead_index]
        dead_ip = dead_server.get('ip', 'unknown')
        dead_name = dead_server.get('name', 'Unknown')
        
        logger.info(f"\n🔄 Ищем замену для: {dead_name} ({dead_ip})")
        
        # Определяем роль сервера
        role, include_time = determine_server_role(dead_index, dead_name)
        
        # Ищем замену
        replacement, updated_pool = find_replacement(
            updated_pool, 
            used_ips, 
            role,
            max_attempts=5
        )
        
        if replacement:
            # Формируем новое имя
            country = replacement.get('country', 'XX')
            is_reality = replacement.get('is_reality', False)
            reality_tag = "🛡️" if is_reality else ""
            
            new_name = format_server_name(
                f"{role}{reality_tag}",
                country,
                include_time=include_time
            )
            
            # Обновляем данные замены
            replacement['name'] = new_name
            
            # Заменяем в списке
            updated_servers[dead_index] = replacement
            used_ips.add(replacement.get('ip'))
            
            replacements_made += 1
            
            country_name = RUS_NAMES.get(country, country)
            logger.info(f"   ✅ Заменён на: {replacement.get('ip')} ({country_name})")
            logger.info(f"      Новое имя: {new_name}")
        else:
            logger.warning(f"   ⚠️ Замена не найдена! Сервер останется мёртвым.")
    
    logger.info("\n" + "─" * 50)
    logger.info(f"📊 Итог ротации: {replacements_made} замен из {len(dead_servers)} мёртвых")
    
    return updated_servers, updated_pool, replacements_made > 0

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    
    # Заголовок
    print("\n" + "═" * 60)
    logger.info("🐕 WATCHDOG V1.0 - Quick Health Check & Rotation")
    logger.info(f"   ⏰ Время запуска: {get_timestamp()}")
    print("═" * 60)
    
    # Проверяем наличие Xray
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ Xray не найден: {XRAY_BIN}")
        logger.error("   Запустите сначала main.py или скачайте Xray вручную")
        return 1
    
    try:
        os.chmod(XRAY_BIN, 0o755)
    except:
        pass
    
    logger.info(f"✅ Xray найден: {XRAY_BIN}")
    
    # Загружаем текущие серверы
    current_servers, original_stats = load_current_servers()
    if not current_servers:
        logger.error("❌ Нет серверов для проверки. Завершение.")
        return 1
    
    # Загружаем резервный пул
    reserve_pool = load_reserve_pool()
    if not reserve_pool:
        logger.warning("⚠️ Резервный пул пуст! Ротация будет невозможна.")
    else:
        logger.info(f"🔄 Резервный пул: {len(reserve_pool)} серверов")
    
    # Выполняем проверку и ротацию
    updated_servers, updated_pool, changes_made = perform_rotation(
        current_servers, 
        reserve_pool,
        original_stats
    )
    
    # Сохраняем изменения если были
    if changes_made:
        logger.info("\n💾 Сохранение изменений...")
        
        # Сохраняем подписку
        if save_updated_subscription(updated_servers):
            logger.info("   ✅ Подписка обновлена")
        else:
            logger.error("   ❌ Ошибка сохранения подписки")
        
        # Сохраняем статистику
        if save_updated_stats(updated_servers, original_stats):
            logger.info("   ✅ Статистика обновлена")
        else:
            logger.error("   ❌ Ошибка сохранения статистики")
        
        # Сохраняем резервный пул
        if save_reserve_pool(updated_pool):
            logger.info(f"   ✅ Резервный пул обновлён: {len(updated_pool)} серверов осталось")
        else:
            logger.error("   ❌ Ошибка сохранения резервного пула")
    else:
        logger.info("\n💤 Изменений нет, файлы не обновлены")
    
    # Итоги
    elapsed = time.time() - start_time
    
    print("\n" + "═" * 60)
    logger.info("🏁 WATCHDOG ЗАВЕРШЁН")
    logger.info(f"   ⏱️ Время работы: {elapsed:.1f} сек")
    logger.info(f"   ✅ Живых: {len([s for s in updated_servers if s in current_servers or s not in [d for d in current_servers if quick_health_check(d)]])}")
    logger.info(f"   🔄 Замен: {len(current_servers) - len([s for s in current_servers if s in updated_servers])}")
    logger.info(f"   📦 Резерв: {len(updated_pool)} серверов")
    
    if changes_made:
        logger.info("   📝 Статус: РОТАЦИЯ ВЫПОЛНЕНА ✅")
    else:
        logger.info("   📝 Статус: ВСЁ РАБОТАЕТ ✅")
    
    print("═" * 60 + "\n")
    
    return 0

# ═══════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Прервано пользователем (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
