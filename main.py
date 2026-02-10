import base64
import concurrent.futures
import json
import logging
import os
import random
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlparse

import geoip2.database
import requests

# --- ЛОГИ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# --- ИСТОЧНИКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/reality",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub/Configs/vless.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/all_extracted_configs.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
    "https://gbr.mydan.online/configs",
    "https://raw.githubusercontent.com/roaster09/V2ray_Config/main/Vless_Config_Base64.txt"
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-all.txt"
]

MMDB_URL = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
MMDB_FILE = "Country.mmdb"
XRAY_BIN = "./xray"
OUTPUT_FILE = "FL1PVPN"
JSON_FILE = "stats.json"
HISTORY_FILE = "history.json"

# --- ЦЕЛИ ПО КАТЕГОРИЯМ ---
TARGET_GAME = 1
TARGET_UNIVERSAL = 3
TARGET_WARP = 2
TARGET_WHITELIST = 2

# --- СЕТЕВЫЕ НАСТРОЙКИ ---
TIMEOUT = 0.7
REAL_TEST_TIMEOUT = 5.5
REAL_TEST_ATTEMPTS = 5
REAL_TEST_MIN_SUCCESS = 4
MAX_ALLOWED_LOSS = 0.20
MAX_ALLOWED_JITTER = 160
MAX_REAL_LATENCY = 650

REAL_TEST_URLS = [
    "https://www.gstatic.com/generate_204",
    "https://cp.cloudflare.com/generate_204",
    "https://www.google.com/generate_204"
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
}

# --- ОБНОВЛЕНИЕ ---
TIMEZONE_OFFSET = 3
UPDATE_INTERVAL_HOURS = 1

RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия',
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция',
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия',
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия', 'DK': 'Дания', 'AE': 'ОАЭ',
    'XX': 'Неизвестно', 'GR': 'Греция', 'CH': 'Швейцария'
}

TIER_1_PLATINUM = {'FI', 'EE', 'SE', 'LV', 'LT', 'PL'}
TIER_2_GOLD = {'DE', 'NL', 'FR', 'KZ', 'RU', 'UA'}
TIER_3_SILVER = {'GB', 'IT', 'ES', 'TR', 'CZ', 'BG', 'AT', 'CH'}

MIN_THEORETICAL_LATENCY = {
    'FI': 15, 'EE': 20, 'SE': 20, 'DE': 35, 'NL': 40, 'GB': 45,
    'FR': 45, 'PL': 30, 'UA': 20, 'TR': 40, 'IT': 50, 'ES': 60,
    'US': 95, 'CA': 100, 'JP': 150, 'KR': 150, 'SG': 120, 'GR': 45,
    'BG': 40, 'RO': 35, 'CH': 40, 'NO': 35
}

geo_reader = None


def download_mmdb():
    if os.path.exists(MMDB_FILE):
        return
    logger.info("Скачивание GeoLite2 базы...")
    try:
        r = requests.get(MMDB_URL, timeout=20, stream=True, headers=HTTP_HEADERS)
        if r.status_code == 200:
            with open(MMDB_FILE, 'wb') as f:
                for chunk in r.iter_content(1024 * 32):
                    f.write(chunk)
            logger.info("GeoLite2 база успешно скачана.")
        else:
            logger.warning(f"Не удалось скачать MMDB: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"Ошибка скачивания MMDB: {e}")


def init_geoip():
    global geo_reader
    try:
        geo_reader = geoip2.database.Reader(MMDB_FILE)
        logger.info("GeoIP инициализирован.")
    except Exception as e:
        logger.error(f"Ошибка инициализации GeoIP: {e}")


def get_ip_country_local(ip):
    if not geo_reader:
        return 'XX'
    try:
        return geo_reader.country(ip).country.iso_code or 'XX'
    except Exception:
        return 'XX'


def safe_base64_decode(s):
    s = (s or '').strip().replace('\n', '').replace('\r', '')
    if not s:
        return ''

    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)

    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder(s).decode('utf-8', errors='ignore')
        except Exception:
            continue
    return ''


