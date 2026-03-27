import urllib.request
import urllib.error
import urllib.parse
import json

from django.http       import JsonResponse
from django.shortcuts  import render
from django.conf       import settings
from django.core.cache import cache
from django.utils      import timezone

# 공통 캐시 설정
CACHE_TTL    = 60 * 60 * 6  # Django cache / mem cache TTL : 6 h
DB_TTL_HOURS = 6  # DB (RiotDataCache) TTL

_MEM_CACHE: dict = {}  # 프로세스 내 1차 메모리 캐시


# RiotDataCache 기반 범용 캐시 (DDragon 정적 데이터 등 전용)
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
    """메모리 → Django cache → DB 순서로 조회."""
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
    """메모리 + Django cache + DB 동시 저장."""
    _MEM_CACHE[key] = data
    cache.set(key, data, CACHE_TTL)
    _db_set(key, data, version=version)

def _cached_delete(key: str):
    _MEM_CACHE.pop(key, None)
    cache.delete(key)
    _db_delete(key)


# Riot_UserINFO + Riot_MatchInfo 기반 전적 캐시 헬퍼
# (LOL / TFT / VAL 공통 사용)

# 전적/랭크 캐시 유효 기간 (초) - 6시간 (너무 짧으면 API 재호출 반복)
MATCH_CACHE_TTL = 60 * 60 * 6  # 6시간

# 전적 목록(match_ids) 캐시 TTL - 갱신 버튼 없이는 10분만 유지
MATCH_IDS_TTL = 60 * 10  # 10분

# 개별 경기 상세 캐시 TTL (경기 결과는 불변이므로 길게)
MATCH_DETAIL_TTL = 60 * 60 * 24  # 24시간

# 캐시 미스와 "row 있음" 을 구분하기 위한 sentinel
# _user_cache_get 이 이 값을 반환하면 DB에 row 없음(미스) or TTL 만료
_CACHE_MISS = object()


def _user_cache_get(puuid: str, game: str, queue_type: str, ttl: int = None):
    effective_ttl = ttl if ttl is not None else MATCH_CACHE_TTL
    try:
        from .models import Riot_UserINFO, Riot_MatchInfo
        user = Riot_UserINFO.get_or_none(puuid)
        if not user:
            print(f'[CACHE MISS] UserINFO 없음 puuid={puuid[:12]}…', flush=True)
            return _CACHE_MISS
        obj = Riot_MatchInfo.objects.filter(
            user=user, game=game, queue_type=queue_type
        ).first()
        if not obj:
            print(f'[CACHE MISS] MatchInfo row 없음 game={game} queue={queue_type}', flush=True)
            return _CACHE_MISS
        age = (timezone.now() - obj.updated_at).total_seconds()
        if age > effective_ttl:
            print(f'[CACHE MISS] TTL 만료 age={int(age)}s ttl={effective_ttl}s queue={queue_type}', flush=True)
            return _CACHE_MISS

        result = obj.cached_data
        print(
            f'[CACHE HIT ] game={game} queue={queue_type} age={int(age)}s '
            f'cached_data_type={type(result).__name__} '
            f'cached_data_empty={not result} '
            f'cached_data_preview={str(result)[:80]}',
            flush=True
        )
        return result
    except Exception as ex:
        print(f'[CACHE ERROR] _user_cache_get 예외: {ex}', flush=True)
        return _CACHE_MISS


