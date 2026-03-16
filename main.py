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
MY_PERSONAL_NODE = "vless://3a9fd220-edb1-41b9-9a78-3f61cf8bd937@212.22.82.138:443?type=tcp&encryption=none&security=reality&pbk=PDooiand9xm-TAu-8HajBWr_is01x3IqABwYct5OiAo&fp=chrome&sni=max.ru&sid=10778ea288&spx=%2F&pqv=vyoU6Up2ZhRKlhT4IJaFt0y9Js0VG0Sh2tsrDkPcYhi2w5X8jktGxvNvlXwErzrsZo-Ur_Y4YgFbL_Z2hLlgjzwT7BX7jSKlxeFyEIe_3AparaBodbnSlsGyTNR81rAL_hqnFg86NTIEZ86FQ3YBCWPv03csYbYeVIjr7ZdbnmBJ0TxSV0f6H1oJUzAUxvIiO5Bytfs9zHKph0iIuyQR7jiodvRkBT2fxJQ4nXBu8hba4Y9GILdRASWoJ4ntN0S4Wx2_4Te0BBt4OXiIDFFt9tgDzSbERKN3cDKUJYSwe3SqmWrTK3uyjws7VzSL8nBW_M96gDyZTZ4JpXAdp5M7mbng7egn6pj-b4id3OKAN4lODWviZfBvh4KgCRT4C-ozP4JDRElEFWZHYts9RWI-G44OBz3F99aIp4lNCEtad_oiDlFSFup7eEUOW_RhxQzhlpYxgv5ZERNbdBXHa2hTwmA6RLvgPkibLg23sLJ9TiZ5w672GHSqHVn3pU-udoMZz40ml1VQM8kyFOrZPRlLAtKkJwaREs_1g6PIOH8dIH1TqYbAA4pAJIfbkYx76iQufct-C9lbWTPhk7j89iALPgR7S5k72WDhlP0VhyOK9MhkNhXIvPqUK8dKWYAREsF30IeWbWGSWrcNNAVF-Af1PC3MUqHMG0nUSyUjvCfk4DAyK5zG09Jp81nDlmWYAMmvwDI-FaHfx4rmbCD8Hgf_WKdiZV_DSuUYvEGquh1wxYjVmSfpOsYsU-2vapIBiT3gyBoLKfDcQWDmpDGhQaRiIqUjJUcsX2HhSJDJl9OJb11JAQZVKo-BtbVANJqWWRaXGzdSJsQoX1kdM5K_4imxBCtxMLv_sH75sdJD5CKvdqA8vMErl17eNVBc3qVRsSmC23SQIavDIrreMOhhWtHNaDpcGKHKuvhvL1OQyrEeMm7wundxLf39Wl0Beggb9JkG2hzs0t5XsYdPaf63nky3xlfdTIT1wZptMV_UMtclqzTnw78M8DnwtoS-VCu9nzltSNe7Juit-wZNY1HjaBupEE9H1_fz7j24ptjxmxNxDNR4sH8T3LnfdokiPieSudOHRjZ_crHEHSKQkBeT1pamB-HP2vQTlvIyYfPLPl0AR0Feudlaz5rlof-Rf-zf2MhDBTpzWwhJRFJWDL0M5E-Puth9GPVFU5P3jDk_Q7G3KcagMjPgvRFEvaNUSNosAn9SmQu5j8Nyl1Zeyye_ZHDDaS30bHiCEPA-VIZTj8-u1ZBGgwAlPIiWUJOzwtKBkYkJIu9CFJUS75ujXrKnoeqvuTN9QcoyWIfo_Q2kch_jSNjtytW6ihUikCyl-IRmgBAVRZbj1lsGgMLfz5gB8T9xebq6PR6ugYlU6uZle9q5tSI1Mz44Sa_RKZ714z5eXyRRZewcfqElZtA316Ryc34VUSiUTcxp17e-PiqqYv0V-n96Ro6s0SXgXopzw7mGSQmONmY6Opo9nxtaOuFH9TjvShOnKJ79-WxOPA0rZM1W7Z5m1z0tEljZK0MjFZBDE1NpFbZcdZrfmGG2ctSWgwKdNUIor1cV2fup9EOj7EgnHJ12GW1m8lJYQCfhsnvtmApkw2aH7pdhPBvq6ih4wpdmTCWkpTTeBpWaHfR1U96ZFSHMw4HXkF6c1VZsoKtTfInmt1iFAnsIm2-VUQUMozCPrA7wmoZwHxoCGBjQInuDJByLSAcurntW027egCNbjElWoxxnJY0NboLK99VaQaQ63U2gyqOe9lQ2lAmluiHmtBtn0Yr_AbCCVKPtSLdc-zkFTS_8HsREvR61p4-B_ebh5W6EG1u31xYtT9UQTQ5Ug3phtNqpx5Svpu35jVnRHWjt7DnIYgNgXGeKOzHw0sHla5ArqeIByT71pFz0P4jXQy1NFcdNvPEGsGlddhe-GRn7aAfNRK4CamuNzQ97ASGcmYlK6REtp4y5YnH67wv-SPRp70lHVZHN5pxRNsxY407kewtYV-clCoE3NgaWlWzbYnUDtXTP5vSlVF_39jtM6kvwK3IU08IRz32WWw-K9qU41rowSMj6c7Xw5EzuF4Ze4Uv_puWEdj8XcqnSSPaCLzAFhOvrbwTvGsLB7ccKGtHQia5wKpvkJ9vkqgsygNA3PckCmBlSjCbQqCsJA_sjngHuwf2DolgyxrdiU27aznMugxH9WBU2WFdKhuxaO_pcCFLoiHz9zFcVVBdz6wSt0Z9o9dJXeDznTnKetrnUe0_Kw1QEjAIWUrL1cipfEnf2A1jOB0amx5Xz_-B0K9PiP5HBuq0kFdDoWV-czAbRQ7YRoRbH8JknshuW79E03MbpQMZXiijfHpWR6ZHKR3R9UZeb1LCacTnYrcEX5DDK1DNJgnM88gezZZwMPWAIJdz4w9VQ1twZ_142T42YB9xcNuX5bdt9I9MYXKgYYODPcKyj2N8e5OkB_m8IvQya0OSU_wXjgxPTPP2VV_BrwFndysWlM0XMXPvOWSwhs5znYW9fzKnn375KDfhPnu1oSvG7sGmSNpejxSOh59E8C8z-Sr5c_T_uUAY0SVlhAoY0npyeh7DYXbwvSSzl-c3I2HArDvNFAGVxT3V9oDjhtPgOAQE&flow=xtls-rprx-vision#💎 🇷🇺 V1A / БЕЛЫЕ СПИСКИ"

