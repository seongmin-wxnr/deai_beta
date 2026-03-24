import urllib.request
import urllib.error
import urllib.parse
import json
import time
import hashlib
import re

from django.http import JsonResponse
from django.shortcuts import render
from django.conf import settings
from django.core.cache import cache

DDRAGON_BASE = 'https://ddragon.leagueoflegends.com'
CACHE_TTL    = 60 * 60 * 6  
DB_TTL_HOURS = 6           

_MEM_CACHE: dict = {}   # 프로세스 내 메모리 캐시

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
def _table_champions_lol(lang: str, ver: str, ddragon_data: dict) -> list:
    """DDragon 챔피언 dict → LOL_infoChampionTable upsert 후 행 목록 반환."""
    from .models import LOL_infoChampionTable
    champs_out = []
    for key, c in ddragon_data.get('data', {}).items():
        tags = c.get('tags', [])
        primary_class = TAG_TO_CLASS.get(tags[0], 'fighter') if tags else 'fighter'
        img_url    = f'{DDRAGON_BASE}/cdn/{ver}/img/champion/{key}.png'
        splash_url = f'{DDRAGON_BASE}/cdn/img/champion/splash/{key}_0.jpg'
        obj, _ = LOL_infoChampionTable.objects.update_or_create(
            champion_id=key,
            defaults={
                'name'          : c.get('name', key),
                'title'         : c.get('title', ''),
                'primary_class' : primary_class,
                'tags'          : [TAG_TO_CLASS.get(t, t.lower()) for t in tags],
                'blurb'         : c.get('blurb', ''),
                'img_url'       : img_url,
                'splash_url'    : splash_url,
                'patch_version' : ver,
            }
        )
        champs_out.append(obj.to_dict())
    champs_out.sort(key=lambda x: x['name'])
    return champs_out


def _table_items_lol(lang: str, ver: str, mapping_hash: str, ddragon_data: dict) -> list:
    """DDragon 아이템 dict → LOL_infoItemTable upsert 후 행 목록 반환."""
    from .models import LOL_infoItemTable
    stat_map = {
        'FlatPhysicalDamageMod': '공격력',
        'FlatMagicDamageMod'   : '주문력',
        'FlatHPPoolMod'        : '체력',
        'FlatArmorMod'         : '방어력',
        'FlatSpellBlockMod'    : '마법 저항력',
        'PercentAttackSpeedMod': '공격속도',
        'FlatCritChanceMod'    : '치명타',
        'FlatMovementSpeedMod' : '이동속도',
        'PercentLifeStealMod'  : '생명력 흡수',
    }
    items_out = []
    for item_id_str, item in ddragon_data.get('data', {}).items():
        itype = _item_type(item, int(item_id_str))
        if not itype:
            continue
        stats    = item.get('stats', {})
        stat_parts   = []
        stats_detail = {}
        for stat_key, stat_name in stat_map.items():
            val = stats.get(stat_key, 0)
            if val:
                if 'Percent' in stat_key:
                    stat_parts.append(f'+{round(val*100)}% {stat_name}')
                    stats_detail[stat_name] = f'+{round(val*100)}%'
                else:
                    stat_parts.append(f'+{int(val)} {stat_name}')
                    stats_detail[stat_name] = f'+{int(val)}'

        desc      = item.get('plaintext', '') or item.get('description', '')
        desc      = re.sub(r'<[^>]+>', '', desc)[:120]
        full_desc = re.sub(r'<[^>]+>', '', item.get('description', ''))
        from_ids  = [int(x) for x in item.get('from', [])]
        into_ids  = [int(x) for x in item.get('into', [])]
        iid       = int(item_id_str)
        name      = (ARENA_ITEMS.get(iid) or ARAM_ITEMS.get(iid)
                     or ARENA_LEGENDARY_ITEMS.get(iid)
                     or FORCE_LEGENDARY_ITEMS.get(iid)
                     or item.get('name', ''))

        obj, _ = LOL_infoItemTable.objects.update_or_create(
            item_id=iid,
            defaults={
                'name'         : name,
                'item_type'    : itype,
                'stats'        : ', '.join(stat_parts) if stat_parts else '—',
                'stats_detail' : stats_detail,
                'desc'         : desc,
                'full_desc'    : full_desc,
                'gold'         : item.get('gold', {}).get('total', 0),
                'gold_sell'    : item.get('gold', {}).get('sell', 0),
                'img_url'      : f'{DDRAGON_BASE}/cdn/{ver}/img/item/{item_id_str}.png',
                'from_ids'     : from_ids,
                'into_ids'     : into_ids,
                'patch_version': ver,
                'mapping_hash' : mapping_hash,
            }
        )
        print(f'[INFO PAGE DEBUG] => ITEM TABLE INFO CREATED -> {name}')
        items_out.append(obj.to_dict())

    type_order = {'legendary': 0, 'arena_legendary': 1, 'arena': 2, 'aram': 3, 'entry': 4}
    items_out.sort(key=lambda x: (type_order.get(x['type'], 9), -x['gold']))
    return items_out