def extract_links(text):
    regex = r"(vless://[^ \n]+|ss://[^ \n]+|vmess://[^ \n]+)"
    links = re.findall(regex, text or '')

    if len(links) < 5:
        decoded = safe_base64_decode(text)
        if decoded:
            links.extend(re.findall(regex, decoded))

    return list(set(links))


def parse_config_info(config_str, source_type):
    try:
        # SS
        if config_str.startswith('ss://'):
            rest = config_str[5:]
            if '#' in rest:
                main_part, original_remark = rest.split('#', 1)
                original_remark = unquote(original_remark).strip()
            else:
                main_part = rest
                original_remark = 'Unknown'

            method = ''
            password = ''

            if '@' in main_part:
                user_info, host_port = main_part.split('@', 1)
                decoded_user = safe_base64_decode(user_info)
                if ':' in decoded_user:
                    method, password = decoded_user.split(':', 1)
                elif ':' in user_info:
                    method, password = user_info.split(':', 1)
                else:
                    return None
            else:
                decoded = safe_base64_decode(main_part)
                if '@' not in decoded:
                    return None
                auth, host_port = decoded.split('@', 1)
                if ':' not in auth:
                    return None
                method, password = auth.split(':', 1)

            if ':' not in host_port:
                return None

            if ']' in host_port:
                host = host_port.rsplit(':', 1)[0]
                port = host_port.rsplit(':', 1)[1]
            else:
                host, port = host_port.split(':', 1)

            return {
                'ip': host,
                'port': int(port),
                'uuid': password,
                'original': config_str,
                'original_remark': original_remark,
                'latency': 9999,
                'jitter': 0,
                'loss_ratio': 1.0,
                'final_score': 9999,
                'info': {},
                'transport': 'tcp',
                'security': 'ss',
                'is_reality': False,
                'is_vision': False,
                'is_pure': False,
                'is_hy2': False,
                'is_ss': True,
                'source_type': source_type,
                'tier_rank': 99,
                'parsed_params': {'method': method}
            }

        # VLESS
        if config_str.startswith('vless://'):
            parsed = urlparse(config_str)
            if '@' not in parsed.netloc:
                return None

            uid, host_port = parsed.netloc.split('@', 1)
            if ':' not in host_port:
                return None

            if ']' in host_port:
                host = host_port.rsplit(':', 1)[0]
                port = host_port.rsplit(':', 1)[1]
            else:
                host, port = host_port.split(':', 1)

            params = parse_qs(parsed.query)
            transport = (params.get('type', ['tcp'])[0] or 'tcp').lower()
            security = (params.get('security', ['none'])[0] or 'none').lower()
            flow_val = (params.get('flow', [''])[0] or '').lower()
            is_reality = security == 'reality'

            if is_reality:
                pbk = params.get('pbk', [''])[0]
                if len(pbk) < 10:
                    return None

            original_remark = unquote(parsed.fragment).strip() if parsed.fragment else 'Unknown'

            return {
                'ip': host,
                'port': int(port),
                'uuid': uid,
                'original': config_str,
                'original_remark': original_remark,
                'latency': 9999,
                'jitter': 0,
                'loss_ratio': 1.0,
                'final_score': 9999,
                'info': {},
                'transport': transport,
                'security': security,
                'is_reality': is_reality,
                'is_vision': 'vision' in flow_val,
                'is_pure': (security in {'none', 'tls'} and not is_reality),
                'is_hy2': False,
                'is_ss': False,
                'source_type': source_type,
                'tier_rank': 99,
                'parsed_params': params
            }
    except Exception:
        return None

    return None


def tcp_ping(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT)
            start = time.perf_counter()
            res = sock.connect_ex((host, port))
            end = time.perf_counter()
            if res == 0:
                return (end - start) * 1000
    except Exception:
        return None
    return None


