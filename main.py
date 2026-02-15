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
# Настройка логирования одновременно в консоль и в файл
logger = logging.getLogger("VPN_Scanner")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Вывод в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Вывод в файл
file_handler = logging.FileHandler("vpn_scanner.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- НАСТРОЙКИ ---
SOURCES = [
    "https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Reality",
    "https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Clash_Reality",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
    "https://sub.shadowproxy66.workers.dev/sub/be80a76c-6044-417c-9bff-e587f9380d05#ShadowProxy66(1)" 
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'

# Настройки проверки
MAX_WORKERS = 25        # Количество потоков
TCP_TIMEOUT = 1.0       # Быстрый отсев
REAL_TEST_TIMEOUT = 5.0 # Время на пинг
SPEED_TEST_TIMEOUT = 4.0 # Время на тест скорости
TOTAL_SERVERS_WANTED = 10 # Цель: 10 серверов
FAST_SPEED_THRESHOLD = 5.0 # Мбит/с для получения значка молнии ⚡

# Словарь с флагами и русскими названиями
COUNTRIES_RU = {
    'RU': '🇷🇺 Россия', 'US': '🇺🇸 США', 'DE': '🇩🇪 Германия', 'NL': '🇳🇱 Нидерланды',
    'FI': '🇫🇮 Финляндия', 'UK': '🇬🇧 Великобритания', 'GB': '🇬🇧 Великобритания',
    'FR': '🇫🇷 Франция', 'SE': '🇸🇪 Швеция', 'PL': '🇵🇱 Польша', 'UA': '🇺🇦 Украина',
    'KZ': '🇰🇿 Казахстан', 'BY': '🇧🇾 Беларусь', 'TR': '🇹🇷 Турция', 'JP': '🇯🇵 Япония',
    'KR': '🇰🇷 Южная Корея', 'CN': '🇨🇳 Китай', 'SG': '🇸🇬 Сингапур', 'IT': '🇮🇹 Италия',
    'ES': '🇪🇸 Испания', 'CA': '🇨🇦 Канада', 'AU': '🇦🇺 Австралия', 'CH': '🇨🇭 Швейцария',
    'AE': '🇦🇪 ОАЭ', 'IN': '🇮🇳 Индия', 'BR': '🇧🇷 Бразилия', 'ZA': '🇿🇦 ЮАР'
}

geo_reader = None

def install_xray_core():
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
        else:
            logger.error(f"❌ Ошибка скачивания Xray: {r.status_code}")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка установки Xray: {e}")

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        logger.info("📥 Скачивание GeoIP базы...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=20)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        except Exception as e:
            logger.error(f"Ошибка скачивания MMDB: {e}")

def init_geoip():
    global geo_reader
    try: 
        geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: 
        pass

def get_country_code(ip):
    if not geo_reader: return 'XX'
    try: 
        code = geo_reader.country(ip).country.iso_code
        return code if code else 'XX'
    except: 
        return 'XX'

def safe_base64_decode(s):
    s = s.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    try:
        return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except:
        try:
            return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
        except:
            return ""

def extract_vless_links(text):
    regex = r"(?i)(vless://[^\s\"']+)"
    links = re.findall(regex, text)
    
    decoded = safe_base64_decode(text)
    if decoded:
        links.extend(re.findall(regex, decoded))
        
    for line in text.splitlines():
        dec_line = safe_base64_decode(line)
        if dec_line:
            links.extend(re.findall(regex, dec_line))
            
    return list(set(links))

def parse_vless(config_str):
    try:
        if not config_str.lower().startswith("vless://"): return None
        config_str = config_str.strip()
        uuid_val = config_str.split("@")[0][8:]
        part = config_str.split("@")[1].split("?")[0]
        
        if "]" in part:
            host_part, port = part.rsplit(":", 1)
            host = host_part.replace("[", "").replace("]", "")
        else:
            host, port = part.rsplit(":", 1)
            
        if "?" in config_str:
            query_part = config_str.split("?")[1].split("#")[0]
        else:
            query_part = ""
            
        params = parse_qs(query_part)
        
        conf = {
            "ip": host,
            "port": int(port),
            "uuid": uuid_val,
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
            "country": "XX",
            "real_delay": 9999,
            "speed_mbps": 0.0
        }
        
        if conf['security'] == 'reality' and not conf['pbk']: return None
        return conf
    except:
        return None

def generate_xray_config(server, local_port):
    outbound = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": server['ip'],
                "port": server['port'],
                "users": [{"id": server['uuid'], "encryption": "none", "flow": server['flow']}]
            }]
        },
        "streamSettings": {
            "network": server['type'],
            "security": server['security']
        }
    }

    ws_set = {}
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
        reality_set.update({
            "show": False, "publicKey": server['pbk'], "shortId": server['sid'], "spiderX": server['spx']
        })
        outbound["streamSettings"]["realitySettings"] = reality_set

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "http"}],
        "outbounds": [outbound]
    }

