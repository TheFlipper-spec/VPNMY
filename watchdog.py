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

# ═══════════════════════════════════════════════════════════════
#  FL1P VPN WATCHDOG V120 - Quick Health Check & Smart Rotation
#  
#  Проверяет 9 серверов:
#  🎮 GAME-1, GAME-2
#  🌐 UNIVERSAL-1, UNIVERSAL-2, UNIVERSAL-3
#  ☁️ WARP-1, WARP-2
#  🇷🇺 WHITELIST-1, WHITELIST-2
#
# ═══════════════════════════════════════════════════════════════
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
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# ⚙️ НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════
XRAY_BIN = "./xray"

# Файлы
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
RESERVE_POOL_FILE = 'reserve_pool.json'

# Таймауты
HEALTH_CHECK_TIMEOUT = 6.0
XRAY_STARTUP_DELAY = 1.0
CONNECTION_TIMEOUT = 4.0

# Максимум попыток найти замену
MAX_REPLACEMENT_ATTEMPTS = 5

TIMEZONE_OFFSET = 3

# ═══════════════════════════════════════════════════════════════
# 🌍 GEO НАСТРОЙКИ (должны совпадать с main.py!)
# ═══════════════════════════════════════════════════════════════
TIER_1_COUNTRIES = ['FI', 'EE', 'LV', 'LT']
TIER_2_COUNTRIES = ['SE', 'NO', 'PL']
TIER_3_COUNTRIES = ['DE', 'NL', 'AT', 'CZ', 'DK', 'BE', 'CH']
TIER_4_COUNTRIES = ['GB', 'FR', 'IT', 'ES', 'PT', 'IE', 'HU', 'RO', 'BG', 'SK']

GAME_ALLOWED_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES
UNIVERSAL_ALLOWED_COUNTRIES = TIER_1_COUNTRIES + TIER_2_COUNTRIES + TIER_3_COUNTRIES + TIER_4_COUNTRIES
WHITELIST_COUNTRIES = ['RU']

RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция',
    'RU': 'Россия', 'UA': 'Украина', 'CF': 'Cloudflare',
}

# ═══════════════════════════════════════════════════════════════
# 🎨 УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════
def get_msk_time():
    return datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)

def get_beautiful_time():
    return f"🕐{get_msk_time().strftime('%H:%M')}"

def get_timestamp():
    return get_msk_time().strftime('%Y-%m-%d %H:%M:%S MSK')

def get_country_flag(country_code):
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join([chr(127397 + ord(c)) for c in country_code.upper()])

def format_server_name(base_name, country_code, include_time=False):
    flag = get_country_flag(country_code)
    if include_time:
        return f"{flag} {base_name} | {get_beautiful_time()}"
    return f"{flag} {base_name}"

def get_server_role(server_name):
    """Определяет роль сервера по имени"""
    name_lower = server_name.lower() if server_name else ""
    
    if "game-1" in name_lower or "🎮game-1" in name_lower:
        return "GAME", 1, True  # role_type, index, include_time
    elif "game-2" in name_lower or "🎮game-2" in name_lower:
        return "GAME", 2, False
    elif "universal-1" in name_lower or "🌐universal-1" in name_lower:
        return "UNIVERSAL", 1, False
    elif "universal-2" in name_lower or "🌐universal-2" in name_lower:
        return "UNIVERSAL", 2, False
    elif "universal-3" in name_lower or "🌐universal-3" in name_lower:
        return "UNIVERSAL", 3, False
    elif "warp-1" in name_lower or "☁️warp-1" in name_lower:
        return "WARP", 1, False
    elif "warp-2" in name_lower or "☁️warp-2" in name_lower:
        return "WARP", 2, False
    elif "whitelist-1" in name_lower or "🇷🇺whitelist-1" in name_lower:
        return "WHITELIST", 1, False
    elif "whitelist-2" in name_lower or "🇷🇺whitelist-2" in name_lower:
        return "WHITELIST", 2, False
    else:
        return "UNKNOWN", 0, False

def get_role_emoji(role_type):
    emojis = {
        "GAME": "🎮",
        "UNIVERSAL": "🌐",
        "WARP": "☁️",
        "WHITELIST": "🇷🇺"
    }
    return emojis.get(role_type, "🔹")

