import sys
import requests
import base64
import socket
import time
import concurrent.futures
import re
import os
import json
import subprocess
import tempfile
import stat
import logging
import urllib3
from datetime import datetime
from urllib.parse import quote, parse_qs

# Отключаем предупреждения о нестрогих SSL-сертификатах для подписок по IP
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logger = logging.getLogger("V1A_Scanner")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# --- НАСТРОЙКИ ---
GITHUB_TOKEN = os.getenv("TOKEN", "") # Изменено на поиск переменной TOKEN
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://gbr.mydan.online/configs",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt"
]

XRAY_BIN = "./xray"
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'
HISTORY_FILE = 'stats_history.json'
MAX_WORKERS = 40
TCP_TIMEOUT = 1.0
REAL_TEST_TIMEOUT = 5.0
SPEED_TEST_TIMEOUT = 6.0
TOTAL_SERVERS_WANTED = 10
SPEED_HARD_LIMIT = 1.5

# Ссылки на подписки для несгораемых нод
HARDCODED_NODES = [
    {"url": "https://212.22.82.138:2096/sub/2u6r7m9fvgv0joz9", "name": "💎 🇷🇺 V1A / БЕЛЫЕ СПИСКИ"},
    {"url": "https://212.22.82.138:2096/sub/ifg3v5yrri9pqkzg", "name": "💎 🇫🇮  V1A / Финляндия"},
    {"url": "https://195.226.92.208:2096/sub/4v7pgpryd3w7de6o", "name": "💎 🇫🇮  V2A / Финляндия"},
    {"url": "https://195.226.92.208:2096/sub/x9dvfd72pv7z2art", "name": "💎 🇪🇪  V2A / Эстония"}
]

COUNTRIES_RU = {
    'RU': '🇷🇺 Россия', 'US': '🇺🇸 США', 'DE': '🇩🇪 Германия', 'NL': '🇳🇱 Нидерланды',
    'FI': '🇫🇮 Финляндия', 'UK': '🇬🇧 Великобритания', 'GB': '🇬🇧 Великобритания',
    'FR': '🇫🇷 Франция', 'SE': '🇸🇪 Швеция', 'PL': '🇵🇱 Польша', 'UA': '🇺🇦 Украина',
    'KZ': '🇰🇿 Казахстан', 'BY': '🇧🇾 Беларусь', 'TR': '🇹🇷 Турция', 'JP': '🇯🇵 Япония',
    'KR': '🇰🇷 Южная Корея', 'CN': '🇨🇳 Китай', 'SG': '🇸🇬 Сингапур', 'IT': '🇮🇹 Италия',
    'ES': '🇪🇸 Испания', 'CA': '🇨🇦 Канада', 'AU': '🇦🇺 Австралия', 'CH': '🇨🇭 Швейцария',
    'AE': '🇦🇪 ОАЭ', 'IN': '🇮🇳 Индия', 'BR': '🇧🇷 Бразилия', 'ZA': '🇿🇦 ЮАР',
    'LT': '🇱🇹 Литва', 'MD': '🇲🇩 Молдова', 'EE': '🇪🇪 Эстония', 'CY': '🇨🇾 Кипр', 'LV': '🇱🇻 Латвия',
    'GR': '🇬🇷 Греция', 'HU': '🇭🇺 Венгрия', 'CZ': '🇨🇿 Чехия', 'NO': '🇳🇴 Норвегия',
    'AT': '🇦🇹 Австрия'
}

CIS_COUNTRIES = ['RU', 'BY', 'KZ']

# --- УТИЛИТЫ ---
def install_xray_core():
    import zipfile, io
    if os.path.exists(XRAY_BIN):
        st = os.stat(XRAY_BIN)
        if not (st.st_mode & stat.S_IEXEC):
            os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
        return
    logger.info("📥 Xray core не найден. Скачивание (v1.8.4)...")
    url = "https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip"
    try:
        r = requests.get(url, stream=True, timeout=30)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                if 'xray' in z.namelist():
                    with z.open('xray') as zf, open(XRAY_BIN, 'wb') as f:
                        f.write(zf.read())
                else:
                    logger.error("❌ В архиве нет файла xray!")
                    return
            st = os.stat(XRAY_BIN)
            os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
            logger.info("✅ Xray установлен успешно.")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка установки Xray: {e}")