def _table_champions_tft(cd_data: dict) -> list:
    """CDragon TFT Set 데이터 → TFT_infoChampionTable upsert 후 행 목록 반환."""
    from .models import TFT_infoChampionTable
    COST7_API_NAMES = {
        'TFT16_Galio', 'TFT16_BaronNashor', 'TFT16_Ryze',
        'TFT16_Lucian', 'TFT16_Volibear', 'TFT16_Brock', 'TFT16_Sylas',
    }
    set16_champs = cd_data.get('sets', {}).get('16', {}).get('champions', [])
    champs_out = []
    for c in set16_champs:
        api_name = c.get('apiName', '')
        if not api_name.startswith('TFT16_'):
            continue
        raw_cost = c.get('cost', 0)
        if raw_cost < 1 or raw_cost > 5:
            continue
        cost    = 7 if api_name in COST7_API_NAMES else raw_cost
        img_url = _tc_img(c.get('squareIcon') or c.get('tileIcon', ''))

        obj, _ = TFT_infoChampionTable.objects.update_or_create(
            api_name=api_name,
            defaults={
                'name'      : c.get('name', api_name),
                'cost'      : cost,
                'traits'    : c.get('traits', []),
                'img_url'   : img_url,
                'set_number': 16,
            }
        )
        champs_out.append(obj.to_dict())

    champs_out.sort(key=lambda x: (x['cost'], x['name']))
    return champs_out