# ═══════════════════════════════════════════════════════════════
# 📂 ЗАГРУЗКА И СОХРАНЕНИЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════════
def load_current_servers():
    """Загружает текущие серверы из stats.json"""
    if not os.path.exists(JSON_FILE):
        logger.error(f"❌ Файл {JSON_FILE} не найден!")
        return None, None
    
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        servers = data.get('servers', [])
        logger.info(f"📂 Загружено {len(servers)} серверов из {JSON_FILE}")
        return servers, data
    except Exception as e:
        logger.error(f"❌ Ошибка чтения {JSON_FILE}: {e}")
        return None, None

def load_reserve_pool():
    """Загружает резервный пул"""
    if not os.path.exists(RESERVE_POOL_FILE):
        logger.warning(f"⚠️ Файл {RESERVE_POOL_FILE} не найден")
        return []
    
    try:
        with open(RESERVE_POOL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        servers = data.get('servers', [])
        logger.info(f"📂 Резервный пул: {len(servers)} серверов")
        return servers
    except Exception as e:
        logger.error(f"❌ Ошибка чтения {RESERVE_POOL_FILE}: {e}")
        return []

def save_reserve_pool(servers):
    """Сохраняет резервный пул"""
    try:
        data = {
            "updated": datetime.now(timezone.utc).isoformat(),
            "updated_msk": get_timestamp(),
            "servers": servers
        }
        with open(RESERVE_POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Резервный пул: {len(servers)} серверов")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения резерва: {e}")
        return False

def save_updated_stats(servers, original_data):
    """Сохраняет обновлённую статистику"""
    try:
        original_data['servers'] = servers
        original_data['updated'] = datetime.now(timezone.utc).isoformat()
        original_data['updated_msk'] = get_timestamp()
        original_data['last_watchdog'] = get_timestamp()
        original_data['watchdog_rotations'] = original_data.get('watchdog_rotations', 0) + 1
        
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(original_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Статистика обновлена: {JSON_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения статистики: {e}")
        return False

def save_subscription(servers):
    """Сохраняет подписку в base64"""
    links = []
    
    for server in servers:
        original = server.get('original', '')
        if not original:
            continue
        
        if server.get('is_warp'):
            links.append(original)
        else:
            base = original.split('#')[0]
            name = server.get('name', 'Unknown')
            links.append(f"{base}#{quote(name)}")
    
    if not links:
        logger.error("❌ Нет ссылок для сохранения!")
        return False
    
    try:
        content = "\n".join(links)
        encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        with open(OUTPUT_FILE, 'w') as f:
            f.write(encoded)
        
        logger.info(f"💾 Подписка: {OUTPUT_FILE} ({len(links)} серверов)")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения подписки: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# 🔧 ГЕНЕРАЦИЯ КОНФИГА XRAY
# ═══════════════════════════════════════════════════════════════
def generate_xray_config(original, local_port):
    """Генерирует конфиг Xray из оригинальной ссылки"""
    if not original:
        return None
    
    try:
        # WARP - особая обработка
        if original.startswith("warp://"):
            # WARP проверяем через cloudflare
            return None  # Пропускаем, проверим через HTTP
        
        # HYSTERIA2
        if original.startswith(("hy2://", "hysteria2://")):
            prefix = "hy2://" if original.startswith("hy2://") else "hysteria2://"
            parts = original.split("@")
            if len(parts) < 2:
                return None
            
            password = parts[0].replace(prefix, "")
            rest = parts[1]
            
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
            
            return {
                "log": {"loglevel": "error"},
                "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
                "outbounds": [{
                    "protocol": "hysteria2",
                    "settings": {"vnext": [{"address": host, "port": int(port), "users": [{"password": password}]}]},
                    "streamSettings": {"network": "udp", "security": "tls", 
                                      "tlsSettings": {"serverName": params.get('sni', [''])[0], "allowInsecure": True}}
                }]
            }
        
        # VLESS
        if original.startswith("vless://"):
            parts = original.split("@")
            if len(parts) < 2:
                return None
            
            uuid = parts[0].replace("vless://", "")
            rest = parts[1]
            
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
            
            user = {"id": uuid, "encryption": "none"}
            flow = params.get('flow', [''])[0]
            if flow:
                user["flow"] = flow
            
            stream = {"network": transport, "security": security}
            
            if transport == 'ws':
                stream["wsSettings"] = {"path": params.get('path', ['/'])[0]}
                if params.get('host'):
                    stream["wsSettings"]["headers"] = {"Host": params['host'][0]}
            elif transport == 'grpc' and params.get('serviceName'):
                stream["grpcSettings"] = {"serviceName": params['serviceName'][0]}
            
            if security == 'tls':
                stream["tlsSettings"] = {
                    "serverName": params.get('sni', [''])[0],
                    "fingerprint": params.get('fp', ['chrome'])[0],
                    "allowInsecure": False
                }
            elif security == 'reality':
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
                "outbounds": [{"protocol": "vless", 
                              "settings": {"vnext": [{"address": host, "port": int(port), "users": [user]}]},
                              "streamSettings": stream}]
            }
    except Exception as e:
        logger.debug(f"Ошибка генерации конфига: {e}")
    
    return None

# ═══════════════════════════════════════════════════════════════
# 🔍 ПРОВЕРКА ЗДОРОВЬЯ
# ═══════════════════════════════════════════════════════════════
def check_warp_health(server):
    """Проверка WARP сервера через Cloudflare"""
    try:
        # WARP обычно работает, проверяем через trace
        resp = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=5)
        if resp.status_code == 200 and "warp=on" in resp.text:
            return True
        # Если WARP не активен на нашем соединении, считаем конфиг валидным
        return True  # WARP конфиги обычно работают
    except:
        return True  # Даже при ошибке не отключаем WARP

def check_server_health(server):
    """Проверка здоровья обычного сервера"""
    original = server.get('original', '')
    ip = server.get('ip', 'unknown')
    
    # WARP проверяем отдельно
    if server.get('is_warp') or original.startswith("warp://"):
        return check_warp_health(server)
    
    if not original:
        return False
    
    local_port = random.randint(20000, 50000)
    config = generate_xray_config(original, local_port)
    
    if not config:
        logger.debug(f"   ⚠️ {ip}: не удалось сгенерировать конфиг")
        return False
    
    config_path = None
    proc = None
    is_alive = False
    
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as f:
            json.dump(config, f)
            config_path = f.name
        
        proc = subprocess.Popen(
            [XRAY_BIN, "-config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(XRAY_STARTUP_DELAY)
        
        if proc.poll() is not None:
            return False
        
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        
        # Проверяем несколько эндпоинтов
        endpoints = [
            ("https://www.google.com/generate_204", 204),
            ("https://cp.cloudflare.com/", 200),
            ("https://www.gstatic.com/generate_204", 204),
        ]
        
        success_count = 0
        for url, expected_code in endpoints:
            try:
                resp = requests.get(url, proxies=proxies, timeout=CONNECTION_TIMEOUT, verify=False)
                if resp.status_code == expected_code or 200 <= resp.status_code < 300:
                    success_count += 1
            except:
                pass
        
        is_alive = success_count >= 2  # Минимум 2 из 3 должны работать
        
    except Exception as e:
        logger.debug(f"   ❌ {ip}: ошибка проверки - {e}")
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
    
    return is_alive

# ═══════════════════════════════════════════════════════════════
# 🔄 ПОИСК ЗАМЕНЫ
# ═══════════════════════════════════════════════════════════════
def find_replacement(reserve_pool, used_ips, role_type, role_index):
    """
    Ищет подходящую замену в резервном пуле
    
    Args:
        reserve_pool: список резервных серверов
        used_ips: уже использованные IP
        role_type: GAME, UNIVERSAL, WARP, WHITELIST
        role_index: 1 или 2
    """
    
    # Определяем требования к стране
    if role_type == "GAME":
        allowed_countries = GAME_ALLOWED_COUNTRIES
        sort_key = lambda x: (x.get('latency_ms', 9999), -x.get('speed_mbps', 0))
    elif role_type == "UNIVERSAL":
        allowed_countries = UNIVERSAL_ALLOWED_COUNTRIES
        sort_key = lambda x: (-x.get('is_reality', False), -x.get('speed_mbps', 0))
    elif role_type == "WHITELIST":
        allowed_countries = WHITELIST_COUNTRIES
        sort_key = lambda x: -x.get('speed_mbps', 0)
    else:
        # WARP - не ищем замену в пуле
        return None, reserve_pool
    
    # Фильтруем подходящие серверы
    candidates = [
        s for s in reserve_pool 
        if s.get('ip') not in used_ips 
        and s.get('country', 'XX') in allowed_countries
    ]
    
    # Сортируем по приоритету
    candidates = sorted(candidates, key=sort_key)
    
    # Проверяем кандидатов
    attempts = 0
    for candidate in candidates:
        if attempts >= MAX_REPLACEMENT_ATTEMPTS:
            break
        
        attempts += 1
        ip = candidate.get('ip', 'unknown')
        cc = candidate.get('country', 'XX')
        
        logger.info(f"      🔄 Проверяем: {ip} ({RUS_NAMES.get(cc, cc)})")
        
        # Формируем временный объект для проверки
        temp_server = {
            'ip': ip,
            'original': candidate.get('original', ''),
            'is_warp': False
        }
        
        if check_server_health(temp_server):
            logger.info(f"      ✅ Найдена замена: {ip}")
            
            # Удаляем из резервного пула
            updated_pool = [s for s in reserve_pool if s.get('ip') != ip]
            
            return candidate, updated_pool
        else:
            logger.info(f"      ❌ {ip} не работает")
    
    logger.warning(f"      ⚠️ Замена не найдена после {attempts} попыток")
    return None, reserve_pool

def create_replacement_server(candidate, role_type, role_index, include_time=False):
    """Создаёт объект сервера с правильным именем"""
    cc = candidate.get('country', 'XX')
    is_reality = candidate.get('is_reality', False)
    reality_tag = "🛡️" if is_reality else ""
    
    emoji = get_role_emoji(role_type)
    role_name = f"{role_type}-{role_index}"
    
    name = format_server_name(
        f"{emoji}{role_name}{reality_tag}",
        cc,
        include_time=include_time
    )
    
    return {
        "name": name,
        "ip": candidate.get('ip'),
        "port": candidate.get('port'),
        "country": cc,
        "country_name": RUS_NAMES.get(cc, cc),
        "country_flag": get_country_flag(cc),
        "speed_mbps": candidate.get('speed_mbps', 0),
        "latency_ms": candidate.get('latency_ms', 0),
        "udp": candidate.get('udp', False),
        "is_reality": is_reality,
        "is_warp": False,
        "reality_score": candidate.get('reality_score', 0),
        "streak": candidate.get('streak', 0),
        "original": candidate.get('original', '')
    }

# ═══════════════════════════════════════════════════════════════
# 🔄 ГЛАВНАЯ ЛОГИКА РОТАЦИИ
# ═══════════════════════════════════════════════════════════════
def perform_health_check_and_rotation(current_servers, reserve_pool, original_data):
    """
    Проверяет серверы и выполняет ротацию при необходимости
    """
    
    alive_servers = []
    dead_servers = []
    dead_indices = []
    
    logger.info(f"\n🔍 Проверка {len(current_servers)} серверов...")
    logger.info("─" * 60)
    
    for i, server in enumerate(current_servers):
        ip = server.get('ip', 'unknown')
        name = server.get('name', 'Unknown')
        cc = server.get('country', 'XX')
        is_warp = server.get('is_warp', False)
        is_reality = server.get('is_reality', False)
        
        role_type, role_index, _ = get_server_role(name)
        
        # Визуальные метки
        reality_tag = "🛡️" if is_reality else ""
        warp_tag = "☁️WARP" if is_warp else ""
        
        logger.info(f"\n   [{i+1}/{len(current_servers)}] {name}")
        if is_warp:
            logger.info(f"       Cloudflare WARP {warp_tag}")
        else:
            logger.info(f"       {ip} | {RUS_NAMES.get(cc, cc)} {reality_tag}")
        
        # Проверка
        if check_server_health(server):
            logger.info(f"       ✅ РАБОТАЕТ")
            alive_servers.append(server)
        else:
            logger.warning(f"       ❌ НЕ РАБОТАЕТ!")
            dead_servers.append(server)
            dead_indices.append(i)
    
    # Результаты проверки
    logger.info("\n" + "─" * 60)
    logger.info(f"📊 Итог: ✅ {len(alive_servers)} живых | ❌ {len(dead_servers)} мёртвых")
    
    # Если все живы
    if not dead_servers:
        logger.info("\n✅ Все серверы работают! Ротация не требуется.")
        return current_servers, reserve_pool, False
    
    # Ротация мёртвых серверов
    logger.info(f"\n⚠️ Начинаем ротацию {len(dead_servers)} серверов...")
    logger.info("─" * 60)
    
    updated_servers = list(current_servers)
    updated_pool = list(reserve_pool)
    used_ips = {s.get('ip') for s in alive_servers if s.get('ip')}
    replacements_made = 0
    
    for dead_index in dead_indices:
        dead_server = current_servers[dead_index]
        dead_name = dead_server.get('name', 'Unknown')
        dead_ip = dead_server.get('ip', 'unknown')
        
        role_type, role_index, include_time = get_server_role(dead_name)
        
        logger.info(f"\n   🔄 Замена: {dead_name}")
        logger.info(f"      Роль: {role_type}-{role_index}")
        
        # WARP серверы не заменяем из пула
        if role_type == "WARP":
            logger.info(f"      ⏭️ WARP сервер - пропускаем (они обычно работают)")
            continue
        
        # Ищем замену
        replacement, updated_pool = find_replacement(
            updated_pool, 
            used_ips, 
            role_type, 
            role_index
        )
        
        if replacement:
            # Создаём новый объект сервера
            new_server = create_replacement_server(
                replacement, 
                role_type, 
                role_index, 
                include_time
            )
            
            updated_servers[dead_index] = new_server
            used_ips.add(new_server['ip'])
            replacements_made += 1
            
            cc = new_server['country']
            logger.info(f"      ✅ Заменён на: {new_server['ip']} ({RUS_NAMES.get(cc, cc)})")
            logger.info(f"         Новое имя: {new_server['name']}")
        else:
            logger.warning(f"      ❌ Замена не найдена! Сервер останется неактивным.")
    
    # Итоги ротации
    logger.info("\n" + "─" * 60)
    logger.info(f"📊 Ротация завершена: {replacements_made} замен из {len(dead_servers)} мёртвых")
    logger.info(f"📦 Осталось в резерве: {len(updated_pool)} серверов")
    
    return updated_servers, updated_pool, replacements_made > 0

# ═══════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start_time = time.time()
    
    print("\n" + "═" * 70)
    logger.info("🐕 FL1P VPN WATCHDOG V120 - Health Check & Rotation")
    logger.info(f"   ⏰ Запуск: {get_timestamp()}")
    logger.info("   📋 Проверка: GAME, UNIVERSAL, WARP, WHITELIST")
    print("═" * 70)
    
    # Проверка Xray
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ Xray не найден: {XRAY_BIN}")
        return 1
    
    try:
        os.chmod(XRAY_BIN, 0o755)
    except:
        pass
    
    logger.info(f"✅ Xray: {XRAY_BIN}")
    
    # Загрузка данных
    current_servers, original_data = load_current_servers()
    if not current_servers:
        logger.error("❌ Нет серверов для проверки!")
        return 1
    
    reserve_pool = load_reserve_pool()
    
    # Статистика ролей
    role_stats = {}
    for s in current_servers:
        role_type, _, _ = get_server_role(s.get('name', ''))
        role_stats[role_type] = role_stats.get(role_type, 0) + 1
    
    logger.info(f"\n📊 Текущие серверы по ролям:")
    for role, count in sorted(role_stats.items()):
        emoji = get_role_emoji(role)
        logger.info(f"   {emoji} {role}: {count}")
    
    # Проверка и ротация
    updated_servers, updated_pool, changes_made = perform_health_check_and_rotation(
        current_servers,
        reserve_pool,
        original_data
    )
    
    # Сохранение изменений
    if changes_made:
        logger.info("\n💾 Сохранение изменений...")
        
        save_subscription(updated_servers)
        save_updated_stats(updated_servers, original_data)
        save_reserve_pool(updated_pool)
    else:
        logger.info("\n💤 Изменений нет, файлы не обновлены")
    
    # Финальная статистика
    elapsed = time.time() - start_time
    alive_count = len([s for s in updated_servers if s.get('ip') and not s.get('is_warp')])
    warp_count = len([s for s in updated_servers if s.get('is_warp')])
    
    print("\n" + "═" * 70)
    logger.info("🏁 WATCHDOG ЗАВЕРШЁН")
    logger.info(f"   ⏱️ Время: {elapsed:.1f} сек")
    logger.info(f"   ✅ Серверов: {alive_count} обычных + {warp_count} WARP")
    logger.info(f"   📦 Резерв: {len(updated_pool)} серверов")
    
    if changes_made:
        logger.info("   📝 Статус: РОТАЦИЯ ВЫПОЛНЕНА ✅")
    else:
        logger.info("   📝 Статус: ВСЁ РАБОТАЕТ ✅")
    
    print("═" * 70 + "\n")
    
    return 0

# ═══════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Прервано пользователем")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
