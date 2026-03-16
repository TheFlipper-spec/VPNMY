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
MY_PERSONAL_NODE = "vless://3a9fd220-edb1-41b9-9a78-3f61cf8bd937@212.22.82.138:443?type=tcp&encryption=none&security=reality&pbk=e9oH55AsHiMyO0vAmMfM9-iEEBDwV8LrVEB5YaNsRhk&fp=chrome&sni=max.ru&sid=10778ea288&spx=%2F&pqv=XGtXZ4xX7QYE71Rtw9mJsgIwRONaHnD-MGIbvpWFQh_UMmPx_IN-afnEJ4Bt6xfMWf9WzrfQNqjpZFLyPvN5TvrVJp6HK7c_WVNX_8awHj04l3YBbwoGV2nXum5lkA382hQz0fTdViY8JNKwfjqWHJICURpHCihQikRxtWtpekBkhwNMggyetK3L_amIu4kyDh4PxDcySY5KKl2fPE1tvYojlm9xw-jnHUFj8jWbVePUy92lMUHaKjxCqD7ME8TFCnQx8Mh8OIZxLT5FX8H6EMDmeSIpcAKVjllitVWhrHQf7RBdb4eVRmbmXiyVID0A3bzDwh2hU7WX014ykHpN9dqmOkwK96SgfCRkZT3uvT0LhKYLSdIqG450pjwni9E1VCXZ8Mnmq6aLHsMJc2b1tHkjazGhKUh00qWdgWUenpVZTRydjjNGS5CXsuQu2u5GpYWqZRjdTj7JFlHs2OcBtxcuSgcZGSt0olGaku3sO_E0y-S7fCCEBQ19nVyohoDsvGVScIvih8zEjdG8APIA_02YIfL0YrXEQ2sIl-5JXGLo42tB12aKxCgDbNJeC2o4nqPE1U65bPVMrjQbmOdXSekqsamI6_fYsM44z5VI3gEwD7eilg0eQ2MgH--sGz2HU92Cdw8hjVJ1o4w64xwgGacWUzYDR-qtN3B8cP7rO4QLhD04yW8CaatOaoiElbgVPqcaniO5u-eme3-ZZH-islIZS3hJV6rd4thROyWqG3QeftIEtDIyuGNOg2MIhUOFDGQrrN3I5LDOzDHT7yPjieCnjiZBm0uZChU7-CtSgEhTK3-VszXkza_V-PIKRQ32T1a5rPOJ_1eqUJYO-m3Xwt0UII4YsGc2B-xcxZhMpcRArL--IXfpDhHtuyS0MHiWkLsOawBkuSED7BJvFHLR2AkSssHLFwmUkwMQkbwOyB_sROCpQ8q4w55fMoRdj9yBwBHIiXPzoxrsYU316VMM0UqiKdLksWbVt3GxaMLDyZ7c-254KtMCheQGVjzVRs3kbneR6qRJNObatCay59IIU7lR7kbgH4VybGr8yVnd7QupbOSTw5ElMBRFem0mhTBGvlEEXDrr3Y3XfezqEN8FBpoAi3B3cJGaNYN-gyIHn-L9mFFmg9YfSkqp38YHCRnigot7M_KV4N5Vx4ls-0zC4pcT9guPjYMTHZlvEkYPLB3-53awksYOEc_65FYPoOlcVwIkCVsdLuZwq2LqFhefNgkAAGFJYK89JIjXKmyJru2rSr3pHAhUU818pz5Ywdfu4sOA87CJX1Jdy-Hi0HZs-IqoXkNZm5bnOh6rF_UEbciF4TLh0j-gJeQkCQe8ajJBPAPM05uYKy-SN_zlQwgz5CzCAqA7Z_2PMNFFpbKX61GU2iHWPBzmlDDQ8GOAelebSrU0M1stcc9SvIBFaC_yfvv3gXQuWvJQHchOd9Wy0btHtnnTeRvi66uIViZAdDV3ZKpAoH69li2vBkebZWFvC2kD0_rh58tDLKc8bl53SLZmxoXTb6f8EPfjZ1oNc_d8isaQh1nnBxwR7wBRwjdX27LuUxJWAoFIRuvl0ZIF2M0v8xbfzfoyETheyJcUgXFuG1hBWCP7px6NeUrE3IL2wN85ZfixDdcZ_z3BbYu7QuCJ7AYPpn6g1LqU6-kI8ltMHEI--5X1rFWI7JaJzNWFDgvg8bmmp-xyzjjmNQSt9AXt4VtUwiMsDwEZgB52I0-IEQXbWobkehrp2-r9yCAim9M6U_r9ax94atrnzZAPHQJWYmxGpLLP95NEzMJPee2yvBE2zvk7OaTgz-sIJ4-uUfMaYUzptcMwJvu7nw-ibgjcGRc5Qkg89u4kxNU5EKeEodN9hrROqQCDuAAJyTWpCd1Dfnkwvob1UtcWk9TRfCtfHdK7hQJkftkapFgOUKEm1cLAe3HkcDeAxxm9QDI9QMWluZUgG2UjbxABNBs1DgNN9eWN4GBNEwaUIlqy8BoKlju4mTi1CXPCcM7onFTQzygilzZCURpYe1o-nv3dBIGmzQnsXdwIVAtrxnRqLUF7aE_8i0DfawotO_0eyRHenP712W9XGVhvn8Ys481j_7b4SqYW683ski8YJlcDw2mBqjqeF2t78ePAZ0e-V9nuhc9q1d2ich7-EJWSoLxmM5tqgA4NvUh6MpVwC2H5p5zKLc285o-MyGukVDMbP_YFK982ug0sKGImw61WA9iyQXaowwujo0qgCuo2eaTlL5Qr55Pz2FmlaJR4QpoZE4rshGRn6UNFo5ShawXjZd4vlaJWhyNnp-jYl3CVMQkA1_mATq8Jf4BDHPcjz8SK5rPmzgAtHWK42-09LVoiQDovQt-q0mD1UBBeoju5lf7Rx80nmZO3f-S5YoTxItVsZtyl94TuOt3PFxnYEwVxy5DR4PZT_s2g9J-_qvTIFHjOJng6j4cSW1ceRsybAhypJVrH8BD_SRvWnIctC5C5mbBX662vljYE4iI23ZVreCf6fkDxzbCLcSPsX32Fcgmd6J5Ep3l8H79NF0u194JEjIT370lx167pfkg5n0wcuSAHP5wnYr0UpGIlM4JTc-7vpIGYmCb8xbWcySeIAIOrl9O1VUM&flow=xtls-rprx-vision#💎 🇷🇺 V1A / БЕЛЫЕ СПИСКИ"

