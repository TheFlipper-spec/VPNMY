import sys
# --- ПАТЧ КОДИРОВКИ ---
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
import statistics
import copy
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, quote, parse_qs

# --- НАСТРОЙКИ ---
GENERAL_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

WHITELIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
]

# КОЛИЧЕСТВО ПОБЕДИТЕЛЕЙ (ЖЕСТКИЙ ЛИМИТ)
TARGET_GAME = 1       # 1 Игровой (Лучший из лучших)
TARGET_REALITY = 3    # 2 Обычных (Стабильные и быстрые)
TARGET_WARP = 2       # 1 Лучший WARP
TARGET_WHITELIST = 2  # 1 Лучший WhiteList

TIMEOUT = 1.5
OUTPUT_FILE = 'FL1PVPN'
TIMEZONE_OFFSET = 3 
UPDATE_INTERVAL_HOURS = 3

# ПЕРЕВОДЧИК
RUS_NAMES = {
    'US': 'США', 'DE': 'Германия', 'NL': 'Нидерланды', 'FI': 'Финляндия', 
    'RU': 'Россия', 'TR': 'Турция', 'GB': 'Великобритания', 'FR': 'Франция', 
    'SE': 'Швеция', 'CA': 'Канада', 'PL': 'Польша', 'UA': 'Украина',
    'KZ': 'Казахстан', 'BY': 'Беларусь', 'EE': 'Эстония', 'LV': 'Латвия', 
    'LT': 'Литва', 'JP': 'Япония', 'SG': 'Сингапур', 'BG': 'Болгария',
    'CZ': 'Чехия', 'RO': 'Румыния', 'IT': 'Италия', 'ES': 'Испания',
    'AT': 'Австрия', 'NO': 'Норвегия'
}

# ПРИОРИТЕТЫ
PRIORITY_1_NEIGHBORS = ['FI', 'EE', 'LV', 'LT', 'SE', 'PL', 'RU', 'KZ', 'BY', 'UA']
PRIORITY_2_EUROPE = ['DE', 'NL', 'AT', 'CZ', 'BG', 'RO', 'NO', 'TR', 'DK', 'GB', 'FR', 'IT', 'ES']

CDN_ISPS = [
    'cloudflare', 'google', 'amazon', 'microsoft', 'oracle', 
    'fastly', 'akamai', 'cdn77', 'g-core', 'alibaba', 'tencent',
    'edgecenter', 'servers.com', 'digitalocean', 'vultr'
]

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_ip_info_retry(ip):
    for attempt in range(2):
        try:
            time.sleep(0.2 + attempt * 0.2) 
            url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,org,isp"
            resp = requests.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success':
                    return data
                return {'status': 'fail', 'countryCode': 'XX', 'org': 'Private', 'isp': 'Private'}
        except:
            pass
    return None

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str, source_type):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            query = config_str.split("?")[1].split("#")[0]
            params = parse_qs(query)
            transport = params.get('type', ['tcp'])[0].lower()
            security = params.get('security', ['none'])[0].lower()
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str,
                "original_remark": original_remark,
                "latency": 9999,
                "jitter": 0,
                "final_score": 9999,
                "info": {},
                "transport": transport, 
                "security": security,
                "source_type": source_type,
                "geo_rank": 99
            }
    except:
        pass
    return None

