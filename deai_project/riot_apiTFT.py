import urllib.request
import urllib.error
import urllib.parse
import json
import re

from django.http       import JsonResponse
from django.shortcuts  import render
from django.conf       import settings
from django.core.cache import cache
from django.utils      import timezone

# 공통 DB 캐시 헬퍼 (riot_apiViews 에서 import)
from .riot_apiViews import (
    _user_cache_get,
    _user_cache_set,
    _user_info_upsert,
    _match_detail_cache_get,
    _match_detail_cache_set,
    _cached_get,
    _cached_set,
    MATCH_CACHE_TTL,
    MATCH_IDS_TTL,
    _CACHE_MISS,
)


_COMPANION_CACHE: dict  = {}
_COMPANION_LOADED: bool = False

_CDRAGON_COMPANIONS_URL = (
    'https://raw.communitydragon.org/latest/plugins/'
    'rcp-be-lol-game-data/global/default/v1/companions.json'
)
_CDRAGON_PLUGIN_BASE = (
    'https://raw.communitydragon.org/latest/plugins/'
    'rcp-be-lol-game-data/global/default'
)


def _load_companion_cache() -> None:
    global _COMPANION_CACHE, _COMPANION_LOADED
    if _COMPANION_LOADED:
        return
    try:
        req = urllib.request.Request(
            _CDRAGON_COMPANIONS_URL,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            companions = json.loads(resp.read().decode('utf-8'))
        for c in companions:
            cid  = c.get('contentId', '')
            icon = c.get('loadoutsIcon', '')
            if not cid or not icon:
                continue
            path = icon.replace('/lol-game-data/assets', '').lower()
            _COMPANION_CACHE[cid] = _CDRAGON_PLUGIN_BASE + path
        _COMPANION_LOADED = True
        print(f'[TFT] companion cache loaded: {len(_COMPANION_CACHE)} items', flush=True)
    except Exception as ex:
        print(f'[TFT] companion cache load failed: {ex}', flush=True)


def _companion_img_url(content_id: str) -> str:
    _load_companion_cache()
    return _COMPANION_CACHE.get(content_id, '')


# 상수

# tft_game_type (match API) 한글
# queue_id 폴백: 1090=일반, 1100=솔로랭크, 1130=하이퍼롤, 1160=더블업
TFT_QUEUE_KO = {
    'standard' : '일반',
    'ranked'   : '솔로랭크',
    'pairs'    : '더블업',
    'turbo'    : '하이퍼롤',
    'tutorial' : '튜토리얼',
    1090       : '일반',
    1100       : '솔로랭크',
    1130       : '하이퍼롤',
    1160       : '더블업',
}

# 랭크 게임 여부
TFT_RANKED_TYPES  = {'ranked', 'pairs'}
TFT_RANKED_QUEUES = {1100, 1160}

# 티어 한글
TFT_TIER_KO = {
    'IRON'        : '아이언',
    'BRONZE'      : '브론즈',
    'SILVER'      : '실버',
    'GOLD'        : '골드',
    'PLATINUM'    : '플래티넘',
    'EMERALD'     : '에메랄드',
    'DIAMOND'     : '다이아몬드',
    'MASTER'      : '마스터',
    'GRANDMASTER' : '그랜드마스터',
    'CHALLENGER'  : '챌린저',
}

# 디비전 없는 최상위 티어
TOP_TIERS = {'MASTER', 'GRANDMASTER', 'CHALLENGER'}

# 모달에서 제외할 고유 특성 ID
UNIQUE_TRAIT_IDS = {
    'TFT16_SylasTrait',   'TFT16_ShyvanaUnique', 'TFT16_KaisaUnique',
    'TFT16_XerathUnique', 'TFT16_KindredUnique', 'TFT16_ZaahenTrait',
    'TFT16_Heroic',       'TFT16_Blacksmith',    'TFT16_DarkChild',
    'TFT16_Emperor',      'TFT16_Caretaker',     'TFT16_Glutton',
    'TFT16_Huntress',     'TFT16_HexMech',       'TFT16_Harvester',
    'TFT16_Chronokeeper', 'TFT16_DarkinWeapon',
}

def _clean_augment(aug_id: str) -> str:
    name = re.sub(r'^TFT\d*_Augment_', '', aug_id)
    name = re.sub(r'^TFT\d*_Item_',    '', name)
    name = re.sub(r'(?<=[a-z])(?=[A-Z])',     ' ', name)
    name = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', name)
    return name.strip()


def _trait_style_name(style: int) -> str:
    return ['', 'bronze', 'silver', 'gold', 'chromatic'][min(style, 4)]


def _placement_str(p: int) -> str:
    return {1:'1위',2:'2위',3:'3위',4:'4위',
            5:'5위',6:'6위',7:'7위',8:'8위'}.get(p, f'{p}위')


def _tier_emblem_url(tier: str) -> str:
    return (
        'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/'
        f'global/default/images/ranked-emblem/emblem-{tier.lower()}.png'
    )


def _parse_rank_entry(entry: dict) -> dict:
    """league entry → 프론트 랭크 dict"""
    tier  = entry['tier']
    total = entry['wins'] + entry['losses']
    return {
        'queueType' : entry['queueType'],
        'tier'      : tier,
        'tierKo'    : TFT_TIER_KO.get(tier, tier),
        'rank'      : entry['rank'] if tier not in TOP_TIERS else '',
        'lp'        : entry['leaguePoints'],
        'wins'      : entry['wins'],
        'losses'    : entry['losses'],
        'winRate'   : round(entry['wins'] / total * 100) if total else 0,
        'hotStreak' : entry['hotStreak'],
        'veteran'   : entry['veteran'],
        'freshBlood': entry['freshBlood'],
        'emblemUrl' : _tier_emblem_url(tier),
    }

class RiotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message     = message
        super().__init__(message)


def _handle_error(e: RiotAPIError) -> JsonResponse:
    MESSAGES = {
        400: '잘못된 요청입니다.',
        401: 'API 키 오류입니다.',
        403: 'API 키가 만료되었거나 권한이 없습니다.',
        404: '플레이어를 찾을 수 없습니다.',
        429: '요청 횟수를 초과했습니다. 잠시 후 재시도해주세요.',
        500: 'Riot 서버 오류입니다.',
        503: '네트워크 연결 오류입니다.',
    }
    return JsonResponse(
        {'success': False,
         'message': MESSAGES.get(e.status_code, e.message),
         'riot_status': e.status_code},
        status=200
    )


def _riot_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            'X-Riot-Token'   : settings.RIOT_API_KEY,
            'User-Agent'     : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'ko-KR,ko;q=0.9',
            'Accept-Charset' : 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin'         : 'https://developer.riotgames.com',
        }
    )
    print(f'[RIOT] GET {url}', flush=True)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            pass
        print(f'[RIOT] {e.code} — {url}', flush=True)
        raise RiotAPIError(e.code, body.get('status', {}).get('message', str(e)))
    except urllib.error.URLError as e:
        raise RiotAPIError(503, f'네트워크 오류: {e.reason}')


