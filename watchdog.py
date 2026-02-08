import json
import os
import sys
import time
import subprocess
import requests
import base64
import random
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse, parse_qs

# ═══════════════════════════════════════════════════════════════
#  FL1P VPN WATCHDOG V3.6 - PERFORMANCE PRIORITY
# ═══════════════════════════════════════════════════════════════

STATS_FILE = 'stats.json'
RESERVE_FILE = 'reserve_pool.json'
OUTPUT_FILE = 'FL1PVPN'
LOG_FILE = 'vpn_scanner.log'
XRAY_BIN = "./xray"

# Словарь стран (перенесен наверх для доступности)
RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция', 'TR': 'Турция',
    'RU': 'Россия', 'UA': 'Украина', 'MD': 'Молдова', 'CF': 'Cloudflare',
    'US': 'США', 'XX': 'Unknown', 'JP': 'Япония', 'KR': 'Корея', 'SG': 'Сингапур',
    'BY': 'Беларусь', 'KZ': 'Казахстан'
}

# Убедимся, что Xray исполняемый
if os.path.exists(XRAY_BIN):
    os.chmod(XRAY_BIN, 0o755)

def log(msg, level="INFO"):
    # Время МСК
    ts = datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M:%S')
    print(f"{ts} [{level}] {msg}")
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{ts} [{level}] {msg}\n")
    except: pass

def get_flag(cc):
    if not cc or len(cc) != 2 or cc == 'XX': return "❓"
    return "".join([chr(127397 + ord(c)) for c in cc.upper()])

# 🔥 1. АВТО-ОПРЕДЕЛЕНИЕ РОЛИ ПО ИКОНКЕ (ЕСЛИ В ФАЙЛЕ UNKNOWN)
def identify_role(server):
    # Если роль уже есть и она валидная - возвращаем её
    current_role = server.get('role', 'UNKNOWN')
    if current_role and current_role not in ['UNKNOWN', 'None', '']:
        return current_role
    
    # Гадаем по имени (Fallback)
    name = server.get('name', '')
    if "🎮" in name: return "GAME"
    if "🌀" in name: return "WARP"
    if "⚪" in name: return "WHITELIST"
    if "⚡" in name: return "UNIVERSAL"
    
    return "UNIVERSAL" # По умолчанию

# 🛠 2. ГЕНЕРАЦИЯ КОНФИГА ДЛЯ ПРОВЕРКИ
def gen_check_config(server, local_port):
    try:
        link = server.get('original', '')
        if not link.startswith('vless://'): return None
        
        # Удаляем фрагмент
        link = link.split('#')[0]
        
        uuid = link.split('@')[0].replace('vless://', '')
        address_part = link.split('@')[1].split('?')[0]
        
        if ':' in address_part:
            host, port = address_part.split(':')
        else:
            return None
            
        params = {}
        if '?' in link:
            query = link.split('?')[1]
            params = {k: v[0] for k, v in parse_qs(query).items()}

        stream_settings = {
            "network": params.get('type', 'tcp'),
            "security": params.get('security', 'none')
        }
        
        if stream_settings['network'] == 'ws':
            stream_settings['wsSettings'] = {
                "path": params.get('path', '/'),
                "headers": {"Host": params.get('host', '')}
            }
        elif stream_settings['network'] == 'grpc':
            stream_settings['grpcSettings'] = {
                "serviceName": params.get('serviceName', '')
            }
            
        if stream_settings['security'] == 'reality':
            stream_settings['realitySettings'] = {
                "fingerprint": params.get('fp', 'chrome'),
                "serverName": params.get('sni', ''),
                "publicKey": params.get('pbk', ''),
                "shortId": params.get('sid', ''),
                "spiderX": params.get('spx', '/')
            }
        elif stream_settings['security'] == 'tls':
            stream_settings['tlsSettings'] = {
                "serverName": params.get('sni', ''),
                "fingerprint": params.get('fp', 'chrome')
            }

        config = {
            "log": {"loglevel": "none"},
            "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks"}],
            "outbounds": [{
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": int(port),
                        "users": [{"id": uuid, "encryption": "none", "flow": params.get('flow', '')}]
                    }]
                },
                "streamSettings": stream_settings
            }]
        }
        return config
    except:
        return None

