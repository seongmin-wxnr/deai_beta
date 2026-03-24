import urllib.request
import urllib.error
import urllib.parse
import json
import time as _time

from django.http      import JsonResponse
from django.shortcuts import render
from django.conf      import settings
from django.core.cache import cache
import requests

CACHE_TTL    = 60 * 60 * 6   # 6시간 Django 캐시
DB_TTL_HOURS = 6

RIOT_API_KEY  = getattr(settings, 'RIOT_API_KEY', '')
LOL_API_BASE  = 'https://kr.api.riotgames.com'
TFT_API_BASE  = 'https://kr.api.riotgames.com'
VAL_API_BASE  = 'https://kr.api.riotgames.com'
ASIA_API_BASE = 'https://asia.api.riotgames.com'

_MEM_CACHE: dict = {}

def _db_get(key: str):
    try:
        from .models import RiotDataCache
        return RiotDataCache.get(key)
    except Exception:
        return None

def _db_set(key: str, data, version: str = '', ttl_hours: int = DB_TTL_HOURS):
    try:
        from .models import RiotDataCache
        RiotDataCache.set(key, data, version=version, ttl_hours=ttl_hours)
    except Exception:
        pass

def _db_delete(key: str):
    try:
        from .models import RiotDataCache
        RiotDataCache.delete_key(key)
    except Exception:
        pass

def _cached_get(key: str):
    if key in _MEM_CACHE:
        return _MEM_CACHE[key]
    data = cache.get(key)
    if data is not None:
        _MEM_CACHE[key] = data
        return data
    data = _db_get(key)
    if data is not None:
        _MEM_CACHE[key] = data
        cache.set(key, data, CACHE_TTL)
        return data
    return None

def _cached_set(key: str, data, version: str = ''):
    _MEM_CACHE[key] = data
    cache.set(key, data, CACHE_TTL)
    _db_set(key, data, version=version)

def _cached_delete(key: str):
    _MEM_CACHE.pop(key, None)
    cache.delete(key)
    _db_delete(key)

class RiotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message     = message
        super().__init__(message)