# Твоя личная хардкод-нода (Несгораемый #2) - Финляндия
MY_FINLAND_NODE = "vless://d975972e-32ba-4684-ad8a-2050e591507b@212.22.82.138:8443?type=tcp&encryption=none&security=reality&pbk=Ep0bVT-syn_L9zqPfyCPnicaM7vgDuB3umRXnXl-pmo&fp=chrome&sni=api-maps.yandex.ru&sid=c6424a351e384d&spx=%2F&pqv=uGWr3ORCCDgRaXDGOvRb3jMkYupvLhC_2hynneYnjK8PRTacW5mXhKjBTHZqJKzmN-dtGKjhLRiYyTnKPwCTKcvO1P7sj4P9GtnMuX5XzfFJfjFKlZD8xcv5gnzZz-3VF-C5lBRcb7emDdrvwat5r7GVyiheemTj50OR927nO8CHK8X9N-b7TNR9Sj32pkGOKtyuxhY9fP37Yoj2KLpuqhOnFpOBcRzx9O8pQhoZcj77gjibTli9uVRgzDHFpj7i5DyclDwkOGU8NYrcFT_X8PODQRZkT8Flg7jUO5CYs7m61sOfyv5o4OzMyjCX1_g0AVYOx0oEXixaUneKLik-kicb2Lok0yxEQXLfxgxrw4OpcUp_Es6g1oE_zrRluTIqm24N7Xsj0vhC0g-5veNPaFPbpwQMLxE7-iJnjrb6s5nZ7-xK3WM2K0eFbo0ARIq2Q9CHsD7o_jRjjNEgXa_Eq2DifkGL6Fbxi1CYRpB5uuSvehdu-x44t6nBWjpVXt3u5kJbpgIb99wrnfYtZ2orXD7qa--YObJxek6RTgn_i5NKesdbmCWni8bvRD66zamvp_jQQXdz_GHGs7TjN1uSDVXWfI2N9ux0ysNfSN9Rz0gydHbrs1sb1nxxQD-StGkI6CslpPIA8cJxNotoeUdJjMoFcfaKAWldus-V3WJ7v7GSbB-8Ev2zrrJhaXXVziS42PFQ5oakzdaF7mf7jDmDXefvCgCJv7sZ-9xKx9lEuqxs0VRjE3bm8ct1uhErgCWOGeudL5dqkDWXak-3fYxhe5gp4-WoFGEH2sdZoLLWrMLtI3iTxq2Pi5KsHbaOfWVeeeGHded-JyR_hf2BrW72caM2oZMy4q5HPQjhj0UweWhfKdy3okrYlkoCO55FCXk1KTuWNq_LY8B5bEM01_Lm8jEceLGCRp59sDUnJySQj9Qeqp3AxPKhp9WQ1OSJ-IiiCOJEdDwCJVOw7KuaAO9ZcQVo3WPf9bhv7BoKMAdpDhy71t81f2brDS83RhNYLjVy4188cQtiyu-l3tuBj12I44FjU_gfDVj13LcVy9356I4qWxhIWJ0tvEQ0kPF0flav9ir-MRsL1yK20wfV0rrLuv5LstksbRy6LlyJf2inMv3NLZBhzC6uHxNa1sxx2QJRcfoW5EVQj7Rd-Z5ofAJNLhc6rU5F8ajipWS9lLDaP6UsLweiXP1_Ohjisx-yjXTq8PlkQkvdjkDSY0JzLmhe7xuKTbNSoafsDAk8GWBw4cL2MKrq6XA8tRYvWWbwEz3pY4lIH-ycZmmST8c8CNGBeaJ8OKFX1BxHBMEKT3AsYSuNNhUNPehKTNV4B8n6yquQT-skDEFTTRtkSs2RDFHGX0Xl86NWzWQFQUsgTvjVQo8MvSluYY4_6pJnVcSjAppaRFsu52fFx59Bwb7C5Yz6waSugvu6zTeyVj-4vDp70MFgdDFrlCnS0Y1_0ZfzGchm3KhTQzLwI8bFgua4wplSTusw0T6zMOzGXxo892n16bH9GV50R98ajouqLnWT-LRW1eqacAn-OumjONITR6sJKm9HKNSewzh-LDQJdY5ixfRWvgkTNMyhqa4EOS-1-XrSWGAXWsq8yQsmXAoX5nsreqEejtR4_q0zw-WsYGMIed31gajr0ieJPpirRQFVH-F5OtIHWBOvsc7Rx-WKL-VYZDi_ySGR6VcSisGjmcv_ywI8bEYZ-mIMkjOEPq0gtSxPeurid5e0Jat5Xr-w2AIQmBCpA_v2dK4QPFWiHsR2bynVps1aOcKewzfcg2ff7rGy7fOWct_nA5A3Lnm-hhWGY4wCvgIkk4vBdHTyffaFf9EAXwYv0jcZAnOqViwC7ohr1T9LZSAjaRx3XEAxVfmXahrGNSPRzPdC8nwT9Hcb5iROonKklz-XHbbUMMWHl3P2JhIUgF3oBplenfQWTq5eBUy7q4N4SkB5iKIiqe3iITEZ6XNFApqDHKKv3h1tMYO5Foyky0PR4fJgOz1BujvUmNcMbHkO8xyYvzVoUt7MdKmuMbeVIda4JG6OYy_MBiqZnttNbRrq1-h23gIB6hZia1doZ3zlgB3NBnEwoE80Z5M1omv5baSZGL80-SCsDR6lsfno8_8FO44NBICyiuHceTYhKscDrWv2bO_nk5krqpmOYqQGyw39lycgQ9xoU3FwbxQNoClF2TviUml3s02r9kw107PiIS2kQZu0IRY7i0XeOa_M542WKCeFteD9VwQs_djf_nd0l-nDYnQv8QlfXzguhv4579YUkXVgSTwnkk3wCGhczmjoIorX0cPomrpt3GmrdusH8hwOTe_vf6EB1Nd3OE2uODtET-1xtOdr9q_Hcl4pm7sWOTyva8nizDA8bldLY_0uG-OiewDvH9IOBfoNAPInf99lCkVfTZ8Xjr1PygsC4sv9_74tBZIaol_rNMyOLMI-OFFUrO45sFuQ5-uWp4ThacqGRfrsT88veacOmPPX5G9NHglVszqUESsZO7dOQ4ezMKB0Rdr17zhwUcvUuf2yYEzRbrPxEN5aion1NM6QVVQ-gUxGLHPf69ZLE3nEk7t3X0z6PKxDEj7MD42a97lq8MAyLNujEgOEsYY#💎 🇫🇮  V1A / Финляндия"