# 🏥 3. ПРОВЕРКА ЖИЗНИ (REAL XRAY TEST)
def check_server_alive(server):
    # Быстрый TCP connect
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        
        ip = server.get('ip')
        if not ip and 'original' in server:
             clean_link = server['original'].split('#')[0]
             parts = clean_link.split('@')[1].split('?')[0].split(':')
             ip = parts[0]
             port = int(parts[1])
        else:
             port = server.get('original', '').split(':')[-1] # fallback logic unlikely needed if ip present
             if 'vless://' in server['original']:
                 clean = server['original'].split('@')[1].split('?')[0]
                 ip, port = clean.split(':')

        if ip:
            if s.connect_ex((ip, int(port))) != 0:
                s.close()
                return False
        s.close()
    except:
        return False

    # Xray (HTTP 204)
    local_port = random.randint(20000, 40000)
    config = gen_check_config(server, local_port)
    if not config: return False 

    proc = None
    try:
        config_str = json.dumps(config)
        proc = subprocess.Popen([XRAY_BIN, "-stdin"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        proc.stdin.write(config_str.encode())
        proc.stdin.close()
        time.sleep(2)

        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        # Проверка через Cloudflare (быстро и надежно)
        resp = requests.get('https://cp.cloudflare.com/', proxies=proxies, timeout=4)
        if 200 <= resp.status_code < 300:
            return True
            
    except:
        pass
    finally:
        if proc:
            proc.terminate()
            try: proc.wait(timeout=1)
            except: proc.kill()
            
    return False

# ♻️ 4. ПОИСК ЗАМЕНЫ (PERFORMANCE BASED)
def find_replacement(role, exclude_ips, preferred_cc=None):
    if not os.path.exists(RESERVE_FILE):
        return None, None
    
    try:
        with open(RESERVE_FILE, 'r', encoding='utf-8') as f:
            pool = json.load(f)
    except:
        return None, None
    
    # 1. Фильтрация кандидатов
    # Исключаем уже использованные IP
    base_candidates = [s for s in pool.get('servers', []) if s['ip'] not in exclude_ips]
    
    candidates = []
    
    # Логика фильтрации по странам в зависимости от роли
    if role == 'WHITELIST':
        # Для вайтлиста ищем ТОЛЬКО Россию
        candidates = [s for s in base_candidates if s.get('cc') == 'RU']
    else:
        # Для всего остального (Game, Universal, Warp) ищем всё, КРОМЕ России
        candidates = [s for s in base_candidates if s.get('cc') != 'RU']

    if not candidates:
        return None, pool

    # 2. СОРТИРОВКА (СЕРДЦЕ ЛОГИКИ)
    if role == 'GAME':
        # Для Игр: Сначала НИЗКИЙ ПИНГ (asc), потом высокая скорость (desc)
        # 9999 - если пинга нет, чтобы улетел в конец
        candidates.sort(key=lambda x: (x.get('ping', 9999), -x.get('speed', 0)))
        sort_mode = "PING"
    else:
        # Для Universal/Warp: Сначала ВЫСОКАЯ СКОРОСТЬ (desc), потом низкий пинг (asc)
        candidates.sort(key=lambda x: (-x.get('speed', 0), x.get('ping', 9999)))
        sort_mode = "SPEED"

    best = None
    
    # 3. Попытка сохранить страну (если была хорошая)
    if preferred_cc:
        # Ищем кандидатов той же страны
        same_cc = [s for s in candidates if s.get('cc') == preferred_cc]
        if same_cc:
            # Так как candidates уже отсортированы по качеству, 
            # первый элемент в same_cc будет ЛУЧШИМ из этой страны
            best = same_cc[0]
            log(f"   ✨ Found preferred country match: {preferred_cc} (Mode: {sort_mode})", "INFO")

    # 4. Если страны нет или она плохая - берем ПРОСТО ЛУЧШЕГО
    if not best:
        best = candidates[0]
        cc = best.get('cc')
        log(f"   💎 Selected best available: {cc} (Mode: {sort_mode}, Speed: {best.get('speed')}, Ping: {best.get('ping')})", "INFO")
    
    # Удаляем выбранного из пула
    if best in pool['servers']:
        pool['servers'].remove(best)
        pool['count'] = len(pool['servers'])
    
    return best, pool

def remove_fragment(link):
    if not link: return ""
    return link.split('#')[0]

# 🚀 MAIN
def main():
    log("🐕 FL1P VPN WATCHDOG V3.6 - STARTED")
    
    if not os.path.exists(STATS_FILE):
        log("❌ stats.json not found", "ERROR")
        return

    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            stats = json.load(f)
    except:
        log("❌ stats.json is corrupted", "ERROR")
        return

    active_servers = stats.get('servers', [])
    new_servers = []
    used_ips = set(s.get('ip') for s in active_servers)
    modified = False
    
    log(f"🔍 Checking {len(active_servers)} active servers...")
    
    for i, s in enumerate(active_servers):
        # 1. Исправляем/Определяем роль
        old_role = s.get('role')
        role = identify_role(s)
        
        # Обновляем роль в памяти, если скрипт был обновлен
        if old_role != role:
            s['role'] = role
            
        name = s.get('name', 'Unknown')
        
        # 2. Проверяем жизнь
        is_alive = check_server_alive(s)
        status = "✅ ONLINE" if is_alive else "❌ DEAD"
        log(f"   [{i+1}] {name} ({role}) -> {status}")
        
        if is_alive:
            new_servers.append(s)
        else:
            # 3. Замена (DEAD)
            log(f"   ⚠️ Replacing {name}...", "WARNING")
            
            # Предпочитаемая страна = та, которая упала
            preferred_cc = s.get('cc')
            
            replacement, new_pool = find_replacement(role, used_ips, preferred_cc)
            
            if replacement:
                flag = get_flag(replacement.get('cc', 'XX'))
                cc_name = RUS_NAMES.get(replacement.get('cc'), replacement.get('cc'))
                
                # 4. Формируем имя и иконку на основе РОЛИ (Slot Role)
                if role == 'GAME':
                    time_label = datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M')
                    new_name = f"🎮 {flag} {cc_name} | 📅 {time_label}"
                elif role == 'WARP':
                    new_name = f"🌀 {flag} {cc_name} (WARP)"
                elif role == 'WHITELIST':
                    new_name = f"⚪ {flag} {cc_name} (РКН)"
                else:
                    new_name = f"⚡ {flag} {cc_name}"

                # Очищаем ссылку от мусора
                clean_original = remove_fragment(replacement['link'])

                new_s = {
                    "name": new_name,
                    "ip": replacement['ip'],
                    "cc": replacement.get('cc'),
                    "speed": replacement.get('speed'),
                    "ping": replacement.get('ping'),
                    "type": "Recovered",
                    "role": role, # Важно: роль наследуется от слота
                    "original": clean_original
                }
                
                new_servers.append(new_s)
                used_ips.add(replacement['ip'])
                
                # Сохраняем пул
                try:
                    with open(RESERVE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(new_pool, f, indent=2)
                except: pass
                    
                log(f"   ✅ Replaced with: {new_name} ({replacement['ip']})", "INFO")
                modified = True
            else:
                log(f"   ❌ No replacement found for {role}. Keeping dead server.", "ERROR")
                new_servers.append(s)

    # 5. Сохранение результатов
    if modified:
        log("💾 Saving changes...", "INFO")
        stats['servers'] = new_servers
        stats['updated_msk'] = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S MSK')
        
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
                
            # Обновляем base64 подписку
            links = []
            for s in new_servers:
                clean_link = remove_fragment(s['original'])
                link = f"{clean_link}#{quote(s['name'])}"
                links.append(link)
                
            with open(OUTPUT_FILE, 'w') as f:
                f.write(base64.b64encode("\n".join(links).encode()).decode())
                
            log("🏁 Watchdog finished: Subscription updated.")
        except Exception as e:
            log(f"❌ Save error: {e}", "ERROR")
    else:
        log("🏁 Watchdog finished: No changes needed.")

if __name__ == "__main__":
    main()