def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    try:
        return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except:
        try:
            return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
        except:
            return ""

def extract_links(text):
    regex = r"(?i)((?:vless|vmess|trojan)://[^\s\"']+)"
    links = re.findall(regex, text)
    decoded = safe_base64_decode(text)
    if decoded:
        links.extend(re.findall(regex, decoded))
    for line in text.splitlines():
        dec_line = safe_base64_decode(line)
        if dec_line:
            links.extend(re.findall(regex, dec_line))
    return list(set(links))

def get_free_port():
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]

# --- ИСТОРИЯ И СКОРИНГ (Этап 2 и 5) ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)

def calculate_quality_score(server, history_data):
    node_id = f"{server['ip']}:{server['port']}"
    node_hist = history_data.get(node_id, {"streak": 0, "failures": 0})
    
    score = 0
    # 1. Скорость (40%)
    speed = min(server.get('speed_mbps', 0) / 10.0, 1.0) # Потолок 10 Mbps
    score += speed * 40
    
    # 2. История (30%) - Gold Node
    streak = node_hist.get("streak", 0)
    score += min(streak * 10, 30)
    score -= min(node_hist.get("failures", 0) * 5, 20) # Штраф за падения
    
    # 3. Протокол (20%)
    if server['protocol'] in ['vless', 'trojan'] and server.get('security') == 'reality':
        score += 20
    elif server['protocol'] == 'trojan' or server['protocol'] == 'vless':
        score += 15
    else: # vmess / ws
        score += 5
        
    # 4. Пинг (10%)
    ping = server.get('real_delay', 1000)
    ping_penalty = min(ping / 1000.0, 1.0) * 10
    score -= ping_penalty
    
    return max(0, round(score, 1))

# --- ПАРСЕРЫ ---
def parse_vmess(config_str):
    try:
        b64_str = config_str[8:]
        json_str = safe_base64_decode(b64_str)
        if not json_str: return None
        data = json.loads(json_str)
        net_type = data.get('net', 'tcp')
        if net_type == 'ws': return None # Игнорируем WS
        tls = data.get('tls', '')
        return {
            "protocol": "vmess", "ip": data.get('add', ''), "port": int(data.get('port', 443)),
            "uuid": data.get('id', ''), "type": net_type,
            "security": "tls" if tls == 'tls' else "none", "flow": "",
            "sni": data.get('sni', data.get('host', '')), "pbk": "", "sid": "", "spx": "/",
            "path": data.get('path', '/'), "host": data.get('host', ''), "fp": data.get('fp', 'chrome'),
            "serviceName": "", "original": config_str, "country": "XX", "real_delay": 9999, "speed_mbps": 0.0
        }
    except: return None

def parse_vless(config_str):
    try:
        config_str = config_str.strip()
        uuid_val = config_str.split("@")[0][8:]
        part = config_str.split("@")[1].split("?")[0]
        host, port = part.rsplit(":", 1) if "]" not in part else (part.rsplit(":", 1)[0].replace("[", "").replace("]", ""), part.rsplit(":", 1)[1])
        params = parse_qs(config_str.split("?")[1].split("#")[0]) if "?" in config_str else {}
        conf = {
            "protocol": "vless", "ip": host, "port": int(port), "uuid": uuid_val,
            "type": params.get('type', ['tcp'])[0], "security": params.get('security', ['none'])[0],
            "flow": params.get('flow', [''])[0], "sni": params.get('sni', [''])[0],
            "pbk": params.get('pbk', [''])[0], "sid": params.get('sid', [''])[0],
            "spx": params.get('spx', ['/'])[0], "path": params.get('path', ['/'])[0],
            "host": params.get('host', [''])[0], "fp": params.get('fp', ['chrome'])[0],
            "serviceName": params.get('serviceName', [''])[0], "original": config_str,
            "country": "XX", "real_delay": 9999, "speed_mbps": 0.0
        }
        if conf['type'] == 'ws': return None # Игнорируем WS
        if conf['security'] == 'reality' and not conf['pbk']: return None
        return conf
    except: return None

