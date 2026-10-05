# 우리 롤체 덱 통계 수집기

한국 서버 마스터 이상 랭크 경기를 매일 새벽 3시에 모아서, 덱별 순방률과 픽률을 `data/stats.json`에 저장해요.
사이트 통계를 바꾸고 싶을 때 Claude에게 `data/stats.json` 링크를 주며 "통계 갱신해줘"라고 하면 돼요.

## 처음 한 번만 하는 설정

1. **저장소 만들기**: GitHub 오른쪽 위 + → New repository. 이름은 `tft-stats`처럼 짓고 **Public**으로 만들어요. (Claude가 결과 파일을 읽으려면 공개여야 해요. API 키는 Secrets에 있어서 공개돼도 보이지 않아요.)
2. **파일 올리기**: 저장소에서 Add file → Upload files로 `collect.py`, `decks.json`, `README.md`를 올려요.
   워크플로 파일은 Add file → Create new file을 누르고, 파일 이름 칸에 `.github/workflows/collect.yml`을 그대로 입력한 뒤 내용을 붙여 넣어요.
3. **라이엇 API 키 받기**: developer.riotgames.com에 라이엇 계정으로 로그인하면 개발용 키가 바로 나와요.
   개발용 키는 24시간마다 만료되니, 대시보드의 Register Product에서 **Personal API Key**를 신청해 두세요. 승인되면 만료 걱정이 없어요.
4. **키 등록**: 저장소 Settings → Secrets and variables → Actions → New repository secret. 이름은 `RIOT_API_KEY`, 값은 받은 키.
5. **첫 실행**: Actions 탭 → "롤체 데이터 수집" → Run workflow. 1~2시간쯤 걸려요. 끝나면 `data/stats.json`이 생겨요.

## 매일 돌아가는 방식

- 챌린저·그랜드마스터·마스터 플레이어의 최근 경기를 받고, 이미 받은 경기는 건너뛰어요.
- 랭크 게임만 남기고, 최신 패치 경기로만 통계를 내요. 오래된 패치 데이터는 최근 2개 패치만 남기고 지워요.
- 통계 범위는 "마스터 이상 플레이어가 참가한 판의 8명 전체"예요.
- 개인용 키 승인 전에는 매일 개발용 키를 새로 받아 4번처럼 Secret 값을 바꿔야 해요. 키가 만료되면 그날 실행은 실패로 표시돼요.

## 덱 인식 규칙 (decks.json)

사이트에 등록한 덱이 경기 기록에서 어떻게 보이는지 적어요. `stats.json`의 `clusters`에 자주 나온 조합(캐리 챔피언과 주요 시너지 ID)이 나오니, 거기서 ID를 골라 쓰면 돼요. Claude에게 맡겨도 돼요.

| 칸 | 뜻 |
| --- | --- |
| `id` | 사이트의 덱 id와 같게 |
| `unit` | 캐리 챔피언 ID |
| `min_items` | 캐리가 든 아이템 최소 개수 |
| `min_star` | 캐리 최소 성 |
| `units` | 꼭 있어야 하는 다른 챔피언 ID 목록 |
| `traits` | 시너지 ID와 최소 인원 |

규칙을 바꾼 뒤 Actions에서 Run workflow를 누르면 저장된 경기로 다시 계산돼요.

## 조절할 수 있는 값

워크플로의 `env`에 넣으면 바뀌어요: `MAX_PLAYERS`(기본 1000), `MATCHES_PER_PLAYER`(10), `MAX_NEW_MATCHES`(3000), `REQUEST_GAP`(요청 간격 1.25초).

라이엇 게임즈의 보증을 받지 않은 개인 프로젝트예요.