def calculate_tier_rank(code):
    if code in TIER_1_PLATINUM:
        return 1
    if code in TIER_2_GOLD:
        return 2
    if code in TIER_3_SILVER:
        return 3
    if code in {'US', 'CA'}:
        return 5
    return 4


def generate_xray_config(server, local_port):
    params = server['parsed_params']

    def get_p(key, default=''):
        val = params.get(key, [default])
        return val[0] if isinstance(val, list) else val

    if server.get('is_ss', False):
        return {
            'log': {'loglevel': 'none'},
            'inbounds': [{
                'port': local_port,
                'listen': '127.0.0.1',
                'protocol': 'socks',
                'settings': {'udp': True}
            }],
            'outbounds': [{
                'tag': 'proxy',
                'protocol': 'shadowsocks',
                'settings': {
                    'servers': [{
                        'address': server['ip'],
                        'port': int(server['port']),
                        'method': params.get('method', ''),
                        'password': server['uuid'],
                        'uot': True
                    }]
                }
            }]
        }

    user = {'id': server['uuid'], 'encryption': 'none'}
    flow = get_p('flow', '')
    if flow:
        user['flow'] = flow

    stream = {
        'network': server['transport'],
        'security': server['security']
    }

    if server['transport'] == 'ws':
        ws = {'path': get_p('path', '/')}
        host = get_p('host', '')
        if host:
            ws['headers'] = {'Host': host}
        stream['wsSettings'] = ws
    elif server['transport'] == 'grpc':
        service = get_p('serviceName', '')
        if service:
            stream['grpcSettings'] = {'serviceName': service}

    if server['security'] == 'tls':
        stream['tlsSettings'] = {
            'serverName': get_p('sni', ''),
            'allowInsecure': False,
            'fingerprint': get_p('fp', 'chrome')
        }
    elif server['security'] == 'reality':
        stream['realitySettings'] = {
            'show': False,
            'fingerprint': get_p('fp', 'chrome'),
            'serverName': get_p('sni', ''),
            'publicKey': get_p('pbk', ''),
            'shortId': get_p('sid', ''),
            'spiderX': get_p('spx', '/')
        }

    return {
        'log': {'loglevel': 'none'},
        'inbounds': [{
            'port': local_port,
            'listen': '127.0.0.1',
            'protocol': 'socks',
            'settings': {'udp': True}
        }],
        'outbounds': [{
            'tag': 'proxy',
            'protocol': 'vless',
            'settings': {
                'vnext': [{
                    'address': server['ip'],
                    'port': int(server['port']),
                    'users': [user]
                }]
            },
            'streamSettings': stream
        }]
    }