def parse_trojan(config_str):
    try:
        config_str = config_str.strip()
        password = config_str.split("@")[0][9:]
        part = config_str.split("@")[1].split("?")[0]
        host, port = part.rsplit(":", 1)
        params = parse_qs(config_str.split("?")[1].split("#")[0]) if "?" in config_str else {}
        conf = {
            "protocol": "trojan", "ip": host, "port": int(port), "uuid": password,
            "type": params.get('type', ['tcp'])[0], "security": params.get('security', ['none'])[0],
            "flow": "", "sni": params.get('sni', [''])[0], "pbk": "", "sid": "", "spx": "/",
            "path": params.get('path', ['/'])[0], "host": params.get('host', [''])[0],
            "fp": params.get('fp', ['chrome'])[0], "serviceName": params.get('serviceName', [''])[0],
            "original": config_str, "country": "XX", "real_delay": 9999, "speed_mbps": 0.0
        }
        if conf['type'] == 'ws': return None # Игнорируем WS
        return conf
    except: return None

# --- GITHUB LIVE SEARCH (Этап 1) ---
def search_github_configs():
    logger.info("🔍 Ищем свежие конфиги на GitHub (Live Search)...")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN: headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    links = []
    # Ищем свежие репозитории/файлы по ключам
    queries = ["vless reality", "trojan proxy"]
    for q in queries:
        try:
            # Ищем репозитории, обновленные недавно
            url = f"https://api.github.com/search/repositories?q={quote(q)}+pushed:>2026-02-25&sort=updated"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('items', [])[:3]: # Берем топ 3 свежих репо
                    # Это упрощенный парсинг readme, в идеале нужно дергать /contents/
                    readme_url = f"https://raw.githubusercontent.com/{item['full_name']}/{item['default_branch']}/README.md"
                    rr = requests.get(readme_url, timeout=5)
                    if rr.status_code == 200:
                        links.extend(extract_links(rr.text))
        except Exception as e:
            logger.warning(f"⚠️ Ошибка GitHub API: {e}")
    return list(set(links))

# --- XRAY CONFIG GENERATOR ---
def generate_xray_config(server, local_port):
    outbound = {
        "protocol": server['protocol'], "settings": {},
        "streamSettings": {"network": server['type'], "security": server['security']}
    }
    
    if server['protocol'] == 'vless':
        outbound['settings'] = {"vnext": [{"address": server['ip'], "port": server['port'], "users": [{"id": server['uuid'], "encryption": "none", "flow": server['flow']}]}]}
    elif server['protocol'] == 'trojan':
        outbound['settings'] = {"servers": [{"address": server['ip'], "port": server['port'], "password": server['uuid']}]}
    else: # vmess
        outbound['settings'] = {"vnext": [{"address": server['ip'], "port": server['port'], "users": [{"id": server['uuid'], "alterId": 0, "security": "auto"}]}]}

    if server['type'] == 'ws':
        ws_set = {"path": server['path']}
        if server['host']: ws_set["headers"] = {"Host": server['host']}
        outbound["streamSettings"]["wsSettings"] = ws_set
    elif server['type'] == 'grpc':
        outbound["streamSettings"]["grpcSettings"] = {"serviceName": server['serviceName']}
        
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

