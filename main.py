import sys
import requests
import base64
import socket
import time
import concurrent.futures
import re
import os
import json
import uuid
import geoip2.database
import subprocess
import tempfile
import random
import zipfile
import io
import stat
import logging
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logger = logging.getLogger("VPN_Scanner")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler("vpn_scanner.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- НАСТРОЙКИ ---
SOURCES = [
    # Твои источники (Reality + VLESS)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Clash_Reality",
    
    # Крупные мировые базы (много VMess/VLESS + WS + CDN)
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'

MAX_WORKERS = 40        # Увеличено для массового пинга
TCP_TIMEOUT = 1.0       # Быстрый отсев мертвых IP
REAL_TEST_TIMEOUT = 4.0 # Таймаут для проверки соединения Xray
SPEED_TEST_TIMEOUT = 5.0 # Время на замер скорости (сек)
TOTAL_SERVERS_WANTED = 10 # Сколько рабочих серверов нужно на выходе

COUNTRIES_RU = {
    'RU': '🇷🇺 Россия', 'US': '🇺🇸 США', 'DE': '🇩🇪 Германия', 'NL': '🇳🇱 Нидерланды',
    'FI': '🇫🇮 Финляндия', 'UK': '🇬🇧 Великобритания', 'GB': '🇬🇧 Великобритания',
    'FR': '🇫🇷 Франция', 'SE': '🇸🇪 Швеция', 'PL': '🇵🇱 Польша', 'UA': '🇺🇦 Украина',
    'KZ': '🇰🇿 Казахстан', 'BY': '🇧🇾 Беларусь', 'TR': '🇹🇷 Турция', 'JP': '🇯🇵 Япония',
    'KR': '🇰🇷 Южная Корея', 'CN': '🇨🇳 Китай', 'SG': '🇸🇬 Сингапур', 'IT': '🇮🇹 Италия',
    'ES': '🇪🇸 Испания', 'CA': '🇨🇦 Канада', 'AU': '🇦🇺 Австралия', 'CH': '🇨🇭 Швейцария',
    'AE': '🇦🇪 ОАЭ', 'IN': '🇮🇳 Индия', 'BR': '🇧🇷 Бразилия', 'ZA': '🇿🇦 ЮАР',
    'LT': '🇱🇹 Литва', 'MD': '🇲🇩 Молдова', 'EE': '🇪🇪 Эстония', 'CY': '🇨🇾 Кипр', 'LV': '🇱🇻 Латвия',
    'GR': '🇬🇷 Греция'
}

geo_reader = None

def install_xray_core():
    if os.path.exists(XRAY_BIN):
        st = os.stat(XRAY_BIN)
        if not (st.st_mode & stat.S_IEXEC):
            os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
        return

    logger.info("📥 Скачивание Xray core (v1.8.4)...")
    url = "https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip"
    try:
        r = requests.get(url, stream=True, timeout=30)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                if 'xray' in z.namelist():
                    with z.open('xray') as zf, open(XRAY_BIN, 'wb') as f:
                        f.write(zf.read())
            st = os.stat(XRAY_BIN)
            os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
            logger.info("✅ Xray установлен.")
    except Exception as e:
        logger.error(f"❌ Ошибка установки Xray: {e}")

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=20)
            with open(MMDB_FILE, 'wb') as f:
                for chunk in r.iter_content(1024): f.write(chunk)
        except: pass

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: pass

def get_country_code(ip):
    if not geo_reader: return 'XX'
    try: 
        code = geo_reader.country(ip).country.iso_code
        return code if code else 'XX'
    except: return 'XX'

def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    try: return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except:
        try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
        except: return ""

def extract_links(text):
    """Ищет как VLESS, так и VMess ссылки"""
    regex = r"(?i)((?:vless|vmess)://[^\s\"']+)"
    links = re.findall(regex, text)
    
    decoded = safe_base64_decode(text)
    if decoded: links.extend(re.findall(regex, decoded))
        
    for line in text.splitlines():
        dec_line = safe_base64_decode(line)
        if dec_line: links.extend(re.findall(regex, dec_line))
            
    return list(set(links))

def parse_vmess(config_str):
    try:
        b64_str = config_str[8:]
        json_str = safe_base64_decode(b64_str)
        if not json_str: return None
        data = json.loads(json_str)

        tls = data.get('tls', '')
        net = data.get('net', 'tcp')
        
        return {
            "protocol": "vmess",
            "ip": data.get('add', ''),
            "port": int(data.get('port', 443)),
            "uuid": data.get('id', ''),
            "type": net,
            "security": "tls" if tls == 'tls' else "none",
            "flow": "",
            "sni": data.get('sni', data.get('host', '')),
            "pbk": "", "sid": "", "spx": "/",
            "path": data.get('path', '/'),
            "host": data.get('host', ''),
            "fp": data.get('fp', 'chrome'),
            "serviceName": "",
            "original": config_str,
            "country": "XX",
            "real_delay": 9999,
            "speed_mbps": 0.0
        }
    except: return None

def parse_vless(config_str):
    try:
        uuid_val = config_str.split("@")[0][8:]
        part = config_str.split("@")[1].split("?")[0]
        
        if "]" in part:
            host, port = part.rsplit(":", 1)
            host = host.replace("[", "").replace("]", "")
        else: host, port = part.rsplit(":", 1)
            
        query_part = config_str.split("?")[1].split("#")[0] if "?" in config_str else ""
        params = parse_qs(query_part)
        
        conf = {
            "protocol": "vless",
            "ip": host, "port": int(port), "uuid": uuid_val,
            "type": params.get('type', ['tcp'])[0],
            "security": params.get('security', ['none'])[0],
            "flow": params.get('flow', [''])[0],
            "sni": params.get('sni', [''])[0],
            "pbk": params.get('pbk', [''])[0],
            "sid": params.get('sid', [''])[0],
            "spx": params.get('spx', ['/'])[0],
            "path": params.get('path', ['/'])[0],
            "host": params.get('host', [''])[0],
            "fp": params.get('fp', ['chrome'])[0],
            "serviceName": params.get('serviceName', [''])[0],
            "original": config_str,
            "country": "XX", "real_delay": 9999, "speed_mbps": 0.0
        }
        if conf['security'] == 'reality' and not conf['pbk']: return None
        return conf
    except: return None

def generate_xray_config(server, local_port):
    """Универсальный генератор конфигов для Xray (VLESS + VMess)"""
    outbound = {
        "protocol": server['protocol'],
        "settings": {},
        "streamSettings": {
            "network": server['type'],
            "security": server['security']
        }
    }

    if server['protocol'] == 'vless':
        outbound['settings'] = {
            "vnext": [{
                "address": server['ip'], "port": server['port'],
                "users": [{"id": server['uuid'], "encryption": "none", "flow": server['flow']}]
            }]
        }
    else: # vmess
        outbound['settings'] = {
            "vnext": [{
                "address": server['ip'], "port": server['port'],
                "users": [{"id": server['uuid'], "alterId": 0, "security": "auto"}]
            }]
        }

    # Настройки транспорта
    if server['type'] == 'ws':
        ws_set = {"path": server['path']}
        if server['host']: ws_set["headers"] = {"Host": server['host']}
        outbound["streamSettings"]["wsSettings"] = ws_set
    elif server['type'] == 'grpc':
        outbound["streamSettings"]["grpcSettings"] = {"serviceName": server['serviceName']}

    # Настройки защиты
    tls_set = {"serverName": server['sni'], "fingerprint": server['fp']}
    if server['security'] == 'tls':
        outbound["streamSettings"]["tlsSettings"] = tls_set
    elif server['security'] == 'reality':
        reality_set = tls_set.copy()
        reality_set.update({"show": False, "publicKey": server['pbk'], "shortId": server['sid'], "spiderX": server['spx']})
        outbound["streamSettings"]["realitySettings"] = reality_set

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "http"}],
        "outbounds": [outbound]
    }