# Твоя личная хардкод-нода (Несгораемый #3) - Финляндия 2
MY_FINLAND_NODE_2 = "vless://3336a974-eca7-4e7b-a41f-1615a8c4dd2a@195.226.92.208:443?type=tcp&encryption=none&security=reality&pbk=i1pUoU92Zwbbtqy48NbuoQWJctyGa9dars7EZVj12Ew&fp=chrome&sni=api-maps.yandex.ru&sid=c6645cc4&spx=%2F&pqv=ppD1uVbnIl1VB1HOhMqRRuu47Dw_Xm79Pfad7PQn6kuNIK_7vxZnAhPJl7kyoFakygHs0jlqqni5bGBV0xu6qiOw5hnBxeuF-hTYq0jMoEQAsjzX2QaCcfOgC5gi444cs8gIkEg2doTh4QPPj4BMNAkcZkKwvv5776J32LJ3uI5QwHz9_n3SAGRNva0jAG-Ic0al4zp_O3YzJvwhdfMZrfTqxxQHNT-fUOCqJVldiUMUXZ-1ahcYWGo-dXQTKRTkxvvnG1DiNqWIMW-tVN3JenwzF9tLXP4tEUFpq5QkTeUnNS5CaGnswCQ-pQWo3TqAao4A8da2yKFw-8vOnPZXcgwyBO4y1JAL3ejZf03Ukwqt6vkdYB-Y7rAyvHsCQuxf8hjWG7fMfEWR5VLL9wT0RF69g3XKhXeoe7q12kC5Flz4Z2y4aEl6c9_OBmhC5Pz81TZkX5llp-CPzAvm4bg0qNgyKRAsYVxKwcLOtWKEO_3gDRL1RUQB5GauFDK4x703mwWyauuBt6sExz-rCi9u4brHeMWaFjenSBGMK-hPewYlKLeQYSvL8e5Q0BImh-HRPMoOPSNpCVIKGmXoNzNXxh20IiyDxBF4RBtTontIUM5V4QZ6-pPXRdVpTVS-RqcQeE0qEaCpzy7XAWgqb6cI9C74m99BlJeGa1TiDd7NX_oahi_eaLp945zf4hI0O3-8rUgEgQPusMv545l1_upafrGUHwWTYUb6Z1UnbNdkqRKCErso1r1JeHTWbQp05KkMyaEXPNioVtxJFttBjmgJ4ha2RpcnQoEGu8nMbXYYISBxmdsahVaMwrCZgLFe1i6bwtM8Laa0g-s-PeudQi8YLD5qYbByHzZSro5A6jZawtc68t8zSMlvVx-jNAecygzLI49AY4dcN8V0IAABb9NbbhyF8m8QkKitr7OYBrNO9wAcHVmsmmxb8OedDD9SUIrKliBC_-DzGrfG7dGaY6HFQNiny0GByE8RGd1J1YHz6uZ7liMJ21nJjUXLdPLOxSlvaU-AAAa_RmoUjwpauqEpzJWLK6TIKYnQJxs7bPb8SpUSzjXsZmvzSNmiZMG0f3pNcHPEjotE98S22a7uYCyNu7Jsm7OVafAWRAlEeRkflwBbomJ0LtQHsTzSGvNSNZAaiTRMPeLcLxm8H5y-MQozwducNgylac8BJYOK-PeAp_3RD-KWGTovZ_BChCEUA1xxkyn3HcZIFG_SZalbo1VdETmZTrXS6HSkg-xzw4TtggqwtwVu40pZdKd48sw6SU1Xsvz0BGoz58HuNIXLs6D5Sb_h712s7zlVLNpzKFTvlMVMGc7f4_GdfyZtEmlENx0HYYzjyxyYhRd7_LDu-YxZEy5zbwBvG362fJBogV4w3Hxnq_FuogsY-s810zZWEkN__y-mH36Dn9I_GiOL9rqKphjLIaKzZTurIfwHXDTJ4rk12AMKzZn4y5_9WiCD6ImnaXlmEn1r23K7mJ7Jkj5qKteQxOjajgPu7MpPQsvZj1AR_ja0AJhghJTOxwSinPNs86wFv79Rq9Su7KZnt7RyiyUnAx8CXW1wt3c5MX0-qiDPj2v5PhRjBmYC-rS52gakB0mRmGdfjrFFJO8aB1-yV2fLMS5M2kVgwMI-ealAOVyypzzeephQwyRGx2tC-_gnwLkf79GXE6zVw-MA-FvZ8enaVBR4eaf8C0njD2hDsuwa55e2iYxKTa6BvhN-XC_6oCGnZCDmfc1BgIWT4oL75TTKirOdO55b-2Nv6dwfnPDdbcIT4PHqDB2LjQ4zUmX1tKNTTZHTKy7D_rIcjpPQh5OFUPQ5XBuQgH_c7na6f6UD5sghpynh0wpNVc6fs4O8ELxEQsE4oW65l50fJCmoaXlyDiEvwyywHG6RFgAXPA1W2Lnf5avykmSptrg1QErD0WdCrDN6Eekfrp2Wwgq_BHfG481Boou4zwawNfHIoSY5oqVeHkhZyStHppgCs-kl0wsQVSe3W3UJxzqQ5w39Ldw2Zo3b_HFbRuIC8Qs6zPOQLkQSIIDEViayZoSuxBv46eQfbiYl42h53VWCXhOCh1kTMOJwCnOMfatkFnXCh_svYgzo7sgtJcyH2UcPaHV7BaWQoaa7mqzaEk-dutx5c8i2bMhtSejkd-C8mkc7CClrLqyXJvN8grqLQh8X6Zb48iwMRu-gLQvgXidhIPeXU366UzfYgvqtjL6ekbidTJERm8xGfpQMwPBYdxHrP4o6PhGQcITVOAGpFituwyKeZsyajY3KGRpzExJMOZI2FGLSDCLChhp3c_AamHTIR3Xfw5TBUZvtFe-CTNCpVdqzDIdYs868l55XcWbSgO1-bmKgKCxeWA-s8ArEKhKR0EEdiXMDerQCyPGLm0CQP8079QpVSt6n6UYuKr_Ng2x5DkdBKp07VW8bBRtC8ibEiRONpZ9UwifHem6PZZvdmVGJ7ZU7FYOVpPaYrx7wfALN1gHoTqP2yw8PdXeH-WSNLa-_TOWyhGuuKYpaNMqo2681cP-rSqMhPQb6sj-e4fzVLWkL5uSQwGK7Kf1nI2a4Sa_6k_Yr47L0Jzy_9RzImGT1UhRHN7TdPmSCk8K5HtqZBZE&flow=xtls-rprx-vision#💎 🇫🇮  V2A / Финляндия"