def _get_region_urls(region: str) -> tuple:
    info = settings.RIOT_REGION_MAP.get(region.lower())
    if not info:
        raise RiotAPIError(400, f'지원하지 않는 지역: {region}')
    return info['platform'], info['regional']


def _fetch_rank_cached(platform: str, puuid: str, prefer_double: bool = False) -> dict | None:
    cache_key = f'tft_rank_{platform}_{puuid}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached else None  # False 저장 = 언랭

    entries = _riot_get(f'https://{platform}/tft/league/v1/by-puuid/{puuid}')

    entry = None
    if prefer_double:
        entry = next((e for e in entries if e['queueType'] == 'RANKED_TFT_DOUBLE_UP'), None)
    if entry is None:
        entry = next((e for e in entries if e['queueType'] == 'RANKED_TFT'), None)

    result = _parse_rank_entry(entry) if entry else None
    cache.set(cache_key, result if result is not None else False, 300)
    return result

def tft_page_rendering(request):
    if not request.session.get('user_id'):
        return render(request, 'login.html')
    return render(request, 'riot_tftUserpage.html', {
        'DD_VERSION': settings.RIOT_DD_VERSION,
    })


def tft_api_search_account(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    name   = request.GET.get('name',   '').strip()
    tag    = request.GET.get('tag',    '').strip()
    region = request.GET.get('region', 'kr').strip().lower()

    if not name or not tag:
        return JsonResponse({'success': False, 'message': '이름과 태그를 입력해주세요.'}, status=400)

    try:
        platform, regional = _get_region_urls(region)

        # 1순위: DB 캐시 조회 (puuid 있으면 API 호출 없음)
        try:
            from .models import Riot_UserINFO
            cached_user = Riot_UserINFO.objects.filter(
                username__iexact=name, tag__iexact=tag, region=region
            ).first()
            if cached_user and cached_user.puuid:
                print(f'[TFT SEARCH HIT] puuid={cached_user.puuid[:12]}…', flush=True)
                return JsonResponse({
                    'success'      : True,
                    'gameName'     : cached_user.username,
                    'tagLine'      : cached_user.tag,
                    'puuid'        : cached_user.puuid,
                    'summonerId'   : getattr(cached_user, 'summoner_id', ''),
                    'profileIconId': getattr(cached_user, 'profile_icon_id', 1),
                    'summonerLevel': getattr(cached_user, 'summoner_level', 0),
                    'cached'       : True,
                })
        except Exception as ex:
            print(f'[TFT SEARCH] DB 조회 실패(API 폴백): {ex}', flush=True)

        # 2순위: Riot API 호출
        account = _riot_get(
            f'https://{regional}/riot/account/v1/accounts/by-riot-id'
            f'/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}'
        )
        puuid    = account['puuid']
        gameName = account.get('gameName', name)
        tagLine  = account.get('tagLine',  tag)

        summoner        = _riot_get(
            f'https://{platform}/tft/summoner/v1/summoners/by-puuid/{puuid}'
        )
        summoner_id     = summoner.get('id', '')
        profile_icon_id = summoner.get('profileIconId', 1)
        summoner_level  = summoner.get('summonerLevel', 0)

        # DB 저장
        _user_info_upsert(
            puuid=puuid, username=gameName, tag=tagLine, region=region,
            summoner_id=summoner_id,
            profile_icon_id=profile_icon_id,
            summoner_level=summoner_level,
        )
        print(f'[TFT SEARCH] API 호출 완료 + DB 저장 puuid={puuid[:12]}…', flush=True)

        return JsonResponse({
            'success'      : True,
            'gameName'     : gameName,
            'tagLine'      : tagLine,
            'puuid'        : puuid,
            'summonerId'   : summoner_id,
            'profileIconId': profile_icon_id,
            'summonerLevel': summoner_level,
            'cached'       : False,
        })

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f'[TFT] account 예외: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=200)


def tft_api_getRank(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    # DB 캐시 조회
    cached_solo   = _user_cache_get(puuid, 'tft', 'tft_ranked')
    cached_double = _user_cache_get(puuid, 'tft', 'tft_double_up')
    if cached_solo is not _CACHE_MISS and cached_double is not _CACHE_MISS:
        print(f'[TFT RANK HIT] puuid={puuid[:12]}… solo={str(cached_solo)[:40]} double={str(cached_double)[:40]}', flush=True)
        return JsonResponse({
            'success': True,
            'solo'   : cached_solo   if cached_solo   else None,
            'double' : cached_double if cached_double else None,
            'cached' : True,
        })

    try:
        platform, _ = _get_region_urls(region)
        entries      = _riot_get(f'https://{platform}/tft/league/v1/by-puuid/{puuid}')

        solo_entry   = next((e for e in entries if e['queueType'] == 'RANKED_TFT'),           None)
        double_entry = next((e for e in entries if e['queueType'] == 'RANKED_TFT_DOUBLE_UP'), None)

        solo_data   = _parse_rank_entry(solo_entry)   if solo_entry   else None
        double_data = _parse_rank_entry(double_entry) if double_entry else None

        # DB 캐시 저장 (언랭=None도 {}로 저장해서 재호출 방지)
        _user_cache_set(puuid, username, tag, region,
                        'tft', 'tft_ranked', solo_data or {})
        _user_cache_set(puuid, username, tag, region,
                        'tft', 'tft_double_up', double_data or {})

        print(f'[TFT RANK] API 호출 solo={str(solo_data)[:40]}', flush=True)
        return JsonResponse({'success': True, 'solo': solo_data, 'double': double_data, 'cached': False})

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f'[TFT] rank 예외: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=200)


def tft_api_getMatchIDs(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()
    count    = min(int(request.GET.get('count', 20)), 100)

    qt_param   = request.GET.get('queueType', '').strip()
    q_slug_map = {
        'ranked'               : 'tft_ranked',
        'RANKED_TFT'           : 'tft_ranked',
        'pairs'                : 'tft_double_up',
        'RANKED_TFT_DOUBLE_UP' : 'tft_double_up',
        'standard'             : 'tft_normal',
    }
    q_slug = q_slug_map.get(qt_param, 'tft_normal')

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    # DB 캐시 조회 (match_ids 필드 기반, 10분 TTL)
    try:
        from .models import Riot_UserINFO, Riot_MatchInfo
        user = Riot_UserINFO.get_or_none(puuid)
        if user:
            obj = Riot_MatchInfo.objects.filter(
                user=user, game='tft', queue_type=q_slug
            ).first()
            if obj:
                stored_ids = getattr(obj, 'match_ids', None) or []
                if stored_ids:
                    age = (timezone.now() - obj.updated_at).total_seconds()
                    if age <= MATCH_IDS_TTL:
                        print(f'[TFT MATCH IDS HIT] slug={q_slug} count={len(stored_ids)} age={int(age)}s', flush=True)
                        return JsonResponse({
                            'success'     : True,
                            'matchIds'    : stored_ids,
                            'lastMatchId' : getattr(obj, 'last_match_id', ''),
                            'cached'      : True,
                        })
                    else:
                        print(f'[TFT MATCH IDS MISS] TTL 만료 age={int(age)}s', flush=True)
                else:
                    print(f'[TFT MATCH IDS MISS] match_ids 비어있음', flush=True)
    except Exception as ex:
        print(f'[TFT MATCH IDS] DB 조회 실패(API 폴백): {ex}', flush=True)

    # Riot API 호출
    try:
        _, regional = _get_region_urls(region)
        data = _riot_get(
            f'https://{regional}/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}'
        )
        ids = data if isinstance(data, list) else []

        # match_ids 필드에 저장
        try:
            _user_cache_set(
                puuid, username, tag, region,
                game='tft', queue_type=q_slug,
                data={},
                last_match_id=ids[0] if ids else '',
                match_ids=ids,
            )
        except Exception as ex:
            print(f'[TFT MATCH IDS] DB 저장 실패(무시): {ex}', flush=True)

        return JsonResponse({'success': True, 'matchIds': ids, 'cached': False})

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f'[TFT] matchlist 예외: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=200)


def tft_api_matchDetail(request, match_id):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    region = request.GET.get('region', 'kr').strip().lower()

    # 24시간 캐시 조회 (경기 결과는 불변)
    cache_key = f'tft_match_detail:{match_id}'
    cached = _cached_get(cache_key)
    if cached:
        print(f'[TFT MATCH HIT] match_id={match_id}', flush=True)
        return JsonResponse({'success': True, 'match': cached, 'cached': True})

    try:
        _, regional = _get_region_urls(region)
        raw        = _riot_get(f'https://{regional}/tft/match/v1/matches/{match_id}')
        info       = raw.get('info', {})
        raw_parts  = info.get('participants', [])

        queue_type = info.get('tft_game_type', '')
        queue_id   = info.get('queue_id', 0)

        # queue_id 기반 폴백 (tft_game_type이 비어있거나 매핑 없을 때)
        if not queue_type or queue_type not in TFT_QUEUE_KO:
            if queue_id in TFT_QUEUE_KO:
                queue_type = {1090:'standard', 1100:'ranked', 1130:'turbo', 1160:'pairs'}.get(queue_id, queue_type)

        queue_ko  = TFT_QUEUE_KO.get(queue_type, '일반')
        is_ranked = queue_type in TFT_RANKED_TYPES or queue_id in TFT_RANKED_QUEUES

        if is_ranked:
            if queue_type == 'pairs' or queue_id == 1160:
                queue_name = '(랭크) 더블업'
            else:
                queue_name = '(랭크) 솔로랭크'
        else:
            queue_name = queue_ko

        match_info = {
            'matchId'       : raw.get('metadata', {}).get('match_id', match_id),
            'gameLength'    : round(info.get('game_length', 0)),
            'tftSetNumber'  : info.get('tft_set_number',    0),
            'tftSetCoreName': info.get('tft_set_core_name', ''),
            'queueType'     : queue_type,
            'queueName'     : queue_name,
            'isRanked'      : is_ranked,
            'gameDate'      : info.get('game_datetime', 0),
        }

        participants = []
        for p in raw_parts:
            # 증강
            augments = [
                {'id': a, 'name': _clean_augment(a)}
                for a in p.get('augments', [])
            ]

            # 시너지 (비활성 + 고유 제외)
            traits = []
            for t in p.get('traits', []):
                style    = t.get('style', 0)
                tier_tot = t.get('tier_total', 0)
                raw_name = t.get('name', '')
                if style <= 0 or tier_tot <= 0:
                    continue
                traits.append({
                    'name'       : raw_name,
                    'numUnits'   : t.get('num_units', 0),
                    'style'      : style,
                    'styleName'  : _trait_style_name(style),
                    'tierCurrent': t.get('tier_current', 0),
                    'tierTotal'  : tier_tot,
                })
            traits.sort(key=lambda x: x['style'], reverse=True)

            # 유닛
            units = []
            for u in p.get('units', []):
                units.append({
                    'characterId': u.get('character_id', ''),
                    'name'       : u.get('name', u.get('character_id', '').split('_')[-1]),
                    'tier'       : u.get('tier',   1),
                    'rarity'     : u.get('rarity', 0),
                    'itemNames'  : u.get('itemNames', []),
                    'items'      : u.get('items', []),
                })
            units.sort(key=lambda x: (x['rarity'], x['tier']), reverse=True)

            companion  = p.get('companion', {})
            content_id = companion.get('content_ID', '')
            placement  = p.get('placement', 0)

            participants.append({
                'puuid'          : p.get('puuid', ''),
                'riotIdGameName' : p.get('riotIdGameName', ''),
                'riotIdTagline'  : p.get('riotIdTagline',  ''),
                'placement'      : placement,
                'placementStr'   : _placement_str(placement),
                'isTop4'         : placement <= 4,
                'level'          : p.get('level', 0),
                'lastRound'      : p.get('last_round', 0),
                'augments'       : augments,
                'traits'         : traits,
                'units'          : units,
                'companionImgUrl': _companion_img_url(content_id) if content_id else '',
                'stats': {
                    'totalDamage'      : p.get('total_damage_to_players', 0),
                    'playersEliminated': p.get('players_eliminated',       0),
                    'goldLeft'         : p.get('gold_left',                0),
                },
            })

        participants.sort(key=lambda x: x['placement'])

        result = {'matchInfo': match_info, 'participants': participants}
        # 24시간 캐시 저장
        _cached_set(cache_key, result)

        return JsonResponse({
            'success': True,
            'match'  : result,
            'cached' : False,
        })

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f'[TFT] match detail 예외: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=200)
def tft_api_bulk_ranks(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    try:
        body       = json.loads(request.body)
        puuids     = body.get('puuids', [])[:8]
        region     = body.get('region', 'kr').strip().lower()
        queue_type = body.get('queueType', '')
        prefer_dbl = queue_type in ('pairs', 'RANKED_TFT_DOUBLE_UP')

        if not puuids:
            return JsonResponse({'success': True, 'ranks': {}})

        platform, _ = _get_region_urls(region)
        result_map  = {}
        to_fetch    = []

        # # // is cachq
        for puuid in puuids:
            if not puuid:
                continue
            cached = cache.get(f'tft_rank_{platform}_{puuid}')
            if cached is not None:
                result_map[puuid] = cached if cached else None
            else:
                to_fetch.append(puuid)

        print(
            f'[TFT response] left cache: {len(result_map)}, need: {len(to_fetch)}',
            flush=True
        )

        # # / isCache -> True == No api or isCache == False == return jsonresponse , exception -> riotapiexceptionhandle
        for puuid in to_fetch:
            try:
                result = _fetch_rank_cached(platform, puuid, prefer_dbl)
                result_map[puuid] = result
            except RiotAPIError as re:
                result_map[puuid] = None
                if re.status_code == 429:
                    print(
                        f'[TFT response] 429 -> 조기 종료 ({len(result_map)}/{len(puuids)})',  # # <<< ??
                        flush=True
                    )
                    for remaining in to_fetch:
                        result_map.setdefault(remaining, None)  # << replace -> origin : for
                    break
            except Exception as ex:
                # return HTTP response 429
                print(f'[TFT response] {puuid[:8]}… 예외: {ex}', flush=True)
                result_map[puuid] = None

        return JsonResponse({'success': True, 'ranks': result_map})

    except Exception as e:
        print(f'[TFT response ] exception: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=200)