def check_real_ping(server):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((server['ip'], server['port']))
        sock.close()
    except:
        return None

    local_port = random.randint(15000, 45000)
    config = generate_xray_config(server, local_port)
    
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(config, tmp)
        config_path = tmp.name

    proc = None
    latency = None
    speed_mbps = 0.0

    try:
        proc = subprocess.Popen([XRAY_BIN, "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.7) 

        proxies = {"http": f"http://127.0.0.1:{local_port}", "https": f"http://127.0.0.1:{local_port}"}
        
        # 1. Проверка Пинга (Cloudflare 204)
        start = time.perf_counter()
        resp = requests.get("http://cp.cloudflare.com/", proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        
        if resp.status_code == 204:
            end = time.perf_counter()
            latency = int((end - start) * 1000)
            
            # 2. Проверка Скорости (Скачиваем 500KB файл)
            try:
                # Скачиваем 500 000 байт для теста пропускной способности
                dl_start = time.perf_counter()
                dl_resp = requests.get("https://speed.cloudflare.com/__down?bytes=500000", proxies=proxies, timeout=SPEED_TEST_TIMEOUT)
                if dl_resp.status_code == 200:
                    dl_end = time.perf_counter()
                    duration = dl_end - dl_start
                    # Формула: (Мегабайты * 8) / Секунды = Мегабиты в секунду (Mbps)
                    speed_mbps = round((0.5 * 8) / duration, 2)
            except Exception:
                # Если тест скорости не удался, мы всё равно сохраняем сервер, просто без высокой скорости
                pass
        else:
            latency = None
            
    except:
        latency = None
    finally:
        if proc:
            proc.terminate()
            try: proc.wait(timeout=0.5)
            except: proc.kill()
        if os.path.exists(config_path):
            os.remove(config_path)

    if latency:
        server['real_delay'] = latency
        server['speed_mbps'] = speed_mbps
        code = get_country_code(server['ip'])
        server['country'] = code
        
        if code == 'XX': return None
        return server
    return None

def main():
    logger.info(f"🚀 START: Smart VLESS Selector (Target: {TOTAL_SERVERS_WANTED}, Strict Mode)")
    
    install_xray_core()
    download_mmdb()
    init_geoip()
    
    if not os.path.exists(XRAY_BIN):
        logger.error(f"❌ ОШИБКА: Не удалось найти {XRAY_BIN}")
        return

    all_configs = []
    logger.info("🌐 Загрузка источников...")
    for url in SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                links = extract_vless_links(resp.text)
                for link in links:
                    parsed = parse_vless(link)
                    if parsed: all_configs.append(parsed)
        except Exception as e:
            logger.warning(f"⚠️ Ошибка источника {url[:30]}...: {e}")

    unique_configs = {f"{c['ip']}:{c['port']}": c for c in all_configs}.values()
    logger.info(f"🔍 Уникальных конфигов собрано: {len(unique_configs)}")

    valid_servers = []
    logger.info(f"⚡ Тестирование серверов (Workers: {MAX_WORKERS})...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_real_ping, s) for s in unique_configs]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                valid_servers.append(res)
                lightning = "⚡ " if res['speed_mbps'] >= FAST_SPEED_THRESHOLD else ""
                logger.info(f"   ✅ {res['country']} | Пинг: {res['real_delay']}ms | Скорость: {res['speed_mbps']} Mbps {lightning}")

    ru_servers = [s for s in valid_servers if s['country'] == 'RU']
    world_servers = [s for s in valid_servers if s['country'] != 'RU']

    ru_servers.sort(key=lambda x: x['real_delay'])
    # Сортируем остальные серверы: сначала более быстрые по скачиванию, затем по пингу
    world_servers.sort(key=lambda x: (-x['speed_mbps'], x['real_delay']))

    final_selection = []
    
    best_ru = ru_servers[0] if ru_servers else None
    needed_world = TOTAL_SERVERS_WANTED - (1 if best_ru else 0)
    
    final_selection.extend(world_servers[:needed_world])
    
    if best_ru:
        final_selection.append(best_ru)
        logger.info(f"🏆 Добавлен RU сервер: {best_ru['ip']}")

    logger.info(f"📊 Итого в подписке сохранено: {len(final_selection)} серверов")

    result_links = []
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header_link)

    json_stats = {"servers": []}

    for s in final_selection:
        # Логика именования: ⚡ (Флаг) Название страны | 120ms
        country_display = COUNTRIES_RU.get(s['country'], f"🏳️ {s['country']}")
        speed_badge = "⚡ " if s['speed_mbps'] >= FAST_SPEED_THRESHOLD else ""
        name = f"{speed_badge}{country_display} | {s['real_delay']}ms"
        
        orig = s['original']
        base = orig.split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)

        json_stats["servers"].append({
            "name": name,
            "ip": s['ip'],
            "ping": s['real_delay'],
            "speed_mbps": s['speed_mbps'],
            "country": s['country']
        })

    raw_str = "\n".join(result_links)
    b64_str = base64.b64encode(raw_str.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(b64_str)
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_stats, f, indent=2, ensure_ascii=False)

    logger.info(f"💾 Файл успешно сохранен: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
