#!/usr/bin/env python3
"""한국 서버 마스터 이상 TFT 랭크 경기를 모아 덱별 순방률·픽률을 계산한다.

필요한 것: 환경 변수 RIOT_API_KEY (GitHub 저장소 Secrets에 등록)
결과물:
  data/raw/<패치>.jsonl.gz  경기 참가자 기록 (덱 규칙을 바꿔도 다시 계산할 수 있게 보관)
  data/seen_ids.txt         이미 받은 경기 ID (중복 수집 방지)
  data/stats.json           최신 패치의 덱별 통계와 많이 쓰인 조합 목록 (사이트 갱신용)
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.environ.get("RIOT_API_KEY", "").strip()
PLATFORM = "https://kr.api.riotgames.com"   # 한국 서버 플레이어 정보
REGION = "https://asia.api.riotgames.com"   # 한국 서버 경기 기록
RANKED_QUEUE = 1100                         # 랭크 게임

DATA = Path("data")
RAW = DATA / "raw"
SEEN = DATA / "seen_ids.txt"
DECKS = Path("decks.json")

MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS", "1000"))
MATCHES_PER_PLAYER = int(os.environ.get("MATCHES_PER_PLAYER", "10"))
MAX_NEW_MATCHES = int(os.environ.get("MAX_NEW_MATCHES", "3000"))
REQUEST_GAP = float(os.environ.get("REQUEST_GAP", "1.25"))      # 2분당 100회 한도 안쪽
TIME_BUDGET = float(os.environ.get("TIME_BUDGET_MIN", "270")) * 60
KEEP_PATCHES = 2
MIN_CLUSTER_GAMES = 30

START = time.time()
_last_request = 0.0


def out_of_time():
    return time.time() - START > TIME_BUDGET


def riot(url, tries=4):
    """라이엇 API 요청. 한도에 걸리면 기다렸다가 다시 시도한다."""
    global _last_request
    for attempt in range(tries):
        wait = _last_request + REQUEST_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        req = urllib.request.Request(url, headers={"X-Riot-Token": API_KEY, "User-Agent": "our-tft-decks/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = int(e.headers.get("Retry-After", "10"))
                print(f"  요청 한도 도달, {ra}초 대기")
                time.sleep(ra + 1)
                continue
            if e.code in (401, 403):
                sys.exit("API 키가 거부됐어요(401/403). 키가 만료되지 않았는지 확인하세요. 개발용 키는 24시간마다 만료돼요.")
            if e.code == 404:
                return None
            if e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (attempt + 1))
    return None


def ladder_puuids():
    entries = []
    for tier in ("challenger", "grandmaster", "master"):
        d = riot(f"{PLATFORM}/tft/league/v1/{tier}")
        got = (d or {}).get("entries", [])
        print(f"{tier}: {len(got)}명")
        entries += sorted(got, key=lambda e: -e.get("leaguePoints", 0))
    puuids = []
    for e in entries[:MAX_PLAYERS]:
        p = e.get("puuid")
        if not p and e.get("summonerId"):
            s = riot(f"{PLATFORM}/tft/summoner/v1/summoners/{e['summonerId']}")
            p = s and s.get("puuid")
        if p:
            puuids.append(p)
        if out_of_time():
            break
    return puuids


def patch_of(info):
    v = info.get("game_version", "")
    m = re.search(r"<Releases/(\d+\.\d+)>", v) or re.search(r"(\d+\.\d+)", v)
    return m.group(1) if m else "unknown"


def compact(match_id, p):
    return {
        "m": match_id,
        "place": p.get("placement"),
        "level": p.get("level"),
        "units": [{"id": u.get("character_id"), "star": u.get("tier", 1), "items": u.get("itemNames", [])}
                  for u in p.get("units", [])],
        "traits": [{"id": t.get("name"), "n": t.get("num_units", 0), "style": t.get("style", 0)}
                   for t in p.get("traits", []) if t.get("style", 0) > 0],
        "aug": p.get("augments", []),
    }


def collect():
    DATA.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    seen = set(SEEN.read_text().split()) if SEEN.exists() else set()
    puuids = ladder_puuids()
    print(f"대상 플레이어 {len(puuids)}명")

    queue, queued = [], set()
    for pu in puuids:
        if out_of_time() or len(queue) >= MAX_NEW_MATCHES:
            break
        for mid in riot(f"{REGION}/tft/match/v1/matches/by-puuid/{pu}/ids?count={MATCHES_PER_PLAYER}") or []:
            if mid not in seen and mid not in queued:
                queue.append(mid)
                queued.add(mid)
    queue = queue[:MAX_NEW_MATCHES]
    print(f"새 경기 {len(queue)}판 수집 시작")

    saved = 0
    with SEEN.open("a") as seen_f:
        for i, mid in enumerate(queue, 1):
            if out_of_time():
                print("시간 예산을 다 써서 여기서 멈춰요.")
                break
            m = riot(f"{REGION}/tft/match/v1/matches/{mid}")
            seen_f.write(mid + "\n")
            if not m:
                continue
            info = m.get("info", {})
            if info.get("queue_id") != RANKED_QUEUE:
                continue
            patch = patch_of(info)
            with gzip.open(RAW / f"{patch}.jsonl.gz", "at", encoding="utf-8") as f:
                for p in info.get("participants", []):
                    f.write(json.dumps(compact(mid, p), ensure_ascii=False) + "\n")
            saved += 1
            if i % 200 == 0:
                print(f"  {i}/{len(queue)}판 처리")
    print(f"랭크 경기 {saved}판 저장")


def version_key(name):
    return tuple(int(x) for x in re.findall(r"\d+", name)) or (0,)


def prune_old_patches():
    files = sorted(RAW.glob("*.jsonl.gz"), key=lambda f: version_key(f.name))
    for f in files[:-KEEP_PATCHES]:
        print(f"오래된 패치 데이터 삭제: {f.name}")
        f.unlink()


def load_names():
    """Community Dragon의 한국어 데이터로 챔피언·시너지·아이템 이름을 바꾼다. 실패해도 계속 진행."""
    try:
        req = urllib.request.Request("https://raw.communitydragon.org/latest/cdragon/tft/ko_kr.json",
                                     headers={"User-Agent": "our-tft-decks/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"한국어 이름을 못 불러와서 영문 ID로 표시해요: {e}")
        return {}
    names = {}
    for it in d.get("items", []):
        if it.get("apiName") and it.get("name"):
            names[it["apiName"]] = it["name"]
    sets = list((d.get("sets") or {}).values()) + list(d.get("setData") or [])
    for s in sets:
        for c in s.get("champions", []):
            if c.get("apiName") and c.get("name"):
                names[c["apiName"]] = c["name"]
        for t in s.get("traits", []):
            if t.get("apiName") and t.get("name"):
                names[t["apiName"]] = t["name"]
    return names


def matches_rule(p, rule):
    """덱 인식 규칙: unit(캐리)·min_items·min_star·units(모두 있어야 함)·traits(최소 인원)."""
    units = {u["id"]: u for u in p["units"]}
    carry = rule.get("unit")
    if carry:
        u = units.get(carry)
        if not u or len(u["items"]) < rule.get("min_items", 0) or u["star"] < rule.get("min_star", 1):
            return False
    if any(uid not in units for uid in rule.get("units", [])):
        return False
    active = {t["id"]: t["n"] for t in p["traits"]}
    for t in rule.get("traits", []):
        if active.get(t["id"], 0) < t.get("min_units", 1):
            return False
    return True


def carry_of(p):
    if not p["units"]:
        return None
    return max(p["units"], key=lambda u: (len(u["items"]), u["star"]))


def build_stats():
    files = sorted(RAW.glob("*.jsonl.gz"), key=lambda f: version_key(f.name))
    if not files:
        print("저장된 경기가 없어 통계를 만들지 않아요.")
        return
    latest = files[-1]
    patch = latest.name.replace(".jsonl.gz", "")
    rows = []
    with gzip.open(latest, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    total = len(rows)
    matches = len({r["m"] for r in rows})
    names = load_names()
    nm = lambda x: names.get(x, x)

    decks = json.loads(DECKS.read_text(encoding="utf-8")).get("decks", []) if DECKS.exists() else []
    deck_rows = defaultdict(list)
    for r in rows:
        for d in decks:  # 여러 덱에 맞으면 decks.json에서 먼저 나온 덱으로 센다
            if matches_rule(r, d.get("rule", {})):
                deck_rows[d["id"]].append(r)
                break

    def summary(rs):
        g = len(rs)
        if not g:
            return {"games": 0, "top4": 0, "pick": 0, "avg_place": None}
        return {"games": g,
                "top4": round(sum(1 for x in rs if x["place"] <= 4) / g, 4),
                "pick": round(g / total, 4),
                "avg_place": round(sum(x["place"] for x in rs) / g, 2)}

    deck_stats = {d["id"]: {"name": d.get("name", d["id"]), **summary(deck_rows[d["id"]])} for d in decks}

    clusters = defaultdict(list)
    for r in rows:
        c = carry_of(r)
        if not c:
            continue
        top = sorted(r["traits"], key=lambda t: (-t["style"], -t["n"]))[:2]
        clusters[(c["id"], tuple(t["id"] for t in top))].append(r)
    cl_out = []
    for (cid, tids), rs in clusters.items():
        if len(rs) < MIN_CLUSTER_GAMES:
            continue
        items = Counter(i for r in rs for u in r["units"] if u["id"] == cid for i in u["items"])
        cl_out.append({
            "carry": cid, "carry_name": nm(cid),
            "traits": list(tids), "trait_names": [nm(t) for t in tids],
            "carry_items": [nm(i) for i, _ in items.most_common(3)],
            **summary(rs),
        })
    cl_out.sort(key=lambda x: -x["games"])

    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "patch": patch,
        "scope": "한국 서버, 마스터 이상 플레이어가 참가한 랭크 경기의 참가자 8명 전체",
        "matches": matches,
        "participants": total,
        "decks": deck_stats,
        "clusters": cl_out[:60],
    }
    (DATA / "stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"패치 {patch}: {matches}판, 덱 {len(deck_stats)}개, 조합 {len(cl_out)}개 통계 저장")


def main():
    if os.environ.get("STATS_ONLY") != "1":
        if not API_KEY:
            sys.exit("RIOT_API_KEY가 설정되지 않았어요. 저장소 Settings > Secrets에 등록하세요.")
        collect()
        prune_old_patches()
    build_stats()


if __name__ == "__main__":
    main()