def _user_cache_set(puuid: str, username: str, tag: str, region: str,
                    game: str, queue_type: str,
                    data,
                    last_match_id: str = '',
                    match_ids: list = None,
                    touch_refresh: bool = False):
    """
    Riot_UserINFO get_or_create 후 Riot_MatchInfo에 캐시를 저장합니다.
    models.py 버전 무관하게 동작합니다.
    """
    try:
        from .models import Riot_UserINFO, Riot_MatchInfo

        # UserINFO 확보
        if username and tag:
            user, _ = Riot_UserINFO.objects.get_or_create(
                puuid=puuid,
                defaults={'username': username, 'tag': tag, 'region': region}
            )
            # 이름 변경 반영
            if user.username != username or user.tag != tag:
                user.username = username
                user.tag      = tag
                user.region   = region
                user.save()
        else:
            try:
                user = Riot_UserINFO.objects.get(puuid=puuid)
            except Riot_UserINFO.DoesNotExist:
                print(f'[CACHE] UserINFO 없음 → 저장 건너뜀', flush=True)
                return

        # MatchInfo upsert
        # upsert 시그니처가 버전마다 다르므로 직접 get_or_create + save
        defaults = {
            'cached_data'  : data if data is not None else {},
            'last_match_id': last_match_id,
        }
        # match_ids 컬럼이 있으면 추가
        if match_ids is not None:
            defaults['match_ids'] = match_ids

        obj, created = Riot_MatchInfo.objects.get_or_create(
            user=user, game=game, queue_type=queue_type,
            defaults=defaults
        )
        if not created:
            obj.cached_data   = data if data is not None else {}
            obj.last_match_id = last_match_id
            if match_ids is not None:
                try:
                    obj.match_ids = match_ids
                except Exception:
                    pass
            if touch_refresh:
                try:
                    obj.last_refresh_at = timezone.now()
                except Exception:
                    pass
            obj.save()

        print(f'[CACHE SET] game={game} queue={queue_type} puuid={puuid[:12]}…', flush=True)
    except Exception as ex:
        print(f'[CACHE ERROR] _user_cache_set 실패: {ex}', flush=True)


def _match_detail_cache_get(match_id: str):
    """경기 상세 정보는 결과가 불변 → RiotDataCache(범용 캐시)에 24시간 저장."""
    return _cached_get(f'match_detail:{match_id}')


def _match_detail_cache_set(match_id: str, data: dict):
    from datetime import timedelta
    _MEM_CACHE[f'match_detail:{match_id}'] = data
    cache.set(f'match_detail:{match_id}', data, MATCH_DETAIL_TTL)
    _db_set(f'match_detail:{match_id}', data, ttl_hours=24)


def _user_info_upsert(puuid: str, username: str, tag: str, region: str,
                      summoner_id: str = '', profile_icon_id: int = 0,
                      summoner_level: int = 0):
    """
    유저 기본 정보 upsert.
    models.py 버전에 관계없이 summoner 필드를 안전하게 저장합니다.
    """
    try:
        from .models import Riot_UserINFO

        # get_or_create로 기본 row 확보
        obj, created = Riot_UserINFO.objects.get_or_create(
            puuid=puuid,
            defaults={
                'username': username,
                'tag'     : tag,
                'region'  : region,
            }
        )
        if not created:
            obj.username = username
            obj.tag      = tag
            obj.region   = region

        # summoner 필드는 컬럼 존재 여부와 관계없이 setattr로 시도
        if summoner_id:
            try:
                obj.summoner_id = summoner_id
            except Exception:
                pass
        if profile_icon_id:
            try:
                obj.profile_icon_id = profile_icon_id
            except Exception:
                pass
        if summoner_level:
            try:
                obj.summoner_level = summoner_level
            except Exception:
                pass

        obj.save()
        print(f'[USER UPSERT] puuid={puuid[:12]}… summoner_id={summoner_id[:8] if summoner_id else "없음"}', flush=True)
    except Exception as ex:
        print(f'[CACHE] _user_info_upsert 실패: {ex}', flush=True)

class RiotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message     = message
        super().__init__(message)


def _riot_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            'X-Riot-Token'   : settings.RIOT_API_KEY,
            'User-Agent'     : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9',
            'Accept-Charset' : 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin'         : 'https://developer.riotgames.com',
        }
    )
    print(f"[RIOT] 호출 URL: {url}", flush=True)
    print(f"[RIOT] 사용 키: {settings.RIOT_API_KEY[:20]}...", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"[RIOT] 성공 응답: {str(data)[:100]}", flush=True)
            return data
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            pass
        print(f"[RIOT] HTTP 에러: {e.code} / body: {body}", flush=True)
        raise RiotAPIError(e.code, body.get('status', {}).get('message', str(e)))
    except urllib.error.URLError as e:
        print(f"[RIOT] URL 에러: {e.reason}", flush=True)
        raise RiotAPIError(503, f'네트워크 오류: {e.reason}')
    except Exception as e:
        print(f"[RIOT] 알 수 없는 에러: {e}", flush=True)
        raise