def check_real_connection(server):
    local_port = random.randint(10000, 60000)
    config = generate_xray_config(server, local_port)

    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp_conf:
        json.dump(config, tmp_conf)
        config_path = tmp_conf.name

    xray_process = None
    latencies = []

    try:
        xray_process = subprocess.Popen(
            [XRAY_BIN, '-config', config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.2)

        if xray_process.poll() is not None:
            return None

        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }

        for i in range(REAL_TEST_ATTEMPTS):
            target_url = REAL_TEST_URLS[i % len(REAL_TEST_URLS)]
            start = time.perf_counter()
            try:
                resp = requests.get(
                    target_url,
                    proxies=proxies,
                    timeout=REAL_TEST_TIMEOUT,
                    verify=True,
                    headers=HTTP_HEADERS
                )
                end = time.perf_counter()
                if 200 <= resp.status_code < 300:
                    latencies.append((end - start) * 1000)
            except Exception:
                continue

    except Exception:
        return None
    finally:
        if xray_process:
            xray_process.terminate()
            try:
                xray_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                xray_process.kill()

        if os.path.exists(config_path):
            os.remove(config_path)

    success_count = len(latencies)
    if success_count < REAL_TEST_MIN_SUCCESS:
        return None

    loss_ratio = (REAL_TEST_ATTEMPTS - success_count) / REAL_TEST_ATTEMPTS
    if loss_ratio > MAX_ALLOWED_LOSS:
        return None

    median_latency = statistics.median(latencies)
    jitter = statistics.pstdev(latencies) if success_count > 1 else 0
    if jitter > MAX_ALLOWED_JITTER:
        return None

    score = median_latency + (jitter * 1.8) + (loss_ratio * 400)

    return {
        'median': median_latency,
        'jitter': jitter,
        'loss_ratio': loss_ratio,
        'score': score,
        'attempts': REAL_TEST_ATTEMPTS,
        'success': success_count,
    }


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_history(history):
    # Храним только недавние записи, чтобы history не рос бесконечно
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    pruned = {}

    for k, v in history.items():
        try:
            last_seen = datetime.fromisoformat(v.get('last_seen', ''))
            if last_seen >= cutoff:
                pruned[k] = v
        except Exception:
            # если формат битый — оставим запись, чтобы не потерять статистику
            pruned[k] = v

    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def update_server_history(history, server, metrics):
    key = f"{server['ip']}:{server['port']}"
    item = history.get(key)
    
    # Если записи нет или она не словарь — создаем новую
    if not isinstance(item, dict):
        item = {}

    # Принудительно задаем дефолтные значения, если ключей не хватает
    item.setdefault('ok_count', 0)
    item.setdefault('fail_count', 0)
    item.setdefault('last_latency', 9999)
    item.setdefault('last_score', 9999)
    item.setdefault('last_seen', None)

    if metrics:
        item['ok_count'] += 1
        item['last_latency'] = int(metrics['median'])
        item['last_score'] = int(metrics['score'])
    else:
        item['fail_count'] += 1

    item['last_seen'] = datetime.now(timezone.utc).isoformat()
    history[key] = item


def get_history_penalty(history, server):
    key = f"{server['ip']}:{server['port']}"
    item = history.get(key)
    if not item:
        return 0

    ok_count = item.get('ok_count', 0)
    fail_count = item.get('fail_count', 0)
    total = ok_count + fail_count
    if total < 3:
        return 0

    fail_ratio = fail_count / total
    return int(fail_ratio * 280)


def check_server_initial(server):
    rem = (server.get('original_remark') or '').lower()

    is_warp = 'warp' in rem or 'cloudflare' in rem or server['transport'] in {'ws', 'grpc'}
    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp:
        server['category'] = 'WARP'
    else:
        server['category'] = 'UNIVERSAL'

    p = tcp_ping(server['ip'], server['port'])
    if p is None:
        return None

    server['tcp_latency'] = int(p)
    code = get_ip_country_local(server['ip'])
    server['info'] = {'countryCode': code}

    # Фейковая гео-эвристика
    is_fake = False
    if code not in {'RU', 'BY', 'UA', 'KZ', 'XX'} and server['tcp_latency'] < 15:
        is_fake = True

    min_ping = MIN_THEORETICAL_LATENCY.get(code, 20)
    if server['tcp_latency'] < (min_ping - 5):
        is_fake = True

    if server['category'] == 'WHITELIST' and code == 'RU':
        is_fake = False

    if is_fake and server['category'] != 'WHITELIST':
        return None

    server['tier_rank'] = calculate_tier_rank(code)
    return server


