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
from datetime import datetime
from urllib.parse import quote, parse_qs

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

# Твоя личная хардкод-нода (Несгораемый #1) - изменено название
MY_PERSONAL_NODE = "vless://3a9fd220-edb1-41b9-9a78-3f61cf8bd937@212.22.82.138:443?type=tcp&encryption=none&security=reality&pbk=PDooiand9xm-TAu-8HajBWr_is01x3IqABwYct5OiAo&fp=chrome&sni=max.ru&sid=10778ea288&spx=%2F&pqv=vyoU6Up2ZhRKlhT4IJaFt0y9Js0VG0Sh2tsrDkPcYhi2w5X8jktGxvNvlXwErzrsZo-Ur_Y4YgFbL_Z2hLlgjzwT7BX7jSKlxeFyEIe_3AparaBodbnSlsGyTNR81rAL_hqnFg86NTIEZ86FQ3YBCWPv03csYbYeVIjr7ZdbnmBJ0TxSV0f6H1oJUzAUxvIiO5Bytfs9zHKph0iIuyQR7jiodvRkBT2fxJQ4nXBu8hba4Y9GILdRASWoJ4ntN0S4Wx2_4Te0BBt4OXiIDFFt9tgDzSbERKN3cDKUJYSwe3SqmWrTK3uyjws7VzSL8nBW_M96gDyZTZ4JpXAdp5M7mbng7egn6pj-b4id3OKAN4lODWviZfBvh4KgCRT4C-ozP4JDRElEFWZHYts9RWI-G44OBz3F99aIp4lNCEtad_oiDlFSFup7eEUOW_RhxQzhlpYxgv5ZERNbdBXHa2hTwmA6RLvgPkibLg23sLJ9TiZ5w672GHSqHVn3pU-udoMZz40ml1VQM8kyFOrZPRlLAtKkJwaREs_1g6PIOH8dIH1TqYbAA4pAJIfbkYx76iQufct-C9lbWTPhk7j89iALPgR7S5k72WDhlP0VhyOK9MhkNhXIvPqUK8dKWYAREsF30IeWbWGSWrcNNAVF-Af1PC3MUqHMG0nUSyUjvCfk4DAyK5zG09Jp81nDlmWYAMmvwDI-FaHfx4rmbCD8Hgf_WKdiZV_DSuUYvEGquh1wxYjVmSfpOsYsU-2vapIBiT3gyBoLKfDcQWDmpDGhQaRiIqUjJUcsX2HhSJDJl9OJb11JAQZVKo-BtbVANJqWWRaXGzdSJsQoX1kdM5K_4imxBCtxMLv_sH75sdJD5CKvdqA8vMErl17eNVBc3qVRsSmC23SQIavDIrreMOhhWtHNaDpcGKHKuvhvL1OQyrEeMm7wundxLf39Wl0Beggb9JkG2hzs0t5XsYdPaf63nky3xlfdTIT1wZptMV_UMtclqzTnw78M8DnwtoS-VCu9nzltSNe7Juit-wZNY1HjaBupEE9H1_fz7j24ptjxmxNxDNR4sH8T3LnfdokiPieSudOHRjZ_crHEHSKQkBeT1pamB-HP2vQTlvIyYfPLPl0AR0Feudlaz5rlof-Rf-zf2MhDBTpzWwhJRFJWDL0M5E-Puth9GPVFU5P3jDk_Q7G3KcagMjPgvRFEvaNUSNosAn9SmQu5j8Nyl1Zeyye_ZHDDaS30bHiCEPA-VIZTj8-u1ZBGgwAlPIiWUJOzwtKBkYkJIu9CFJUS75ujXrKnoeqvuTN9QcoyWIfo_Q2kch_jSNjtytW6ihUikCyl-IRmgBAVRZbj1lsGgMLfz5gB8T9xebq6PR6ugYlU6uZle9q5tSI1Mz44Sa_RKZ714z5eXyRRZewcfqElZtA316Ryc34VUSiUTcxp17e-PiqqYv0V-n96Ro6s0SXgXopzw7mGSQmONmY6Opo9nxtaOuFH9TjvShOnKJ79-WxOPA0rZM1W7Z5m1z0tEljZK0MjFZBDE1NpFbZcdZrfmGG2ctSWgwKdNUIor1cV2fup9EOj7EgnHJ12GW1m8lJYQCfhsnvtmApkw2aH7pdhPBvq6ih4wpdmTCWkpTTeBpWaHfR1U96ZFSHMw4HXkF6c1VZsoKtTfInmt1iFAnsIm2-VUQUMozCPrA7wmoZwHxoCGBjQInuDJByLSAcurntW027egCNbjElWoxxnJY0NboLK99VaQaQ63U2gyqOe9lQ2lAmluiHmtBtn0Yr_AbCCVKPtSLdc-zkFTS_8HsREvR61p4-B_ebh5W6EG1u31xYtT9UQTQ5Ug3phtNqpx5Svpu35jVnRHWjt7DnIYgNgXGeKOzHw0sHla5ArqeIByT71pFz0P4jXQy1NFcdNvPEGsGlddhe-GRn7aAfNRK4CamuNzQ97ASGcmYlK6REtp4y5YnH67wv-SPRp70lHVZHN5pxRNsxY407kewtYV-clCoE3NgaWlWzbYnUDtXTP5vSlVF_39jtM6kvwK3IU08IRz32WWw-K9qU41rowSMj6c7Xw5EzuF4Ze4Uv_puWEdj8XcqnSSPaCLzAFhOvrbwTvGsLB7ccKGtHQia5wKpvkJ9vkqgsygNA3PckCmBlSjCbQqCsJA_sjngHuwf2DolgyxrdiU27aznMugxH9WBU2WFdKhuxaO_pcCFLoiHz9zFcVVBdz6wSt0Z9o9dJXeDznTnKetrnUe0_Kw1QEjAIWUrL1cipfEnf2A1jOB0amx5Xz_-B0K9PiP5HBuq0kFdDoWV-czAbRQ7YRoRbH8JknshuW79E03MbpQMZXiijfHpWR6ZHKR3R9UZeb1LCacTnYrcEX5DDK1DNJgnM88gezZZwMPWAIJdz4w9VQ1twZ_142T42YB9xcNuX5bdt9I9MYXKgYYODPcKyj2N8e5OkB_m8IvQya0OSU_wXjgxPTPP2VV_BrwFndysWlM0XMXPvOWSwhs5znYW9fzKnn375KDfhPnu1oSvG7sGmSNpejxSOh59E8C8z-Sr5c_T_uUAY0SVlhAoY0npyeh7DYXbwvSSzl-c3I2HArDvNFAGVxT3V9oDjhtPgOAQE&flow=xtls-rprx-vision#💎 V1A RU / БЕЛЫЕ СПИСКИ"