def _get_region_urls(region: str) -> tuple:
    region = region.lower()
    info   = settings.RIOT_REGION_MAP.get(region)
    if not info:
        raise RiotAPIError(400, f'지원하지 않는 지역입니다: {region}')
    return info['platform'], info['regional']


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

def riot_api_debug_ping(request):
    """프론트 JS init() 실행 여부 확인용 핑."""
    puuid  = request.GET.get('puuid', '').strip()
    step   = request.GET.get('step',  'unknown')
    detail = request.GET.get('detail', '')
    print(f'[JS PING] step={step} puuid={puuid[:12] if puuid else "없음"}… detail={detail}', flush=True)
    if not puuid:
        return JsonResponse({'ok': True})
    return render(request, 'riot_lolSearch.html')

def riotSearchPage_rendering(request):
    return render(request, 'riot_lolSearch.html')

def riotUserPage_rendering(request):
    from django.conf import settings as _s
    dd_ver = getattr(_s, 'RIOT_DD_VERSION', 'MISSING')
    print(f'[USERPAGE] 렌더링 DD_VERSION={dd_ver}', flush=True)
    return render(request, 'riot_lolUserpage.html', {
        'DD_VERSION': dd_ver,
    })

def riot_api_search_user(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드 입니다.'}, status=405)

    name   = request.GET.get('name',   '').strip()
    tag    = request.GET.get('tag',    '').strip()
    region = request.GET.get('region', 'kr').strip().lower()
    print(f"[SEARCH] name={name} tag={tag} region={region}", flush=True)

    if not name or not tag:
        return JsonResponse({'success': False, 'message': '소환사 이름과 태그를 입력해주세요.'}, status=400)

    platform, regional = _get_region_urls(region)

    # 1순위: name#tag DB에서 puuid 조회 puuid 있으면 API 호출 없음
    # summoner_id 유무와 관계없이 puuid만 있으면 캐시 히트
    try:
        from .models import Riot_UserINFO
        cached_user = Riot_UserINFO.objects.filter(
            username__iexact=name,
            tag__iexact=tag,
            region=region,
        ).first()

        if cached_user and cached_user.puuid:
            sid   = getattr(cached_user, 'summoner_id',     '')
            icon  = getattr(cached_user, 'profile_icon_id', 0)
            level = getattr(cached_user, 'summoner_level',  0)
            print(
                f'[SEARCH HIT ] puuid={cached_user.puuid[:12]}… '
                f'username={cached_user.username} tag={cached_user.tag} '
                f'summoner_id={"있음("+sid[:8]+"…)" if sid else "없음"} '
                f'icon={icon} level={level}',
                flush=True
            )
            return JsonResponse({
                'success'       : True,
                'puuid'         : cached_user.puuid,
                'gameName'      : cached_user.username,
                'tagLine'       : cached_user.tag,
                'summonerId'    : getattr(cached_user, 'summoner_id',     ''),
                'accountId'     : '',
                'profileIconId' : getattr(cached_user, 'profile_icon_id', 0),
                'summonerLevel' : getattr(cached_user, 'summoner_level',  0),
                'region'        : region,
                'platform'      : platform,
                'regional'      : regional,
                'cached'        : True,
            })
    except Exception as ex:
        print(f'[SEARCH] DB 조회 실패(API 폴백): {ex}', flush=True)

    # 2순위: DB 미스 Riot API 호출 후 DB 저장
    try:
        account = _riot_get(
            f'https://{regional}/riot/account/v1/accounts/by-riot-id'
            f'/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}'
        )
        puuid    = account['puuid']
        gameName = account['gameName']
        tagLine  = account['tagLine']

        summoner        = _riot_get(
            f'https://{platform}/lol/summoner/v4/summoners/by-puuid/{puuid}'
        )
        summoner_id     = summoner.get('id', summoner.get('summonerId', ''))
        profile_icon_id = summoner.get('profileIconId', 0)
        summoner_level  = summoner.get('summonerLevel', 0)

        _user_info_upsert(
            puuid=puuid, username=gameName, tag=tagLine, region=region,
            summoner_id=summoner_id,
            profile_icon_id=profile_icon_id,
            summoner_level=summoner_level,
        )
        print(f"[SEARCH] API 호출 완료 + DB 저장 puuid={puuid[:12]}…", flush=True)

        return JsonResponse({
            'success'       : True,
            'puuid'         : puuid,
            'gameName'      : gameName,
            'tagLine'       : tagLine,
            'summonerId'    : summoner_id,
            'accountId'     : summoner.get('accountId', ''),
            'profileIconId' : profile_icon_id,
            'summonerLevel' : summoner_level,
            'region'        : region,
            'platform'      : platform,
            'regional'      : regional,
            'cached'        : False,
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)

def riot_api_rankInfo(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    summoner_id = request.GET.get('summonerId', '').strip()
    puuid       = request.GET.get('puuid',      '').strip()
    region      = request.GET.get('region', 'kr').strip().lower()
    username    = request.GET.get('name',  '').strip()
    tag         = request.GET.get('tag',   '').strip()

    if not summoner_id and not puuid:
        return JsonResponse({'success': False, 'message': '올바른 정보를 입력해주세요.'}, status=400)

    # DB 캐시 조회
    if puuid:
        solo_result = _user_cache_get(puuid, 'lol', 'lol_ranked_solo')
        flex_result = _user_cache_get(puuid, 'lol', 'lol_ranked_flex')
        if solo_result is not _CACHE_MISS and flex_result is not _CACHE_MISS:
            print(
                f'[RANK HIT  ] puuid={puuid[:12]}… '
                f'solo={str(solo_result)[:60]} '
                f'flex={str(flex_result)[:60]}',
                flush=True
            )
            return JsonResponse({
                'success': True,
                'solo'   : solo_result if solo_result else None,
                'flex'   : flex_result if flex_result else None,
                'cached' : True,
            })

    try:
        platform, _ = _get_region_urls(region)
        if puuid:
            print(f"[LOL RANK] API 호출 → {platform} : {puuid[:12]}…")
            entries = _riot_get(
                f'https://{platform}/lol/league/v4/entries/by-puuid/{puuid}'
            )
        elif summoner_id:
            print(f"[LOL RANK] API 호출 → {platform} : {summoner_id[:12]}…")
            entries = _riot_get(
                f'https://{platform}/lol/league/v4/entries/by-summoner/{summoner_id}'
            )
        else:
            return JsonResponse({'success': True, 'solo': None, 'flex': None})

        def parsing_entry(var):
            if not var:
                return None
            total    = var['wins'] + var['losses']
            win_rate = round(var['wins'] / total * 100) if total > 0 else 0
            return {
                'tier'        : var['tier'],
                'rank'        : var['rank'],
                'leaguePoints': var['leaguePoints'],
                'wins'        : var['wins'],
                'losses'      : var['losses'],
                'winRate'     : win_rate,
                'hotStreak'   : var.get('hotStreak',  False),
                'veteran'     : var.get('veteran',    False),
                'freshBlood'  : var.get('freshBlood', False),
                'miniSeries'  : var.get('miniSeries'),
            }

        solo = next((e for e in entries if e['queueType'] == 'RANKED_SOLO_5x5'), None)
        flex = next((e for e in entries if e['queueType'] == 'RANKED_FLEX_SR'),  None)

        solo_data = parsing_entry(solo)
        flex_data = parsing_entry(flex)

        # DB 캐시 저장 (언랭=None도 반드시 저장해서 재호출 방지)
        # username/tag 없어도 _user_cache_set 내부에서 puuid로 기존 유저 재사용
        _user_cache_set(puuid, username, tag, region,
                        'lol', 'lol_ranked_solo', solo_data)
        _user_cache_set(puuid, username, tag, region,
                        'lol', 'lol_ranked_flex', flex_data)

        print(f"[LOL RANK] solo={solo_data}, flex={flex_data}")
        return JsonResponse({
            'success': True,
            'solo'   : solo_data,
            'flex'   : flex_data,
            'cached' : False,
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_getChampionMastery(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()

    try:
        count = min(int(request.GET.get('count', 5)), 10)
    except (TypeError, ValueError):
        count = 5

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    # 캐시 조회 (RiotDataCache 범용 캐시 사용, lol_normal 슬롯 충돌 방지)
    cache_key = f'lol_mastery:{puuid}'
    cached = _cached_get(cache_key)
    if cached is not None:
        print(
            f'[MASTERY HIT] puuid={puuid[:12]}… '
            f'count={len(cached) if isinstance(cached, list) else "?"} '
            f'preview={str(cached)[:80]}',
            flush=True
        )
        return JsonResponse({'success': True, 'masteries': cached, 'cached': True})

    try:
        platform, _ = _get_region_urls(region)
        data        = _riot_get(
            f'https://{platform}/lol/champion-mastery/v4/champion-masteries'
            f'/by-puuid/{puuid}/top?count={count}'
        )
        result = [
            {
                'championId'    : m['championId'],
                'championLevel' : m['championLevel'],
                'championPoints': m['championPoints'],
                'lastPlayTime'  : m['lastPlayTime'],
                'tokensEarned'  : m.get('tokensEarned', 0),
            }
            for m in data
        ]

        # 캐시 저장 (10분, 메모리+Django cache+DB)
        _cached_set(cache_key, result)

        return JsonResponse({'success': True, 'masteries': result, 'cached': False})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_getMatchIDs(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid    = request.GET.get('puuid',    '').strip()
    region   = request.GET.get('region',   'kr').strip().lower()
    username = request.GET.get('name',     '').strip()
    tag      = request.GET.get('tag',      '').strip()

    try:
        start = max(int(request.GET.get('start', 0)),   0)
        count = min(int(request.GET.get('count', 20)), 20)
    except (TypeError, ValueError):
        start, count = 0, 20

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    # DB 캐시 조회 (start=0, lol_all 슬롯)
    if start == 0:
        try:
            from .models import Riot_UserINFO, Riot_MatchInfo
            user = Riot_UserINFO.get_or_none(puuid)
            print(f'[MATCH IDS ] user_found={user is not None} puuid={puuid[:12]}…', flush=True)
            if user:
                obj = Riot_MatchInfo.objects.filter(
                    user=user, game='lol', queue_type='lol_all'
                ).first()
                if obj:
                    stored_ids = getattr(obj, 'match_ids', None) or []
                    age        = (timezone.now() - obj.updated_at).total_seconds()
                    print(
                        f'[MATCH IDS ] lol_all row found: '
                        f'match_ids_count={len(stored_ids)} '
                        f'last_match_id={obj.last_match_id} '
                        f'age={int(age)}s ttl={MATCH_IDS_TTL}s',
                        flush=True
                    )
                    if stored_ids:
                        if age <= MATCH_IDS_TTL:
                            print(f'[MATCH IDS HIT] count={len(stored_ids)} ids[0]={stored_ids[0] if stored_ids else "없음"}', flush=True)
                            return JsonResponse({
                                'success'     : True,
                                'matchIds'    : stored_ids,
                                'lastMatchId' : obj.last_match_id,
                                'start'       : 0,
                                'count'       : len(stored_ids),
                                'cached'      : True,
                            })
                        else:
                            print(f'[MATCH IDS MISS] TTL 만료 age={int(age)}s', flush=True)
                    else:
                        print(f'[MATCH IDS MISS] match_ids 비어있음 (컬럼 없거나 미저장)', flush=True)
                else:
                    print(f'[MATCH IDS MISS] lol_all row 없음', flush=True)
        except Exception as ex:
            print(f'[MATCH IDS] DB 조회 실패(API 폴백): {ex}', flush=True)

    # Riot API 호출
    try:
        _, regional = _get_region_urls(region)
        ids = _riot_get(
            f'https://{regional}/lol/match/v5/matches/by-puuid/{puuid}/ids'
            f'?start={start}&count={count}'
        )

        # DB 저장 (start=0 일 때만, lol_all 슬롯에 20게임 보관)
        if start == 0:
            try:
                _user_cache_set(
                    puuid, username, tag, region,
                    game='lol', queue_type='lol_all',
                    data={},
                    last_match_id=ids[0] if ids else '',
                    match_ids=ids[:20],
                )
            except Exception as ex:
                print(f'[MATCH IDS] DB 저장 실패(무시): {ex}', flush=True)

        return JsonResponse({
            'success'     : True,
            'matchIds'    : ids,
            'lastMatchId' : ids[0] if ids else '',
            'start'       : start,
            'count'       : len(ids),
            'cached'      : False,
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


# 전적 갱신 전용 엔드포인트 (갱신 버튼 last_match_id 이후만 조회)
def riot_api_refreshMatches(request):
    """
    last_match_id 이후 새 경기만 조회해서 match_ids 앞쪽에 붙이고 20개로 유지.
    3분 쿨다운 적용.
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    COOLDOWN = 180  # 3분

    try:
        from .models import Riot_UserINFO, Riot_MatchInfo

        user = Riot_UserINFO.get_or_none(puuid)
        if not user:
            # 유저 row가 없으면 일반 조회로 폴백
            return riot_api_getMatchIDs(request)

        obj = Riot_MatchInfo.objects.filter(
            user=user, game='lol', queue_type='lol_all'
        ).first()

        # 쿨다운 체크
        if obj and not obj.can_refresh(COOLDOWN):
            remaining = obj.seconds_until_refresh(COOLDOWN)
            print(f'[REFRESH] 쿨다운 중 remaining={remaining}s puuid={puuid[:12]}…', flush=True)
            return JsonResponse({
                'success'   : False,
                'cooldown'  : True,
                'remaining' : remaining,
                'message'   : f'갱신은 {remaining}초 후에 가능합니다.',
            }, status=429)

        # 새 경기 조회
        _, regional = _get_region_urls(region)
        # 최신 5개만 먼저 조회해서 새 게임이 있는지 확인 (최소 요청)
        latest_ids = _riot_get(
            f'https://{regional}/lol/match/v5/matches/by-puuid/{puuid}/ids'
            f'?start=0&count=5'
        )

        stored_ids    = getattr(obj, 'match_ids', None) or [] if obj else []
        stored_last   = obj.last_match_id if obj else ''
        new_ids       = []

        if latest_ids and latest_ids[0] != stored_last:
            # 새 경기 존재 stored_last 위치까지 추가 조회
            for mid in latest_ids:
                if mid == stored_last:
                    break
                new_ids.append(mid)

            # 5개 안에 기준점이 없으면 한 번 더 (최대 20개까지 조회)
            if stored_last and stored_last not in latest_ids:
                extra = _riot_get(
                    f'https://{regional}/lol/match/v5/matches/by-puuid/{puuid}/ids'
                    f'?start=0&count=20'
                )
                new_ids = []
                for mid in extra:
                    if mid == stored_last:
                        break
                    new_ids.append(mid)

        # 새 경기를 앞에 붙이고 20개로 자르기
        merged = (new_ids + stored_ids)[:20]
        new_last = merged[0] if merged else stored_last

        # DB 저장 + last_refresh_at 갱신
        _user_cache_set(
            puuid, username, tag, region,
            game='lol', queue_type='lol_all',
            data={},
            last_match_id=new_last,
            match_ids=merged,
            touch_refresh=True,
        )

        print(f'[REFRESH] 완료 new={len(new_ids)}게임 total={len(merged)} puuid={puuid[:12]}…', flush=True)
        return JsonResponse({
            'success'     : True,
            'matchIds'    : merged,
            'lastMatchId' : new_last,
            'newCount'    : len(new_ids),
            'cached'      : False,
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


# 더보기 전용 엔드포인트 (start 오프셋 기반, DB에 누적 저장)
def riot_api_loadMoreMatches(request):
    """
    현재 저장된 match_ids 길이를 start로 삼아 추가 10게임을 조회합니다.
    조회된 id를 기존 match_ids 뒤에 append하고 DB에 누적 저장합니다.
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()
    LOAD_COUNT = 10

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    try:
        from .models import Riot_UserINFO, Riot_MatchInfo

        # DB에서 현재까지 저장된 match_ids 조회 start 계산
        user        = Riot_UserINFO.get_or_none(puuid)
        obj         = None
        stored_ids  = []
        if user:
            obj = Riot_MatchInfo.objects.filter(
                user=user, game='lol', queue_type='lol_all'
            ).first()
            if obj:
                    stored_ids = getattr(obj, 'match_ids', None) or []

        start = len(stored_ids)  # 이미 가진 게임 수 다음부터 조회
        print(f'[LOAD MORE] start={start} puuid={puuid[:12]}…', flush=True)

        _, regional = _get_region_urls(region)
        new_ids = _riot_get(
            f'https://{regional}/lol/match/v5/matches/by-puuid/{puuid}/ids'
            f'?start={start}&count={LOAD_COUNT}'
        )

        if not new_ids:
            return JsonResponse({
                'success'  : True,
                'matchIds' : [],
                'hasMore'  : False,
                'cached'   : False,
            })

        # 기존 목록 뒤에 append (중복 제거)
        existing_set = set(stored_ids)
        deduped      = [mid for mid in new_ids if mid not in existing_set]
        merged       = stored_ids + deduped

        # DB에 누적 저장 (last_match_id는 변경 없음 - 갱신 기준점 보존)
        _user_cache_set(
            puuid, username, tag, region,
            game='lol', queue_type='lol_all',
            data={},
            last_match_id=obj.last_match_id if obj else (merged[0] if merged else ''),
            match_ids=merged,
        )

        print(f'[LOAD MORE] 완료 new={len(deduped)}게임 total={len(merged)} puuid={puuid[:12]}…', flush=True)
        return JsonResponse({
            'success'  : True,
            'matchIds' : deduped,
            'totalIds' : merged,
            'hasMore'  : len(new_ids) == LOAD_COUNT,
            'cached'   : False,
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_matchDetail(request, match_id: str):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    region = request.GET.get('region', 'kr').strip().lower()

    # 캐시 조회 (경기 결과는 불변 24시간)
    cached = _match_detail_cache_get(match_id)
    if cached:
        print(f'[MATCH DETAIL HIT] match_id={match_id} keys={list(cached.keys()) if isinstance(cached, dict) else type(cached).__name__}', flush=True)
        return JsonResponse({'success': True, 'match': cached, 'cached': True})

    try:
        _, regional = _get_region_urls(region)
        data        = _riot_get(
            f'https://{regional}/lol/match/v5/matches/{match_id}'
        )
        _match_detail_cache_set(match_id, data)
        return JsonResponse({'success': True, 'match': data, 'cached': False})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)

def riot_api_ddVersion(request):
    CACHE_KEY = 'ddragon:versions'
    cached = _cached_get(CACHE_KEY)
    if cached:
        current = settings.RIOT_DD_VERSION
        print(f'[DDRAGON] versions 캐시 히트', flush=True)
        return JsonResponse({
            'success'    : True,
            'current'    : current,
            'latest'     : cached[0],
            'is_outdated': cached[0] != current,
            'cached'     : True,
        })
    try:
        versions = _riot_get('https://ddragon.leagueoflegends.com/api/versions.json')
        _cached_set(CACHE_KEY, versions)
        current = settings.RIOT_DD_VERSION
        latest  = versions[0] if versions else None
        return JsonResponse({
            'success'    : True,
            'current'    : current,
            'latest'     : latest,
            'is_outdated': (latest != current) if (latest and current) else False,
            'cached'     : False,
        })
    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def riot_api_champions(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    lang    = request.GET.get('lang', 'ko_KR')
    version = settings.RIOT_DD_VERSION

    CACHE_KEY = f'ddragon:champions:{version}:{lang}'
    cached = _cached_get(CACHE_KEY)
    if cached:
        print(f'[DDRAGON] champions 캐시 히트 ver={version}', flush=True)
        return JsonResponse({'success': True, 'champions': cached, 'version': version, 'cached': True})

    url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/champion.json'
    try:
        raw    = _riot_get(url)
        champs = {
            int(c['key']): {'name': c['name'], 'id': c['id']}
            for c in raw['data'].values()
        }
        _cached_set(CACHE_KEY, champs)
        print(f'[DDRAGON] champions 캐시 저장 count={len(champs)}', flush=True)
        return JsonResponse({'success': True, 'champions': champs, 'version': version, 'cached': False})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def riot_api_ddSpell(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    lang    = request.GET.get('lang', 'ko_KR')
    version = settings.RIOT_DD_VERSION

    CACHE_KEY = f'ddragon:spells:{version}:{lang}'
    cached = _cached_get(CACHE_KEY)
    if cached:
        print(f'[DDRAGON] spells 캐시 히트 ver={version}', flush=True)
        return JsonResponse({'success': True, 'data': cached, 'cached': True})

    url = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/summoner.json'
    try:
        raw        = _riot_get(url)
        spell_data = raw.get('data', {})
        _cached_set(CACHE_KEY, spell_data)
        print(f'[DDRAGON] spells 캐시 저장 count={len(spell_data)}', flush=True)
        return JsonResponse({'success': True, 'data': spell_data, 'cached': False})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)