# --- ТЕСТИРОВАНИЕ (Этап 4) ---
def deep_verify(server):
    """TCP Пинг -> CF Геолокация -> YouTube 204 Test -> Speed Test"""
    
    # 1. TCP Check
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((server['ip'], server['port']))
        sock.close()
    except: return None

    local_port = get_free_port()
    config = generate_xray_config(server, local_port)
    
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(config, tmp)
        config_path = tmp.name

    proc = None
    real_country = 'XX'
    latency = None
    speed_mbps = 0.0
    youtube_ok = False

    try:
        proc = subprocess.Popen([XRAY_BIN, "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.7)
        proxies = {"http": f"http://127.0.0.1:{local_port}", "https": f"http://127.0.0.1:{local_port}"}

        # 2. CF Trace & Пинг
        start = time.perf_counter()
        resp = requests.get("https://cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        if resp.status_code == 200:
            latency = int((time.perf_counter() - start) * 1000)
            match = re.search(r'loc=([A-Z]{2})', resp.text)
            if match: real_country = match.group(1)
        else:
            return None # Провалил базовую маршрутизацию
            
        # 3. YouTube 204 Test (Хардкор)
        yt_resp = requests.get("https://www.youtube.com/generate_204", proxies=proxies, timeout=3.0)
        if yt_resp.status_code == 204:
            youtube_ok = True
        else:
            return None # Не тянет трубы Google

        # 4. Speed Test
        dl_start = time.perf_counter()
        downloaded_bytes = 0
        dl_resp = requests.get(
            "https://speed.cloudflare.com/__down?bytes=5000000", # 5MB тест
            proxies=proxies, timeout=(2.0, SPEED_TEST_TIMEOUT), stream=True
        )
        if dl_resp.status_code == 200:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                if chunk: downloaded_bytes += len(chunk)
                if time.perf_counter() - dl_start > SPEED_TEST_TIMEOUT: break
            duration = time.perf_counter() - dl_start
            if duration > 0:
                speed_mbps = round((downloaded_bytes * 8 / 1_000_000) / duration, 2)
                
    except Exception:
        pass
    finally:
        if proc:
            proc.terminate()
            try: proc.wait(timeout=0.5)
            except: proc.kill()
        if os.path.exists(config_path): os.remove(config_path)

    if latency and youtube_ok:
        server['real_delay'] = latency
        server['country'] = real_country
        server['speed_mbps'] = speed_mbps
        return server
    return None

def get_speed_badge(speed_mbps):
    if speed_mbps >= 10.0: return "🚀 "
    elif speed_mbps >= 5.0: return "⚡⚡ "
    elif speed_mbps >= 1.5: return "⚡ "
    return "🐢 "

# --- MAIN ---
def main():
    logger.info(f"🚀 START: V1A Smart Selector (Target: {TOTAL_SERVERS_WANTED})")
    install_xray_core()
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ ОШИБКА: Не удалось найти {XRAY_BIN}")
        return

    history_data = load_history()
    all_configs = []

    # Сбор статики + GitHub Live Search
    logger.info("🌐 Загрузка источников (VLESS + VMess + Trojan)...")
    for url in SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                links = extract_links(resp.text)
                for link in links:
                    if link.lower().startswith("vless"): parsed = parse_vless(link)
                    elif link.lower().startswith("trojan"): parsed = parse_trojan(link)
                    else: parsed = parse_vmess(link)
                    if parsed: all_configs.append(parsed)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка источника {url[:30]}...: {e}")

    github_links = search_github_configs()
    for link in github_links:
        if link.lower().startswith("vless"): parsed = parse_vless(link)
        elif link.lower().startswith("trojan"): parsed = parse_trojan(link)
        else: parsed = parse_vmess(link)
        if parsed: all_configs.append(parsed)

    unique_configs = {f"{c['ip']}:{c['port']}": c for c in all_configs}.values()
    logger.info(f"🔍 Уникальных конфигов собрано: {len(unique_configs)}")

    # ЭТАП 4: Хардкор-тестирование
    tested_servers = []
    logger.info(f"⚡ Запуск Deep Verification. Workers: {MAX_WORKERS}...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(deep_verify, s) for s in unique_configs]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                tested_servers.append(res)
                logger.info(f"   [{res['country']}] {res['protocol'].upper()} | Пинг: {res['real_delay']}ms | Скорость: {res['speed_mbps']} Mbps")

    # ЭТАП 3: Двойной пул
    pool_global = []
    pool_ru_cis = []
    
    for s in tested_servers:
        node_id = f"{s['ip']}:{s['port']}"
        s['score'] = calculate_quality_score(s, history_data)
        
        # Обновляем историю
        if node_id not in history_data:
            history_data[node_id] = {"streak": 0, "failures": 0, "last_seen": str(datetime.now().date())}
        
        if s['speed_mbps'] >= SPEED_HARD_LIMIT or s['country'] in CIS_COUNTRIES:
            history_data[node_id]["streak"] += 1
            history_data[node_id]["failures"] = max(0, history_data[node_id]["failures"] - 1)
        else:
            history_data[node_id]["failures"] += 1
            history_data[node_id]["streak"] = 0

        # Разносим по пулам
        if s['country'] in CIS_COUNTRIES:
            pool_ru_cis.append(s)
        else:
            if s['speed_mbps'] >= SPEED_HARD_LIMIT: # Жесткий отбор для глобала
                pool_global.append(s)

    save_history(history_data)

    # ЭТАП 6: Сборка элитного отряда
    pool_ru_cis.sort(key=lambda x: x['score'], reverse=True)
    pool_global.sort(key=lambda x: x['score'], reverse=True)

    final_selection = []
    
    # №5-10: Топ Global (только иностранные серверы для V1A)
    needed_global = TOTAL_SERVERS_WANTED - len(HARDCODED_NODES) # Вычитаем хардкод ноды
    final_selection.extend(pool_global[:needed_global])

    logger.info(f"📊 Итого собрано: {len(HARDCODED_NODES)}(Хардкода) + {len(final_selection)} живых узлов.")

    # Формирование файла
    result_links = []
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header_link)
    
    # Получение несгораемых нод по ссылкам подписок
    for node_info in HARDCODED_NODES:
        try:
            # verify=False нужен, так как IP-адреса часто используют самоподписанные сертификаты
            resp = requests.get(node_info["url"], timeout=10, verify=False)
            if resp.status_code == 200:
                links = extract_links(resp.text)
                if links:
                    # Берем первую ссылку из подписки, отрезаем старое имя и клеим наше красивое
                    base_link = links[0].split('#')[0]
                    result_links.append(f"{base_link}#{quote(node_info['name'])}")
                else:
                    logger.error(f"❌ Не найдено ссылок в подписке {node_info['name']}")
            else:
                logger.error(f"❌ Ошибка HTTP {resp.status_code} при загрузке {node_info['name']}")
        except Exception as e:
            logger.error(f"❌ Ошибка запроса к {node_info['url']}: {e}")

    # Имя изменено здесь тоже для единообразия в json файле
    json_stats = {"servers": [
        {"name": "💎 V1A RU / БЕЛЫЕ СПИСКИ (Hardcoded)", "ip": "212.22.82.138", "protocol": "vless reality"},
        {"name": "💎 🇫🇮  V1A / Финляндия", "ip": "212.22.82.138", "protocol": "vless reality"},
        {"name": "💎 🇫🇮  V2A / Финляндия", "ip": "195.226.92.208", "protocol": "vless reality"},
        {"name": "💎 🇪🇪  V2A / Эстония", "ip": "195.226.92.208", "protocol": "vless reality"}
    ]}
    
    for s in final_selection:
        country_display = COUNTRIES_RU.get(s['country'], f"🏳️ {s['country']}")
        speed_badge = get_speed_badge(s['speed_mbps'])
        
        # Индикатор Золотой Ноды
        node_id = f"{s['ip']}:{s['port']}"
        streak = history_data.get(node_id, {}).get("streak", 0)
        gold_star = "🌟" if streak >= 3 else ""

        # Убрана приписка [YT]
        name = f"{gold_star}{speed_badge}{country_display}" 
        
        orig = s['original']
        base = orig.split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)
        
        json_stats["servers"].append({
            "name": name,
            "ip": s['ip'],
            "ping": s['real_delay'],
            "speed_mbps": s['speed_mbps'],
            "score": s['score'],
            "country": s['country'],
            "protocol": f"{s['protocol']} {s.get('security', '')}".strip()
        })

    raw_str = "\n".join(result_links)
    b64_str = base64.b64encode(raw_str.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(b64_str)
    
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_stats, f, indent=2, ensure_ascii=False)
        
    logger.info(f"💾 Подписка успешно сохранена: {OUTPUT_FILE} (Сформирован пул из {len(result_links)-1} узлов)")

if __name__ == "__main__":
    main()