def _riot_get_requests(url: str) -> dict:
    """Riot API GET — requests 라이브러리 (429 미처리, 호출부에서 핸들링)"""
    resp = requests.get(url, headers={
        'X-Riot-Token': RIOT_API_KEY,
        'Accept'      : 'application/json',
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()

def _riot_get_with_retry(url: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers={
                'X-Riot-Token': RIOT_API_KEY,
                'Accept'      : 'application/json',
            }, timeout=10)
            if resp.status_code == 429:
                wait = min(int(resp.headers.get('Retry-After', '5')), 30)
                print(f'[RIOT 429] Retry-After {wait}s (시도 {attempt+1}/{max_retries}): {url}', flush=True)
                _time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            raise RiotAPIError(e.response.status_code, str(e))
        except requests.exceptions.RequestException as e:
            raise RiotAPIError(503, f'네트워크 오류: {e}')
    raise RiotAPIError(429, '요청 횟수를 초과했습니다. 잠시 후 재시도해주세요.')

def _error_response(e: RiotAPIError) -> JsonResponse:
    messages = {
        400: '잘못된 요청입니다.',
        401: 'API 키 오류입니다.',
        403: 'API 키가 만료되었습니다.',
        404: '소환사를 찾을 수 없습니다.',
        429: '요청 횟수를 초과했습니다. 잠시 후 재시도해주세요.',
        500: 'Riot 서버 오류입니다.',
        503: '네트워크 연결 오류입니다.',
    }
    msg       = messages.get(e.status_code, e.message)
    http_code = e.status_code if e.status_code in [400, 401, 403, 404, 429, 500, 503] else 500
    return JsonResponse(
        {'success': False, 'message': msg, 'riot_status': e.status_code},
        status=http_code
    )

def _format_rank(tier: str, division: str) -> str:
    TIER_KO = {
        'IRON':'아이언','BRONZE':'브론즈','SILVER':'실버','GOLD':'골드',
        'PLATINUM':'플래티넘','EMERALD':'에메랄드','DIAMOND':'다이아몬드',
        'MASTER':'마스터','GRANDMASTER':'그랜드마스터','CHALLENGER':'챌린저',
    }
    if not tier:
        return '챌린저'
    label = TIER_KO.get(tier.upper(), tier)
    if tier.upper() in ('MASTER', 'GRANDMASTER', 'CHALLENGER'):
        return label
    return f'{label} {division}'

def _resolve_names_by_puuid(entries: list, max_resolve: int = 500) -> list:
    if not hasattr(_resolve_names_by_puuid, '_cache'):
        _resolve_names_by_puuid._cache = {}
    name_cache = _resolve_names_by_puuid._cache

    # 캐시 적용
    for e in entries[:max_resolve]:
        puuid = e.get('puuid', '')
        if puuid and puuid in name_cache:
            cached = name_cache[puuid]
            if cached.get('name'):
                e['name']      = cached['name']
                e['tagLine']   = cached['tagLine']
                e['iconId']    = cached.get('iconId', 1)
                e['level']     = cached.get('level', 1)
                e['rankLabel'] = _format_rank(e['tier'], e['division'])

    to_resolve = [
        e for e in entries[:max_resolve]
        if (e['name'] == '?' or e.get('iconId', 1) == 1)
        and e.get('puuid')
        and e['puuid'] not in name_cache
    ]

    if not to_resolve:
        return entries

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_info(e):
        puuid = e['puuid']
        try:
            acc       = _riot_get_with_retry(f'{ASIA_API_BASE}/riot/account/v1/accounts/by-puuid/{puuid}')
            game_name = acc.get('gameName', '')
            tag_line  = acc.get('tagLine', '')
            icon_id, level = 1, 1
            try:
                s = _riot_get_with_retry(f'{LOL_API_BASE}/lol/summoner/v4/summoners/by-puuid/{puuid}')
                icon_id = s.get('profileIconId', 1)
                level   = s.get('summonerLevel', 1)
            except Exception:
                pass
            return puuid, game_name, tag_line, icon_id, level
        except Exception:
            return puuid, '', '', 1, 1

    BATCH = 20
    for batch_start in range(0, len(to_resolve), BATCH):
        batch = to_resolve[batch_start:batch_start + BATCH]
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_info, e): e for e in batch}
            for future in as_completed(futures):
                e = futures[future]
                puuid, game_name, tag_line, icon_id, level = future.result()
                if game_name:
                    e['name']      = game_name
                    e['tagLine']   = tag_line
                    e['iconId']    = icon_id
                    e['level']     = level
                    e['rankLabel'] = _format_rank(e['tier'], e['division'])
                    name_cache[puuid] = {
                        'name'   : game_name,
                        'tagLine': tag_line,
                        'iconId' : icon_id,
                        'level'  : level,
                    }
        if batch_start + BATCH < len(to_resolve):
            _time.sleep(0.5)

    return entries

def _get_active_snapshot(game: str, queue: str):
    try:
        from .models import RankingSnapshot
        return RankingSnapshot.objects.filter(
            game=game, queue=queue, is_active=True
        ).order_by('-collected_at').first()
    except Exception:
        return None

def _snapshot_entries_to_list(snapshot) -> list:
    return [e.to_dict() for e in snapshot.entries.order_by('rank')]

