- `steady`: 정직한 GPU 100대, 하루 40명이 그룹을 원함(목표 발행 50보다 적음)
- `spam-10x`: 30일째 공격자가 GPU 1,000대(정직한 쪽의 10배)를 붙이고, 얻는 대로 가지를 만듦
- `hoard-10x`: 같은 공격자가 권리를 쓰지 않고 쌓아 둠(시장 독점, 재고 부풀리기)
- `buy-surplus`: GPU 없는 공격자가 정직한 채굴자의 남는 권리를 매일 절반씩 사서 가지를 만듦(양도 가능)
- `flash-50x`: 30~32일 사흘만 GPU 5,000대(50배)를 붙였다가 뺌: 조절이 따라오기 전의 틈
- `miners-leave`: 60일째 정직한 GPU가 90% 빠짐
- `demand-surge`: 60~90일 그룹을 원하는 사람이 하루 120명으로 늘어남
- `growth-2y`: 2년 동안 생태계가 자람: 정직한 GPU 50→400대, 그룹을 원하는 사람 하루 10→160명
- `growth-2y-spam`: 같은 2년, 30일째부터 공격자 GPU 1,000대가 계속 마구 씀

### D1 처음 설계

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 47.7 | 346.4 | 39.1 | 154.4 | 67.2 | 48.3 | 59.8 | 85.2 | 423.8 |
| max mints in a day | 229 | 2106 | 551 | 457 | 2488 | 229 | 293 | 894 | 5139 |
| max branches in a day | 55 | 1941 | 52 | 277 | 2468 | 53 | 151 | 212 | 3891 |
| attacker share of mints | 0.0 | 0.879 | 0.685 | 0.0 | 0.265 | 0.0 | 0.0 | 0.0 | 0.795 |
| attacker branches | 0 | 51409 | 0 | 20711 | 3225 | 0 | 0 | 0 | 238451 |
| honest branches | 7031 | 7084 | 2363 | 7185 | 7185 | 7160 | 9581 | 60885 | 61174 |
| honest founders served | 1.0 | 1.0 | 0.334 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| honest queue at the end | 0 | 0 | 4711 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean wait (days) | 0.0 | 0.01 | 9.33 | 0.0 | 0.0 | 0.0 | 0.0 | 0.01 | 0.13 |
| all issued | 8923 | 58500 | 7498 | 28032 | 12151 | 9025 | 10921 | 61047 | 300068 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 1902 | 640 | 3435 | 249 | 1768 | 1865 | 1340 | 2406 | 1450 |
| expired | 0 | 0 | 2754 | 0 | 0 | 0 | 0 | 0 | 0 |
| difficulty end / start | 1.74 | 7.89 | 12.2 | 0.27 | 1.55 | 0.13 | 1.54 | 1.58 | 2.49 |
| GPU-days per attacker right | None | 2.92 | 29.21 | None | 4.65 | None | None | None | 2.89 |
| GPU-days per honest right | 2.02 | 2.54 | 7.62 | 0.64 | 2.02 | 0.8 | 1.65 | 2.65 | 2.63 |

### D2 흐름만

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 50.9 | 54.3 | 54.3 | 50.9 | 71.1 | 50.3 | 50.9 | 50.7 | 52.0 |
| max mints in a day | 92 | 602 | 602 | 92 | 2846 | 130 | 83 | 92 | 936 |
| max branches in a day | 65 | 595 | 51 | 77 | 2839 | 65 | 132 | 112 | 894 |
| attacker share of mints | 0.0 | 0.766 | 0.766 | 0.0 | 0.295 | 0.0 | 0.0 | 0.0 | 0.787 |
| attacker branches | 0 | 7445 | 0 | 2076 | 3686 | 0 | 0 | 0 | 29454 |
| honest branches | 7095 | 2278 | 2278 | 7084 | 7083 | 7178 | 9159 | 36519 | 7981 |
| honest founders served | 1.0 | 0.322 | 0.322 | 0.998 | 1.0 | 1.0 | 0.949 | 0.595 | 0.131 |
| honest queue at the end | 0 | 4788 | 4788 | 11 | 0 | 0 | 495 | 24827 | 53121 |
| mean wait (days) | 0.0 | 18.41 | 18.41 | 0.02 | 0.0 | 0.0 | 10.79 | 38.27 | 222.97 |
| all issued | 9160 | 9723 | 9723 | 9160 | 12516 | 9060 | 9159 | 36519 | 37435 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 2087 | 369 | 4688 | 36 | 1747 | 1886 | 686 | 4098 | 1182 |
| expired | 0 | 0 | 3347 | 0 | 0 | 0 | 0 | 0 | 0 |
| difficulty end / start | 1.13 | 10.6 | 10.6 | 1.13 | 1.08 | 0.09 | 0.82 | 6.63 | 31.02 |
| GPU-days per attacker right | None | 20.15 | 20.15 | None | 4.07 | None | None | None | 23.43 |
| GPU-days per honest right | 1.97 | 7.9 | 7.9 | 1.97 | 2.04 | 0.79 | 1.97 | 4.43 | 20.28 |

