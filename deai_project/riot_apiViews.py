import urllib.request
import urllib.error
import urllib.parse
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.conf import settings
from django.core.cache import cache

# from .models import BaseUserInformation_data

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

def riotSearchPage_rendering(request):
    return render(request, 'riot_lolSearch.html')


def riotUserPage_rendering(request):
    return render(request, 'riot_lolUserpage.html', {
        'DD_VERSION': settings.RIOT_DD_VERSION,
    })

def riot_api_search_user(request):
    print(f"[DEBUG] 함수 진입 - method: {request.method}", flush=True)
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드 입니다.'}, status=405)

    name   = request.GET.get('name',   '').strip()
    tag    = request.GET.get('tag',    '').strip()
    region = request.GET.get('region', 'kr').strip().lower()
    print(f"[DEBUG] 함수 진입 - name tag region: {name} - {tag} - {region}", flush=True)
    if not name or not tag:
        return JsonResponse({'success': False, 'message': '소환사 이름과 태그를 입력해주세요.'}, status=400)

    try:
        platform, regional = _get_region_urls(region)

        account = _riot_get(
            f'https://{regional}/riot/account/v1/accounts/by-riot-id'
            f'/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}'
        )
        print(f"[DEBUG] account 응답: {account}", flush=True)
        summoner = _riot_get(
            f'https://{platform}/lol/summoner/v4/summoners/by-puuid/{account["puuid"]}'
        )
        print(f"[DEBUG] summoner 응답: {summoner}", flush=True)
        return JsonResponse({
            'success'       : True,
            'puuid'         : account['puuid'],
            'gameName'      : account['gameName'],
            'tagLine'       : account['tagLine'],
            'summonerId'    : summoner.get('id', summoner.get('summonerId', '')),
            'accountId'     : summoner.get('accountId', ''),
            'profileIconId' : summoner.get('profileIconId', 0),
            'summonerLevel' : summoner.get('summonerLevel', 0),
            'region'        : region,
            'platform'      : platform,
            'regional'      : regional,
        })

    except RiotAPIError as e:
        return _error_response(e)

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)

def riot_api_rankInfo(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    summoner_id = request.GET.get('summonerId', '').strip() ## 씨ㅣㅣ빨 키에서 반환 안해줌 아무래도 puuid로 직접 조회해야할 듯
    puuid = request.GET.get('puuid', '').strip()
    region = request.GET.get('region', 'kr').strip().lower()

    if not summoner_id and not puuid:
        return JsonResponse({'success': False, 'message': '올바른 정보를 입력해주세요.'}, status=400)

    try:
        platform, _ = _get_region_urls(region)
        if puuid:
            print(f"[TEST RIOT API] -> {platform} : {puuid}")
            entries = _riot_get(
                f'https://{platform}/lol/league/v4/entries/by-puuid/{puuid}'
            )
        elif summoner_id:
            print(f"[TEST RIOT API] -> {platform} : {summoner_id}")
            entries = _riot_get(
                f'https://{platform}/lol/league/v4/entries/by-summoner/{summoner_id}'
            )
        else:
            return JsonResponse({'success': True, 'solo': None, 'flex': None})

        def parsing_entry(var):
            print("[LOL API] --> 파싱 함수 실행됌.")
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

        print(f"[LOL API] -> {solo}")
        print(f"[LOL API] -> {flex}")
        return JsonResponse({
            'success': True,
            'solo'   : parsing_entry(solo),
            'flex'   : parsing_entry(flex),
        })

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_getChampionMastery(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid  = request.GET.get('puuid',  '').strip()
    region = request.GET.get('region', 'kr').strip().lower()

    try:
        count = min(int(request.GET.get('count', 5)), 10)
    except (TypeError, ValueError):
        count = 5

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

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
        return JsonResponse({'success': True, 'masteries': result})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_getMatchIDs(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    puuid  = request.GET.get('puuid',  '').strip()
    region = request.GET.get('region', 'kr').strip().lower()

    try:
        start = max(int(request.GET.get('start', 0)),   0)
        count = min(int(request.GET.get('count', 10)), 20)
    except (TypeError, ValueError):
        start, count = 0, 10

    if not puuid:
        return JsonResponse({'success': False, 'message': 'puuid가 필요합니다.'}, status=400)

    try:
        _, regional = _get_region_urls(region)
        ids         = _riot_get(
            f'https://{regional}/lol/match/v5/matches/by-puuid/{puuid}/ids'
            f'?start={start}&count={count}'
        )
        return JsonResponse({'success': True, 'matchIds': ids, 'start': start, 'count': len(ids)})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def riot_api_matchDetail(request, match_id: str):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    region = request.GET.get('region', 'kr').strip().lower()

    try:
        _, regional = _get_region_urls(region)
        data        = _riot_get(
            f'https://{regional}/lol/match/v5/matches/{match_id}'
        )
        return JsonResponse({'success': True, 'match': data})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)

def riot_api_ddVersion(request):
    try:
        versions = _riot_get('https://ddragon.leagueoflegends.com/api/versions.json')
        current  = settings.RIOT_DD_VERSION
        latest   = versions[0] if versions else None
        return JsonResponse({
            'success'    : True,
            'current'    : current,
            'latest'     : latest,
            'is_outdated': (latest != current) if (latest and current) else False,
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
    url     = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/champion.json'

    try:
        raw    = _riot_get(url)
        champs = {
            int(c['key']): {'name': c['name'], 'id': c['id']}
            for c in raw['data'].values()
        }
        return JsonResponse({'success': True, 'champions': champs, 'version': version})

    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def riot_api_ddSpell(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)
    lang    = request.GET.get('lang', 'ko_KR')
    version = settings.RIOT_DD_VERSION
    url     = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/summoner.json'
    try:
        raw = _riot_get(url)
        return JsonResponse({'success': True, 'data': raw.get('data', {})})
    except RiotAPIError as e:
        return _error_response(e)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)