# Твоя личная хардкод-нода (Несгораемый #2) - Финляндия
MY_FINLAND_NODE = " vless://3336a974-eca7-4e7b-a41f-1615a8c4dd2a@195.226.92.208:443?type=tcp&encryption=none&security=reality&pbk=cv14_PfH47rZFhrfSUN_L8A5-3Mg9dHZ5k1YB3AtSwI&fp=chrome&sni=api-maps.yandex.ru&sid=c6645cc4&spx=%2F&pqv=oswrsqArEEY-zQmEvaLgJPHW-FMH3CQPAkyY8OhPgAKBzmIDXkHBdLumtuU_w7zyErNwMzk-ixBgjD8hpx_XJqCp2D_ma7ldCjOnVQ5HLGxu4YGABr9-eiNhmi1VmCSFL3WA61B4KgfYSVDPYCZjpeRxAvxhR0d_cPOKkZsRYitYW4U35Q0Y2VFveqZQT6i8bhXWi_MzOv8ptWkQiBaU-LDRcV6J8Rl3LkAwkIrfVRtE3g-Owrmy1mEd_zOaPKSZUBiGRqsQ0044hf1wIeGqYzeL2d2zO7EB7acUncYWgFP5AHW5DTBrWQFPzaU-4tRqnaKNPApkppA4VAIDtrnsZ1xXBL8D_NN8IC7igUfN2LmqUo9uq0soSaZpcvG1_2LdFdeTe9WMu6bVB8mPDRZUqYCh3EooduzDWVdrvmwIxGrA-vhlFA26L1bWWMvYKn8y-JlQ2oxmBa0cx9Vt_3J6yrSJe-BSbianhsTJ4Aj4FoChsuLs_XUvPJRl2d2oMKcA2F4_3x3FRTc_TtzZ5S-8SnF0geQWLv21XhcLeTwZzWQv5L4tN491HNqFlOMUyPAUVpQ9GV1Ur-MiJLjgj-1MLZriG4MckZ41tplG8SDTM34JFayDQShzqR3gOdf5jh1uHJuXFXhaydVBJkf1hxuZ4RZUxjUnF6FdpuAWbPZxX94Zz2S5Y9TPrv7cPhJOzfrGDBe_VaZH_rziJc3jh8UbRoodddynnTK3D3FehPUwokJELpHy0IExtTlFBVm6XQBVUl0AnOA9PUshZ-xxfbZpqS1Y-zJt-qp5QOgeoDCLMnNNR86Dd_qtnIxwlhTObIQBjv8rv8kcRgMYHuHSM0TAUuYn70Z9DlkZNRJ_p8YLZHrkkPsmdy6h7RkO1i6tTKFdtRzpWgEg_eY6LWbVzr4-UB03wATnkQYbm3MInCiREV7yVG_E-P14BfFSdt6IKWWvsmPuSJEmELp9T6iaotq_hdOD2wmtHb8lNt5GidGpvpvjKii-86BjeGY4kN6k5knE3aN-V4rFdOHCuojOCUOKBLg-QRgTWvqx6z6J1Ne8ZZYhdz9gjgSNatSx-X2-afWp8kf-WaNjAEAkUjcBHf4-r4AHZEtGZf2hfu0N4J1wzCrslVjQuxPpSzVmENRnMpl0gY6fkhDBUBJ_enVs4o5bru3-mpvjAxuK57YntVouAQ29VSIeW11jKujnqQ7UF7BSJHke08YUYLMWJ26psY7b82PBs8OJUFaitIJXe_9qDy_qcOTH-UHyizuBh4LdQVM5f0NXFKmI56qZRx3vVp1V0ELmmwH3EyuVhRWCYeB16FAWX_tNMh9nQG_hYkrMaAAefBrz5d91IrIV-c1L3XVBJJ44hDoXIWGIlSy0Us1PmvqTpuGnMMb4BhKit3Ao8hbNccAJjSklATEA_-LqWfSpTgLlF2Ireh034i8lMVctDThkih6H-ML3zlUGQ8AqDTV2G_0qsinzFOrVSTE7WfJFf-qMPEVMnBKA2R2Pn5SGnDPEj2NpxmceLpzFHiHKm9mkNJHGA-b4ApIoGQVu5TpJ3g6RMo91rjxucCmp5fG8Nm6Uf1FanIjlngrpZWNUCC3fuH8PfwZ3qmuV4k3O2nXYyktR55tUDmVTB8VrQQAa8cO_0pgpb2O8gisbXHiMv56CgRfV2KGc7n6E9WX9EX29MpWMzQOvR3EpXGLjjxhSuSCpgJlDGXm1qB3avd70Eofxwsq8ochXtpc5AXFAl7uUP0PAMbfKCy-rCBTlnaWtGQMcUCEjJZ6N3UKqz5xb9bNLFlvw63tQVC4InjrcIwXIG3DSzexZsvRNTshGS8W79KWDIMaaw22n2Nwza8YyCzp4q2nkWN3WVxuhjEO5uT7nZ005UPWu9sURzZwJ3SaCBU3mmw_ebTpDQoGvKjSZlup8i7ixPWjB3lIHqXfxGCrtQyyv0fDKtNZ_KAsp1KTIWoChxyykf6Q26fo8xFt9BnMYvuR1AQ6C8UGx-Ff1xp82X3ZzLCciBdeG5zt2N5sdhz_RABFSNN5NtFiH0xYBqNLnILf4GbFK7QCrwTVysac1YmCkZ1He5n21fcEUliBROqcD0nlv0NeHTxbznr6Hswv1nGPhSJtcB3r6rNv-n_WCHXO0R4YZAOqwdCeZAWyqvZg5nagDo6-9HfZqMIW6KOzhtRv8xITQ1Osfl1VfgmXzd834FEH9QJg095h9M3Ag38cstuDtRXHIsSOQFww03w1wTBGnA6Vn2fwgNvi3XNrEQWdNMLKDPgACsyBbhV2hFiRvuyLQpIoNEoOiOD6D44fXzqSO2I4UwBOuZJrllj3AYZLtBjcCRDu9xI1G2RcP0oLwvxDOLIB24XfUQJdYUZXnXkmGbxdYd9IlzQDO49KlfY4Y9uuEAXTm_lZ7Ut6M3G_AlIX_U_M79yC7pARp3YFizDtVqnoiHvHtz5FmPjWBzeZ7B9VAkhhlmy4Pd822chW-gLaXv23TdCXSEvMU1bV_p9cUBkqxCVEqe2vWWtl9WpG_2sOYR4zufEO3DrM7zqN-rzfiyIpoBwuky1DBV6mX1Rne4ftPG83lhhVkOQ-ru11-OOQ_5OOeZnu77zbd0KE&flow=xtls-rprx-vision#💎 🇫🇮  V1A / Финляндия"