### D3 흐름만 + 하루 상한

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 50.9 | 51.8 | 51.8 | 50.9 | 51.5 | 50.5 | 50.9 | 50.7 | 50.9 |
| max mints in a day | 92 | 100 | 100 | 92 | 100 | 100 | 83 | 92 | 100 |
| max branches in a day | 65 | 137 | 51 | 77 | 143 | 65 | 132 | 112 | 116 |
| attacker share of mints | 0.0 | 0.762 | 0.762 | 0.0 | 0.031 | 0.0 | 0.0 | 0.0 | 0.782 |
| attacker branches | 0 | 7086 | 0 | 2076 | 290 | 0 | 0 | 0 | 28669 |
| honest branches | 7095 | 2214 | 2214 | 7084 | 7124 | 7232 | 9159 | 36519 | 7974 |
| honest founders served | 1.0 | 0.315 | 0.315 | 0.998 | 1.0 | 1.0 | 0.949 | 0.595 | 0.13 |
| honest queue at the end | 0 | 4819 | 4819 | 11 | 0 | 0 | 495 | 24827 | 53303 |
| mean wait (days) | 0.0 | 16.57 | 16.57 | 0.02 | 0.0 | 0.0 | 10.79 | 38.27 | 223.57 |
| all issued | 9160 | 9300 | 9300 | 9160 | 9251 | 9093 | 9159 | 36519 | 36643 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 2087 | 369 | 4306 | 36 | 1841 | 1863 | 686 | 4098 | 1140 |
| expired | 0 | 0 | 2958 | 0 | 0 | 0 | 0 | 0 | 0 |
| difficulty end / start | 1.13 | 15.21 | 15.21 | 1.13 | 1.28 | 0.12 | 0.82 | 6.63 | 37.95 |
| GPU-days per attacker right | None | 21.17 | 21.17 | None | 51.72 | None | None | None | 24.07 |
| GPU-days per honest right | 1.97 | 8.13 | 8.13 | 1.97 | 2.01 | 0.79 | 1.97 | 4.43 | 20.29 |

### D4 D3 + 보증 길

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 80.2 | 81.4 | 81.4 | 80.2 | 81.2 | 79.6 | 80.5 | 80.3 | 81.0 |
| max mints in a day | 123 | 135 | 135 | 123 | 139 | 129 | 130 | 122 | 137 |
| max branches in a day | 60 | 133 | 55 | 100 | 143 | 60 | 145 | 156 | 137 |
| attacker share of mints | 0.0 | 0.485 | 0.485 | 0.0 | 0.02 | 0.0 | 0.0 | 0.0 | 0.493 |
| attacker branches | 0 | 7107 | 0 | 7206 | 295 | 0 | 0 | 0 | 28757 |
| honest branches | 7214 | 7199 | 7199 | 7214 | 7104 | 7122 | 9583 | 53181 | 29615 |
| honest founders served | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.876 | 0.483 |
| honest queue at the end | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 7522 | 31738 |
| mean wait (days) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 4.09 | 69.99 |
| all issued | 14454 | 14649 | 14649 | 14454 | 14621 | 14356 | 14499 | 57858 | 58372 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 7240 | 1208 | 4969 | 65 | 7222 | 7234 | 4916 | 7302 | 2667 |
| expired | 0 | 0 | 2940 | 0 | 0 | 0 | 0 | 4677 | 0 |
| difficulty end / start | 1.15 | 10.29 | 10.29 | 1.15 | 1.2 | 0.13 | 1.1 | 7.23 | 24.38 |
| GPU-days per attacker right | None | 21.11 | 21.11 | None | 50.85 | None | None | None | 23.99 |
| GPU-days per honest right | 1.25 | 2.39 | 2.39 | 1.25 | 1.26 | 0.5 | 1.24 | 2.8 | 5.46 |

