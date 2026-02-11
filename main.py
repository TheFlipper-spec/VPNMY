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
import uuid
import geoip2.database
import subprocess
import tempfile
import random
import shutil
from urllib.parse import unquote, quote, parse_qs, urlparse

# --- НАСТРОЙКИ ---
SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'

# Настройки проверки
MAX_WORKERS = 20        # Количество одновременных проверок
TCP_TIMEOUT = 1.0       # Быстрый отсев мертвых портов
REAL_TEST_TIMEOUT = 3.0 # Тайм-аут реального теста через Xray

# Страны для красоты
COUNTRY_FLAGS = {
    'RU': '🇷🇺', 'US': '🇺🇸', 'DE': '🇩🇪', 'NL': '🇳🇱', 'FI': '🇫🇮', 'UK': '🇬🇧',
    'GB': '🇬🇧', 'FR': '🇫🇷', 'SE': '🇸🇪', 'PL': '🇵🇱', 'UA': '🇺🇦', 'KZ': '🇰🇿',
    'BY': '🇧🇾', 'TR': '🇹🇷', 'JP': '🇯🇵', 'KR': '🇰🇷', 'CN': '🇨🇳', 'SG': '🇸🇬',
    'IT': '🇮🇹', 'ES': '🇪🇸', 'CA': '🇨🇦', 'AU': '🇦🇺', 'CH': '🇨🇭', 'AE': '🇦🇪'
}

geo_reader = None

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        print("📥 Скачивание GeoIP базы...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=20)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        except Exception as e:
            print(f"Ошибка скачивания MMDB: {e}")

def init_geoip():
    global geo_reader
    try: 
        geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: 
        pass

def get_country_code(ip):
    if not geo_reader: return 'XX'
    try: 
        return geo_reader.country(ip).country.iso_code or 'XX'
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
    # Ищем только VLESS, игнорируем SS
    regex = r"(vless://[^ \n]+)"
    links = re.findall(regex, text)
    if not links:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_vless(config_str):
    try:
        if not config_str.startswith("vless://"): return None
        
        # Парсинг основной части
        part = config_str.split("@")[1].split("?")[0]
        if ":" not in part: return None
        
        host, port = part.split(":")
        query_part = config_str.split("?")[1].split("#")[0]
        params = parse_qs(query_part)
        
        uuid_val = config_str.split("@")[0].replace("vless://", "")
        
        # Данные для конфига Xray
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
            "real_delay": 9999
        }
        
        # Фильтрация Reality (должен быть ключ)
        if conf['security'] == 'reality' and not conf['pbk']: return None
        
        return conf
    except:
        return None

def generate_xray_config(server, local_port):
    """Генерация JSON конфига для Xray-core"""
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

    # Настройка транспорта
    ws_set = {}
    if server['type'] == 'ws':
        ws_set = {"path": server['path']}
        if server['host']: ws_set["headers"] = {"Host": server['host']}
        outbound["streamSettings"]["wsSettings"] = ws_set
    elif server['type'] == 'grpc':
        outbound["streamSettings"]["grpcSettings"] = {"serviceName": server['serviceName']}

    # Настройка шифрования
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
        "log": {"loglevel": "none"}, # Отключаем логи для скорости
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "http"}], # HTTP inbound быстрее для теста
        "outbounds": [outbound],
        "policy": {"levels": {"0": {"handshake": 2, "connIdle": 2}}} # Жесткие тайминги
    }