# Твоя личная хардкод-нода (Несгораемый #3) - Финляндия 2
MY_FINLAND_NODE_2 = " vless://c54fd376-cc4d-491b-8791-10b5de2df020@195.226.92.208:8443?type=tcp&encryption=none&security=reality&pbk=vVHXKGBSXWAL8dJpYYTLKMzBd8Yj4P2bIhFhdP4-IkY&fp=chrome&sni=api-maps.yandex.ru&sid=e4ab1919&spx=%2F&pqv=l4sSsKEwcUJi1fmKsKKrW151BOGu0kDcofZ3hl6fQipVp7nRRWZUrKk8qRingXtTjw9p79rk6jWwKDGGE0Wk_jrGTI3J6jkqi0rTQj9RY4y6awySaKPlXAiG1QaKDE7JexIlOZLYSiaKH07VB8WLwnYxoZvC2cTreLb2Dmw1BzgVHV1JNV08eOcRxWDJzOC54wI9t_JrD6lEFT89Oru3miYm3dXsME1DCMrOPb_iPVnTefGoBEwVBY2qBad0QFNyPE371T4m5k-BjoZ14KZdldfTCiJX7hjtk8piGLAVbHe4fA42KrKLb2gdkJfHOFngKyz0QbYsb92l6UfoxCSOFlvdY6SJYISahGTYwJB02a032nXmqIXQcqc9xU9VPiuWlhmaXaQfkARwmJLUljnHj7C9KwxVTfq_Pf_D9WOjFIW7Emi7SsVJEYlNb6hnzQxb10CFZTXJzWahHAOO9GE7zNLmElvOjNdFRuVhpri378K23-CjoN4jb_KcPhzZYZJGfpbvFgCnpU3n1kEM01VmRKVpIPvP7UwiyzDRj9BMPWQLq7cjI0urBa19KaGTgS6ZcyjO4TI2AVY7Pe2rEF8MDzLdboOLZYEMuUqqthlKCG0baF_DIatCqrdVBwXovx4ru4XBO9zaqAGvmetUmAyuRi_Glrca9LLRdwuHnFUwyFM_I9NsGICX80vquTklEbBwrkKOzfVdkUBniuFi4g9iH862kt-UU9caWQmhtwRbXwp5Zde6SJow2pm5Y7cltAOUJ-ulmMN6ePxynJj-Yt7G29Kf9IEbHOA95p31jQrE4sgxAOXetzPsYoeNUDK2YbZu9VB_HXiHZ_r2SQD_X-4Rnuid4r4JqDGu8tKTPeVO9o6d1Q58zATe3Qdpc1NvZTZC8QUZoo182OkoT7rWRPqg--Xlya4DmQ41uejk6iIKfByrc9ZQEWOKEFARma0qehl0VGcCYdMx8cs-qy3eq1M49KBESeLmUvBH6glhTda6KAwcEYlV6Ng2Z86wK-uKGW4vYqF7q2mSIQrMGDHRmvbmX_HYMNxe8zZI00pwi3hrHujO7LjI4vfiJWM_SKe5tOo_b6IeOotMP0rhHC-euxQ4dhDuyFVDTvrOjU96hBMwTTsmQ2z2CGMnEXuadMz8OoPD6lWLkXsirP3Qk4vvreO_WViM_d3Md6cxq956VzMJqbjlFSX8ZrsNrSsosUyvkEH-O4FBNT7xRAk_CsGoSfkSbxebEo0ks09BveBNhnWg1v8AMsbg73dCNpBz8Xs8W2L0bCoIOwtXp0A3Z6AD0zwU2pcXqTz6XgDbA7F-JOy8dVzWxQgfN2X6u90a4lPh0-OASJoH8ktd7LYn6LvkNUijgyn-JD0NPFS52AyJntzOwm0wNUWAGFFiDRuN9c07gaE-KWrwPJkedbLQZ6v7tvC5OJNqYBEPtxxuoGq0gwz5Zlwocu-nh3zRwKy-_5XP1KSOaFlpxfp3HmSAdrcVXIulY9rruRCDv1HXnGtslH1yEfpnu_Ymjd56VCwmJ6Jiej2IUyl8gPEBOstX3ZKnssFwavEMF0GVVkhME_lz6Dv2xSfozcUpo9Bc9Q6KyVSKBa8mL0lzQWsqblVjnKaWgyFmHbtDppds2clI2q-xYKaXVpcxxAWBY25ak-5ZxtPUBKa2lqUvWG-GBKwu26HctPYjS6Q816R1QwEp-bm8eahFjKH9ol9HiEbhsw96ufP5X-6zqCSw57y1dBseFK40fRrEmuRr9jgu-DP8EkW71IvPGhRhWn-zex5-JYESrIRgf6_lghFdhHpyIjAPIY2pO7nq-uuq-_NR_o7txYGp9GN9oub4DhHA6y3VXnAiB2lFgtJfpCfTiGgBCSKSY0G9p6RfyCvyhGNHq1qZEaHLcr_ap4-Hv6NJUzHvJ3IfQBZAizalpSbiOLIZ7GQzbNdGNXOQX-9EUKEzGuMRd8fY8k1V8lkfbrGoytQzkc2_010zxieS8-fGQTHmwzdcOY3KJmdGmSLHwQ8qlJJxNWT0k1jV3EJ5OjaYKwv2dkm4Xgiy_rXo086SC-7UIV_lpapT_6_P_QHuLdEJMQ7CC8fKBZ9_TyqRXjC4QHPFyddkqnOLrGle-KZADj5yCs2v_ehrJXgeaZ6tt9U0bjpUGOIuz3uAlr1LxBhrkF0ZbWRbcGAsbR12QX5vx6S_flt8moZs0Y3bBPNsBK9RmkJYisHHrI23aJSHMNrTtPWFe43SrEHPBdFkJk8LlsFjx2RwCxTb5MuQcprg3g1rpdsBR9koC-EE-77IdGKGJJQWhZBe5mchDbB8-tAFGP468mvBxkxso15g4HbEyPxBdqBI4MmFa7in7XOOk2jHfxrOVgzllIw4oHuxd5C0F_b2oX63HS-9IeFBQ4nsZpDBgeemRXXYW1kPYwIZd0BFYqRJS_ctIz7E-76Hh1GV2KN1MztV7Lzeh9B3Z4v633EFktQfI0qtk4hsZQSAO2sHiu5NTVP1tK5DPsAyEe3vXCfwDSEb6GnX2pZd3SXjb2QPmBFGVWIRiiqbXWq9fVfk_gDODS70NHYr8-GANoMSQ31da6soPR_1Tla1cTjlZ3AiK4xbbFaouaric9k#💎 🇫🇮  V2A / Финляндия"