# Твоя личная хардкод-нода (Несгораемый #4) - Эстония
MY_ESTONIA_NODE = "vless://c54fd376-cc4d-491b-8791-10b5de2df020@195.226.92.208:8443?type=tcp&encryption=none&security=reality&pbk=dvIr932rH1xnpIhbCiw5Ky2Lh4s_hHgsydgctseo5Tk&fp=chrome&sni=api-maps.yandex.ru&sid=e4ab1919&spx=%2F&pqv=gYtTBdBv4dklfLTckzs41XFDOqZAEdAGft6v2wP7xXPPrcKjYzhp7Oz3JYnqc7MeyauP7ZnHuvHjTKFR717V730McWHQgii8wRZ-MObWRFezENyGEBLDeLXS3qStfpMl4bBY69JqWJ43vPlcQNDx0_j2vjV46aaxn_gaRCWENLCtemcdI063vxO2cOC0h9SKOrRpkTI2k9xUGbpO4oRbajJ-4t0nCzE65G3iQdJ_HCRWjrOfUPJDZeXEn5GHknLJfa6twQgcP8ZdLQCvBH5gyfgXwHFknLeT-ngqBUyXlQxtLA7owgRcPr9wkng7bjbdz5vgG35fyGB--CfowB9NVYbzajx8KanW20-bDWAe1yo8uds3rKbeRAaKLAShPcTzI5vFLbaXJVkl8S8rHuOU_s_5k8I0969-wuUabPzkQTyJB3ezygWSOc0JirPiSkDOi30hboqcn_LFu_MjMbDR89hE86gF6Wg96VW-mQtxmpciO9pvDOTUofNUCgDdYsOHrZc6-pCVbTRs37bd5vZGUnTiHVC34Sfq-H1nvirl1eE95Za8Cdwi5SexdfabO1wUBoe-gkGunD7sAAJ1iUdnN9oKLd-K77fpWp9JSQuZOEl0F18ARSnfaaIFTXeWnofHuuG5zhWDZVDZSJmzc3zj58qvF3wm1rqLwWhfnw0Zz-Qks__u_MHmidRvRgMVqf55riC_eZrq-6Qxpox1_PAzUK1W6UOCK7FlBZsaFRSm14reBeg_LDcslP1x1PCr4J-qms7v_1A-zZ6pHuK4X4Ojfvm1IU3XCjequP9NrGc1fwyUY-ho3NvE-cX0-7J31kbviQgqJ3f1RqhxV84GeynmsTRrp_7EmqpnrKNC_h6Gwsv3OcjbsZ4i8hivX_fj9Q77ECmEVzKD8wiNJNA8rxLveFsEbA-5OQ8KkyshgELIIcADJPmKFrWFlQpqdIEKzO6TVuPF9FTxXpIsmQ4BRpeTtUph1pTvui7k4Zdwii_HmVNIPjqBGsQCUh9z5B8g3hhfJ4JELXYhYCpnrjLugsDbMTn4eFXjE5EfVe-ykY785iyjZWdT6NEisPSFg510ocW6PMdvBcqDHxsB6rn7hFKOY4TFGCCI0XqB-0DN_QHd-4ULPSg-qFst-KpU0enGMq6k3ctgFM1FZsqh3JP5PiIlzZuaulKeV8Ll-n0aOpww160UVV1XC1HgAaJEJREUsNGv_NRqkBud_qqqiGFIjsh6TFw_7li500IRVMvF-kFXrPSPj5P7OVB8JqKnvpAHF2-y_YiKNYJ1NaG-qqbXEYRCH3F_atMZXSfQnR2L8UmIVBSkx2hEO4IlIy_6mZHRkJpLxN4mix9lOwcuC3EMv4BQ13EPdcD7A9-oIxaa8BVTr6GEndIdhyRKqVtZcLywO49HOmmbaEzqoaIUM6Ne8pA42KoyVkDf_2zaXnWCDH7tB5xXP13yjelO49FuLzXxIxdd6Gq846bRpuQjSdOEd-vuktYVN4Nrzb_Tr9G129SwCAWYhZcFmEiAg54qJbT0YTxSfku8UPxIC_H2lw0rk2MPmg54VFHGXLo0Xl69NB3kJ-5yt_aXwU-VALZRg6hqxVQgUpJ8P0zdrNNNGTosrMFO-RYwQaTxDivcc-VT284j300UCMf9hRoBZ5bIcgZzd65kkgKyoPtL6BugfKu9EYRg_GxRbxecje7l6mNrFjqgyy8a_Bzrc1qm1fAjISVV2doUtul8O2RmbYlIOxmZ0GaJpdvZMS35CfSkmzpnAOD6TJbrdyAi6vbdivtplf4wY5aIQarU1z2NVFhrlak7TRef0ysvvMfHyuWbisqKaMmC7KXa41GVU4osufjHqcmwmOgIfS6LOAKXwiHAL61vws6wSqUdi4ZQ_GFEUipftq9tArMmN4fqJSFuYzhpJnm_U1AY2a4uAj5zXVThd257FSE125B-WeRKKYEnLHO47oiYfwUgE3yNZPnqddCfQZCKOcQmWxcQbr57HA6NrbJEZHQP3-Z5aCc3j2keNRf174jdnjVyFwvmPiYTLgQ1O9-CEQ8FhjJEFDdkK2OIxcI8MDd4bPkKVjH_6a_fSgM8R9fGFn5YggNpAsN2-y6f1rnXbxtvC_pHUs3Fx4c0Pcp_FO7Fgz6uyZQzSE1ezjnvMEMDvJkGywEr7zGzBanXItTbqVME5M2FRJmF1cnTfIG1xdzDHygAlgF8cmdEOMhy_bdSMDkqwhAuboG5JK9jz2FvAt3L6aSd5BTuz8Hxwck5HV5fKXCC0T9Y3zP45ujc8uovD63_rfIxyV4XJT6xvDwdwgvR5gw3QFZCI0NtPj4QOLOq6uj-tbT8bm7cjMcY-TX_-fZSFN_X6JZ9CBjrOGXiBMhlv30yF25ci4CBwukJJL9OJrED5gkYvAt3judCNaFByYDhbXcZM88V9v0GWgy51ok3bxRICpuI11cxdlfkcAv1Mgi092KEotD3ROFV19CNSTRcOqSpfUugyHvIpce-emVGUM__MYISFkiSd73J1uv_WbDTEMWfFieAISwHEtXx85gpkREqDeLv4pv8oHBUYxjr39kuzrv2yvOwIma2oasDx6mT-jFG0Htye3CWDUEL9go#💎 🇪🇪  V2A / Эстония"

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