def _enrich_snapshot_bg(snapshot_id: int):
    try:
        from .models import RankingEntry
        from django.db import models as _dj_models

        qs = list(RankingEntry.objects.filter(snapshot_id=snapshot_id).filter(
            _dj_models.Q(name='?') | _dj_models.Q(icon_id=1)
        ))
        if not qs:
            print(f'[ENRICH] snapshot {snapshot_id}: 보강 대상 없음', flush=True)
            return

        print(f'[ENRICH] snapshot {snapshot_id}: {len(qs)}명 보강 시작', flush=True)

        dicts = [{
            'rank'     : e.rank,
            'puuid'    : e.puuid,
            'name'     : e.name,
            'tagLine'  : e.tag_line,
            'iconId'   : e.icon_id,
            'level'    : e.level,
            'tier'     : e.tier,
            'division' : e.division,
            'rankLabel': e.rank_label,
        } for e in qs]

        enriched  = _resolve_names_by_puuid(dicts, max_resolve=len(dicts))
        entry_map = {e.puuid: e for e in qs}
        to_update = []
        for d in enriched:
            obj = entry_map.get(d.get('puuid', ''))
            if obj and (d.get('name', '?') != '?' or d.get('iconId', 1) != 1):
                obj.name       = d.get('name',      obj.name)
                obj.tag_line   = d.get('tagLine',   obj.tag_line)
                obj.icon_id    = d.get('iconId',    obj.icon_id)
                obj.level      = d.get('level',     obj.level)
                obj.rank_label = d.get('rankLabel', obj.rank_label)
                to_update.append(obj)

        if to_update:
            RankingEntry.objects.bulk_update(
                to_update, ['name', 'tag_line', 'icon_id', 'level', 'rank_label']
            )
            print(f'[ENRICH] snapshot {snapshot_id}: {len(to_update)}명 업데이트 완료', flush=True)
        else:
            print(f'[ENRICH] snapshot {snapshot_id}: 업데이트 대상 없음', flush=True)
    except Exception as ex:
        print(f'[ENRICH] snapshot {snapshot_id} 실패 | {type(ex).__name__}: {ex}', flush=True)


def _save_snapshot(game: str, queue: str, ranked: list):
    """
    기존 활성 스냅샷을 비활성화하고 새 스냅샷 + RankingEntry 저장.
    ranked: info_lol/tft_ranking 에서 만든 dict 리스트 (to_dict 호환 형태)
    """
    try:
        from .models import RankingSnapshot, RankingEntry
        from django.utils import timezone

        RankingSnapshot.objects.filter(game=game, queue=queue, is_active=True).update(is_active=False)

        snapshot = RankingSnapshot.objects.create(
            game=game, queue=queue, collected_at=timezone.now(), is_active=True
        )

        entries = [
            RankingEntry(
                snapshot    = snapshot,
                rank        = e['rank'],
                summoner_id = e.get('summonerId', ''),
                puuid       = e.get('puuid', ''),
                name        = e.get('name', '?'),
                tag_line    = e.get('tagLine', ''),
                icon_id     = e.get('iconId', 1),
                level       = e.get('level', 1),
                tier        = e.get('tier', ''),
                division    = e.get('division', ''),
                rank_label  = e.get('rankLabel', ''),
                lp          = e.get('lp', 0),
                wins        = e.get('wins', 0),
                losses      = e.get('losses', 0),
                winrate     = e.get('winrate', 0),
                hot_streak  = e.get('hotStreak', False),
                veteran     = e.get('veteran', False),
                fresh_blood = e.get('freshBlood', False),
            )
            for e in ranked
        ]
        RankingEntry.objects.bulk_create(entries)
        print(f'[c_userTable] ✔ 저장 성공 | {game}/{queue} | snapshot_id={snapshot.id} | {len(entries)}명 insert', flush=True)

        import threading
        threading.Thread(
            target=_enrich_snapshot_bg, args=(snapshot.id,), daemon=True
        ).start()
        print(f'[c_userTable] 보강 스레드 시작 (snapshot_id={snapshot.id})', flush=True)
    except Exception as ex:
        print(f'[c_userTable] ✘ 저장 실패 | {game}/{queue} | {type(ex).__name__}: {ex}', flush=True)
LOL_TIER_EP = {
    'challenger' : 'challengerleagues',
    'grandmaster': 'grandmasterleagues',
    'master'     : 'masterleagues',
}