def tcp_ping(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.perf_counter()
        res = sock.connect_ex((host, port))
        end = time.perf_counter()
        sock.close()
        if res == 0:
            return (end - start) * 1000
    except:
        pass
    return None

def calculate_geo_rank(server):
    code = server['info'].get('countryCode', 'XX')
    ping = server['latency']
    is_fake = False
    if ping < 40 and (code in PRIORITY_1_NEIGHBORS or code in PRIORITY_2_EUROPE):
        is_fake = True
    if is_fake: return 5 
    if code in PRIORITY_1_NEIGHBORS: return 1 
    if code in PRIORITY_2_EUROPE: return 2
    if code == 'US' or code == 'CA': return 4
    return 3

def check_server_initial(server):
    """Первичная быстрая проверка"""
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    ip_data = get_ip_info_retry(server['ip'])
    if not ip_data:
        if server['source_type'] == 'whitelist':
             ip_data = {'countryCode': 'RU', 'org': 'Unknown', 'isp': 'Unknown'}
        else:
             return None 
    
    server['info'] = ip_data
    code = ip_data.get('countryCode', 'XX')
    org_str = (ip_data.get('org', '') + " " + ip_data.get('isp', '')).lower()
    
    is_warp_cdn = False
    if server['transport'] in ['ws', 'grpc']: is_warp_cdn = True
    if any(cdn in org_str for cdn in CDN_ISPS): is_warp_cdn = True
    if avg_ping < 2: is_warp_cdn = True
    if server['security'] != 'reality': is_warp_cdn = True

    if server['source_type'] == 'whitelist':
        server['category'] = 'WHITELIST'
    elif is_warp_cdn:
        server['category'] = 'WARP'
    else:
        server['category'] = 'REALITY'

    server['geo_rank'] = calculate_geo_rank(server)
    return server

def stress_test_server(server):
    """СТРЕСС-ТЕСТ: 5 замеров для выявления лагов"""
    pings = []
    for _ in range(5):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.15) # Пауза побольше для точности
    
    # Если пакеты теряются (меньше 4 успешных из 5) - это мусор
    if len(pings) < 4: 
        return 9999, 9999
        
    avg_ping = statistics.mean(pings)
    try:
        jitter = statistics.stdev(pings)
    except:
        jitter = 0
    
    return avg_ping, jitter

def run_tournament(candidates, winners_needed, strict_geo=False):
    """Проводит турнир среди кандидатов"""
    if not candidates: return []
    
    # Отбираем топ-8 претендентов по первичной сортировке (GeoRank + Ping)
    # Если strict_geo=True, берем только ранги 1 и 2
    if strict_geo:
        preliminary = [c for c in candidates if c['geo_rank'] <= 2]
    else:
        preliminary = candidates
        
    if not preliminary: # Если строгий отбор не дал результатов, берем лучших из того что есть
         preliminary = candidates
         
    # Берем топ-8 для стресс-теста (чтобы не ждать вечность)
    finalists = sorted(preliminary, key=lambda x: (x['geo_rank'], x['latency']))[:8]
    
    scored_results = []
    print(f"   >>> Турнир среди {len(finalists)} серверов...")
    
    for f in finalists:
        avg, jitter = stress_test_server(f)
        
        # ФОРМУЛА СТАБИЛЬНОСТИ: Score = Ping + (Jitter * 3)
        # Штраф за лаги очень высокий
        score = avg + (jitter * 3)
        
        # Если это игровой турнир, штрафуем за плохой GeoRank
        if strict_geo:
             score += (f['geo_rank'] * 10) 
             
        f['latency'] = int(avg)
        f['jitter'] = int(jitter)
        f['final_score'] = score
        scored_results.append(f)
        
    # Сортируем по финальному баллу (меньше = лучше)
    scored_results.sort(key=lambda x: x['final_score'])
    
    # Возвращаем победителей
    return scored_results[:winners_needed]

def process_urls(urls, source_type):
    links = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                found = extract_vless_links(content)
                if not found:
                    try:
                        decoded = base64.b64decode(content).decode('utf-8', errors='ignore')
                        found = extract_vless_links(decoded)
                    except: pass
                for link in found:
                    p = parse_config_info(link, source_type)
                    if p: links.append(p)
        except Exception as e:
            print(f"Error {url}: {e}")
    return links

