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
#  FL1P VPN WATCHDOG V3.5 - SMART RECOVERY & ROLE FIX
# ═══════════════════════════════════════════════════════════════

STATS_FILE = 'stats.json'
RESERVE_FILE = 'reserve_pool.json'
OUTPUT_FILE = 'FL1PVPN'
LOG_FILE = 'vpn_scanner.log' # Пишем в общий лог, чтобы видеть все в одном месте
XRAY_BIN = "./xray"

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

# ═══════════════════════════════════════════════════════════════
# 🌍 СТРАНЫ И ПРИОРИТЕТЫ (Синхронизировано с main.py)
# ═══════════════════════════════════════════════════════════════
# Близкие к РФ (Идеально для игр и Универсальных)
PRIORITY_COUNTRIES = ['FI', 'EE', 'LV', 'SE', 'LT'] 

# Хорошая Европа (Вторая очередь)
TIER_2_COUNTRIES = ['NO', 'PL', 'DE', 'NL', 'DK', 'CZ', 'AT']      

TIER_3_COUNTRIES = ['BE', 'CH', 'GB', 'FR', 'IT', 'ES']

# Словарь стран (для нейминга)
# RUS_NAMES MOVED UP


# 🔥 1. АВТО-ОПРЕДЕЛЕНИЕ РОЛИ ПО ИКОНКЕ (ЕСЛИ В ФАЙЛЕ UNKNOWN)
def identify_role(server):
    # Если роль уже есть и она нормальная - возвращаем её
    current_role = server.get('role', 'UNKNOWN')
    if current_role not in ['UNKNOWN', None, '']:
        return current_role
    
    # Гадаем по имени
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
        
        # Удаляем фрагмент, чтобы не мешал парсингу
        link = link.split('#')[0]
        
        # Парсинг ссылки
        uuid = link.split('@')[0].replace('vless://', '')
        address_part = link.split('@')[1].split('?')[0]
        
        if ':' in address_part:
            host, port = address_part.split(':')
        else:
            return None # Битая ссылка
            
        params = {}
        if '?' in link:
            query = link.split('?')[1]
            params = {k: v[0] for k, v in parse_qs(query).items()}

        stream_settings = {
            "network": params.get('type', 'tcp'),
            "security": params.get('security', 'none')
        }
        
        # Настройки транспорта
        if stream_settings['network'] == 'ws':
            stream_settings['wsSettings'] = {
                "path": params.get('path', '/'),
                "headers": {"Host": params.get('host', '')}
            }
        elif stream_settings['network'] == 'grpc':
            stream_settings['grpcSettings'] = {
                "serviceName": params.get('serviceName', '')
            }
            
        # Настройки безопасности (Reality/TLS)
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
    # Сначала быстрый TCP connect (отсеивает совсем мертвые IP)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        
        ip = server.get('ip')
        # Если порта нет в JSON, пытаемся вытащить из ссылки
        if 'original' in server and 'vless://' in server['original']:
             clean_link = server['original'].split('#')[0]
             parts = clean_link.split('@')[1].split('?')[0].split(':')
             ip = parts[0]
             port = int(parts[1])
        else:
             return False # Нет данных
             
        if s.connect_ex((ip, int(port))) != 0:
            s.close()
            return False # Порт закрыт
        s.close()
    except:
        return False

    # Если TCP ок, делаем проверку через Xray (HTTP 204)
    local_port = random.randint(20000, 40000)
    config = gen_check_config(server, local_port)
    if not config: return False 

    proc = None
    try:
        # Запуск Xray
        config_str = json.dumps(config)
        proc = subprocess.Popen([XRAY_BIN, "-stdin"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        proc.stdin.write(config_str.encode())
        proc.stdin.close()
        time.sleep(2) # Даем время на старт

        # Проверка через прокси
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }
        # Пытаемся стукнуться в Google или Cloudflare
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

# ♻️ 4. ПОИСК ЗАМЕНЫ В РЕЗЕРВЕ
def find_replacement(role, exclude_ips, preferred_cc=None):
    if not os.path.exists(RESERVE_FILE):
        return None, None
    
    try:
        with open(RESERVE_FILE, 'r', encoding='utf-8') as f:
            pool = json.load(f)
    except:
        return None, None
    
    candidates = []
    
    # 1. Ищем всех кандидатов подходящей роли
    for s in pool.get('servers', []):
        if s['ip'] in exclude_ips: continue
        
        cand_role = s.get('role', 'UNIVERSAL')
        if cand_role == 'UNKNOWN': cand_role = 'UNIVERSAL'
        
        # Основной поиск по роли
        if cand_role == role:
            candidates.append(s)

    # 2. Фолбэк: Если для GAME нет серверов, берем быстрые UNIVERSAL
    if not candidates and role == 'GAME':
        for s in pool.get('servers', []):
            if s['ip'] in exclude_ips: continue
            if s.get('role') == 'UNIVERSAL':
                candidates.append(s)

    # 3. Фолбэк: Если для WARP нет серверов, берем любые Reality
    if not candidates and role == 'WARP':
        for s in pool.get('servers', []):
            if s['ip'] in exclude_ips: continue
            if s.get('role') == 'UNIVERSAL':
                candidates.append(s)

    if not candidates:
        return None, pool

    # 4. СОРТИРОВКА И ВЫБОР (SMART SELECTION)
    # Сортируем всех кандидатов по качеству:
    # 1. Tier (Приоритетные страны РФ > Европа 1 > Европа 2 > Остальные)
    # 2. Скорость (Больше - лучше)
    # 3. Пинг (Меньше - лучше, но это пинг до Германии!)
    
    def get_tier(cc):
        if cc in PRIORITY_COUNTRIES: return 0  # 🥇 Элита (FI, SE, EE...)
        if cc in TIER_2_COUNTRIES: return 1    # 🥈 Отличная Европа (DE, NL...)
        if cc in TIER_3_COUNTRIES: return 2    # 🥉 Обычная Европа
        return 3                               # 💩 Остальной мир (US и т.д.)

    def quality_key(s):
        cc = s.get('cc', 'XX')
        tier = get_tier(cc)
        sp = s.get('speed', 0)
        pi = s.get('ping', 9999)
        
        # Сортируем кортежи. Python сравнивает элементы по порядку.
        # Tier: ASC (0 лучше 1)
        # Speed: DESC (умножаем на -1)
        # Ping: ASC (меньше лучше)
        return (tier, -sp, pi)

    candidates.sort(key=quality_key)

    best = None
    
    # 🌟 ЛОГИКА "СОХРАНЕНИЯ ГРАЖДАНСТВА" (Но умнее)
    # Если у нас был сервер в приоритетной стране (например, Финляндия),
    # мы ОЧЕНЬ хотим сохранить его или заменить на такой же приоритетный.
    # Если был сервер в Германии, мы попытаемся оставить Германию, но если есть Финляндия, которая ЛУЧШЕ...
    # Нет, пользователь хочет: "если была Германия - ищи Германию".
    
    if preferred_cc:
        same_cc_candidates = [s for s in candidates if s.get('cc') == preferred_cc]
        if same_cc_candidates:
            # Внутри одной страны выбираем самого быстрого
            best = same_cc_candidates[0]
            log(f"   ✨ Found preferred country match: {preferred_cc} (Speed: {best.get('speed')}, Ping: {best.get('ping')})", "INFO")

    # Если не нашли по стране (или страна не важна), берем ЛУЧШЕГО по ТИРАМ
    if not best:
        best = candidates[0]
        cc = best.get('cc')
        tier = get_tier(cc)
        log(f"   💎 Selected best available (Tier {tier}): {cc} (Speed: {best.get('speed')})", "INFO")
    
    # Удаляем его из пула
    if best in pool['servers']:
        pool['servers'].remove(best)
        pool['count'] = len(pool['servers'])
    
    return best, pool

def remove_fragment(link):
    """Удаляет #fragment из ссылки"""
    if not link: return ""
    return link.split('#')[0]

# 🚀 MAIN
def main():
    log("🐕 FL1P VPN WATCHDOG V3.5 - STARTED")
    
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
        # 1. Исправляем роль "UNKNOWN"
        old_role = s.get('role')
        role = identify_role(s)
        
        if old_role != role:
            s['role'] = role # Исправляем в памяти
            
        name = s.get('name', 'Unknown')
        
        # 2. Проверяем
        is_alive = check_server_alive(s)
        status = "✅ ONLINE" if is_alive else "❌ DEAD"
        log(f"   [{i+1}] {name} ({role}) -> {status}")
        
        if is_alive:
            new_servers.append(s)
        else:
            # 3. Замена
            log(f"   ⚠️ Replacing {name}...", "WARNING")
            
            # Пытаемся найти замену той же страны
            preferred_cc = s.get('cc')
            
            replacement, new_pool = find_replacement(role, used_ips, preferred_cc)
            
            if replacement:
                flag = get_flag(replacement.get('cc', 'XX'))
                cc_name = RUS_NAMES.get(replacement.get('cc'), replacement.get('cc'))
                
                # Формируем имя
                if role == 'GAME':
                    time_label = datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M')
                    new_name = f"🎮 {flag} {cc_name} | 📅 {time_label}"
                elif role == 'WARP':
                    new_name = f"🌀 {flag} {cc_name} (WARP)"
                elif role == 'WHITELIST':
                    new_name = f"⚪ {flag} {cc_name} (РКН)"
                else:
                    new_name = f"⚡ {flag} {cc_name}"

                # Очищаем ссылку от старого имени
                clean_original = remove_fragment(replacement['link'])

                # Создаем объект сервера
                new_s = {
                    "name": new_name,
                    "ip": replacement['ip'],
                    "cc": replacement.get('cc'),
                    "speed": replacement.get('speed'),
                    "ping": replacement.get('ping'),
                    "type": "Recovered",
                    "role": role,
                    "original": clean_original
                }
                
                new_servers.append(new_s)
                used_ips.add(replacement['ip'])
                
                # Сохраняем обновленный пул сразу
                try:
                    with open(RESERVE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(new_pool, f, indent=2)
                except: pass
                    
                log(f"   ✅ Replaced with: {new_name} ({replacement['ip']})", "INFO")
                modified = True
            else:
                log(f"   ❌ No replacement found for {role}. Keeping dead server.", "ERROR")
                new_servers.append(s)

    # 4. Сохранение
    if modified:
        log("💾 Saving changes...", "INFO")
        stats['servers'] = new_servers
        stats['updated_msk'] = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S MSK')
        
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
                
            # Обновляем файл подписки
            links = []
            for s in new_servers:
                # ВАЖНО: Удаляем старый фрагмент перед добавлением нового имени
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

# Словарь стран (для нейминга)
RUS_NAMES = {
    'FI': 'Финляндия', 'EE': 'Эстония', 'LV': 'Латвия', 'LT': 'Литва',
    'SE': 'Швеция', 'NO': 'Норвегия', 'PL': 'Польша',
    'DE': 'Германия', 'NL': 'Нидерланды', 'AT': 'Австрия', 'CZ': 'Чехия',
    'DK': 'Дания', 'BE': 'Бельгия', 'CH': 'Швейцария',
    'GB': 'Британия', 'FR': 'Франция', 'IT': 'Италия', 'ES': 'Испания',
    'PT': 'Португалия', 'IE': 'Ирландия', 'HU': 'Венгрия', 'RO': 'Румыния',
    'BG': 'Болгария', 'SK': 'Словакия', 'GR': 'Греция', 'TR': 'Турция',
    'RU': 'Россия', 'UA': 'Украина', 'MD': 'Молдова', 'CF': 'Cloudflare',
    'US': 'США', 'XX': 'Unknown', 'JP': 'Япония', 'KR': 'Корея', 'SG': 'Сингапур'
}

if __name__ == "__main__":
    main()
