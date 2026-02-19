import sys
import os
import json
import time
import base64
import re
import random
import zipfile
import io
import stat
import logging
import asyncio
from urllib.parse import unquote, quote, parse_qs

import aiohttp
from aiohttp_socks import ProxyConnector
import geoip2.database
import requests

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logger = logging.getLogger("VPN_Scanner")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler("vpn_scanner.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- ИСТОЧНИКИ И АВТОРИЗАЦИЯ ---
# Значение токена (название токена в GitHub - VPN)
GITHUB_TOKEN = "Ghp_OmDhaHZvJ0Aag6tsrBnWBMEG7iD2ke1rFvBI"

TG_CHANNELS = [
    "oneclickvpnkeys",
    "configV2rayForFree",
    "ConfigV2rayNG",
    "V2RayRootFree",
    "DailyV2RY",
    "V2rayng_Fast",
    "proxyvpn11",
    "V2ray_Alpha"
]

SOURCES = [
     "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
     "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
     "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile-2.txt",
     "https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/Clash_Reality",
     "https://raw.githubusercontent.com/CidVpn/cid-vpn-config/refs/heads/main/general.txt",
     "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/refs/heads/main/sub/mix",
     "https://raw.githubusercontent.com/TheFlipper-spec/VPNMY/refs/heads/main/my_source",
     "https://raw.githubusercontent.com/Rayan-Config/C-Sub/refs/heads/main/configs/proxy.txt"
]

# --- БАЗОВЫЕ НАСТРОЙКИ ---
MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"
OUTPUT_FILE = 'FL1PVPN'
JSON_FILE = 'stats.json'

# --- ПАРАМЕТРЫ ПРОИЗВОДИТЕЛЬНОСТИ ---
TCP_TIMEOUT = 1.0            
MAX_XRAY_CONCURRENT = 20     
CANDIDATES_TO_TEST = 80      
TOTAL_SERVERS_WANTED = 15    
SPEED_TEST_URL = "https://speed.cloudflare.com/__down?bytes=1500000"

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

    logger.info("📥 Скачивание Xray core...")
    url = "https://github.com/XTLS/Xray-core/releases/download/v1.8.4/Xray-linux-64.zip"
    try:
        r = requests.get(url, stream=True, timeout=30)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                with z.open('xray') as zf, open(XRAY_BIN, 'wb') as f:
                    f.write(zf.read())
            st = os.stat(XRAY_BIN)
            os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
            logger.info("✅ Xray установлен.")
    except Exception as e:
        logger.error(f"❌ Ошибка установки Xray: {e}")

def download_mmdb():
    if not os.path.exists(MMDB_FILE):
        logger.info("📥 Скачивание GeoIP...")
        try:
            r = requests.get(MMDB_URL, stream=True, timeout=20)
            if r.status_code == 200:
                with open(MMDB_FILE, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
        except Exception as e:
            logger.error(f"Ошибка MMDB: {e}")

def init_geoip():
    global geo_reader
    try: geo_reader = geoip2.database.Reader(MMDB_FILE)
    except: pass

def get_country_code(ip):
    if not geo_reader: return 'XX'
    try: 
        c = geo_reader.country(ip).country.iso_code
        return c if c else 'XX'
    except: return 'XX'

def extract_vpn_links(text):
    regex = r"(?i)((?:vless|ss|trojan)://[a-zA-Z0-9@:%._\-\+~#=/?&;]+)"
    links = re.findall(regex, text)
    
    s = text.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    decoded = ""
    try: decoded = base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: pass
    
    if decoded: links.extend(re.findall(regex, decoded))
    return list(set(links))

def parse_vless(config_str):
    try:
        config_str = config_str.strip()
        uuid_val = config_str.split("@")[0][8:]
        part = config_str.split("@")[1].split("?")[0]
        host, port = part.rsplit(":", 1) if "]" not in part else (part.rsplit(":", 1)[0].strip("[]"), part.rsplit(":", 1)[1])
        params = parse_qs(config_str.split("?")[1].split("#")[0] if "?" in config_str else "")
        conf = {
            "protocol": "vless", "ip": host, "port": int(port), "uuid": uuid_val,
            "type": params.get('type', ['tcp'])[0], "security": params.get('security', ['none'])[0],
            "sni": params.get('sni', [''])[0], "pbk": params.get('pbk', [''])[0],
            "sid": params.get('sid', [''])[0], "spx": params.get('spx', ['/'])[0],
            "path": params.get('path', ['/'])[0], "host": params.get('host', [''])[0],
            "fp": params.get('fp', ['chrome'])[0], "original": config_str
        }
        if conf['security'] == 'reality' and not conf['pbk']: return None
        return conf
    except: return None

def generate_xray_config(server, local_port):
    outbound = {"protocol": server.get('protocol', 'vless'), "settings": {}}
    if server['protocol'] == "vless":
        outbound["settings"] = {"vnext": [{"address": server['ip'], "port": server['port'], "users": [{"id": server['uuid'], "encryption": "none"}]}]}
    
    network, security = server.get('type', 'tcp'), server.get('security', 'none')
    outbound["streamSettings"] = {"network": network, "security": security}

    if network == 'ws': outbound["streamSettings"]["wsSettings"] = {"path": server.get('path', '/'), "headers": {"Host": server.get('host', '')}}
    tls_set = {"serverName": server.get('sni', ''), "fingerprint": server.get('fp', 'chrome')}
    
    if security == 'tls': outbound["streamSettings"]["tlsSettings"] = tls_set
    elif security == 'reality':
        tls_set.update({"show": False, "publicKey": server.get('pbk', ''), "shortId": server.get('sid', ''), "spiderX": server.get('spx', '/')})
        outbound["streamSettings"]["realitySettings"] = tls_set

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks"}],
        "outbounds": [outbound]
    }

async def fetch_from_telegram(session, channel):
    url = f"https://t.me/s/{channel}"
    configs = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                html = await resp.text()
                configs.extend(extract_vpn_links(html))
    except Exception as e:
        logger.debug(f"Ошибка TG {channel}: {e}")
    return configs

async def fetch_from_github_search(session):
    url = "https://api.github.com/search/code?q=%22vless://%22+in:file&sort=indexed&order=desc"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    configs = []
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                for item in data.get('items', [])[:5]:
                    raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                    async with session.get(raw_url, timeout=5) as raw_resp:
                        if raw_resp.status == 200:
                            configs.extend(extract_vpn_links(await raw_resp.text()))
    except Exception as e:
        logger.error(f"Ошибка GitHub API: {e}")
    return configs

async def tcp_ping_async(server):
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server['ip'], server['port']), timeout=TCP_TIMEOUT
        )
        writer.close()
        await writer.wait_closed()
        server['tcp_ping'] = int((time.perf_counter() - start) * 1000)
        return server
    except:
        return None