def check_real_ping(server):
    """ЭТАП 1: Проверка коннекта и пинг через Xray"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((server['ip'], server['port']))
        sock.close()
    except: return None

    local_port = random.randint(15000, 45000)
    config = generate_xray_config(server, local_port)
    
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(config, tmp)
        config_path = tmp.name

    proc = None
    try:
        proc = subprocess.Popen([XRAY_BIN, "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        proxies = {"http": f"http://127.0.0.1:{local_port}", "https": f"http://127.0.0.1:{local_port}"}
        
        start = time.perf_counter()
        resp = requests.get("http://cp.cloudflare.com/", proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        
        if resp.status_code == 204:
            server['real_delay'] = int((time.perf_counter() - start) * 1000)
            code = get_country_code(server['ip'])
            server['country'] = code
            if code != 'XX': return server
    except: pass
    finally:
        if proc: proc.kill()
        if os.path.exists(config_path): os.remove(config_path)
    return None

def measure_speed(server):
    """ЭТАП 2: Жесткий замер скорости. 0 Мбит/с = отбраковка"""
    local_port = random.randint(15000, 45000)
    config = generate_xray_config(server, local_port)
    
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(config, tmp)
        config_path = tmp.name

    proc = None
    server['speed_mbps'] = 0.0

    try:
        proc = subprocess.Popen([XRAY_BIN, "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        proxies = {"http": f"http://127.0.0.1:{local_port}", "https": f"http://127.0.0.1:{local_port}"}
        
        dl_start = time.perf_counter()
        downloaded_bytes = 0
        
        # Скачиваем файл 2.5 МБ для замера
        dl_resp = requests.get("https://speed.cloudflare.com/__down?bytes=2500000", proxies=proxies, timeout=SPEED_TEST_TIMEOUT, stream=True)
        
        if dl_resp.status_code == 200:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                if chunk: downloaded_bytes += len(chunk)
                if time.perf_counter() - dl_start > SPEED_TEST_TIMEOUT: break
                    
            duration = time.perf_counter() - dl_start
            if duration > 0:
                speed = round((downloaded_bytes * 8 / 1_000_000) / duration, 2)
                # Если сервер еле дышит (скачал меньше 100 КБ), считаем его мертвым
                if downloaded_bytes > 100000:
                    server['speed_mbps'] = speed
    except: pass
    finally:
        if proc: proc.kill()
        if os.path.exists(config_path): os.remove(config_path)

    return server

def get_speed_badge(speed):
    if speed >= 3.0: return "⚡⚡ "
    elif speed >= 1.0: return "⚡ "
    return ""

def main():
    logger.info("🚀 START: Гибридный сканер VLESS/VMess (Reality + CDN WebSocket)")
    install_xray_core()
    download_mmdb()
    init_geoip()
    
    all_configs = []
    for url in SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                links = extract_links(resp.text)
                for link in links:
                    parsed = parse_vless(link) if link.lower().startswith("vless") else parse_vmess(link)
                    if parsed: all_configs.append(parsed)
        except: logger.warning(f"⚠️ Ошибка источника {url[:30]}...")

    unique_configs = {f"{c['ip']}:{c['port']}": c for c in all_configs}.values()
    logger.info(f"🔍 Найдено уникальных конфигов: {len(unique_configs)}")

    # ЭТАП 1: Массовый пинг для отбора кандидатов
    logger.info(f"📡 ЭТАП 1: Массовый пинг (отсеиваем оффлайн)...")
    valid_candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for res in executor.map(check_real_ping, unique_configs):
            if res: valid_candidates.append(res)

    valid_candidates.sort(key=lambda x: x['real_delay'])
    
    # Берем ТОП-40 самых быстрых по пингу кандидатов для проверки скорости
    top_candidates = valid_candidates[:40]
    logger.info(f"🏎️ ЭТАП 2: Замер скорости для ТОП-{len(top_candidates)} кандидатов. Выкидываем сервера со скоростью 0...")
    
    working_servers = []
    # Параллельно замеряем скорость (15 потоков оптимально, чтобы не перегрузить сеть)
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        for res in executor.map(measure_speed, top_candidates):
            # Строгое условие: скорость должна быть больше 0.1 Мбит/с
            if res['speed_mbps'] > 0.1:
                working_servers.append(res)
                badge = get_speed_badge(res['speed_mbps'])
                logger.info(f"   [OK] {res['country']} | {res['protocol'].upper()} | Пинг: {res['real_delay']}ms | Скорость: {res['speed_mbps']} Mbps {badge}")

    # Сортируем выжившие сервера (сначала самые скоростные)
    working_servers.sort(key=lambda x: x['speed_mbps'], reverse=True)
    
    # Отбираем нужное количество (например, 10)
    final_selection = working_servers[:TOTAL_SERVERS_WANTED]

    logger.info(f"📊 Итого рабочих серверов (Speed > 0) сохранено: {len(final_selection)}")
    if len(final_selection) < TOTAL_SERVERS_WANTED:
        logger.warning(f"⚠️ Удалось найти только {len(final_selection)} живых серверов из запрошенных {TOTAL_SERVERS_WANTED}.")

    # Генерация файлов подписки
    result_links = []
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header)

    json_stats = {"servers": []}

    for s in final_selection:
        flag = COUNTRIES_RU.get(s['country'], f"🏳️ {s['country']}")
        badge = get_speed_badge(s['speed_mbps'])
        name = f"{badge}{flag} | {s['protocol'].upper()} | {s['real_delay']}ms"
        
        # Заменяем старое имя в ссылке на наше красивое
        orig = s['original']
        base = orig.split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)

        json_stats["servers"].append({
            "name": name, "ip": s['ip'], "protocol": s['protocol'],
            "ping": s['real_delay'], "speed_mbps": s['speed_mbps'], "country": s['country']
        })

    raw_str = "\n".join(result_links)
    b64_str = base64.b64encode(raw_str.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f: f.write(b64_str)
    with open(JSON_FILE, 'w', encoding='utf-8') as f: json.dump(json_stats, f, indent=2, ensure_ascii=False)

    logger.info(f"💾 Подписка обновлена: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