def main():
    print("--- ЗАПУСК V20 (ELITE SQUAD) ---")
    
    all_servers = []
    all_servers.extend(process_urls(GENERAL_URLS, 'general'))
    all_servers.extend(process_urls(WHITELIST_URLS, 'whitelist'))
    
    unique_map = {s['original']: s for s in all_servers}
    servers_to_check = list(unique_map.values())
    
    if not servers_to_check: exit(1)

    print(f"Первичный отсев {len(servers_to_check)} серверов...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(check_server_initial, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    # Раскладываем по корзинам
    bucket_whitelist = [s for s in working_servers if s['category'] == 'WHITELIST']
    bucket_reality   = [s for s in working_servers if s['category'] == 'REALITY']
    bucket_warp      = [s for s in working_servers if s['category'] == 'WARP']

    final_list = []

    # 1. ВЫБОР GAME SERVER (1 шт)
    # Используем строгий гео-фильтр (только соседи/европа)
    print("\n⚔️ Выбор GAME SERVER...")
    game_winners = run_tournament(bucket_reality, TARGET_GAME, strict_geo=True)
    
    if game_winners:
        champion = copy.deepcopy(game_winners[0])
        champion['category'] = 'GAMING'
        final_list.append(champion)
        print(f"🏆 Победитель: {champion['info'].get('countryCode')} (Score: {champion['final_score']:.1f})")
        
        # Удаляем победителя из списка Reality, чтобы не дублировать
        # (сравниваем по IP и порту)
        bucket_reality = [s for s in bucket_reality if s['ip'] != champion['ip'] or s['port'] != champion['port']]

    # 2. ВЫБОР ОБЫЧНЫХ REALITY (2 шт)
    print("\n⚔️ Выбор TOP REALITY...")
    reality_winners = run_tournament(bucket_reality, TARGET_REALITY, strict_geo=False)
    final_list.extend(reality_winners)

    # 3. ВЫБОР WARP (1 шт)
    print("\n⚔️ Выбор TOP WARP...")
    warp_winners = run_tournament(bucket_warp, TARGET_WARP, strict_geo=False)
    final_list.extend(warp_winners)

    # 4. ВЫБОР WHITELIST (1 шт)
    print("\n⚔️ Выбор TOP WHITELIST...")
    wl_winners = run_tournament(bucket_whitelist, TARGET_WHITELIST, strict_geo=False)
    final_list.extend(wl_winners)

    # ГЕНЕРАЦИЯ
    print("\n--- СБОРКА ПОДПИСКИ ---")
    
    # INFO
    utc_now = datetime.now(timezone.utc)
    msk_now = utc_now + timedelta(hours=TIMEZONE_OFFSET)
    next_update = msk_now + timedelta(hours=UPDATE_INTERVAL_HOURS)
    info_remark = f"📅 Обновлено: {msk_now.strftime('%H:%M')} | След: {next_update.strftime('%H:%M')}"
    info_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&type=tcp&security=none#{quote(info_remark)}"
    
    result_links = [info_link]

    for s in final_list:
        code = s['info'].get('countryCode', 'XX')
        
        if code == 'XX' and s['category'] == 'WARP':
            rem = s['original_remark'].lower()
            if "united states" in rem or "usa" in rem: code = 'US'
            elif "germany" in rem: code = 'DE'
            elif "finland" in rem: code = 'FI'
            elif "netherlands" in rem: code = 'NL'
        
        country_ru = RUS_NAMES.get(code, code)
        if code == 'XX': country_ru = "Глобал"

        flag = get_flag(code)
        ping = s['latency']
        
        new_remark = ""
        
        if s['category'] == 'GAMING':
            # Добавим значок стабильности
            new_remark = f"🎮 GAME SERVER | {country_ru} | Stable"

        elif s['category'] == 'WHITELIST':
            new_remark = f"⚪ 🇷🇺 Россия (WhiteList) | {ping}ms"
            
        elif s['category'] == 'WARP':
            new_remark = f"🌀 {flag} {country_ru} WARP | {ping}ms"
            
        else:
            isp_lower = (s['info'].get('isp', '')).lower()
            vps_tag = ""
            if any(v in isp_lower for v in ['hetzner', 'aeza', 'm247', 'stark']):
                vps_tag = " (VPS)"
            
            # Для элиты добавим значок "Звезда" или "Молния"
            new_remark = f"⚡ {flag} {country_ru}{vps_tag} | {ping}ms"

        base_link = s['original'].split('#')[0]
        final_link = f"{base_link}#{quote(new_remark)}"
        result_links.append(final_link)
        
        print(f"[{s['category']}] {new_remark} (Score: {s.get('final_score', 0):.1f})")

    result_text = "\n".join(result_links)
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print(f"\nSaved {len(result_links)} links.")

if __name__ == "__main__":
    main()
