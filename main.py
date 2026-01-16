import requests
import base64
import socket
import time
import concurrent.futures
import os
from urllib.parse import unquote

# --- НАСТРОЙКИ ---
SOURCE_URLS = [
    # Основной репозиторий (пробуем разные варианты ссылок)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/configs/vless.txt", 
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/vless.txt",
    # Резервные проверенные базы (чтобы точно работало)
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/vless.txt",
    "https://raw.githubusercontent.com/tbbatbb/Proxy/master/dist/vless.txt"
]
MAX_SERVERS = 15       # Оставим чуть больше, 15 штук
MAX_PER_COUNTRY = 2    # Не больше 2 серверов от одной страны
TIMEOUT = 1.5          # Тайм-аут (сек)

def parse_vless(config_str):
    try:
        config_str = config_str.strip()
        if not config_str.startswith("vless://"):
            return None
        
        remark = "Unknown"
        if "#" in config_str:
            parts = config_str.split("#")
            remark = unquote(parts[-1]).strip()
        
        part = config_str.split("@")[1].split("?")[0]
        host, port = part.split(":")
        return {"ip": host, "port": int(port), "remark": remark, "original": config_str, "latency": 9999}
    except:
        return None

def check_server(server):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        start = time.time()
        res = sock.connect_ex((server['ip'], server['port']))
        diff = (time.time() - start) * 1000
        sock.close()
        if res == 0:
            server['latency'] = diff
            return server
    except:
        pass
    return None

def main():
    print("--- ЗАПУСК (ОБНОВЛЕННАЯ ВЕРСИЯ) ---")
    all_configs = []

    # 1. Скачивание
    for url in SOURCE_URLS:
        try:
            print(f"Пробую скачать: {url}")
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                content = resp.text
                # Если base64
                try:
                    content = base64.b64decode(content).decode('utf-8', errors='ignore')
                except:
                    pass
                
                added = 0
                for line in content.splitlines():
                    p = parse_vless(line)
                    if p:
                        all_configs.append(p)
                        added += 1
                print(f"  -> Найдено: {added} ключей")
            else:
                print(f"  -> Ошибка: статус {resp.status_code}")
        except Exception as e:
            print(f"  -> Ошибка соединения: {e}")

    unique_configs = {c['original']: c for c in all_configs}.values()
    print(f"Всего уникальных ключей для проверки: {len(unique_configs)}")

    if not unique_configs:
        print("!!! НЕ НАЙДЕНО НИ ОДНОГО КЛЮЧА !!!")
        # Создаем пустой файл, чтобы GitHub не ругался ошибкой
        with open('sub.txt', 'w') as f:
            f.write("")
        return

    # 2. Проверка
    print("Начинаю проверку скорости...")
    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        futures = [ex.submit(check_server, c) for c in unique_configs]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                working.append(res)

    print(f"Рабочих серверов: {len(working)}")
    working.sort(key=lambda x: x['latency'])

    # 3. Фильтрация
    final = []
    countries = {}
    for s in working:
        if len(final) >= MAX_SERVERS: break
        
        # Пытаемся угадать страну по первым 5 символам ремарки (флаг)
        tag = s['remark'][:5]
        if countries.get(tag, 0) < MAX_PER_COUNTRY:
            final.append(s)
            countries[tag] = countries.get(tag, 0) + 1

    # 4. Сохранение
    res_str = "\n".join([x['original'] for x in final])
    encoded = base64.b64encode(res_str.encode('utf-8')).decode('utf-8')

    with open('sub.txt', 'w') as f:
        f.write(encoded)
    
    print(f"Успешно сохранено {len(final)} серверов в sub.txt")

if __name__ == "__main__":
    main()