def _table_items_tft(cd_data: dict) -> list:
    """CDragon TFT items → TFT_infoItemTable upsert 후 행 목록 반환."""
    from .models import TFT_infoItemTable
    all_items = cd_data.get('items', [])
    set_data  = cd_data.get('setData', [])

    set16_item_ids: set = set()
    for s in (set_data if isinstance(set_data, list) else set_data.values()):
        if s.get('name') == 'Set16' and s.get('mutator') == 'TFTSet16':
            set16_item_ids = set(s.get('items', []))
            break

    BASIC_COMPONENTS = {
        'TFT_Item_BFSword', 'TFT_Item_RecurveBow', 'TFT_Item_ChainVest',
        'TFT_Item_NeedlesslyLargeRod', 'TFT_Item_TearOfTheGoddess',
        'TFT_Item_NegatronCloak', 'TFT_Item_GiantsBelt',
        'TFT_Item_SparringGloves', 'TFT_Item_Spatula',
    }
    EMBLEM_BASES = {'TFT_Item_FryingPan', 'TFT_Item_Spatula'}
    EMBLEM_COMP  = BASIC_COMPONENTS | EMBLEM_BASES

    item_map = {
        i['apiName']: {'name': i.get('name', ''), 'icon': i.get('icon', '')}
        for i in all_items if i.get('apiName')
    }
    trait_icon_map = {}
    for t in cd_data.get('sets', {}).get('16', {}).get('traits', []):
        if t.get('name') and t.get('icon'):
            trait_icon_map[t['name']] = _tc_img(t['icon'])

    STAT_MAP = {
        'AD'              : ('공격력',         'pct_conv'),
        'AP'              : ('주문력',         'int'),
        'Armor'           : ('방어력',         'int'),
        'MagicResist'     : ('마법 저항력',    'int'),
        'Health'          : ('체력',           'int'),
        'HP'              : ('체력',           'int'),
        'Mana'            : ('마나',           'int'),
        'ManaRegen'       : ('마나 재생',      'int'),
        'AS'              : ('공격속도',       'int_pct'),
        'CritChance'      : ('치명타',         'int_pct'),
        'Omnivamp'        : ('모든 피해 흡혈', 'int_pct'),
        'CritDamageToGive': ('치명타 피해',    'pct_conv'),
        'StatOmnivamp'    : ('모든 피해 흡혈', 'pct_conv'),
        'AllyHealing'     : ('아군 치유',      'pct_conv'),
        'OmnivampPct'     : ('모든 피해 흡혈', 'pct_conv'),
        'SV'              : ('주문 흡혈',      'pct_conv'),
    }

    def effects_to_stats(effects):
        if not effects:
            return []
        parts, seen_labels = [], set()
        for k, v in effects.items():
            if k not in STAT_MAP or v is None:
                continue
            label, conv = STAT_MAP[k]
            if label in seen_labels:
                continue
            try:
                num = float(v)
                if conv == 'pct_conv':
                    val = round(num * 100)
                    if val == 0:
                        continue
                    parts.append(f'+{val}% {label}')
                elif conv == 'int_pct':
                    val = round(num)
                    if val == 0:
                        continue
                    parts.append(f'+{val}% {label}')
                else:
                    val = int(round(num))
                    if val == 0:
                        continue
                    parts.append(f'+{val} {label}')
                seen_labels.add(label)
            except (ValueError, TypeError):
                pass
        return parts

    items_out = []
    seen_keys  = set()

    for item in all_items:
        name    = item.get('name', '')
        api     = item.get('apiName', '')
        icon    = item.get('icon', '')
        comp    = item.get('composition') or []
        effects = item.get('effects') or {}

        if set16_item_ids and api not in set16_item_ids:
            continue
        if not name or '@' in name or len(name) < 2:
            continue
        if not icon or not (icon.startswith('ASSETS') or icon.startswith('assets')):
            continue
        if 'Items/' not in icon and 'Traits/' not in icon:
            continue

        if api in BASIC_COMPONENTS:
            itype = 'component'
        elif api in EMBLEM_BASES:
            itype = 'component'
        elif '찬란한' in name and 'Radiant' in api:
            itype = 'radiant'
        elif (
            len(comp) >= 2
            and all(c in BASIC_COMPONENTS for c in comp)
            and not any(b in comp for b in EMBLEM_BASES)
        ):
            itype = 'combined'
        elif (
            api.startswith('TFT16_') and 'Emblem' in api
            and len(comp) >= 2
            and any(b in comp for b in EMBLEM_BASES)
            and all(c in EMBLEM_COMP for c in comp)
        ):
            itype = 'emblem'
        elif (
            (api.startswith('TFT_Item_Artifact_') and not any(x in api for x in ['Grant', 'Debug', 'Lesser']))
            or api.startswith('TFT16_The')
            or (api.startswith('TFT7_Item_Shimmerscale') and not api.endswith('_Revival') and not api.endswith('_HR'))
        ):
            itype = 'artifact'
        else:
            continue

        dedup_key = f'{itype}_{name}'
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        comp_detail = []
        for c in comp:
            cm = item_map.get(c, {})
            comp_detail.append({
                'apiName': c,
                'name'   : cm.get('name', c),
                'img'    : _tc_img(cm.get('icon', '')),
            })

        stat_parts = effects_to_stats(effects)
        trait_name = ''
        trait_icon = ''
        if itype == 'emblem':
            trait_name = name.replace(' 상징', '').strip()
            trait_icon = trait_icon_map.get(trait_name, '')

        desc_clean = _clean_tft_desc(item.get('desc', ''))

        obj, _ = TFT_infoItemTable.objects.update_or_create(
            api_name=api,
            defaults={
                'name'      : name,
                'item_type' : itype,
                'stats'     : ', '.join(stat_parts) if stat_parts else '',
                'desc'      : desc_clean,
                'img_url'   : _tc_img(icon),
                'comp'      : comp_detail,
                'trait_name': trait_name,
                'trait_icon': trait_icon,
                'set_number': 16,
            }
        )
        items_out.append(obj.to_dict())

    type_order = {'component': 0, 'combined': 1, 'radiant': 2, 'emblem': 3, 'artifact': 4}
    items_out.sort(key=lambda x: (type_order.get(x['type'], 9), x['name']))
    return items_out