def run_tournament(candidates, winners_needed, title='TOURNAMENT', mode='mixed', history=None):
    if not candidates:
        return []

    filtered = candidates
    if mode in {'gaming', 'universal'}:
        filtered = [
            c for c in candidates
            if c['is_reality'] and c['info']['countryCode'] not in {'RU', 'XX'}
        ]
        logger.info(f"{title}: Фильтр Reality+Foreign (No RU/XX).")
    elif mode == 'whitelist':
        filtered = [c for c in candidates if c['info']['countryCode'] == 'RU']
    elif mode == 'warp':
        filtered = [c for c in candidates if c['info']['countryCode'] not in {'RU', 'XX'}]

    if not filtered:
        return []

    semifinalists = sorted(filtered, key=lambda x: x['tcp_latency'])[:45]
    logger.info(f"🏟️ {title} (Проверка Xray: {len(semifinalists)} кандидатов...)")

    scored = []
    for server in semifinalists:
        metrics = check_real_connection(server)
        if history is not None:
            update_server_history(history, server, metrics)

        if metrics is None:
            continue

        if metrics['median'] > MAX_REAL_LATENCY:
            continue

        server['latency'] = int(metrics['median'])
        server['jitter'] = int(metrics['jitter'])
        server['loss_ratio'] = metrics['loss_ratio']

        tier_penalty = 0
        if mode != 'gaming':
            if server['tier_rank'] == 2:
                tier_penalty = 25
            elif server['tier_rank'] >= 3:
                tier_penalty = 60

        warp_penalty = 0
        if mode == 'warp' and server['transport'] not in {'ws', 'grpc'}:
            warp_penalty = 2000

        history_penalty = get_history_penalty(history, server) if history is not None else 0

        final_score = metrics['score'] + tier_penalty + warp_penalty + history_penalty
        server['final_score'] = final_score

        proto = 'SS' if server.get('is_ss') else ('Reality' if server['is_reality'] else server['transport'].upper())
        logger.info(
            f"✅ {server['info']['countryCode']:<4} | {proto:<8} | "
            f"Median: {int(metrics['median'])}ms | Jitter: {int(metrics['jitter'])}ms | "
            f"Loss: {int(metrics['loss_ratio'] * 100)}% | TCP: {server['tcp_latency']}ms | "
            f"Score: {int(final_score)}"
        )
        scored.append(server)

    scored.sort(key=lambda x: x['final_score'])
    if not scored:
        logger.warning(f"⚠️ {title}: Не найдено рабочих серверов.")
        return []

    return scored[:winners_needed]


def request_text(url, timeout=10):
    for _ in range(2):
        try:
            resp = requests.get(url, timeout=timeout, headers=HTTP_HEADERS)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception:
            continue
    return ''


def process_urls(urls, source_type):
    links = []
    ts = int(time.time())

    for url in urls:
        separator = '&' if '?' in url else '?'
        final_url = f"{url}{separator}t={ts}"
        content = request_text(final_url, timeout=10)
        if not content:
            continue

        for link in extract_links(content):
            parsed = parse_config_info(link, source_type)
            if parsed:
                links.append(parsed)

    return links