def _fetch_lol_all_tiers(queue: str) -> list:
    """챌/그마/마스 순차 호출 (1.2s 간격) → 합산 상위 100명 반환."""
    tag        = f'[LOL RANKING | {queue}]'
    api_count  = 0
    all_entries = []

    for t, ep in LOL_TIER_EP.items():
        url  = f'{LOL_API_BASE}/lol/league/v4/{ep}/by-queue/{queue}'
        print(f'{tag} API 요청 #{api_count+1} → {ep}', flush=True)
        data = _riot_get_with_retry(url)
        api_count += 1
        tier_str = data.get('tier', t.upper())
        cnt = len(data.get('entries', []))
        print(f'{tag}   └ 응답: {tier_str} {cnt}명', flush=True)
        for e in data.get('entries', []):
            e['_tier_override'] = tier_str
        all_entries.extend(data.get('entries', []))
        _time.sleep(1.2)

    all_entries.sort(key=lambda e: -e.get('leaguePoints', 0))
    ranked = []
    for rank, e in enumerate(all_entries[:100], 1):
        tier_str = e.get('_tier_override', 'CHALLENGER')
        div      = e.get('rank', '')
        wins     = e.get('wins', 0)
        losses   = e.get('losses', 0)
        total    = wins + losses
        ranked.append({
            'rank'      : rank,
            'summonerId': e.get('summonerId', ''),
            'puuid'     : e.get('puuid', ''),
            'name'      : (e.get('riotIdGameName') or e.get('summonerName') or '?').strip() or '?',
            'tagLine'   : (e.get('riotIdTagline') or '').strip(),
            'iconId'    : 1,
            'level'     : 1,
            'tier'      : tier_str,
            'division'  : div,
            'rankLabel' : _format_rank(tier_str, div),
            'lp'        : e.get('leaguePoints', 0),
            'wins'      : wins,
            'losses'    : losses,
            'winrate'   : round(wins / total * 100) if total else 0,
            'hotStreak' : e.get('hotStreak', False),
            'veteran'   : e.get('veteran', False),
            'freshBlood': e.get('freshBlood', False),
        })

    print(f'{tag} 합산 완료: 총 {len(all_entries)}명 → 상위 {len(ranked)}명 선발 (API 요청 {api_count}개)', flush=True)
    ranked = _resolve_names_by_puuid(ranked, max_resolve=100)
    return ranked

TFT_TIER_EP = {
    'challenger' : 'challenger',
    'grandmaster': 'grandmaster',
    'master'     : 'master',
}

def _fetch_tft_all_tiers(queue: str) -> list:
    """챌/그마/마스 순차 호출 (1.2s 간격) → 합산 상위 100명 반환."""
    tag        = f'[TFT RANKING | {queue}]'
    api_count  = 0
    all_entries = []

    for t, ep in TFT_TIER_EP.items():
        url  = f'{TFT_API_BASE}/tft/league/v1/{ep}?queue={queue}'
        print(f'{tag} API 요청 #{api_count+1} → {ep}', flush=True)
        data = _riot_get_with_retry(url)
        api_count += 1
        tier_str = data.get('tier', t.upper())
        cnt = len(data.get('entries', []))
        print(f'{tag}   └ 응답: {tier_str} {cnt}명', flush=True)
        for e in data.get('entries', []):
            e['_tier_override'] = tier_str
        all_entries.extend(data.get('entries', []))
        _time.sleep(1.2)

    all_entries.sort(key=lambda e: -e.get('leaguePoints', 0))
    ranked = []
    for rank, e in enumerate(all_entries[:100], 1):
        tier_str = e.get('_tier_override', 'CHALLENGER')
        div      = e.get('rank', '')
        wins     = e.get('wins', 0)
        losses   = e.get('losses', 0)
        total    = wins + losses
        ranked.append({
            'rank'      : rank,
            'summonerId': e.get('summonerId', ''),
            'puuid'     : e.get('puuid', ''),
            'name'      : (e.get('riotIdGameName') or e.get('summonerName') or '?').strip() or '?',
            'tagLine'   : (e.get('riotIdTagline') or '').strip(),
            'iconId'    : 1,
            'level'     : 1,
            'tier'      : tier_str,
            'division'  : div,
            'rankLabel' : _format_rank(tier_str, div),
            'lp'        : e.get('leaguePoints', 0),
            'wins'      : wins,
            'losses'    : losses,
            'winrate'   : round(wins / total * 100) if total else 0,
            'hotStreak' : e.get('hotStreak', False),
            'veteran'   : e.get('veteran', False),
            'freshBlood': e.get('freshBlood', False),
        })

    print(f'{tag} 합산 완료: 총 {len(all_entries)}명 → 상위 {len(ranked)}명 선발 (API 요청 {api_count}개)', flush=True)
    ranked = _resolve_names_by_puuid(ranked, max_resolve=100)
    return ranked