def _tc_img(path: str) -> str:
    """CDragon asset 경로 → 이미지 URL 변환"""
    if not path:
        return ''
    p = path.lower().lstrip('/')
    if p.startswith('game/'):
        p = p[5:]
    for ext in ('.tex', '.dds'):
        if p.endswith(ext):
            p = p[:-len(ext)] + '.png'
            break
    return f'https://raw.communitydragon.org/latest/game/{p}'


def _clean_tft_desc(text: str, max_len: int = 300) -> str:
    if not text:
        return ''
    s = re.sub(r'<tftitemrules>(.*?)</tftitemrules>', r'\1', text, flags=re.DOTALL)
    s = re.sub(r'<TFTBonus>(.*?)</TFTBonus>',         r'\1', s,    flags=re.DOTALL)
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'@TFTUnitProperty[^@]*@', '', s)
    s = re.sub(r'%i:[^%\s]+%', '', s)
    s = re.sub(r'\(%i:[^)]+\)', '', s)
    s = re.sub(r'@[^@]+@', '?', s)
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s[:max_len]


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={'User-Agent': 'DeaiWeb/1.0'})
    with urllib.request.urlopen(req, timeout=8) as res:
        return json.loads(res.read().decode('utf-8'))


_CDRAGON_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept'         : 'application/json, */*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Connection'     : 'keep-alive',
}


def _get_cdragon(url: str, cache_key: str = '') -> dict:
    if cache_key:
        cached = _cached_get(cache_key)
        if cached is not None:
            return cached

    last_err = None
    try:
        import requests as _req
        use_requests = True
    except ImportError:
        use_requests = False

    for attempt in range(3):
        try:
            if use_requests:
                resp = _req.get(url, headers=_CDRAGON_HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            else:
                req = urllib.request.Request(url, headers=_CDRAGON_HEADERS)
                with urllib.request.urlopen(req, timeout=30) as res:
                    data = json.loads(res.read().decode('utf-8'))
            if cache_key:
                _cached_set(cache_key, data)
            return data
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_err


def _dd_version() -> str:
    ver = _cached_get('ddragon_version')
    if ver:
        return ver
    versions = _get(f'{DDRAGON_BASE}/api/versions.json')
    ver = versions[0]
    _cached_set('ddragon_version', ver)
    return ver

TAG_TO_CLASS = {
    'Fighter' : '브루저',
    'Tank'    : '탱커',
    'Mage'    : '마법사',
    'Assassin': '암살자',
    'Marksman': '원거리딜러',
    'Support' : '서포터',
}

ARENA_ITEMS = {
    663039: "아트마의 심판",    663056: "불사대마왕의 왕관",
    663058: "용암의 방패",      663060: "신성의 검",
    663172: "서풍",             664011: '꽃피는 새벽의 검',
    664644: '부서진 여왕의 왕관', 667101: '도박꾼의 칼날',
    667109: '잔혹 행위',        667112: '살점포식자',
    663059: '별빛밤 망토',      4636:   '밤의 수확자',
    663146: '마법공학 총검',
}

ARENA_LEGENDARY_ITEMS = {3193: '가고일 돌갑옷'}

FORCE_LEGENDARY_ITEMS = {
    3031: '무한의 대검',
    3089: '라바돈의 죽음모자',
    3193: '가고일 돌갑옷',
}

ARAM_ITEMS = {
    2051: '수호자의 뿔피리',
    3112: '수호자의 보주',
    3177: '수호자의 검',
    3184: '수호자의 망치',
}

EXCLUDE_ITEM_IDS_HARD = {663074, 3011}
EXCLUDE_ITEM_IDS = set(ARENA_ITEMS.keys()) | set(ARAM_ITEMS.keys()) | EXCLUDE_ITEM_IDS_HARD


def _item_type(item: dict, item_id: int = 0):
    tags  = item.get('tags', [])
    depth = item.get('depth', 1)
    maps  = item.get('maps', {})

    if item_id in EXCLUDE_ITEM_IDS_HARD:
        return None
    if item_id in ARENA_LEGENDARY_ITEMS:
        return 'arena_legendary'
    if item_id in FORCE_LEGENDARY_ITEMS:
        return 'legendary'
    if item_id in ARENA_ITEMS:
        return 'arena'
    if item_id in ARAM_ITEMS:
        return 'aram'
    if item_id in EXCLUDE_ITEM_IDS:
        return None
    if not maps.get('11', True):
        return None
    if item.get('requiredChampion') or item.get('requiredAlly'):
        return None
    if 'Consumable' in tags or 'Trinket' in tags or 'Boots' in tags:
        return None
    if 'Mythic' in tags or (depth and depth >= 3):
        return 'legendary'
    if depth and depth == 2:
        return 'entry'
    if depth and depth == 1 and item.get('gold', {}).get('purchasable', False):
        return 'entry'
    return None

def infoPageRender(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '잘못된 메서드입니다.'}, status=405)
    try:
        return render(request, 'riot_infoPage.html')
    except Exception as e:
        print(f'[INFO PAGE] -> {e}')
        return JsonResponse({'success': False, 'message': f'오류: {e}'}, status=400)


def info_dd_version(request):
    try:
        ver = _dd_version()
        return JsonResponse({'success': True, 'version': ver})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def info_cache_clear(request):
    try:
        cleared = []
        mapping_sig  = str(
            sorted(EXCLUDE_ITEM_IDS_HARD) + sorted(ARENA_LEGENDARY_ITEMS)
            + sorted(FORCE_LEGENDARY_ITEMS) + sorted(ARENA_ITEMS) + sorted(ARAM_ITEMS)
        )
        mapping_hash = hashlib.md5(mapping_sig.encode()).hexdigest()[:8]

        keys_to_delete = []
        for lang in ['ko_KR', 'en_US']:
            keys_to_delete += [
                f'info_lol_items_{lang}',
                f'info_lol_items_{lang}_{mapping_hash}',
                f'info_lol_champs_{lang}',
                f'info_tft_champs_{lang}',
                f'info_tft_items_{lang}',
                f'info_tft_augments_{lang}',
            ]
            for h in ['00000000', 'aaaaaaaa', 'ffffffff']:
                keys_to_delete.append(f'info_lol_items_{lang}_{h}')
        keys_to_delete += ['ddragon_version', 'cdragon_tft_ko_kr']

        for key in keys_to_delete:
            _cached_delete(key)
            cleared.append(key)

        _MEM_CACHE.clear()
        return JsonResponse({'success': True, 'cleared': cleared, 'count': len(cleared)})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
def info_lol_champions(request):
    lang      = request.GET.get('lang', 'ko_KR')
    cache_key = f'info_lol_champs_{lang}'

    cached = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)
    try:
        from .models import LOL_infoChampionTable
        qs = LOL_infoChampionTable.objects.all()
        if qs.exists():
            champs  = [obj.to_dict() for obj in qs.order_by('name')]
            ver     = qs.first().patch_version
            result  = {'success': True, 'version': ver, 'champions': champs}
            _cached_set(cache_key, result, version=ver)
            return JsonResponse(result)
    except Exception as e:
        print(f'[INFO LOL CHAMPS] DB 조회 오류: {e}')
    try:
        ver  = _dd_version()
        data = _get(f'{DDRAGON_BASE}/cdn/{ver}/data/{lang}/champion.json')
        champs = _table_champions_lol(lang, ver, data)
        result = {'success': True, 'version': ver, 'champions': champs}
        _cached_set(cache_key, result, version=ver)
        return JsonResponse(result)
    except Exception as e:
        print(f'[INFO LOL CHAMPS] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def info_lol_items(request):
    lang         = request.GET.get('lang', 'ko_KR')
    mapping_sig  = str(
        sorted(EXCLUDE_ITEM_IDS_HARD) + sorted(ARENA_LEGENDARY_ITEMS)
        + sorted(FORCE_LEGENDARY_ITEMS) + sorted(ARENA_ITEMS) + sorted(ARAM_ITEMS)
    )
    mapping_hash = hashlib.md5(mapping_sig.encode()).hexdigest()[:8]
    cache_key    = f'info_lol_items_{lang}_{mapping_hash}'

    cached = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)
    try:
        from .models import LOL_infoItemTable
        qs = LOL_infoItemTable.objects.filter(mapping_hash=mapping_hash)
        if qs.exists():
            type_order = {'legendary': 0, 'arena_legendary': 1, 'arena': 2, 'aram': 3, 'entry': 4}
            items  = sorted(
                [obj.to_dict() for obj in qs],
                key=lambda x: (type_order.get(x['type'], 9), -x['gold'])
            )
            ver    = qs.first().patch_version
            result = {'success': True, 'version': ver, 'items': items}
            _cached_set(cache_key, result, version=ver)
            return JsonResponse(result)
    except Exception as e:
        print(f'[INFO LOL ITEMS] DB 조회 오류: {e}')
    try:
        ver   = _dd_version()
        data  = _get(f'{DDRAGON_BASE}/cdn/{ver}/data/{lang}/item.json')
        items = _table_items_lol(lang, ver, mapping_hash, data)
        result = {'success': True, 'version': ver, 'items': items}
        _cached_set(cache_key, result, version=ver)
        return JsonResponse(result)
    except Exception as e:
        print(f'[INFO LOL ITEMS] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def info_tft_champions(request):
    lang      = request.GET.get('lang', 'ko_KR')
    cache_key = f'info_tft_champs_{lang}'

    cached = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)

    # 전용 DB 테이블 확인
    try:
        from .models import TFT_infoChampionTable
        qs = TFT_infoChampionTable.objects.filter(set_number=16)
        if qs.exists():
            champs = sorted(
                [obj.to_dict() for obj in qs],
                key=lambda x: (x['cost'], x['name'])
            )
            result = {'success': True, 'champions': champs}
            _cached_set(cache_key, result)
            return JsonResponse(result)
    except Exception as e:
        print(f'[INFO TFT CHAMPS] DB 조회 오류: {e}')

    try:
        cd_data = _get_cdragon(
            'https://raw.communitydragon.org/latest/cdragon/tft/ko_kr.json',
            'cdragon_tft_ko_kr'
        )
        champs = _table_champions_tft(cd_data)
        result = {'success': True, 'champions': champs}
        _cached_set(cache_key, result)
        return JsonResponse(result)
    except Exception as e:
        print(f'[INFO TFT CHAMPS] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def info_tft_items(request):
    lang      = request.GET.get('lang', 'ko_KR')
    cache_key = f'info_tft_items_{lang}'

    cached = _cached_get(cache_key)
    if cached:
        return JsonResponse(cached)

    # 전용 DB 테이블 확인
    try:
        from .models import TFT_infoItemTable
        qs = TFT_infoItemTable.objects.filter(set_number=16)
        if qs.exists():
            type_order = {'component': 0, 'combined': 1, 'radiant': 2, 'emblem': 3, 'artifact': 4}
            items = sorted(
                [obj.to_dict() for obj in qs],
                key=lambda x: (type_order.get(x['type'], 9), x['name'])
            )
            result = {'success': True, 'items': items}
            _cached_set(cache_key, result)
            return JsonResponse(result)
    except Exception as e:
        print(f'[INFO TFT ITEMS] DB 조회 오류: {e}')

    # 외부 API → DB 테이블 upsert
    try:
        cd_data = _get_cdragon(
            'https://raw.communitydragon.org/latest/cdragon/tft/ko_kr.json',
            'cdragon_tft_ko_kr'
        )
        items = _table_items_tft(cd_data)
        result = {'success': True, 'items': items}
        _cached_set(cache_key, result)
        return JsonResponse(result)
    except Exception as e:
        print(f'[INFO TFT ITEMS] {e}')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
def info_tft_augments(request):
    lang      = request.GET.get('lang', 'ko_KR')
    cache_key = f'info_tft_augments_{lang}'
    cached    = _cached_get(cache_key)
    if cached and cached.get('total', 0) > 0:
        return JsonResponse(cached)

    try:
        cd_data   = _get_cdragon(
            'https://raw.communitydragon.org/latest/cdragon/tft/ko_kr.json',
            'cdragon_tft_ko_kr'
        )
        all_items = cd_data.get('items', [])
        print(f'[INFO TFT AUGMENTS] 전체 items 수: {len(all_items)}', flush=True)

        _SUFFIX_RE = re.compile(r'(\d)$')

        def infer_tier(item) -> int:
            raw = item.get('tier')
            if isinstance(raw, (int, float)) and int(raw) in (1, 2, 3):
                return int(raw)
            if isinstance(raw, str) and raw.isdigit() and int(raw) in (1, 2, 3):
                return int(raw)
            api = item.get('apiName', '')
            m   = _SUFFIX_RE.search(api)
            if m:
                n = int(m.group(1))
                if n in (1, 2, 3):
                    return n
            return 1

        TIER_LABEL = {1: 'silver', 2: 'gold', 3: 'prismatic'}
        TIER_KO    = {1: '실버',   2: '골드',  3: '프리즘'}
        tier_dist  = {1: 0, 2: 0, 3: 0}

        augments = []
        for item in all_items:
            api  = item.get('apiName', '')
            name = item.get('name', '')
            if not api.startswith('TFT16_') or 'Augment' not in api:
                continue
            if not name or '@' in name or len(name) < 2:
                continue
            icon = item.get('icon', '')
            if not icon:
                continue

            tier_num = infer_tier(item)
            tier_dist[tier_num] = tier_dist.get(tier_num, 0) + 1
            augments.append({
                'id'     : api,
                'name'   : name,
                'tier'   : TIER_LABEL[tier_num],
                'tierKo' : TIER_KO[tier_num],
                'tierNum': tier_num,
                'desc'   : _clean_tft_desc(item.get('desc', ''), max_len=400),
                'img'    : _tc_img(icon),
            })

        print(
            f'[INFO TFT AUGMENTS] 추출: {len(augments)}개 '
            f'| 실버: {tier_dist[1]} 골드: {tier_dist[2]} 프리즘: {tier_dist[3]}',
            flush=True
        )
        augments.sort(key=lambda x: (x['tierNum'], x['name']))
        seen, unique = set(), []
        for a in augments:
            if a['name'] not in seen:
                seen.add(a['name'])
                unique.append(a)

        print(f'[INFO TFT AUGMENTS] 중복 제거 후: {len(unique)}개', flush=True)

        result = {'success': True, 'augments': unique, 'total': len(unique)}
        if unique:
            _cached_set(cache_key, result)
        else:
            print('[INFO TFT AUGMENTS] 결과 0개 — 캐싱 생략', flush=True)
        return JsonResponse(result)

    except Exception as e:
        print(f'[INFO TFT AUGMENTS] 실패: {type(e).__name__}: {e}', flush=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
