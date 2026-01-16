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
from urllib.parse import unquote, quote

# --- НАСТРОЙКИ ---
SOURCE_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt",
]

MAX_SERVERS = 15       
MAX_PER_COUNTRY = 3    
TIMEOUT = 1.5          
OUTPUT_FILE = 'FL1PVPN'

def get_flag(country_code):
    try:
        if not country_code or len(country_code) != 2: return "🏳️"
        return "".join([chr(127397 + ord(c)) for c in country_code.upper()])
    except:
        return "🏳️"

def get_real_geoip(ip):
    """Определяет страну. Если сбой API - возвращает None"""
    try:
        # Пауза, чтобы не словить бан API при многопоточности
        time.sleep(0.1) 
        url = f"http://ip-api.com/json/{ip}?fields=country,countryCode"
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('country', None), data.get('countryCode', None)
    except:
        pass
    return None, None

def extract_vless_links(text):
    regex = r"(vless://[a-zA-Z0-9\-@:?=&%.#_]+)"
    matches = re.findall(regex, text)
    return matches

def parse_config_info(config_str):
    try:
        part = config_str.split("@")[1].split("?")[0]
        if ":" in part:
            host, port = part.split(":")
            
            # Определяем Reality
            is_reality = False
            if "security=reality" in config_str or "pbk=" in config_str:
                is_reality = True
            
            # Достаем оригинальное имя на случай сбоя GeoIP
            original_remark = "Unknown"
            if "#" in config_str:
                original_remark = unquote(config_str.split("#")[-1]).strip()

            return {
                "ip": host, 
                "port": int(port), 
                "original": config_str,
                "original_remark": original_remark, 
                "latency": 9999,
                "score": 9999,
                "real_country": None,
                "country_code": None,
                "is_reality": is_reality
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

def check_server_smart(server):
    """Замеры + GeoIP + Fallback"""
    pings = []
    for _ in range(3):
        p = tcp_ping(server['ip'], server['port'])
        if p is not None: pings.append(p)
        time.sleep(0.05)
    
    if not pings: return None
        
    avg_ping = int(statistics.mean(pings))
    server['latency'] = avg_ping
    
    # --- SMART SCORE ---
    score = avg_ping
    if server['is_reality']:
        score -= 50 # Бонус Reality
    
    # Если пинг подозрительно низкий для WS - это CDN
    is_cdn_fake = False
    if avg_ping < 5 and not server['is_reality']:
        score += 300
        is_cdn_fake = True
    
    # --- GEOIP LOGIC ---
    country = None
    code = None
    
    # Если это не явный CDN, пробуем узнать IP
    if not is_cdn_fake:
        country, code = get_real_geoip(server['ip'])
    
    # ФОЛЛБЭК: Если API не ответил (или это CDN), пытаемся достать страну из названия
    if not country:
        # Ищем слова USA, Germany и т.д. в оригинальном названии
        rem = server['original_remark'].lower()
        if "united states" in rem or "usa" in rem or "🇺🇸" in rem:
            country, code = "United States", "US"
        elif "germany" in rem or "🇩🇪" in rem:
            country, code = "Germany", "DE"
        elif "netherlands" in rem or "🇳🇱" in rem:
            country, code = "Netherlands", "NL"
        elif "finland" in rem or "🇫🇮" in rem:
            country, code = "Finland", "FI"
        elif "russia" in rem or "🇷🇺" in rem:
            country, code = "Russia", "RU"
        elif "turkey" in rem or "🇹🇷" in rem:
            country, code = "Turkey", "TR"
        else:
            # Если совсем ничего не нашли
            country = "Unknown" if not is_cdn_fake else "Cloudflare"
            code = "XX" if not is_cdn_fake else "CDN"

    server['real_country'] = country
    server['country_code'] = code
    server['score'] = score
    return server

def main():
    print("--- ЗАПУСК V7 (VISUAL FIX) ---")
    raw_links = []

    for url in SOURCE_URLS:
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
                raw_links.extend(found)
        except Exception as e:
            print(f"Error {url}: {e}")

    raw_links = list(set(raw_links))
    servers_to_check = []
    for link in raw_links:
        p = parse_config_info(link)
        if p: servers_to_check.append(p)

    if not servers_to_check: exit(1)

    print(f"Checking {len(servers_to_check)} servers...")
    working_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_server_smart, s) for s in servers_to_check]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working_servers.append(res)

    working_servers.sort(key=lambda x: x['score'])

    final_list = []
    countries_count = {}
    
    print("\n--- ТОП СЕРВЕРОВ ---")
    for s in working_servers:
        if len(final_list) >= MAX_SERVERS: break
            
        country_name = s['real_country']
        country_code = s['country_code']
        
        # Упрощаем имена
        short_name = country_name.replace("United States", "USA").replace("United Kingdom", "UK").replace("Russian Federation", "Russia").replace("Netherlands", "NL")
        
        limit = MAX_PER_COUNTRY
        if country_code == "CDN": limit = 1 
        
        if countries_count.get(country_name, 0) < limit:
            
            # --- НОВЫЙ ВИЗУАЛ ---
            # 1. Меняем Ракету на Молнию
            speed_icon = ""
            if s['latency'] < 100: speed_icon = "⚡" # Быстро
            elif s['latency'] < 200: speed_icon = "✨" # Средне
            else: speed_icon = "🐢" # Медленно

            flag = get_flag(country_code) if country_code != "CDN" else "🌐"
            
            # 2. Убираем [REAL], меняем [WS] на WARP
            type_tag = "" 
            if s['is_reality']:
                type_tag = "" # Чистое имя для Reality
            else:
                type_tag = "WARP" # Метка для остальных

            # Сборка имени
            # Пример: ⚡ 🇺🇸 USA WARP | 50ms
            # Пример: ⚡ 🇩🇪 Germany | 35ms
            new_remark = f"{speed_icon} {flag} {short_name} {type_tag} | {s['latency']}ms"
            # Убираем двойные пробелы если тег пустой
            new_remark = " ".join(new_remark.split())

            base_link = s['original'].split('#')[0]
            s['original'] = f"{base_link}#{quote(new_remark)}"
            
            final_list.append(s)
            countries_count[country_name] = countries_count.get(country_name, 0) + 1
            
            try:
                print(f"Score: {s['score']} | {new_remark}")
            except:
                pass

    result_text = "\n".join([s['original'] for s in final_list])
    final_base64 = base64.b64encode(result_text.encode('utf-8')).decode('utf-8')
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(final_base64)
    print("Saved.")

if __name__ == "__main__":
    main()