### D5 D4, 보증 권리는 양도 불가

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 80.2 | 81.4 | 81.4 | 80.2 | 81.2 | 79.6 | 80.5 | 80.3 | 81.0 |
| max mints in a day | 123 | 135 | 135 | 123 | 139 | 129 | 130 | 122 | 137 |
| max branches in a day | 60 | 133 | 55 | 103 | 143 | 60 | 145 | 145 | 136 |
| attacker share of mints | 0.0 | 0.485 | 0.485 | 0.0 | 0.02 | 0.0 | 0.0 | 0.0 | 0.493 |
| attacker branches | 0 | 7107 | 0 | 7206 | 295 | 0 | 0 | 0 | 28757 |
| honest branches | 7214 | 7199 | 7199 | 7214 | 7104 | 7122 | 9583 | 50427 | 27820 |
| honest founders served | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.831 | 0.453 |
| honest queue at the end | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10276 | 33533 |
| mean wait (days) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 8.92 | 88.66 |
| all issued | 14454 | 14649 | 14649 | 14454 | 14621 | 14356 | 14499 | 57858 | 58372 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 4602 | 1208 | 4724 | 66 | 4661 | 4619 | 4591 | 5466 | 2640 |
| expired | 2685 | 261 | 3201 | 0 | 2645 | 2694 | 329 | 7431 | 1795 |
| difficulty end / start | 1.15 | 10.29 | 10.29 | 1.15 | 1.2 | 0.13 | 1.1 | 7.23 | 24.38 |
| GPU-days per attacker right | None | 21.11 | 21.11 | None | 50.85 | None | None | None | 23.99 |
| GPU-days per honest right | 1.25 | 2.39 | 2.39 | 1.25 | 1.26 | 0.5 | 1.24 | 2.8 | 5.46 |

### D6 D5 + 남으면 어렵게

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 49.0 | 73.5 | 49.9 | 80.2 | 50.7 | 48.9 | 59.7 | 67.3 | 74.4 |
| max mints in a day | 103 | 137 | 137 | 123 | 137 | 103 | 118 | 135 | 124 |
| max branches in a day | 54 | 132 | 56 | 103 | 145 | 56 | 136 | 135 | 129 |
| attacker share of mints | 0.0 | 0.46 | 0.27 | 0.0 | 0.031 | 0.0 | 0.0 | 0.0 | 0.461 |
| attacker branches | 0 | 6137 | 0 | 7206 | 294 | 0 | 0 | 0 | 24678 |
| honest branches | 7088 | 7136 | 6723 | 7214 | 7038 | 7103 | 9654 | 46854 | 27854 |
| honest founders served | 1.0 | 1.0 | 0.949 | 1.0 | 1.0 | 1.0 | 1.0 | 0.767 | 0.455 |
| honest queue at the end | 0 | 0 | 361 | 0 | 0 | 0 | 0 | 14199 | 33305 |
| mean wait (days) | 0.0 | 0.0 | 0.93 | 0.0 | 0.0 | 0.0 | 0.07 | 22.61 | 88.69 |
| all issued | 9282 | 13342 | 9427 | 14454 | 9564 | 9267 | 11048 | 48592 | 53579 |
| target R at the end | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| max unspent stock | 1716 | 981 | 1788 | 66 | 1705 | 1723 | 1394 | 2557 | 2021 |
| expired | 685 | 23 | 1294 | 0 | 724 | 671 | 0 | 1738 | 1047 |
| difficulty end / start | 2.13 | 11.23 | 37.72 | 1.15 | 4.93 | 0.22 | 2.06 | 8.22 | 22.06 |
| GPU-days per attacker right | None | 24.44 | 59.01 | None | 51.02 | None | None | None | 27.96 |
| GPU-days per honest right | 1.94 | 2.5 | 2.61 | 1.25 | 1.94 | 0.78 | 1.63 | 3.33 | 5.6 |

### D7 일정형(반감 360일) + 따라가는 상한

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 72.1 | 73.4 | 73.4 | 72.1 | 72.5 | 71.5 | 71.2 | 57.1 | 57.3 |
| max mints in a day | 119 | 128 | 128 | 119 | 128 | 119 | 119 | 119 | 139 |
| max branches in a day | 54 | 127 | 58 | 105 | 133 | 58 | 139 | 105 | 108 |
| attacker share of mints | 0.0 | 0.439 | 0.439 | 0.0 | 0.021 | 0.0 | 0.0 | 0.0 | 0.376 |
| attacker branches | 0 | 5841 | 0 | 5974 | 272 | 0 | 0 | 0 | 15638 |
| honest branches | 7091 | 7110 | 7110 | 7091 | 7240 | 7116 | 9663 | 35966 | 24165 |
| honest founders served | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.588 | 0.395 |
| honest queue at the end | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 25153 | 36988 |
| mean wait (days) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 33.73 | 94.48 |
| all issued | 13098 | 13315 | 13315 | 13098 | 13180 | 13004 | 12960 | 41435 | 41570 |
| target R at the end | 35.4 | 35.4 | 35.4 | 35.4 | 35.4 | 35.4 | 35.4 | 12.5 | 12.5 |
| max unspent stock | 4022 | 1163 | 4196 | 60 | 3955 | 3985 | 3297 | 5074 | 2772 |
| expired | 2484 | 350 | 2958 | 0 | 2127 | 2359 | 0 | 5469 | 1767 |
| difficulty end / start | 1.41 | 11.19 | 11.19 | 1.41 | 1.49 | 0.12 | 1.41 | 39.9 | 125.03 |
| GPU-days per attacker right | None | 25.68 | 25.68 | None | 55.15 | None | None | None | 44.12 |
| GPU-days per honest right | 1.37 | 2.41 | 2.41 | 1.37 | 1.39 | 0.55 | 1.39 | 3.91 | 6.24 |