# Твоя личная хардкод-нода (Несгораемый #4) - Эстония
MY_ESTONIA_NODE = "vless://c54fd376-cc4d-491b-8791-10b5de2df020@195.226.92.208:8443?type=tcp&encryption=none&security=reality&pbk=pctFPNpNpaHrCww6uHWUCR6za5f3KCeVyMdV2Qg7LC8&fp=chrome&sni=api-maps.yandex.ru&sid=e4ab1919&spx=%2F&pqv=LY5Jd2owXcD51lr_M94lnL6t-iSv23RfZNDh1l_YRpxGRBhufGSmioSlM58JIRJqk_7qZUiuGndv4bTKprogbvUZqrvGrsS5Nu8Vk7DvXoRnLnzUMWRz9d_eGWOrhqHOIL6ApHVmY7uxCt3cXkX7IpJaWxNQk8Rs42Pg-BSE8LoSeZKqS1-eDMVx6RMGsN0nGpE4HzdfX83cIvUB6tbyjO7rqality9nvWUFqb7lXYxJ2hyMMFgvVmcm8GcShRFf9uuZwLbCwTSEoZtAgnP69WnGFWz_9HrdDawYyB-Hg0sBUeamVpM23gpJdn9c8bOxKqYpoidwBUou4ejvfnZ5TeoKBvDRadERB-9Hdb5ckI56_zw1kiprB5jEUtBWTjd1D6XJ73WxhCgT-zbvYPtoQnNKGGhuXbU3SVnzbmyeADR9KK9DpujV6P9ar245TTRx_xlxtPrMZ-br_-BZdJiXLCxKdgx-5IeDlgBQnf7Nf92CX8mlEyD2e5YroyuW0fcfb3N3ShduiYh1OtfB8lVVb7hD_H1epMx3d6IiCSzSAtm9vXn897UNi5_LULbF1wU2t9bxwIBQABgwTeoly9OFryw6DF3RIEnpCfGTg-byqTymR6naI7DRuuzoUMIF40t1K6N49rc_kpWheD80Pz_4rJbBWnlNKvh687LU23lsXvnhsFE_fRBtHm9pdjGdLtoPDbEEu1SUS4l73z8ksqOEtIjxlr4RGsbJhhwnxfBZzpwcSlInsUS-AYausQOj-0qWp_YPcvf1BCA4vJZvUwEdJ15s31OD4fbNE0V9u-l_bddnjUz6_ew9LRoynS1YTUE9evt6N6WmYx_GD7_TDBEBPTM3fAk4me6pjvBeoTt2nTcbewPDJIn9Tf9dfGRHryTtmrRoAVxLskj5LM6kGkYOIWRoKDMepAxKIEnRUNNVyJALeI6ikHit7E4Nb6LFRJPBIOOGdA9oGQGDn6gLBXR9ILz8QeJUOflHz9I7mOIy6978J4zabTyQ4-db-fnAOoFCDI3KCyf9yv4mN-sL0fMhkkqcwlijCCiU7Q1c5HS7HInnJXQ2oDGpBGMLMv5vCoVt5wuMgOe2Y8serIYqq-IszE07W31HxYQNZjkc45RC-j0WZztX1napRNFvg9OotjA6A5jQ8yRzSYs-3r9WsM2asFRPJINre4h4sXUToeYABh3HP1foPjy-o4Jv5Y0ZjjTvttDFEwSYsvWaG4MTq8ljAFs1nGcvXNwDguI4R_4CLMWWrRXTcRSGQq7HzQZwpDgNQtnYACxAp5QrY5pXRZTTBo36bYMiuue7L3cjJL3y3HHCnHPsDI_lqkoY-ZlOzmMjBO6Z9UZaoNHT7_zKTHJlfrFr40VsLHp03nw2xjq5CqMJXxQujbUvmjc6aVczSWdNOQXZuMmp4iVnjH9wxrMdEyPeZFuMivjw0L0viW2y1AGBYx2VEX-ICxC6pwm_qaJN8TAitVZStYxGEB3lRIjNJL2-tEnPcrYWSAajYgl13_LJPwOr4a1cmckovigYc-DpLsgjQEcEJbfFpMaDmpTDRXoyqb8fHqALQbAxsNJRB1jeOpCKcJRrQ5MdlyR63q12yWId6rzEemmeUXWj52K30apfaB-mwIRCHmepv_SFF2_i3bTs1u9naHgiCB8KvpBDKSP__pMe5NQxB5931YNBYugvDHzRsbeF4KoGbRo1MCaOFrENHuq9449j9ZbUYw7Y_vcTTLBgiHaaQ7IhZs0JSmxcWGCasVP4F-XAJEUx9l-ImRUVAV3VL5X3uYidUS7LguZlTsOToTPA2jmivp3MGicaKiW4EHPALpkRtdHMzZNwGPbrkf_cBDm35UJxko4GxLHStlTFBzRCHv7d5BflyL7HbMF6IiOr3t7y8ZoCOGDHw03M8F5AxWXcrKU6AHG9LhLNz7fwSvWhS6bQyaf5_GGHLYCvSEIBWNY0iHauCCFtD0TWw7f1uv2ry-v0rdDAFLctuDt4UHfvSU71x-OKZdBcYtb8DKqTiqpLEo6dsOpxHwS46zsa5xklA50fVMJFXE5o3Aq_xMZ5_0Q5KMyAJOY4DmKuxLj2WyVp4_UX3Kw7wlwKZhT1at4bgEhvwGESdgvbeaC4tq5A7c4ixl6aCeyHZq61VaLsFtpPPRasl0631knHRy2TX0E4eUfQdDlrGnVR2A5hQbdFutHpNxi7pBGjzezjCeTLatEZd0S3nRDUVgisIfqmSeTs_gmb2HW7SNkDB4YBMcwur1QHsRyiXGrv1GdANHlMjUSATI8PRQY8meVNxTPZZ0mfuW8Md74uv2b14YxRGb1_u1h80b12SYJZfaqYh8VIPLiSakDRLd5JQcu_nLDTyR2j00TDBWCdP4fnt0KVhaHIfQm8yFoxqVLXHJp3yJ4k366-WMXi2IFVsdH3zy_IpUGfEYdHOD-CSSbbF36kH2DorgT3mJakPjt6UJFaPJumX_Ibfgsx1ZRmi__sATqrsuMbtumcgri2rSchewZ3OjVDVhE9CABNg84qMgqjRxFoIJRiMfUIeTS2f0RCo6ijunBvMOi3wlw2iNw0T0zVhNtTVuTTFhi__jomuwZgQsrvEK89XZszBtY#💎 🇪🇪  V2A / Эстония"

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
    
    # №5-10: Топ Global (только иностранные серверы для V1A)
    needed_global = TOTAL_SERVERS_WANTED - 4 # Минус 4 твоих личных хардкода
    final_selection.extend(pool_global[:needed_global])

    logger.info(f"📊 Итого собрано: 4(Хардкода) + {len(final_selection)} живых узлов.")

    # Формирование файла
    result_links = []
    msk_time = time.strftime('%H:%M', time.gmtime(time.time() + 3*3600))
    header_link = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1080?encryption=none&security=none&type=tcp#{quote(f'Обновлено: {msk_time} (MSK)')}"
    result_links.append(header_link)
    
    # №1: Хардкод нода пользователя
    result_links.append(MY_PERSONAL_NODE)
    
    # №2: Хардкод нода Финляндии
    result_links.append(MY_FINLAND_NODE)

    # №3: Хардкод нода Финляндии 2
    result_links.append(MY_FINLAND_NODE_2)

    # №4: Хардкод нода Эстонии
    result_links.append(MY_ESTONIA_NODE)

    # Имя изменено здесь тоже для единообразия в json файле
    json_stats = {"servers": [
        {"name": "💎 V1A RU / БЕЛЫЕ СПИСКИ (Hardcoded)", "ip": "212.22.82.138", "protocol": "vless reality"},
        {"name": "💎 🇫🇮  V1A / Финляндия", "ip": "212.22.82.138", "protocol": "vless reality"},
        {"name": "💎 🇫🇮  V2A / Финляндия", "ip": "195.226.92.208", "protocol": "vless reality"},
        {"name": "💎 🇪🇪  V2A / Эстония", "ip": "195.226.92.208", "protocol": "vless reality"}
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
