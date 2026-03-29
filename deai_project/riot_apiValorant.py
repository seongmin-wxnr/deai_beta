import urllib.request
import urllib.error
import urllib.parse
import json

from django.http      import JsonResponse
from django.shortcuts import render
from django.conf      import settings
from django.core.cache import cache
from django.utils     import timezone

# 공통 DB 캐시 헬퍼
from .riot_apiViews import (
    _user_cache_get,
    _user_cache_set,
    _user_info_upsert,
    _cached_get,
    _cached_set,
    MATCH_CACHE_TTL,
    MATCH_IDS_TTL,
    _CACHE_MISS,
)

# VALORANT Tier System
# competitiveTier 숫자 티어 이름 매핑
# 0~2 : 배치 없음
# 3~5 : Iron 1/2/3
# 6~8 : Bronze 1/2/3
# 9~11 : Silver 1/2/3
# 12~14: Gold 1/2/3
# 15~17: Platinum 1/2/3
# 18~20: Diamond 1/2/3
# 21~23: Ascendant 1/2/3
# 24~26: Immortal 1/2/3
# 27 : Radiant
# RR (Rating Rank): 0 ~ 99 (Immortal 이하)

class RiotAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message     = message
        super().__init__(message)


def _handle_error(e: RiotAPIError) -> JsonResponse:
    MESSAGES = {
        400: '잘못된 요청입니다.',
        401: 'API 키 오류입니다.',
        403: 'API 키가 만료되었습니다. 관리자에게 문의하세요.',
        404: '플레이어를 찾을 수 없습니다.',
        429: '요청 횟수를 초과했습니다. 잠시 후 재시도해주세요.',
        500: 'Riot 서버 오류입니다.',
        503: '네트워크 연결 오류입니다.',
    }
    msg  = MESSAGES.get(e.status_code, e.message)
    code = e.status_code if e.status_code in MESSAGES else 500
    return JsonResponse(
        {'success': False, 'message': msg, 'riot_status': e.status_code},
        status=code
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
    print(f"[VAL API] → {url}", flush=True)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"[VAL API] ✓ {str(data)[:100]}", flush=True)
            return data
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            pass
        print(f"[VAL API] ✗ HTTP {e.code}: {body}", flush=True)
        raise RiotAPIError(e.code, body.get('status', {}).get('message', str(e)))
    except urllib.error.URLError as e:
        print(f"[VAL API] ✗ URL: {e.reason}", flush=True)
        raise RiotAPIError(503, f'네트워크 오류: {e.reason}')


def _get_region_urls(region: str) -> tuple:
    info = settings.RIOT_REGION_MAP.get(region.lower())
    if not info:
        raise RiotAPIError(400, f'지원하지 않는 지역: {region}')
    return info['platform'], info['regional']


def _get_tier_info(tier: int) -> dict:
    return settings.VAL_TIER_MAP.get(tier, settings.VAL_TIER_MAP[0])


def _calc_kda(kills: int, deaths: int, assists: int) -> str:
    if deaths == 0:
        return 'Perfect'
    return f"{(kills + assists) / deaths:.2f}"


def _calc_hit_map(round_results: list) -> dict:
    hit_map = {}
    for rr in round_results:
        for ps in rr.get('playerStats', []):
            puuid = ps.get('puuid', '')
            if puuid not in hit_map:
                hit_map[puuid] = {'head': 0, 'body': 0, 'leg': 0}
            for dmg in ps.get('damage', []):
                hit_map[puuid]['head'] += dmg.get('headshots', 0)
                hit_map[puuid]['body'] += dmg.get('bodyshots', 0)
                hit_map[puuid]['leg']  += dmg.get('legshots',  0)
    return hit_map


def _get_agent_name(character_id: str) -> str:
    return settings.VAL_AGENT_MAP.get(character_id.lower() if character_id else '', '?')


def _get_agent_icon(character_id: str) -> str:
    if not character_id:
        return ''
    return f'https://media.valorant-api.com/agents/{character_id.lower()}/displayiconsmall.png'


def _get_map_name(map_id: str) -> str:
    return settings.VAL_MAP_MAP.get(map_id, map_id.split('/')[-1] if map_id else 'Unknown')