async def check_xray_and_speed(server, port_queue):
    local_port = await port_queue.get()
    config_path = f"temp_conf_{local_port}.json"
    
    with open(config_path, 'w') as f:
        json.dump(generate_xray_config(server, local_port), f)

    proc = None
    server['speed_mbps'] = 0.0
    server['real_delay'] = 9999
    is_working = False

    try:
        proc = await asyncio.create_subprocess_exec(
            XRAY_BIN, "-c", config_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.sleep(0.8) 

        connector = ProxyConnector.from_url(f'socks5://127.0.0.1:{local_port}')
        async with aiohttp.ClientSession(connector=connector) as session:
            t_start = time.perf_counter()
            async with session.get("http://cp.cloudflare.com/", timeout=4.0) as resp:
                if resp.status == 204:
                    server['real_delay'] = int((time.perf_counter() - t_start) * 1000)
                    is_working = True
            
            if is_working:
                dl_start = time.perf_counter()
                downloaded = 0
                async with session.get(SPEED_TEST_URL, timeout=6.0) as resp:
                    if resp.status == 200:
                        async for chunk in resp.content.iter_chunked(8192):
                            downloaded += len(chunk)
                            if time.perf_counter() - dl_start > 5.0: break
                
                duration = time.perf_counter() - dl_start
                if duration > 0 and downloaded > 100_000: 
                    server['speed_mbps'] = round((downloaded * 8 / 1_000_000) / duration, 2)

    except Exception:
        pass
    finally:
        if proc:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                proc.kill()
        if os.path.exists(config_path):
            os.remove(config_path)
        port_queue.put_nowait(local_port)

    return server if is_working and server['speed_mbps'] > 0 else None

def get_speed_badge(speed_mbps):
    if speed_mbps >= 5.0: return "⚡⚡ "
    elif speed_mbps >= 1.5: return "⚡ "
    return ""

async def async_main():
    logger.info("🚀 START: Async Smart VPN Selector")
    install_xray_core()
    download_mmdb()
    init_geoip()

    all_configs = []
    async with aiohttp.ClientSession() as session:
        tasks = [session.get(url, timeout=10) for url in SOURCES]
        tasks.extend([fetch_from_telegram(session, ch) for ch in TG_CHANNELS])
        if GITHUB_TOKEN: tasks.append(fetch_from_github_search(session))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            links = []
            if isinstance(res, aiohttp.ClientResponse) and res.status == 200:
                links = extract_vpn_links(await res.text())
            elif isinstance(res, list):
                links = res

            for link in links:
                if link.lower().startswith("vless://"): 
                    parsed = parse_vless(link)
                    if parsed: all_configs.append(parsed)

    unique_configs = list({f"{c['ip']}:{c['port']}": c for c in all_configs}.values())
    logger.info(f"🔍 Найдено уникальных конфигов: {len(unique_configs)}")

    logger.info("⚡ ЭТАП 1: Массовый TCP-пинг...")
    ping_tasks = [asyncio.create_task(tcp_ping_async(c)) for c in unique_configs]
    ping_results = await asyncio.gather(*ping_tasks)
    
    alive_servers = sorted([s for s in ping_results if s is not None], key=lambda x: x['tcp_ping'])
    candidates = alive_servers[:CANDIDATES_TO_TEST]
    logger.info(f"✅ Прошли TCP-пинг: {len(alive_servers)}. На глубокую проверку: {len(candidates)}")

    logger.info("🏎️ ЭТАП 2: Xray протокольная проверка + Скорость...")
    port_queue = asyncio.Queue()
    for port in range(10800, 10800 + MAX_XRAY_CONCURRENT):
        port_queue.put_nowait(port)

    xray_tasks = [asyncio.create_task(check_xray_and_speed(s, port_queue)) for s in candidates]
    xray_results = await asyncio.gather(*xray_tasks)

    valid_servers = [s for s in xray_results if s is not None]
    for s in valid_servers: s['country'] = get_country_code(s['ip'])
    valid_servers.sort(key=lambda x: (-x['speed_mbps'], x['real_delay']))

    final_selection = []
    ru_servers = [s for s in valid_servers if s['country'] == 'RU']
    world_servers = [s for s in valid_servers if s['country'] != 'RU']

    best_ru = ru_servers[0] if ru_servers else None
    needed_world = TOTAL_SERVERS_WANTED - (1 if best_ru else 0)
    
    final_selection.extend(world_servers[:needed_world])
    if best_ru: final_selection.append(best_ru)

    for s in final_selection:
        c_name = COUNTRIES_RU.get(s['country'], s['country'])
        logger.info(f"🏆 {c_name} | Пинг: {s['real_delay']}ms | Скорость: {s['speed_mbps']} Mbps {get_speed_badge(s['speed_mbps'])}")

    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    result_links = [f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"]
    json_stats = {"servers": []}

    for s in final_selection:
        name = f"{get_speed_badge(s['speed_mbps'])}{COUNTRIES_RU.get(s['country'], f'🏳️ {s['country']}')} | {s['real_delay']}ms"
        result_links.append(f"{s['original'].split('#')[0]}#{quote(name)}")
        json_stats["servers"].append({
            "name": name, "ip": s['ip'], "ping": s['real_delay'],
            "speed_mbps": s['speed_mbps'], "country": s['country'], "protocol": s['protocol']
        })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(base64.b64encode("\n".join(result_links).encode('utf-8')).decode('utf-8'))
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_stats, f, indent=2, ensure_ascii=False)

    logger.info(f"💾 Итого сохранено {len(final_selection)} серверов. Файл: {OUTPUT_FILE}")

def main():
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