def _refresh_all_rankings():
    """모든 큐 랭킹을 Riot API에서 새로 가져와 c_userTable 갱신."""
    print('[SCHEDULER] 랭킹 갱신 시작', flush=True)
    jobs = [
        ('lol', 'RANKED_SOLO_5x5', _fetch_lol_all_tiers),
        ('lol', 'RANKED_FLEX_SR',  _fetch_lol_all_tiers),
        ('tft', 'RANKED_TFT',             _fetch_tft_all_tiers),
        ('tft', 'RANKED_TFT_DOUBLE_UP',   _fetch_tft_all_tiers),
    ]
    for game, queue, fetcher in jobs:
        try:
            ranked = fetcher(queue)
            _save_snapshot(game, queue, ranked)

            _MEM_CACHE.pop(f'ranking_{game}_{queue}', None)
            cache.delete(f'ranking_{game}_{queue}')
            print(f'[SCHEDULER] {game}/{queue} 갱신 완료 ({len(ranked)}명)', flush=True)
        except Exception as ex:
            print(f'[SCHEDULER] {game}/{queue} 갱신 실패: {ex}', flush=True)
        _time.sleep(30)  # 큐 간 간격
    print('[SCHEDULER] 랭킹 갱신 완료', flush=True)


def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron         import CronTrigger
        import pytz

        kst = pytz.timezone('Asia/Seoul')
        scheduler = BackgroundScheduler(timezone=kst)
        scheduler.add_job(
            _refresh_all_rankings,
            CronTrigger(hour='0,12', minute=0, timezone=kst),
            id='ranking_refresh',
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduler.start()
        print('[SCHEDULER] 랭킹 자동 갱신 스케줄 등록 (KST 0시 / 12시)', flush=True)
    except ImportError:
        print('[SCHEDULER] APScheduler 미설치 — 자동 갱신 비활성. pip install apscheduler pytz', flush=True)
    except Exception as ex:
        print(f'[SCHEDULER] 스케줄러 시작 실패: {ex}', flush=True)

def info_lol_ranking(request):
    queue = request.GET.get('queue', 'RANKED_SOLO_5x5')

    if not RIOT_API_KEY:
        return JsonResponse({'success': False, 'message': 'API 키 미설정'}, status=500)

    tag = f'[LOL RANKING | {queue}]'
    try:
        snapshot = _get_active_snapshot('lol', queue)
        if snapshot:
            entries = _snapshot_entries_to_list(snapshot)
            print(
                f'{tag} DB 히트 → API 요청 0개 '
                f'| snapshot_id={snapshot.id} | {len(entries)}명 '
                f'| 수집: {snapshot.collected_at.strftime("%Y-%m-%d %H:%M:%S")}',
                flush=True
            )
            return JsonResponse({
                'success'     : True,
                'queue'       : queue,
                'tier'        : 'ALL',
                'total'       : len(entries),
                'entries'     : entries,
                'from_cache'  : True,
                'collected_at': snapshot.collected_at.isoformat(),
            })

        print(f'{tag} DB 미스 → Riot API 호출 시작 (챌/그마/마스 3개 엔드포인트)', flush=True)
        ranked = _fetch_lol_all_tiers(queue)
        _save_snapshot('lol', queue, ranked)

        return JsonResponse({
            'success': True,
            'queue'  : queue,
            'tier'   : 'ALL',
            'total'  : len(ranked),
            'entries': ranked,
            'from_cache': False,
        })

    except RiotAPIError as e:
        print(f'{tag} ✘ RiotAPIError {e.status_code}: {e.message}', flush=True)
        return _error_response(e)
    except Exception as e:
        print(f'{tag} ✘ 예외 발생 | {type(e).__name__}: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def info_tft_ranking(request):
    """
    queue: RANKED_TFT | RANKED_TFT_DOUBLE_UP
    동일 패턴: c_userTable 히트 → 반환 / 미스 → Riot API
    """
    queue = request.GET.get('queue', 'RANKED_TFT')

    if not RIOT_API_KEY:
        return JsonResponse({'success': False, 'message': 'API 키 미설정'}, status=500)

    tag = f'[TFT RANKING | {queue}]'
    try:
        snapshot = _get_active_snapshot('tft', queue)
        if snapshot:
            entries = _snapshot_entries_to_list(snapshot)
            print(
                f'{tag} DB 히트 → API 요청 0개 '
                f'| snapshot_id={snapshot.id} | {len(entries)}명 '
                f'| 수집: {snapshot.collected_at.strftime("%Y-%m-%d %H:%M:%S")}',
                flush=True
            )
            return JsonResponse({
                'success'     : True,
                'queue'       : queue,
                'tier'        : 'ALL',
                'total'       : len(entries),
                'entries'     : entries,
                'from_cache'  : True,
                'collected_at': snapshot.collected_at.isoformat(),
            })

        print(f'{tag} DB 미스 → Riot API 호출 시작 (챌/그마/마스 3개 엔드포인트)', flush=True)
        ranked = _fetch_tft_all_tiers(queue)
        _save_snapshot('tft', queue, ranked)

        return JsonResponse({
            'success': True,
            'queue'  : queue,
            'tier'   : 'ALL',
            'total'  : len(ranked),
            'entries': ranked,
            'from_cache': False,
        })

    except RiotAPIError as e:
        print(f'{tag} ✘ RiotAPIError {e.status_code}: {e.message}', flush=True)
        return _error_response(e)
    except Exception as e:
        print(f'{tag} ✘ 예외 발생 | {type(e).__name__}: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def info_val_ranking(request):
    cache_key = 'val_ranking_kr'
    cached = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)

    if not RIOT_API_KEY:
        return JsonResponse({'success': False, 'message': 'API 키 미설정'}, status=500)

    try:
        content_data = _riot_get_requests(f'{VAL_API_BASE}/val/content/v1/contents?locale=ko-KR')
        acts = content_data.get('acts', [])
        current_act = next((a for a in acts if a.get('isActive')), None) or (acts[-1] if acts else {})
        act_id = current_act.get('id', '')
        if not act_id:
            return JsonResponse({'success': False, 'message': 'Act ID 조회 실패'}, status=500)

        lb_data = _riot_get_requests(
            f'{VAL_API_BASE}/val/ranked/v1/leaderboards/by-act/{act_id}?size=200&startIndex=0'
        )
        RANK_LABELS = {
            27:'레디언트', 26:'이모탈 3', 25:'이모탈 2', 24:'이모탈 1',
            23:'다이아 3',  22:'다이아 2',  21:'다이아 1',
        }
        entries = [{
            'rank'     : p.get('leaderboardRank', 0),
            'name'     : p.get('gameName', '?'),
            'tagLine'  : p.get('tagLine', ''),
            'rankLabel': RANK_LABELS.get(p.get('competitiveTier', 0), f"Tier {p.get('competitiveTier',0)}"),
            'lp'       : p.get('rankedRating', 0),
            'wins'     : p.get('numberOfWins', 0),
            'losses'   : 0, 'winrate': 0,
            'tier'     : 'RADIANT' if p.get('competitiveTier') == 27 else 'IMMORTAL',
        } for p in lb_data.get('players', [])]

        result = {
            'success': True, 'actId': act_id,
            'actName': current_act.get('name', ''),
            'total'  : len(entries), 'entries': entries,
        }
        _cached_set(cache_key, result)
        return JsonResponse(result)

    except Exception as e:
        print(f'[VAL RANKING] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def riot_api_rankRendering(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '올바르지 않은 요청입니다.'}, status=400)
    try:
        return render(request, 'riot_ranking.html')
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'{e}'})


def info_ranking_cache_clear(request):
    """c_userTable 스냅샷 비활성화 + 메모리/Django 캐시 삭제 후 즉시 갱신"""
    try:
        from .models import RankingSnapshot
        RankingSnapshot.objects.filter(is_active=True).update(is_active=False)
    except Exception as ex:
        print(f'[CACHE CLEAR] snapshot 비활성화 실패: {ex}', flush=True)

    for key in list(_MEM_CACHE.keys()):
        if key.startswith('ranking_') or key.startswith('lol_ranking_') or key.startswith('tft_ranking_'):
            _MEM_CACHE.pop(key, None)
    cache.delete_many([
        'ranking_lol_RANKED_SOLO_5x5', 'ranking_lol_RANKED_FLEX_SR',
        'ranking_tft_RANKED_TFT',      'ranking_tft_RANKED_TFT_DOUBLE_UP',
        'val_ranking_kr',
    ])

    import threading
    threading.Thread(target=_refresh_all_rankings, daemon=True).start()

    return JsonResponse({'success': True, 'message': '캐시 초기화 및 백그라운드 갱신 시작'})
def info_lol_ranking_debug(request):
    if not RIOT_API_KEY:
        return JsonResponse({'error': 'no api key'})
    try:
        url  = f'{LOL_API_BASE}/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5'
        data = _riot_get_requests(url)
        entries = data.get('entries', [])
        first = entries[0] if entries else {}
        return JsonResponse({
            'tier_in_root': data.get('tier'),
            'entry_keys'  : list(first.keys()),
            'first_entry' : first,
            'total'       : len(entries),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)})