### D8 비례형(누적의 1%) + 따라가는 상한

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 96.3 | 95.3 | 95.3 | 96.3 | 93.5 | 96.0 | 95.5 | 400.3 | 400.7 |
| max mints in a day | 242 | 219 | 219 | 242 | 229 | 226 | 207 | 634 | 659 |
| max branches in a day | 59 | 219 | 57 | 219 | 72 | 56 | 129 | 183 | 638 |
| attacker share of mints | 0.0 | 0.598 | 0.598 | 0.0 | 0.005 | 0.0 | 0.0 | 0.0 | 0.73 |
| attacker branches | 0 | 9831 | 0 | 9421 | 78 | 0 | 0 | 0 | 206796 |
| honest branches | 7007 | 6604 | 6604 | 7007 | 7196 | 7096 | 9462 | 60903 | 61221 |
| honest founders served | 1.0 | 0.925 | 0.925 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| honest queue at the end | 0 | 537 | 537 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean wait (days) | 0.0 | 7.71 | 7.71 | 0.01 | 0.0 | 0.0 | 2.2 | 0.0 | 0.0 |
| all issued | 16597 | 16435 | 16435 | 16597 | 16124 | 16552 | 16457 | 283135 | 283440 |
| target R at the end | 163.9 | 162.3 | 162.3 | 163.9 | 159.4 | 163.6 | 162.6 | 500 | 500 |
| max unspent stock | 9015 | 125 | 8134 | 184 | 8742 | 9010 | 6995 | 45262 | 12286 |
| expired | 575 | 0 | 1697 | 0 | 108 | 446 | 0 | 177126 | 3137 |
| difficulty end / start | 0.06 | 0.58 | 0.58 | 0.06 | 0.06 | 0.01 | 0.06 | 0.17 | 0.6 |
| GPU-days per attacker right | None | 15.26 | 15.26 | None | 192.31 | None | None | None | 3.34 |
| GPU-days per honest right | 1.08 | 2.73 | 2.73 | 1.08 | 1.12 | 0.43 | 1.09 | 0.57 | 2.11 |

### D9 보증 쓰임 추이형 + 따라가는 상한

| 지표 | steady | spam-10x | hoard-10x | buy-surplus | flash-50x | miners-leave | demand-surge | growth-2y | growth-2y-spam |
|---|---|---|---|---|---|---|---|---|---|
| mints/day (after settling) | 73.0 | 77.4 | 77.4 | 73.0 | 72.6 | 73.0 | 93.8 | 169.9 | 169.5 |
| max mints in a day | 107 | 124 | 124 | 107 | 111 | 118 | 248 | 384 | 351 |
| max branches in a day | 64 | 124 | 87 | 102 | 97 | 64 | 142 | 180 | 306 |
| attacker share of mints | 0.0 | 0.418 | 0.418 | 0.0 | 0.009 | 0.0 | 0.0 | 0.0 | 0.385 |
| attacker branches | 0 | 5525 | 0 | 5287 | 106 | 0 | 0 | 0 | 46228 |
| honest branches | 7120 | 7229 | 7229 | 7120 | 7120 | 7145 | 9527 | 61018 | 60855 |
| honest founders served | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| honest queue at the end | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mean wait (days) | 1.03 | 2.03 | 2.03 | 1.03 | 1.29 | 1.02 | 0.77 | 0.0 | 0.0 |
| all issued | 12476 | 13219 | 13219 | 12476 | 12413 | 12477 | 15931 | 120248 | 119931 |
| target R at the end | 38.8 | 39.3 | 39.3 | 38.8 | 38.9 | 39.3 | 41.4 | 158.3 | 152.1 |
| max unspent stock | 3654 | 360 | 3907 | 57 | 3626 | 3688 | 5338 | 13244 | 3605 |
| expired | 1740 | 131 | 2339 | 25 | 1651 | 1729 | 1853 | 45986 | 9243 |
| difficulty end / start | 0.24 | 4.06 | 4.06 | 0.24 | 0.22 | 0.03 | 0.24 | 0.52 | 1.73 |
| GPU-days per attacker right | None | 27.15 | 27.15 | None | 141.51 | None | None | None | 14.93 |
| GPU-days per honest right | 1.44 | 2.34 | 2.34 | 1.44 | 1.46 | 0.58 | 1.13 | 1.35 | 2.2 |