def check_real_ping(server):
    """
    Гениальная простота: запускаем Xray и делаем 1 запрос к Cloudflare.
    Это именно то, что показывает 'Real Delay' в приложениях.
    """
    
    # 1. Сначала TCP проверка (самая дешевая) - жив ли порт вообще?
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((server['ip'], server['port']))
        sock.close()
    except:
        return None # Порт закрыт, сразу на выход

    # 2. Реальный тест через Xray
    local_port = random.randint(15000, 45000)
    config = generate_xray_config(server, local_port)
    
    # Создаем временный файл конфига
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(config, tmp)
        config_path = tmp.name

    proc = None
    latency = None

    try:
        # Запуск Xray
        proc = subprocess.Popen([XRAY_BIN, "-c", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.7) # Даем время на разгон (меньше 1.5с, так как конфиг легкий)

        # Замер HTTP запроса
        proxies = {"http": f"http://127.0.0.1:{local_port}"}
        start = time.perf_counter()
        # Используем легкий ресурс для пинга
        requests.get("http://cp.cloudflare.com/", proxies=proxies, timeout=REAL_TEST_TIMEOUT)
        end = time.perf_counter()
        
        latency = int((end - start) * 1000)
        
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
        server['country'] = get_country_code(server['ip'])
        return server
    return None

def main():
    print("🚀 START: Smart VLESS Selector (No Shadowsocks)")
    
    if not os.path.exists(XRAY_BIN):
        print(f"❌ ОШИБКА: Не найден файл {XRAY_BIN}. Положите ядро Xray рядом со скриптом.")
        return

    download_mmdb()
    init_geoip()

    # 1. Сбор ссылок
    all_configs = []
    print("🌐 Загрузка источников...")
    for url in SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                links = extract_vless_links(resp.text)
                for link in links:
                    parsed = parse_vless(link)
                    if parsed: all_configs.append(parsed)
        except Exception as e:
            print(f"   ⚠️ Ошибка источника: {e}")

    # Удаление дубликатов по IP и порту
    unique_configs = {f"{c['ip']}:{c['port']}": c for c in all_configs}.values()
    print(f"🔍 Найдено уникальных VLESS конфигов: {len(unique_configs)}")

    # 2. Массовая проверка (TCP + Real Ping)
    valid_servers = []
    print(f"⚡ Запуск тестов (Workers: {MAX_WORKERS})...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_real_ping, s) for s in unique_configs]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                valid_servers.append(res)
                print(f"   ✅ {res['country']} | Ping: {res['real_delay']}ms")

    if not valid_servers:
        print("❌ Нет рабочих серверов.")
        return

    # 3. Сортировка и Отбор
    # Разделяем на РФ и Остальной мир
    ru_servers = [s for s in valid_servers if s['country'] == 'RU']
    world_servers = [s for s in valid_servers if s['country'] != 'RU']

    # Сортируем ТОЛЬКО по реальному пингу (от меньшего к большему)
    ru_servers.sort(key=lambda x: x['real_delay'])
    world_servers.sort(key=lambda x: x['real_delay'])

    final_selection = []
    
    # Берем ТОП-1 RU
    if ru_servers:
        best_ru = ru_servers[0]
        print(f"🏆 Лучший RU: {best_ru['ip']} ({best_ru['real_delay']}ms)")
        final_selection.append(best_ru)
    else:
        print("⚠️ RU серверы не найдены или мертвы.")

    # Берем ТОП-4 World
    top_world = world_servers[:4]
    print(f"🌍 Лучшие World ({len(top_world)} шт):")
    for s in top_world:
        print(f"   -> {s['country']} ({s['real_delay']}ms)")
    final_selection.extend(top_world)

    # 4. Генерация итогового файла
    result_links = []
    
    # Добавляем инфо-заголовок
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header_link)

    json_stats = {"servers": []}

    for s in final_selection:
        flag = COUNTRY_FLAGS.get(s['country'], s['country'])
        
        # Формируем красивое имя: "🇸🇪 SE | 58ms"
        # Это имя будет видно в приложении
        name = f"{flag} {s['country']} | {s['real_delay']}ms"
        
        # Собираем ссылку обратно
        orig = s['original']
        base = orig.split('#')[0]
        final_link = f"{base}#{quote(name)}"
        result_links.append(final_link)

        # Данные для JSON
        json_stats["servers"].append({
            "name": name,
            "ip": s['ip'],
            "ping": s['real_delay'],
            "country": s['country']
        })

    # Сохранение в base64
    raw_str = "\n".join(result_links)
    b64_str = base64.b64encode(raw_str.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(b64_str)
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_stats, f, indent=2, ensure_ascii=False)

    print(f"💾 Готово! Файл {OUTPUT_FILE} создан (всего {len(final_selection)} конфигов).")

if __name__ == "__main__":
    main()