def info_mastery_by_puuid(request):
    """
    챔피언 숙련도 TOP3 조회.
    개발자 키(Development API Key)는 champion-mastery 엔드포인트가 403으로 막혀 있음.
    403 수신 시 빈 결과를 캐싱해 반복 호출을 차단한다.
    """
    puuid = request.GET.get('puuid', '').strip()
    game  = request.GET.get('game', 'lol')
    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid 필요'}, status=400)

    cache_key = f'mastery_{game}_{puuid}'
    cached    = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)

    if not RIOT_API_KEY:
        return JsonResponse({'success': False, 'message': 'API 키 미설정'}, status=500)

    try:
        if game == 'tft':
            summoner    = _riot_get_requests(f'{TFT_API_BASE}/tft/summoner/v1/summoners/by-puuid/{puuid}')
            summoner_id = summoner.get('id', '')
            masteries   = _riot_get_requests(
                f'{TFT_API_BASE}/tft/champion-mastery/v1/by-summoner/{summoner_id}/top?count=3'
            )
        else:
            masteries = _riot_get_requests(
                f'{LOL_API_BASE}/lol/champion-mastery/v4/by-puuid/{puuid}/top?count=3'
            )

        try:
            ver_data = _riot_get_requests('https://ddragon.leagueoflegends.com/api/versions.json')
            dd_ver   = ver_data[0] if ver_data else '15.1.1'
        except Exception:
            dd_ver = '15.1.1'

        try:
            champ_data = _riot_get_requests(
                f'https://ddragon.leagueoflegends.com/cdn/{dd_ver}/data/ko_KR/champion.json'
            )
            id_to_key = {
                int(c['key']): c['id']
                for c in champ_data.get('data', {}).values()
                if c.get('key', '').isdigit()
            }
        except Exception:
            id_to_key = {}

        champs = []
        for m in masteries[:3]:
            cid  = m.get('championId', 0)
            ckey = id_to_key.get(cid, '')
            champs.append({
                'championId' : cid,
                'championKey': ckey,
                'points'     : m.get('championPoints', 0),
                'img'        : (f'https://ddragon.leagueoflegends.com/cdn/{dd_ver}/img/champion/{ckey}.png'
                                if ckey else ''),
            })

        result = {'success': True, 'champions': champs}
        _cached_set(cache_key, result)
        return JsonResponse(result)

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            # 캐싱 데이터 조회 중 레이트 리밋 처리
            empty = {'success': True, 'champions': [], 'unavailable': True}
            _cached_set(cache_key, empty)
            return JsonResponse(empty)
        print(f'[MASTERY] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    except RiotAPIError as e:
        if e.status_code == 403:
            empty = {'success': True, 'champions': [], 'unavailable': True}
            _cached_set(cache_key, empty)
            return JsonResponse(empty)
        return _error_response(e)
    except Exception as e:
        print(f'[MASTERY] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def riot_api_rankingPage(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 메서드 접근 입니다.'}, status=400)