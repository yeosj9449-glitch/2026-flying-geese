# 집 밖에서 접속하기 · 리포트 메일 · 백업

웹앱을 휴대폰으로 출근길에 보거나, 매월 결산 리포트를 메일로 받으려면 아래 중 하나를 고릅니다.

| 방법 | 이런 분께 | 필요한 것 | 보안 |
| --- | --- | --- | --- |
| **A. Tailscale (권장)** | 부부만 쓰면 충분할 때 | 집 컴퓨터 1대 + 부부 휴대폰에 Tailscale 앱 | 우리 기기끼리만 연결되는 사설망. 인터넷에 웹앱이 노출되지 않음 |
| B. 도메인 + HTTPS | 어떤 기기·브라우저에서든 주소로 접속하고 싶을 때 | 항상 켜 둘 컴퓨터(NAS·미니PC·클라우드 VM), 도메인, 공유기 포트포워딩 | 인터넷에 공개됨. 아래 보안 장치가 켜짐 |

어느 쪽이든 **집 컴퓨터는 켜 두어야** 합니다. 데이터는 `우리집.db` 파일 하나에 있습니다.

---

## A. Tailscale로 우리 기기에서만 접속 (권장)

1. 집 컴퓨터와 부부 휴대폰에 [Tailscale](https://tailscale.com/download)을 설치하고 **같은 계정**(또는 초대한 계정)으로 로그인합니다.
2. 집 컴퓨터에서 웹앱을 켭니다.
   ```bash
   python -m household_finance serve --db 우리집.db          # 이 컴퓨터에서만 열림 (127.0.0.1:8000)
   ```
3. 같은 컴퓨터에서 Tailscale이 HTTPS 주소를 만들어 연결하게 합니다.
   ```bash
   tailscale serve --bg 8000
   ```
   화면에 나온 `https://<컴퓨터이름>.<tailnet>.ts.net` 주소를 휴대폰 브라우저에 북마크하면 끝입니다.
   Tailscale에 로그인한 우리 기기에서만 열립니다.
4. (선택) 예약 작업도 켜 두면 매일 백업하고 매월 리포트를 메일로 보냅니다 → [리포트 메일](#리포트-메일)

Docker를 쓴다면 2번 대신 `docker compose up -d --build app scheduler`(B의 1~2단계, 도메인 없이)로 켜고 3번을 그대로 하면 됩니다.

## B. 도메인 + HTTPS로 공개 (Docker)

항상 켜 둘 컴퓨터에 [Docker](https://docs.docker.com/get-docker/)가 설치되어 있어야 합니다.

1. **도메인 연결**: 도메인(예: `home.우리집.com`)의 A 레코드를 집 공인 IP로 지정합니다. 공유기에서 **80·443 포트**를 이 컴퓨터로 포트포워딩합니다.
2. **설정 파일**: 저장소의 `household_finance/deploy` 폴더에서
   ```bash
   cp .env.example .env      # DOMAIN과 메일 설정을 채움
   docker compose up -d --build
   ```
   Caddy가 Let's Encrypt 인증서를 자동으로 받아 `https://도메인`으로 웹앱을 엽니다.
3. **처음 설정**: 공개된 서버는 아무나 먼저 가계를 만들 수 없도록 **설치 코드**를 요구합니다.
   ```bash
   docker compose logs app | grep 설치     # 처음 설정용 설치 코드: 6F0871
   ```
   `https://도메인`에 접속해 코드와 함께 본인·배우자 계정을 만듭니다. 1단계 엑셀이 있으면 [내역 가져오기 → 엑셀 파일과 주고받기]에서 올립니다.

### 공개 서버에서 켜지는 보안 장치
- 로그인 쿠키는 HTTPS로만 전송(Secure·HttpOnly·SameSite=Strict), 30일 후 만료. DB에는 세션 토큰의 해시만 저장
- 같은 아이디·IP에서 로그인 5번 실패하면 15분간 차단
- 다른 사이트에서 몰래 보내는 저장 요청 차단, 보안 헤더(CSP·HSTS·프레임 금지)
- 비밀번호는 scrypt 해시로 저장
- 웹앱 컨테이너는 관리자 권한 없이 실행, 웹앱 포트(8000)는 이 컴퓨터 안에서만 열림

**권장 습관**: 비밀번호는 다른 사이트와 다르게 12자 이상, 공유기·서버 업데이트, 아래 백업 확인.

---

## 리포트 메일

매월 정한 날(기본 3일)에 지난달 결산 리포트를 부부에게 메일로 보냅니다. 웹앱 [결산 리포트] 화면의 **메일로 보내기** 버튼으로 바로 보낼 수도 있습니다.

`.env`(Docker) 또는 환경변수에 설정합니다. 비밀번호를 코드나 DB에 남기지 않기 위해서입니다.

```bash
HH_SMTP_HOST=smtp.gmail.com
HH_SMTP_PORT=587
HH_SMTP_USER=우리집@gmail.com
HH_SMTP_PASSWORD=앱비밀번호16자리      # Gmail: 구글 계정 → 보안 → 2단계 인증 → 앱 비밀번호
HH_MAIL_TO=본인@gmail.com, 배우자@naver.com
REPORT_DAY=3
```

Docker 없이 쓸 때는 웹앱과 별도로 예약 작업을 켭니다.
```bash
python -m household_finance scheduler --db 우리집.db --backup-dir 백업 --report-day 3
python -m household_finance report --db 우리집.db --out 리포트.html     # 메일 없이 미리 보기
python -m household_finance report --db 우리집.db --send                 # 지금 바로 발송
```
같은 달에는 한 번만 보내고, 발송에 실패하면 한 시간 뒤에 다시 시도합니다.

## 백업과 복원

- **자동**: 예약 작업이 매일 한 번 `백업/우리집_YYYY-MM-DD.db`를 만들고 최근 30개만 남깁니다 (Docker: `hh-data` 볼륨의 `/data/백업`).
- **수동**: `python -m household_finance backup --db 우리집.db --out-dir 백업`
- **엑셀로도**: 웹앱 [내역 가져오기 → 현재 데이터를 엑셀로 내려받기]. 다른 곳(클라우드 드라이브)에 한 부 더 보관하세요.
- **복원**: 웹앱을 끄고 백업 파일을 `우리집.db`로 복사한 뒤 다시 켭니다.
  Docker: `docker compose cp app:/data/백업/우리집_2026-10-01.db ./` 로 꺼내고, 되돌릴 때는 `docker compose stop app scheduler` 후 `docker compose cp ./우리집_2026-10-01.db app:/data/우리집.db`, `docker compose start app scheduler`.

## 업데이트

```bash
git pull
docker compose up -d --build          # 데이터(hh-data 볼륨)는 그대로 유지됩니다
```