def riot_api_VRTUserPageRendering(request):
    if not request.session.get('user_id'):
        return render(request, 'login.html')
    return render(request, 'riot_vrtUserpage.html', {
        'DD_VERSION': settings.RIOT_DD_VERSION,
    })

# GET /api/val/account/?name=...&tag=...&region=...
# Riot Account v1 /riot/account/v1/accounts/by-riot-id/{name}/{tag}
def val_api_search_account(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    name   = request.GET.get('name',   '').strip()
    tag    = request.GET.get('tag',    '').strip()
    region = request.GET.get('region', 'kr').strip().lower()

    if not name or not tag:
        return JsonResponse({'success': False, 'message': '이름과 태그를 입력해주세요.'}, status=400)

    try:
        _, regional = _get_region_urls(region)

        # 1순위: DB 캐시 조회 (puuid 있으면 API 호출 없음)
        try:
            from .models import Riot_UserINFO
            cached_user = Riot_UserINFO.objects.filter(
                username__iexact=name, tag__iexact=tag, region=region
            ).first()
            if cached_user and cached_user.puuid:
                print(f'[VAL SEARCH HIT] puuid={cached_user.puuid[:12]}…', flush=True)
                return JsonResponse({
                    'success'       : True,
                    'gameName'      : cached_user.username,
                    'tagLine'       : cached_user.tag,
                    'puuid'         : cached_user.puuid,
                    'summonerId'    : '',
                    'profileIconId' : 29,
                    'summonerLevel' : 0,
                    'cached'        : True,
                })
        except Exception as ex:
            print(f'[VAL SEARCH] DB 조회 실패(API 폴백): {ex}', flush=True)

        # 2순위: Riot API 호출
        account  = _riot_get(
            f'https://{regional}/riot/account/v1/accounts/by-riot-id'
            f'/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}'
        )
        puuid    = account['puuid']
        gameName = account.get('gameName', name)
        tagLine  = account.get('tagLine',  tag)

        _user_info_upsert(puuid=puuid, username=gameName, tag=tagLine, region=region)
        print(f'[VAL SEARCH] API 호출 완료 + DB 저장 puuid={puuid[:12]}…', flush=True)

        return JsonResponse({
            'success'       : True,
            'gameName'      : gameName,
            'tagLine'       : tagLine,
            'puuid'         : puuid,
            'summonerId'    : '',
            'profileIconId' : 29,
            'summonerLevel' : 0,
            'cached'        : False,
        })

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f"[VAL] account 예외: {e}", flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# GET /api/val/matches/?puuid=...&region=...
# VAL Match List v1
# /val/match/v1/matchlists/by-puuid/{puuid}

def val_api_getMatchIDs(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    puuid       = request.GET.get('puuid',  '').strip()
    region      = request.GET.get('region', 'kr').strip().lower()
    username    = request.GET.get('name',   '').strip()
    tag         = request.GET.get('tag',    '').strip()
    queue_param = request.GET.get('queueId', '').strip()
    q_slug_map  = {
        'competitive'   : 'val_competitive',
        'unrated'       : 'val_unrated',
        'spikerush'     : 'val_spike_rush',
        'deathmatch'    : 'val_deathmatch',
        'teamdeathmatch': 'val_team_deathmatch',
    }
    q_slug = q_slug_map.get(queue_param, 'val_unrated')

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    # DB 캐시 조회 (match_ids 필드, 10분 TTL)
    try:
        from .models import Riot_UserINFO, Riot_MatchInfo
        user = Riot_UserINFO.get_or_none(puuid)
        if user:
            obj = Riot_MatchInfo.objects.filter(
                user=user, game='val', queue_type=q_slug
            ).first()
            if obj:
                stored_ids = getattr(obj, 'match_ids', None) or []
                if stored_ids:
                    age = (timezone.now() - obj.updated_at).total_seconds()
                    if age <= MATCH_IDS_TTL:
                        print(f'[VAL MATCH IDS HIT] slug={q_slug} count={len(stored_ids)} age={int(age)}s', flush=True)
                        return JsonResponse({
                            'success' : True,
                            'matchIds': stored_ids,
                            'cached'  : True,
                        })
                    else:
                        print(f'[VAL MATCH IDS MISS] TTL 만료 age={int(age)}s', flush=True)
    except Exception as ex:
        print(f'[VAL MATCH IDS] DB 조회 실패(API 폴백): {ex}', flush=True)

    # Riot API 호출
    try:
        platform, _ = _get_region_urls(region)
        ml_data = _riot_get(f'https://{platform}/val/match/v1/matchlists/by-puuid/{puuid}')
        history = ml_data.get('history', [])
        if queue_param:
            history = [h for h in history if h.get('queueId') == queue_param]
        ids = [h['matchId'] for h in history if h.get('matchId')]

        try:
            _user_cache_set(
                puuid, username, tag, region,
                game='val', queue_type=q_slug,
                data={},
                last_match_id=ids[0] if ids else '',
                match_ids=ids,
            )
        except Exception as ex:
            print(f'[VAL MATCH IDS] DB 저장 실패(무시): {ex}', flush=True)

        return JsonResponse({'success': True, 'matchIds': ids, 'cached': False})

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f"[VAL] matchlist 예외: {e}", flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def val_api_matchDetail(request, match_id):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    region = request.GET.get('region', 'kr').strip().lower()

    # 24시간 캐시 조회 (경기 결과는 불변)
    cache_key = f'val_match_detail:{match_id}'
    cached = _cached_get(cache_key)
    if cached:
        print(f'[VAL MATCH HIT] match_id={match_id}', flush=True)
        return JsonResponse({'success': True, 'match': cached, 'cached': True})

    try:
        platform, _ = _get_region_urls(region)
        raw = _riot_get(f'https://{platform}/val/match/v1/matches/{match_id}')

        match_info    = raw.get('matchInfo',    {})
        raw_players   = raw.get('players',      [])
        raw_teams     = raw.get('teams',        [])
        round_results = raw.get('roundResults', [])

        hit_map = _calc_hit_map(round_results)
        players = []
        for p in raw_players:
            puuid  = p.get('puuid', '')
            stats  = p.get('stats', {})
            tier   = p.get('competitiveTier', 0)
            ti     = _get_tier_info(tier)

            rounds  = stats.get('roundsPlayed', 1) or 1
            score   = stats.get('score',   0)
            kills   = stats.get('kills',   0)
            deaths  = stats.get('deaths',  0)
            assists = stats.get('assists', 0)

            # ACS
            acs = round(score / rounds, 1)

            # 히트 통계
            hits       = hit_map.get(puuid, {'head': 0, 'body': 0, 'leg': 0})
            total_hits = hits['head'] + hits['body'] + hits['leg']
            hs_pct     = round(hits['head'] / total_hits * 100, 1) if total_hits else 0.0

            # 피해량
            total_dmg     = sum(rd.get('damage', 0) for rd in p.get('roundDamage', []))
            dmg_per_round = round(total_dmg / rounds, 1)

            char_id = p.get('characterId', '')

            players.append({
                'puuid'          : puuid,
                'teamId'         : p.get('teamId', ''),
                'characterId'    : char_id,
                'agentName'      : _get_agent_name(char_id),
                'agentIconUrl'   : _get_agent_icon(char_id),
                'competitiveTier': tier,
                'tierName'       : ti['name'],
                'tierDivision'   : ti['division'],
                'riotIdGameName' : p.get('riotIdGameName', ''),
                'riotIdTagline'  : p.get('riotIdTagline',  ''),
                'playerCard'     : p.get('playerCard', ''),
                'stats': {
                    'score'        : score,
                    'roundsPlayed' : rounds,
                    'kills'        : kills,
                    'deaths'       : deaths,
                    'assists'      : assists,
                },
                'damage': {
                    'total'    : total_dmg,
                    'perRound' : dmg_per_round,
                    'headshots': hits['head'],
                    'bodyshots': hits['body'],
                    'legshots' : hits['leg'],
                    'hsPercent': hs_pct,
                },
                'acs': acs,
                'kda': _calc_kda(kills, deaths, assists),
            })

        teams = [
            {
                'teamId'      : t.get('teamId',       ''),
                'won'         : t.get('won',          False),
                'roundsPlayed': t.get('roundsPlayed', 0),
                'roundsWon'   : t.get('roundsWon',    0),
                'numPoints'   : t.get('numPoints',    0),
            }
            for t in raw_teams
        ]
        queue_id = match_info.get('queueId', '')
        map_id   = match_info.get('mapId',   '')

        result = {
            'matchInfo': {
                'matchId'          : match_info.get('matchId', match_id),
                'mapId'            : map_id,
                'mapName'          : _get_map_name(map_id),
                'gameLengthMillis' : match_info.get('gameLengthMillis', 0),
                'gameStartMillis'  : match_info.get('gameStartMillis', 0),
                'queueId'          : queue_id,
                'queueName'        : settings.VAL_QUEUE_MAP.get(queue_id, queue_id or '커스텀'),
                'seasonId'         : match_info.get('seasonId', ''),
            },
            'players': players,
            'teams'  : teams,
        }
        _cached_set(cache_key, result)
        return JsonResponse({'success': True, 'match': result, 'cached': False})

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f"[VAL] match detail 예외: {e}", flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def val_api_getRank(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)

    puuid    = request.GET.get('puuid',  '').strip()
    region   = request.GET.get('region', 'kr').strip().lower()
    username = request.GET.get('name',   '').strip()
    tag      = request.GET.get('tag',    '').strip()

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    UNRANKED_RESP = {
        'success': True, 'ranked': False,
        'tier': 0, 'tierName': 'UNRANKED', 'tierDivision': '',
        'rr': 0, 'wins': 0, 'losses': 0, 'matches': 0,
        'cached': False,
    }
    cached = _user_cache_get(puuid, 'val', 'val_competitive')
    if cached is not _CACHE_MISS:
        print(f'[VAL RANK HIT] puuid={puuid[:12]}… data={str(cached)[:60]}', flush=True)
        if cached:
            return JsonResponse({**cached, 'success': True, 'cached': True})
        else:
            return JsonResponse({**UNRANKED_RESP, 'cached': True})

    try:
        platform, _ = _get_region_urls(region)
        ml_data  = _riot_get(f'https://{platform}/val/match/v1/matchlists/by-puuid/{puuid}')
        history  = ml_data.get('history', [])
        comp_his = [h for h in history if h.get('queueId') == 'competitive']

        if not comp_his:
            return JsonResponse(UNRANKED_RESP)

        latest    = _riot_get(f'https://{platform}/val/match/v1/matches/{comp_his[0]["matchId"]}')
        me_player = next((p for p in latest.get('players', []) if p.get('puuid') == puuid), None)

        if not me_player:
            return JsonResponse(UNRANKED_RESP)

        tier      = me_player.get('competitiveTier', 0)
        tier_info = _get_tier_info(tier)

        wins = 0; losses = 0
        for h in comp_his[:5]:
            try:
                m  = _riot_get(f'https://{platform}/val/match/v1/matches/{h["matchId"]}')
                me = next((p for p in m.get('players', []) if p.get('puuid') == puuid), None)
                if not me:
                    continue
                my_team = next((t for t in m.get('teams', []) if t.get('teamId') == me.get('teamId')), None)
                if my_team:
                    wins   += 1 if my_team.get('won') else 0
                    losses += 0 if my_team.get('won') else 1
            except Exception:
                pass

        rank_data = {
            'success'      : True,
            'ranked'       : tier > 2,
            'tier'         : tier,
            'tierName'     : tier_info['name'],
            'tierDivision' : tier_info['division'],
            'rr'           : 0,
            'wins'         : wins,
            'losses'       : losses,
            'matches'      : wins + losses,
        }
        _user_cache_set(puuid, username, tag, region,
                        'val', 'val_competitive', rank_data if tier > 2 else {})
        print(f'[VAL RANK] API 호출 tier={tier} wins={wins} losses={losses}', flush=True)

        return JsonResponse({**rank_data, 'cached': False})

    except RiotAPIError as e:
        return _handle_error(e)
    except Exception as e:
        print(f"[VAL] rank 예외: {e}", flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)