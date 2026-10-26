# GNS3 Lab Studio

GNS3와 VM이 없어도 시작할 수 있는 **VRRP + OSPF 이중화 실습 설계 도우미**입니다.
Python 표준 라이브러리만 사용하며 외부 패키지와 API 키가 필요 없습니다.

## 내 PC에서 실행

Python 3.10 이상을 설치하고 저장소를 내려받은 후, 저장소 폴더에서 실행하세요.

```bash
python -m gns3_auto serve
```

Windows에서 `python` 명령이 없다면 `py -m gns3_auto serve`를 사용하세요.
브라우저 주소창에 `http://127.0.0.1:8080`을 입력하세요.
종료는 터미널에서 Ctrl+C입니다. 기본 서버는 해당 PC에서만 접근할 수 있습니다.
클라우드 환경의 localhost는 사용자 PC의 localhost와 다릅니다.

1. 요청에 `이중화`, `VRRP`, `OSPF` 중 하나를 포함합니다.
2. 설계를 생성하고 장비별 설정 초안을 확인합니다.
3. ZIP 파일을 다운로드합니다.

CLI만 사용할 수도 있습니다. 기존 출력 파일은 덮어쓰지 않습니다.

```bash
python -m gns3_auto plan "VRRP와 OSPF 이중화" --output lab.zip
python -m unittest discover -s tests -v
```

## 현재 구현 범위

- 한국어 요청에서 지원 실습 여부를 판별하는 규칙 기반 플래너
- 고정 토폴로지: PC1 — LAN 스위치 — R1/R2 — R3 — PC2
- VRRP VIP `192.168.10.1`, R1 우선순위 150 / R2 우선순위 100
- R1/R2/R3 OSPF area 0, LAN 인터페이스는 passive
- FRRouting `frr.conf`, `daemons`, keepalived 설정과 VPCS 호스트 명령 ZIP 내보내기
- GNS3 v2 API 서버 조회와 정지된 장비·링크 생성용 CLI
- 플래너·ZIP·웹 API·모의 GNS3 호출 테스트

현재 버전은 LLM 기반 범용 에이전트가 아닙니다. 요청한 장비 수, 주소 대역, 임의의
프로토콜을 해석하지 않으며 지원 키워드가 있는 요청은 동일한 실습을 만듭니다.
실제 장비 설정 주입, 자동 장애 실행, ping 측정, 원인 분석·복구는 아직 구현하지 않았습니다.
화면과 다운로드 파일은 설계 초안이며 실제 통신 성공이나 이중화 동작을 증명하지 않습니다.

## 실제 GNS3 연결 (선택)

설계 도우미를 쓰는 데 GNS3는 필요하지 않습니다. 실제 패킷을 보내려면 별도 단계로
사용자 PC 또는 서버에 GNS3 서버와 실행 가능한 장비 템플릿을 준비해야 합니다.
이 저장소는 GNS3 서버나 장비 이미지를 자동 설치하지 않습니다.

```bash
python -m gns3_auto inspect --url http://127.0.0.1:3080
python -m gns3_auto deploy --url http://127.0.0.1:3080 --router-template ROUTER_TEMPLATE_ID --host-template VPCS_TEMPLATE_ID --confirm-create
```

위 주소는 **이 명령을 실행하는 컴퓨터의** GNS3 서버입니다. 클라우드에서 실행하는
명령으로 PC의 localhost에 연결할 수 없습니다. 첫 버전은 인증 없는 격리된 로컬 GNS3
v2 API를 대상으로 합니다. 서버를 인터넷에 공개하지 말고, 인증 서버 연결은 별도 구현이 필요합니다.

`inspect`로 나온 template_id를 사용하세요. 라우터 템플릿은 다음 조건이 필요합니다.

- Linux + FRRouting + keepalived, eth0부터 eth2까지 3개 이상 Ethernet 어댑터
- IPv4 forwarding과 zebra/ospfd 활성화
- VRRP multicast와 keepalived에 필요한 네트워크 권한 지원
- 호스트 템플릿은 VPCS 사용

`deploy`는 프로젝트, 정지된 노드, 링크만 만듭니다. 설정은 자동 적용하지 않습니다.
이미지에 맞게 ZIP의 설정을 적용한 다음 장비를 실행하세요. 실행 중 실패하면
프로젝트 ID를 오류에 표시하고 진단을 위해 부분 생성된 프로젝트를 남깁니다.
자동 재시도하면 별도 프로젝트가 생길 수 있으므로 먼저 기존 프로젝트를 확인하세요.

### 인터페이스 매핑

| 장비 | eth0 | eth1 | eth2 |
|---|---|---|---|
| R1 | LAN: 192.168.10.2/24 | R3: 10.0.13.1/30 | 미사용 |
| R2 | LAN: 192.168.10.3/24 | R3: 10.0.23.1/30 | 미사용 |
| R3 | R1: 10.0.13.2/30 | R2: 10.0.23.2/30 | PC2: 192.168.20.1/24 |

어댑터 번호 0/1/2가 eth0/1/2에 매핑되는 템플릿을 사용해야 합니다.
생성한 라우터 설정을 개발 PC의 네트워크에 적용하지 마세요.

### 실제 장비 검증 절차 (미실행)

1. R1/R2/R3에서 `vtysh -c 'show ip ospf neighbor'`로 R3와 인접 관계를 확인합니다.
2. R1에 VIP가 있고 R2에는 없는지 `ip address show dev eth0`로 확인합니다.
3. PC1에서 `ping 192.168.20.10`을 실행해 정상 통신을 확인합니다.
4. PC1에서 연속 ping을 보내며 **R1 전체를 정지**합니다.
5. R2 VIP 인계와 통신 복구를 확인하고 패킷 손실과 시간을 기록합니다.
6. R1을 복구하고 기본 preemption에 따른 주 역할 복귀와 통신을 확인합니다.

업링크만 끊는 장애는 현재 keepalived 설정이 감지하지 않습니다.
단일 LAN 스위치와 R3도 이 실습에서 이중화 대상이 아닙니다.
가상 환경의 측정 시간은 물리 장비 성능을 보장하지 않습니다.

## 개발 환경

의존성 설치나 빌드 단계가 없습니다. 테스트는 `unittest`로 실행합니다.
이 클라우드에서 `/dev/kvm`은 확인되지 않았으며 실제 GNS3 및 가상 라우터 실행은
검증하지 않았습니다. 실제 배포 연결은 모의 API 호출 테스트로만 확인했습니다.