# Твоя личная хардкод-нода (Несгораемый #2) - Финляндия
MY_FINLAND_NODE = "vless://d975972e-32ba-4684-ad8a-2050e591507b@212.22.82.138:8443?type=tcp&encryption=none&security=reality&pbk=0wb9OHlgxLXjUioPcuDGs_RBQ4hkww2saLKTxT0T-jU&fp=chrome&sni=vk.com&sid=c6424a351e384d&spx=%2F&pqv=uhaswgBBj0v8j7v3nYtbB5L0sikWI4RS9L-zrfkGqZyGnp27WO99gL-OqPuNkJkPvVQTJ_hFfTXYXSNB8fOe0OiPUk_KzB9qFZXcvayETO01xBhm6cOqMGxCxxQxOWrpkjU3yWAxbTyh5kiqC3fkVjhDZj_01mbDmx9w5e_HvoMgJpNubll-FECxr4d1Vgoz3-MVXMQrKFlyuLcqQg6lsZXYMHAEbBn2hHoXQV2ga67Hw1VxnVPcSJ6W_UGKhM4qj9IUMMXiiYoUAn7VYgbDN6bF8zxnvz0wUnh7MoYudubGNibOfHU1jBsMZmt4tJqRtlq65ejctyENOc-D54VP70oDVUVgDnSRve4G91BkndRtCx0L9H76AcxaUERfiSdIPkqD7DNkI6dnQi3dbx2X-MaNBXUZTAGzU2EF8fwlbgKiBpjUJLf64a1w1LeCIZqSsTNT-Kk_UdsSdAazDXKPYF0t020YyOv1UE3x25vtjgkxf-NxFTAVjjx8v7OJdKigH8g0OsWdwreobR2A0pPEnbz7WW_RqtnJAnthFYmPuMHAwZPFMotWTI_jvc7DEddy27P4ZSeO4vf6LJqFDKBglg1sQBh7NiVTX79FoUDuP5RMzDZ2up3z1WLxVzhLOlBHayVcPV-n6DOEu_vP4wjLjxrk5IMSCjesqZoBQMrOSUvhqvo-Re7gygagE1BMq4o4rQ0aGxstXqr95tCE9bxiJPx4FIoZRVgGv2L7AMIQSoR9ng6u_pC_fGRBG7Hq5eQiauEiXr2ood5zZOkK7XaO18CwmDxL2tbNii2uOruUv07J-2SpVeWxh9MtA1MXvuxnVJ8wa6M9gtY1ZTHP9rn54XRQGm0EUlFoWehaK0hv3gRCE03euF5qZ0Dcsirp_jHMB5fvUPlgO_nllhZym-F-J_KprQo-m16v5nRABVoHicW1G8jws5ducJZ06Ue3jVnOkKpR0Ia5D1uqoUzuyoR1DYTym2DS92znzBdB9FhkBoSzyOQnh6BYnMDt_YEe_skUunm12A9C1UvtuZkNG12DMPYvbZ1cL4q9mekQ63tC-4_B_fd0Y0m3SFvNtlZJYiOrF0YD7PpzwSYELX-yavfnvsRFXWkCmsOOM96e35ICa5qLQdpVkfKTUyFuZkBIwzhykSdn-iaz7l61N0V1jiaH5RfgTigH_fjXtugPN1BwLrJGpli_95NiYXOoZaxfajOk9AYzC_7Mi7YDIXQMS52XZ5-fRXfO8kbZWsbtAtht6YqXN-gftmJXGLmluyBoNuxHztzcqVCx5r8uV3KuMm6xlGNKdG5twUiEWvuF_MI0skbqKM1-e6VdNbmsJOTowcrCSOsDA9y8dWki60qg_Nz6C_dVVh4mHHEzfJTwwW5Jt22tEAwn6ZOvocKEjQDKLYXjR81ayt59_tsHnEYW5NhqGiumQ5PHP-RuTFWv0UV6y7ftf-bIurkSfNNWvCjFEl6Fbn-R0sDSzcfHpFPZuq5dQj_H34AQc-wbjoMWFIghKLLbBV628xPmZRNAxzS43_GT3N0C5POHxGoyXX0_ZEMNKjNHb_ylTAzXc5yzZlznQ0NT-oZK1axtqExHfJeS_NlL5nZ5i6WKpdls3jcZP9kPcdfXrf5SGtY7iuUnN3WNmYwt25c63vjFk-bBAw8FouDi-bBtANVSDfEuC6ecW9-y0M9cV9NjsQP21Y849KCU8GYWgNN1r2gMCyJX7IScURBZOkMsgV4rC1OQjvTvilfnzd2xmuYyV6JuhQHtayYJTe5byhV7Ct0TO4XT3kxC_yrdi5JXFq0w1dtN4YOCPp1CsTQb3fVP0AWAorbgbxzPeOlIiQk37LCOid4eYBwB4mQngkGyWQFEb9YeEyMHbSmIuRGAZFnnELzUoNP9uplN238lASzt0ZwaT17isqcwOByYKtxnhthxQ1LybVzJRPKVqQCgMjQ_KaRxY_E2G7G4mUKAxdHzLQ-XPCZJchsHwlxNSjeGGrrFbWuMptoBZuUYMPhipuqR9oHkkZdWF6cmxXDacrHfxz1ic_lrbq1b9UlJ63knbdVYEcv3gEYqYk5rvT1HauGgjXtVnluiMhLW7a0cSst1X1ui71zLC90XJysWnWWgPPPz84t64nvzna5lQt8RiqNFr1AxuJVXu8vN6RfJLCjGGDSQ2iUtUg6Iv_e7k-NTjSqQSzZzMBp85E_X44SbKLvN19s3XGRsRPhj1KPISENFFJktWMvaTHd75C25FSq5nsjmZvs3tbtHEhhq4KIs3TCNb8gyBiLunb94Byw3a7W8Yrp9jCdlSRVGNyy5ouB3cVz-jKjwUUDEgaR_VIzEDF7HQ6k2F3qJh_XkdK8AUj0AgtcT3K7FYHaVZvQu0-bMFSJg9R3GCmAO2qKiynLojxeb3nz3VGgJtepEXxnur2ftqiXZ61EYqh2sGEtV2zSjQG5fN1fy0y9nRWO_E7ftGER0PqPOBiGVY0R7o5eBnQFtbc-52DvZ7oRYd6oACBjm0tfhtmsyNIlfLddsKX7nNEXADvjVDpGYTdx8q4jpOoUt4HwC3y-iS3GD7qRG3-WfhxgSCmiIg11VoA7weZmrSmxPLIEA0THRotczv-w#💎 🇫🇮  V1A / Финляндия"

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
    
    # №3-10: Топ Global (только иностранные серверы для V1A)
    needed_global = TOTAL_SERVERS_WANTED - 2 # Минус 2 твоих личных хардкода
    final_selection.extend(pool_global[:needed_global])

    logger.info(f"📊 Итого собрано: 2(Хардкода) + {len(final_selection)} живых узлов.")

    # Формирование файла
    result_links = []
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header_link)
    
    # №1: Хардкод нода пользователя
    result_links.append(MY_PERSONAL_NODE)
    
    # №2: Хардкод нода Финляндии
    result_links.append(MY_FINLAND_NODE)

    # Имя изменено здесь тоже для единообразия в json файле
    json_stats = {"servers": [
        {"name": "💎 V1A RU / БЕЛЫЕ СПИСКИ (Hardcoded)", "ip": "212.22.82.138", "protocol": "vless reality"},
        {"name": "💎🇫🇮  V1A / Финляндия", "ip": "212.22.82.138", "protocol": "vless reality"}
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