def fetch_smart_github_links(max_files_per_query=10):
    logger.info("🧠 GitHub Backup Search...")
    token = os.environ.get('GITHUB_TOKEN')
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        **HTTP_HEADERS
    }
    if token:
        headers['Authorization'] = f'token {token}'

    queries = [
        'vless:// reality extension:txt',
        'vmess:// extension:txt',
        'vless:// subscription'
    ]

    raw_links = set()
    api_url = 'https://api.github.com/search/code'

    for q in queries:
        params = {'q': q, 'sort': 'indexed', 'order': 'desc', 'per_page': max_files_per_query}
        try:
            resp = requests.get(api_url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get('items', [])
                for item in items:
                    raw_url = item.get('html_url', '').replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
                    if raw_url:
                        raw_links.add(raw_url)
            time.sleep(1.0)
        except Exception:
            continue

    return list(raw_links)


def server_name(server):
    code = server['info'].get('countryCode', 'XX')
    flag = ''.join(chr(127397 + ord(c)) for c in code.upper()) if len(code) == 2 else '🏳️'
    country = RUS_NAMES.get(code, code)
    ping = max(15, int(server.get('latency', 999)))

    if server['category'] == 'Game Server':
        return f"🎮 Game Reality | {flag} {country} | {ping}ms"
    if server['category'] == 'WHITELIST':
        return f"⚪ {flag} RU (WhiteList) | {ping}ms"
    if server['category'] == 'WARP':
        return f"🌀 {flag} {country} WARP | {ping}ms"
    return f"⚡ {flag} {country} | {ping}ms"


def main():
    logger.info("--- ЗАПУСК V79 (STABILITY-FIRST REAL PROBING) ---")

    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
    else:
        logger.error(f"❌ Error: Xray binary not found at {XRAY_BIN}")

    download_mmdb()
    init_geoip()
    history = load_history()

    backup_urls = fetch_smart_github_links(max_files_per_query=8)
    combined_general_urls = GENERAL_URLS + backup_urls

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        logger.info(f"🌐 Скачивание источников ({len(combined_general_urls)} combined + {len(WHITELIST_URLS)} whitelist)...")
        f1 = executor.submit(process_urls, combined_general_urls, 'general')
        f2 = executor.submit(process_urls, WHITELIST_URLS, 'whitelist')
        all_servers = f1.result() + f2.result()

    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    logger.info(f"🔍 Найдено {len(servers_to_check)} серверов. Начинаем TCP-сканирование...")

    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                working.append(res)

    b_white = [s for s in working if s['category'] == 'WHITELIST']
    b_univ = [s for s in working if s['category'] == 'UNIVERSAL']
    b_warp = [s for s in working if s['category'] == 'WARP']

    final_list = []

    game_winners = run_tournament(b_univ, TARGET_GAME, 'GAME CUP', 'gaming', history)
    game_ips = []
    for g in game_winners:
        g['category'] = 'Game Server'
        game_ips.append(g['ip'])
    final_list.extend(game_winners)

    b_univ_filtered = [s for s in b_univ if s['ip'] not in game_ips]
    final_list.extend(run_tournament(b_univ_filtered, TARGET_UNIVERSAL, 'UNIVERSAL CUP', 'universal', history))
    final_list.extend(run_tournament(b_warp, TARGET_WARP, 'WARP CUP', 'warp', history))
    final_list.extend(run_tournament(b_white, TARGET_WHITELIST, 'WHITELIST CUP', 'whitelist', history))

    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)

    time_str = msk_now.strftime('%H:%M')
    next_str = next_update.strftime('%H:%M')

    update_msg = f"📅 Обновлено: {time_str} (МСК) | След. обновление: {next_str}"
    info_link = (
        "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080"
        f"?encryption=none&type=tcp&security=none#{quote(update_msg)}"
    )

    result_links = [info_link]
    json_data = {
        'updated_at': time_str,
        'next_update': next_str,
        'servers': []
    }

    for s in final_list:
        name = server_name(s)
        base = s['original'].split('#')[0]
        result_links.append(f"{base}#{quote(name)}")

        code = s['info'].get('countryCode', 'XX')
        flag = ''.join(chr(127397 + ord(c)) for c in code.upper()) if len(code) == 2 else '🏳️'
        country = RUS_NAMES.get(code, code)

        type_label = 'VLESS'
        if s['is_hy2']:
            type_label = 'Hy2'
        elif s.get('is_ss', False):
            type_label = 'SS'
        elif s['is_reality']:
            type_label = 'Reality'
        elif s['is_pure']:
            type_label = 'TCP'

        json_data['servers'].append({
            'name': name,
            'category': s['category'],
            'country': country,
            'iso': code,
            'flag': flag,
            'ping': int(s.get('latency', 999)),
            'jitter': int(s.get('jitter', 0)),
            'loss_percent': int(s.get('loss_ratio', 1) * 100),
            'ip': s['ip'],
            'port': s['port'],
            'protocol': s['transport'].upper(),
            'type': type_label
        })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(base64.b64encode('\n'.join(result_links).encode('utf-8')).decode('utf-8'))

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    save_history(history)

    logger.info(f"DONE. {len(result_links)} links saved to {OUTPUT_FILE}.")
    logger.info(f"SECURE stats saved to {JSON_FILE} (No configs inside).")


if __name__ == '__main__':
    main()
