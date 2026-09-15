#!/usr/bin/env python3
"""Демо «до/после» для новых правил отбора.

Синтетический набор имитирует ситуацию из задачи: много финских узлов в одной сети
показывают n/a из российской сети пользователя, тогда как часть RU/DE/LT отвечает.
Демонстрируется, как новые лимиты и скор без географии дают разнообразие
и штрафуют нестабильность.

Запуск: python scripts/demo_diversity.py
"""
from __future__ import annotations

from datetime import UTC, datetime

from vpnmy.models import CheckResult, Source
from vpnmy.parser import parse_link
from vpnmy.selector import compute_diversity_stats, quality_score, select_final

U_BASE = "123e4567-e89b-12d3-a456-42661417"


def node(i, h, country_name, category="universal", source="demo"):
    name = country_name
    uid = f"{U_BASE}{i:04x}"
    return parse_link(
        f"vless://{uid}@{h}:443?encryption=none&security=tls&type=ws&sni=x.com#{name}",
        Source(source, "Demo", "https://example.com", category),
    )


def main():
    now = datetime.now(UTC)
    # Стартовая конфигурация 12 узлов: макс 3 на страну, 2 на ASN, 1 на IP, 2 на подсеть
    category_quotas = {"universal": 7, "whitelist": 5}
    history = {"nodes": {}}
    # Синтетика: 12 узлов, 6 из них FI в одной сети/ASN (как на скриншоте 6 из 12 n/a)
    # Остальные — DE, RU, LT, EE — с разными ASN/сетями и стабильной задержкой.
    # Нестабильные FI: два с большой дисперсией 400/450/3800 -> jitter 3400
    # Стабильные альтернативы: 650/700/680 -> jitter 50
    # ASN: FI клонированные — один ASN, одна /24
    # Для наглядности задаём resolved_ip, asn, egress_ip, медиану, джиттер.

    def mk(i, host, country, asn, subnet_ip, median, jitter, max_ms, country_name, cat="universal"):
        n = node(i, host, country_name, category=cat)
        # смещение для уникальности host, но resolved_ip задаёт физический IP
        # Используем egress разный для разных входов, кроме двух FI которые ведут на один выход
        egress = f"198.51.100.{10+i}" if i < 10 else "198.51.100.10"  # два входа — один выход
        return CheckResult(
            n,
            tcp_ms=20 + i,
            http_ms=median,
            speed_mbps=10,
            country=country,
            checked_at=now.isoformat().replace("+00:00", "Z"),
            resolved_ip=subnet_ip,
            asn=asn,
            egress_ip=egress,
            http_max_ms=max_ms,
            jitter_ms=jitter,
            attempts=3,
            samples=(median - 50, median, max_ms),
        )

    # 6 FI в одной сети/ASN (клон), часть нестабильна
    fi_nodes = [
        mk(0, "fi1.example.com", "FI", "AS1001", "185.220.10.1", 450, 3400, 3800, "🇫🇮 Finland"),
        mk(1, "fi2.example.com", "FI", "AS1001", "185.220.10.2", 460, 3300, 3750, "🇫🇮 Finland"),
        mk(2, "fi3.example.com", "FI", "AS1001", "185.220.10.3", 680, 50, 700, "🇫🇮 Finland",),  # стабильный
        mk(3, "fi4.example.com", "FI", "AS1001", "185.220.10.4", 470, 3400, 3850, "🇫🇮 Finland"),
        mk(4, "fi5.example.com", "FI", "AS1001", "185.220.10.5", 690, 40, 710, "🇫🇮 Finland"),
        mk(5, "fi6.example.com", "FI", "AS1001", "185.220.10.6", 680, 60, 720, "🇫🇮 Finland"),
    ]
    # Остальные страны — разнообразие
    other = [
        mk(6, "de1.example.com", "DE", "AS2001", "95.216.1.10", 650, 50, 680, "🇩🇪 Germany"),
        mk(7, "de2.example.com", "DE", "AS2002", "95.216.2.10", 660, 30, 670, "🇩🇪 Germany"),
        mk(8, "lt1.example.com", "LT", "AS3001", "185.193.10.10", 640, 45, 660, "🇱🇹 Lithuania"),
        mk(9, "ru1.example.com", "RU", "AS4001", "31.173.80.10", 620, 35, 640, "🇷🇺 Russia"),
        mk(10, "ru2.example.com", "RU", "AS4002", "31.173.81.10", 630, 25, 645, "🇷🇺 Russia"),
        mk(11, "ee1.example.com", "EE", "AS5001", "141.95.1.10", 670, 30, 680, "🇪🇪 Estonia"),
        mk(12, "pl1.example.com", "PL", "AS6001", "152.89.1.10", 680, 70, 710, "🇵🇱 Poland"),
    ]
    # Два входа, один выход — тест дедупа egress
    fi_nodes[0] = CheckResult(fi_nodes[0].node, fi_nodes[0].tcp_ms, fi_nodes[0].http_ms, 10, "FI", fi_nodes[0].checked_at, resolved_ip="185.220.10.1", asn="AS1001", egress_ip="203.0.113.1", http_max_ms=3800, jitter_ms=3400, attempts=3, samples=(400,450,3800))
    fi_nodes[1] = CheckResult(fi_nodes[1].node, fi_nodes[1].tcp_ms, fi_nodes[1].http_ms, 10, "FI", fi_nodes[1].checked_at, resolved_ip="185.220.10.2", asn="AS1001", egress_ip="203.0.113.1", http_max_ms=3750, jitter_ms=3300, attempts=3, samples=(410,460,3750))

    all_results = fi_nodes + other
    # Оценка «до» — представим старый скор с географией: FI +15, DE +10, RU +4
    # Мы симулируем старый отбор, беря top по старому скору (география)
    # Для сравнения посчитаем новый скор без географии
    print("=== СИНТЕТИЧЕСКИЙ НАБОР ===")
    print(f"Всего кандидатов: {len(all_results)}")
    for r in all_results:
        print(f" {r.country:2} {r.resolved_ip:15} {r.asn:8} egress={r.egress_ip:15} median={r.http_ms:4} jitter={r.jitter_ms:4} max={r.http_max_ms:4}")

    print("\n=== ОЦЕНКА КАЧЕСТВА (без географии, с штрафом за разброс) ===")
    for r in all_results:
        score = quality_score(r, history, ("FI", "DE", "RU"))
        print(f" {r.country:2} median={r.http_ms:4} jitter={r.jitter_ms:4} -> score={score:4.1f} {'(нестабильный)' if r.jitter_ms>1000 else '(стабильный)'}")

    # Новый отбор с лимитами
    selected = select_final(
        all_results,
        history=history,
        preferred_countries=("FI", "DE", "RU"),  # игнорируется
        category_quotas=category_quotas,
        target_count=12,
        max_per_endpoint=1,
        country_limits={"RU": 4},
        max_per_subnet=2,
        max_per_country=3,
        max_per_asn=2,
        max_per_ip=1,
        verify_median_threshold_ms=1500,
    )
    print(f"\n=== ИТОГОВАЯ ПОДПИСКА (новые лимиты) — отобрано {len(selected)} из {len(all_results)} ===")
    stats = compute_diversity_stats(selected)
    print(" По странам:", stats["by_country"])
    print(" По ASN:   ", stats["by_asn"])
    print(" По IP:    ", len(stats["by_ip"]), "уникальных")
    print(" По подсетям:", stats["by_subnet"])
    for r in selected:
        print(f"  -> {r.country:2} {r.resolved_ip:15} {r.asn:8} egress={r.egress_ip:15} median={r.http_ms:4} jitter={r.jitter_ms:4} score={r.score}")

    # Причины отсева
    selected_ids = {r.node.node_id for r in selected}
    excluded = [r for r in all_results if r.node.node_id not in selected_ids]
    print(f"\n=== ОТСЕЯНО {len(excluded)} узлов ===")
    for r in excluded:
        print(f"  {r.country:2} {r.resolved_ip:15} median={r.http_ms} jitter={r.jitter_ms} — исключён (лимит страны/ASN/IP/подсети/egress/медиана)")

    # Демонстрация эффекта стабильности: нестабильный FI vs стабильный DE
    print("\n=== ВЛИЯНИЕ СТАБИЛЬНОСТИ ===")
    unstable = fi_nodes[0]
    stable = [x for x in all_results if x.country == "DE"][0]
    print(f" Нестабильный FI: median 450 jitter 3400 score {quality_score(unstable, history, ()): .1f}")
    print(f" Стабильный DE: median 650 jitter 50 score {quality_score(stable, history, ()): .1f}")
    print(" Вывод: при прочих равных стабильный 650/700/680 уступает? Нет — выигрывает за счёт меньшего разброса.")

    # Бюджет 70/30 и российский VPS план — текстовое пояснение
    print("\n=== ОЦЕНКА ВРЕМЕНИ (вписывается в 12 минут) ===")
    print(" max_candidates 480 * probe 1.5с /64 воркера ~11с")
    print(" shortlist ~36 узлов * 3 измерения *8с таймаут /6 воркеров ~144с")
    print(" + ASN 36 IP *3с/5 ~22с + скорость 0.5мин => <5 минут")

if __name__ == "__main__":
    main()
