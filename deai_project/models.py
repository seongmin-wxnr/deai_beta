from django.db import models
from django.utils import timezone

class BaseUserInformation_data(models.Model):
    email      = models.EmailField(unique=True, verbose_name='이메일', max_length=254)
    username   = models.CharField(max_length=30, unique=True, verbose_name='닉네임')
    password   = models.CharField(max_length=256, verbose_name='비밀번호')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='가입일')  
    is_active  = models.BooleanField(default=True, verbose_name='활성 여부')
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'user_info'

    def __str__(self):
        return f'{self.username} ({self.email})'
    
class UserPreferGame(models.Model):

    user = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='prefer_games',
        verbose_name='유저'
    )

    GAME_CHOICES = [
        ('lol',     '리그 오브 레전드'),
        ('val',     '발로란트'),
        ('ow',      '오버워치 2'),
        ('fifa',    '피파 온라인 4'),
        ('genshin', '원신'),
    ]
    game_id = models.CharField(max_length=10, choices=GAME_CHOICES, verbose_name='게임')

    name_tag      = models.CharField(max_length=50, verbose_name='Name#Tag')
    tier          = models.CharField(max_length=20, blank=True, verbose_name='티어')
    score_best    = models.IntegerField(default=0, verbose_name='최고 점수')
    score_current = models.IntegerField(default=0, verbose_name='현재 점수')
    sub_info      = models.CharField(max_length=30, blank=True, verbose_name='포지션/역할')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table     = 'user_prefer_game'
        unique_together = ('user', 'game_id')

    def __str__(self):
        return f'{self.user.username} - {self.game_id}'

class Post_Community(models.Model):
    user = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='posts',
        verbose_name='작성자'
    )

    GAME_CHOICES = [
        ('lol',     '리그 오브 레전드'),
        ('val',     '발로란트'),
        ('ow',      '오버워치 2'),
        ('fifa',    '피파 온라인 4'),
        ('genshin', '원신'),
    ]
    game_id   = models.CharField(max_length=10, choices=GAME_CHOICES, verbose_name='게임')

    post_title     = models.CharField(max_length=100, verbose_name='제목')
    post_body      = models.TextField(blank=True, verbose_name='한마디')

    current_member = models.IntegerField(default=1, verbose_name='현재 인원')
    total_member   = models.IntegerField(default=5, verbose_name='모집 인원')
    tier_condition = models.CharField(max_length=20, default='무관', verbose_name='티어 조건')

    is_open        = models.BooleanField(default=True, verbose_name='모집 중')
    post_upload_at = models.DateTimeField(auto_now_add=True, verbose_name='작성일')

    class Meta:
        db_table = 'user_post_circuit'
        ordering = ['-post_upload_at'] 

    def __str__(self):
        return f'[{self.game_id}] {self.post_title} - {self.user.username}'
    
class PostParticipant(models.Model):
    post = models.ForeignKey(
        Post_Community,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name='게시글'
    )
    user = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='joined_posts',
        verbose_name='참여자'
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_participant'
        unique_together = ('post', 'user')

    def __str__(self):
        return f'{self.user.username} → {self.post.post_title}'

class Friendship(models.Model):
    STATUS_CHOICES = [
        ('pending',  '대기 중'),
        ('accepted', '수락됨'),
        ('rejected', '거절됨'),
    ]

    from_user = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='sent_requests',
        verbose_name='요청자'
    )
    to_user = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='received_requests',
        verbose_name='수신자'
    )
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table     = 'friendship'
        unique_together = ('from_user', 'to_user')

    def __str__(self):
        return f'{self.from_user.username} → {self.to_user.username} ({self.status})'
    
class ChatMessage(models.Model):
    post    = models.ForeignKey(
        Post_Community,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    user     = models.ForeignKey(
        BaseUserInformation_data,
        on_delete=models.CASCADE,
        related_name='chat_messages'
    )
    message  = models.TextField()
    sent_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'chat_message'
        ordering  = ['sent_at']

    def __str__(self):
        return f'[{self.post_id}] {self.user.username}: {self.message[:20]}'

class JoinRequest(models.Model):
    STATUS_CHOICES = [
        ('pending',  '대기 중'),
        ('accepted', '수락됨'),
        ('rejected', '거절됨'),
    ]
    post       = models.ForeignKey(Post_Community, on_delete=models.CASCADE, related_name='join_requests')
    user       = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='join_requests')
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table       = 'join_request'
        unique_together = ('post', 'user')

    def __str__(self):
        return f'{self.user.username} → {self.post.post_title} ({self.status})'
    
class Notification(models.Model):
    TYPE_CHOICES = [
        ('join_request', '가입 요청'),
        ('join_accept',  '가입 수락'),
        ('join_reject',  '가입 거절'),
    ]
    user       = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='notifications')
    type       = models.CharField(max_length=20, choices=TYPE_CHOICES)
    message    = models.CharField(max_length=200)
    is_read    = models.BooleanField(default=False)
    related_join_request = models.ForeignKey(
        JoinRequest, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} - {self.type}'

class DirectMessage(models.Model):
    sender   = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='sent_dms')
    receiver = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='received_dms')
    message  = models.TextField()
    sent_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'direct_message'
        ordering = ['sent_at']

    def __str__(self):
        return f'{self.sender.username} → {self.receiver.username}: {self.message[:20]}'

class UserReport(models.Model):
    reporter = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='reports_sent')
    reported = models.ForeignKey(BaseUserInformation_data, on_delete=models.CASCADE, related_name='reports_received')
    category = models.CharField(max_length=50)
    status    = models.CharField(max_length=20, default='pending')
    detail   = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_report'

# ## riot api search user cache table

class Riot_UserINFO(models.Model):
    """
    Riot 유저 기본 정보 캐시 테이블.
    puuid 기준으로 유저를 식별하며, 마지막 조회 시각을 함께 저장합니다.
    한 유저가 LOL / TFT / VAL 3개 게임을 모두 플레이하는 경우,
    Riot_MatchInfo 와 1:N 관계로 게임별 큐 정보를 별도 저장합니다.
    """

    puuid    = models.CharField(
        max_length=120, unique=True, db_index=True,
        verbose_name='PUUID'
    )
    username = models.CharField(
        max_length=40, db_index=True,
        verbose_name='게임 이름 (gameName)'
    )
    tag      = models.CharField(
        max_length=10,
        verbose_name='태그 라인 (#tagLine)'
    )
    region   = models.CharField(
        max_length=10, default='kr',
        verbose_name='지역 (kr / na / euw …)'
    )

    # Summoner API 필드 - 재검색 시 API 호출 없음 달성에 필요
    summoner_id     = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='소환사 ID (encrypted)'
    )
    profile_icon_id = models.IntegerField(
        default=0,
        verbose_name='프로필 아이콘 ID'
    )
    summoner_level  = models.IntegerField(
        default=0,
        verbose_name='소환사 레벨'
    )

    # 마지막 조회 시각 (save() 호출 시 auto_now 갱신)
    last_searched_at = models.DateTimeField(
        auto_now=True,
        verbose_name='마지막 조회 시각'
    )

    class Meta:
        db_table     = 'riot_user_info'
        verbose_name = 'Riot 유저 정보 캐시'

    def __str__(self):
        return f'{self.username}#{self.tag} ({self.puuid[:12]}…) [{self.last_searched_at:%Y-%m-%d %H:%M}]'

    @classmethod
    def get_or_none(cls, puuid: str):
        try:
            return cls.objects.get(puuid=puuid)
        except cls.DoesNotExist:
            return None

    @classmethod
    def find_by_name_tag(cls, username: str, tag: str, region: str):
        """이름#태그로 유저 조회 (대소문자 무시)."""
        return cls.objects.filter(
            username__iexact=username,
            tag__iexact=tag,
            region=region,
        ).first()

    @classmethod
    def upsert(cls, puuid: str, username: str, tag: str, region: str = 'kr',
               summoner_id: str = '', profile_icon_id: int = 0,
               summoner_level: int = 0):
        """
        유저 정보 저장/갱신.
        update_or_create 는 auto_now(last_searched_at)를 갱신하지 않으므로
        get_or_create + save() 로 처리합니다.
        summoner 필드는 값이 있을 때만 덮어씁니다 (0/빈 문자열 → 기존 값 유지).
        """
        obj, created = cls.objects.get_or_create(
            puuid=puuid,
            defaults={
                'username'        : username,
                'tag'             : tag,
                'region'          : region,
                'summoner_id'     : summoner_id,
                'profile_icon_id' : profile_icon_id,
                'summoner_level'  : summoner_level,
            }
        )
        if not created:
            obj.username = username
            obj.tag      = tag
            obj.region   = region
            if summoner_id:
                obj.summoner_id = summoner_id
            if profile_icon_id:
                obj.profile_icon_id = profile_icon_id
            if summoner_level:
                obj.summoner_level = summoner_level
            obj.save()  # auto_now(last_searched_at) 갱신
        return obj


class Riot_MatchInfo(models.Model):
    # 유저별 게임별 큐타입별 전적 캐시 테이블.

    # 게임 종류(game)와 큐 타입(queue_type) 조합으로 데이터를 구분합니다.
    # 한 유저가 여러 게임을 동시에 플레이하면 game 값만 다른 row 여러 개가 생성됩니다.

    # LoL 큐 ID : 420(솔로랭크) / 440(자유랭크) / 430(일반) / 450(칼바람)
    # 900(우르프) / 1700(아레나) 등
    # TFT 큐 ID : 1100(솔로랭크) / 1160(더블업) / 1090(일반)
    # VAL 큐 ID : Riot VAL API는 공개 불가 문자열 슬러그로 관리
    GAME_CHOICES = [
        ('lol', 'League of Legends'),
        ('tft', 'Teamfight Tactics'),
        ('val', 'Valorant'),
    ]

    QUEUE_CHOICES = [
        # LoL
        ('lol_ranked_solo',    'LoL 솔로랭크'),
        ('lol_ranked_flex',    'LoL 자유랭크'),
        ('lol_normal',         'LoL 일반'),
        ('lol_aram',           'LoL 칼바람'),
        ('lol_urf',            'LoL 우르프'),
        ('lol_arena',          'LoL 아레나'),
        # TFT
        ('tft_ranked',         'TFT 솔로랭크'),
        ('tft_double_up',      'TFT 더블업'),
        ('tft_normal',         'TFT 일반'),
        # Valorant
        ('val_competitive',    'Valorant 경쟁전'),
        ('val_unrated',        'Valorant 일반(비경쟁)'),
        ('val_spike_rush',     'Valorant 스파이크 러쉬'),
        ('val_deathmatch',     'Valorant 데스매치'),
        ('val_team_deathmatch','Valorant 팀 데스매치'),
    ]

    LOL_QUEUE_ID_MAP = {
        420 : 'lol_ranked_solo',
        440 : 'lol_ranked_flex',
        430 : 'lol_normal',
        450 : 'lol_aram',
        900 : 'lol_urf',
        1700: 'lol_arena',
    }
    TFT_QUEUE_ID_MAP = {
        1100: 'tft_ranked',
        1160: 'tft_double_up',
        1090: 'tft_normal',
    }

    user = models.ForeignKey(
        Riot_UserINFO,
        on_delete=models.CASCADE,
        related_name='match_infos',
        verbose_name='Riot 유저'
    )
    game       = models.CharField(max_length=5,  choices=GAME_CHOICES,  verbose_name='게임 종류')
    queue_type = models.CharField(max_length=25, choices=QUEUE_CHOICES, verbose_name='큐 타입')

    # 가장 최근 경기 ID (전적 갱신 기준점)
    last_match_id = models.CharField(
        max_length=30, blank=True, default='',
        verbose_name='최근 매치 ID'
    )
    # 최근 20게임 match_id 목록 (순서 보존)
    match_ids = models.JSONField(
        default=list, blank=True,
        verbose_name='전적 매치 ID 목록 (최대 20개)'
    )
    # 랭크 등 기타 캐시 데이터
    cached_data = models.JSONField(
        default=dict, blank=True,
        verbose_name='캐시 데이터 (JSON)'
    )
    # 마지막 전적 갱신 시각 (갱신 버튼 3분 쿨다운 기준)
    last_refresh_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='마지막 전적 갱신 시각'
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table        = 'riot_match_info'
        verbose_name    = 'Riot 전적 캐시'
        unique_together = ('user', 'game', 'queue_type')
        indexes = [
            models.Index(fields=['user', 'game']),
        ]

    def __str__(self):
        return (
            f'{self.user.username}#{self.user.tag} '
            f'[{self.get_game_display()} / {self.get_queue_type_display()}] '
            f'{self.updated_at:%Y-%m-%d %H:%M}'
        )

    def can_refresh(self, cooldown_seconds: int = 180) -> bool:
        """갱신 쿨다운(기본 3분) 경과 여부."""
        if self.last_refresh_at is None:
            return True
        from datetime import timedelta
        return timezone.now() - self.last_refresh_at >= timedelta(seconds=cooldown_seconds)

    def seconds_until_refresh(self, cooldown_seconds: int = 180) -> int:
        """갱신까지 남은 초. 0이면 즉시 가능."""
        if self.last_refresh_at is None:
            return 0
        from datetime import timedelta
        elapsed   = (timezone.now() - self.last_refresh_at).total_seconds()
        remaining = cooldown_seconds - elapsed
        return max(0, int(remaining))

    @classmethod
    def queue_slug_from_id(cls, game: str, queue_id: int):
        mapping = cls.LOL_QUEUE_ID_MAP if game == 'lol' else cls.TFT_QUEUE_ID_MAP
        return mapping.get(queue_id)

    @classmethod
    def upsert(cls, user, game: str, queue_type: str,
               cached_data: dict = None, last_match_id: str = '',
               match_ids: list = None, touch_refresh: bool = False):
        """
        게임·큐 조합 기준으로 캐시 저장/갱신.
        touch_refresh=True 이면 last_refresh_at 을 현재 시각으로 갱신합니다.
        update_or_create 는 auto_now(updated_at)를 갱신하지 않으므로 save() 직접 호출.
        """
        obj, created = cls.objects.get_or_create(
            user=user,
            game=game,
            queue_type=queue_type,
            defaults={
                'cached_data'    : cached_data if cached_data is not None else {},
                'last_match_id'  : last_match_id,
                'match_ids'      : match_ids if match_ids is not None else [],
                'last_refresh_at': timezone.now() if touch_refresh else None,
            }
        )
        if not created:
            update_fields = ['cached_data', 'last_match_id', 'match_ids', 'updated_at']
            obj.cached_data   = cached_data if cached_data is not None else {}
            obj.last_match_id = last_match_id
            if match_ids is not None:
                obj.match_ids = match_ids
            if touch_refresh:
                obj.last_refresh_at = timezone.now()
                update_fields.append('last_refresh_at')
            obj.save(update_fields=update_fields)
        return obj

    @classmethod
    def get_by_user_game(cls, user, game: str):
        return cls.objects.filter(user=user, game=game)


# ## riot api info page cache table

class RiotDataCache(models.Model):
    """
    API 응답 JSON을 통째로 저장하는 범용 캐시 테이블.
    cache_key 예시:
      info_lol_champs_ko_KR
      info_lol_items_ko_KR_<hash>
      info_tft_champs_ko_KR
      info_tft_items_ko_KR
      cdragon_tft_ko_kr
      ddragon_version
    """
    cache_key   = models.CharField(max_length=120, unique=True, db_index=True,
                                   verbose_name='캐시 키')
    data        = models.JSONField(verbose_name='JSON 데이터')
    version     = models.CharField(max_length=20, blank=True, default='',
                                   verbose_name='데이터 버전(패치)')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='최초 저장')
    updated_at  = models.DateTimeField(auto_now=True,     verbose_name='최근 갱신')
    expires_at  = models.DateTimeField(null=True, blank=True,
                                       verbose_name='만료 시각 (null=영구)')

    class Meta:
        db_table     = 'riot_data_cache'
        verbose_name = 'Riot 데이터 캐시'

    def __str__(self):
        return f'{self.cache_key} (v{self.version}, {self.updated_at:%Y-%m-%d %H:%M})'

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @classmethod
    def get(cls, key: str):
        """캐시 조회. 없거나 만료됐으면 None 반환."""
        try:
            obj = cls.objects.get(cache_key=key)
            if obj.is_expired():
                return None
            return obj.data
        except cls.DoesNotExist:
            return None

    @classmethod
    def set(cls, key: str, data, version: str = '', ttl_hours: int = 6):
        """캐시 저장/갱신."""
        from datetime import timedelta
        expires = timezone.now() + timedelta(hours=ttl_hours) if ttl_hours else None
        cls.objects.update_or_create(
            cache_key=key,
            defaults={
                'data'      : data,
                'version'   : version,
                'expires_at': expires,
            }
        )

    @classmethod
    def delete_key(cls, key: str):
        cls.objects.filter(cache_key=key).delete()

class RankingSnapshot(models.Model):
    GAME_CHOICES = [
        ('lol', 'League of Legends'),
        ('tft', 'Teamfight Tactics'),
    ]
    QUEUE_CHOICES = [
        ('RANKED_SOLO_5x5',        'LoL 솔로랭크'),
        ('RANKED_FLEX_SR',         'LoL 자유랭크'),
        ('RANKED_TFT',             'TFT 솔로'),
        ('RANKED_TFT_DOUBLE_UP',   'TFT 더블업'),
    ]

    game       = models.CharField(max_length=5,  choices=GAME_CHOICES)
    queue      = models.CharField(max_length=30, choices=QUEUE_CHOICES)
    collected_at = models.DateTimeField(default=timezone.now, verbose_name='수집 시각')
    is_active  = models.BooleanField(default=True, verbose_name='활성 스냅샷')

    class Meta:
        db_table = 'c_ranking_snapshot'
        indexes  = [models.Index(fields=['game', 'queue', 'is_active'])]

    def __str__(self):
        return f'[{self.game}/{self.queue}] {self.collected_at:%Y-%m-%d %H:%M} active={self.is_active}'


class RankingEntry(models.Model):
    snapshot    = models.ForeignKey(
        RankingSnapshot, on_delete=models.CASCADE, related_name='entries'
    )
    rank        = models.PositiveIntegerField(verbose_name='순위')
    summoner_id = models.CharField(max_length=100, blank=True)
    puuid       = models.CharField(max_length=100, blank=True, db_index=True)
    name        = models.CharField(max_length=80,  default='?')
    tag_line    = models.CharField(max_length=20,  blank=True)
    icon_id     = models.PositiveIntegerField(default=1)
    level       = models.PositiveIntegerField(default=1)
    tier        = models.CharField(max_length=20)
    division    = models.CharField(max_length=4, blank=True)
    rank_label  = models.CharField(max_length=30)
    lp          = models.IntegerField(default=0)
    wins        = models.IntegerField(default=0)
    losses      = models.IntegerField(default=0)
    winrate     = models.IntegerField(default=0)
    hot_streak  = models.BooleanField(default=False)
    veteran     = models.BooleanField(default=False)
    fresh_blood = models.BooleanField(default=False)

    class Meta:
        db_table = 'c_userTable'
        ordering = ['rank']
        indexes  = [models.Index(fields=['snapshot', 'rank'])]

    def __str__(self):
        return f'#{self.rank} {self.name}#{self.tag_line} {self.tier} {self.lp}LP'

    def to_dict(self) -> dict:
        return {
            'rank': self.rank,
            'summonerId': self.summoner_id,
            'puuid': self.puuid,
            'name': self.name,
            'tagLine': self.tag_line,
            'iconId': self.icon_id,
            'level': self.level,
            'tier': self.tier,
            'division': self.division,
            'rankLabel' : self.rank_label,
            'lp': self.lp,
            'wins': self.wins,
            'losses': self.losses,
            'winrate': self.winrate,
            'hotStreak' : self.hot_streak,
            'veteran': self.veteran,
            'freshBlood': self.fresh_blood,
        }

class LOL_infoChampionTable(models.Model):
    champion_id= models.CharField(max_length=50, unique=True, db_index=True,
                                      verbose_name='챔피언 키(DDragon id)')  # e.g. "Ahri"
    name= models.CharField(max_length=50, verbose_name='챔피언 이름')
    title= models.CharField(max_length=100, blank=True, verbose_name='타이틀')
    primary_class  = models.CharField(max_length=20, verbose_name='주 포지션')
    tags= models.JSONField(default=list, verbose_name='태그 목록')  # ["마법사", "암살자"]
    blurb= models.TextField(blank=True, verbose_name='설명')
    img_url= models.CharField(max_length=200, verbose_name='아이콘 URL')
    splash_url= models.CharField(max_length=200, blank=True, verbose_name='스플래시 URL')
    patch_version  = models.CharField(max_length=20, verbose_name='패치 버전')
    updated_at= models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table= 'lol_info_champion'
        verbose_name = 'LoL 챔피언 정보'
        ordering= ['name']

    def __str__(self):
        return f'{self.name} ({self.champion_id})'

    def to_dict(self) -> dict:
        return {
            'id': self.champion_id,
            'name': self.name,
            'title' : self.title,
            'class' : self.primary_class,
            'tags': self.tags,
            'blurb': self.blurb,
            'img': self.img_url,
            'splash': self.splash_url,
        }


class LOL_infoItemTable(models.Model):
    ITEM_TYPE_CHOICES = [
        ('legendary','레전더리'),
        ('arena_legendary', '아레나 레전더리'),
        ('arena','아레나 전용'),
        ('aram','칼바람 전용'),
        ('entry','중간/기본 아이템'),
    ]

    item_id= models.IntegerField(unique=True, db_index=True, verbose_name='아이템 ID')
    name= models.CharField(max_length=100, verbose_name='아이템 이름')
    item_type= models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, verbose_name='아이템 종류')
    stats= models.CharField(max_length=300, blank=True, verbose_name='스탯 텍스트')
    stats_detail= models.JSONField(default=dict, verbose_name='스탯 상세 (dict)')
    desc= models.CharField(max_length=200, blank=True, verbose_name='짧은 설명')
    full_desc= models.TextField(blank=True, verbose_name='전체 설명')
    gold= models.IntegerField(default=0, verbose_name='구매 가격')
    gold_sell= models.IntegerField(default=0, verbose_name='판매 가격')
    img_url= models.CharField(max_length=200, verbose_name='아이콘 URL')
    from_ids= models.JSONField(default=list, verbose_name='조합 재료 ID 목록')
    into_ids= models.JSONField(default=list, verbose_name='합성 결과 ID 목록')
    patch_version= models.CharField(max_length=20, verbose_name='패치 버전')
    mapping_hash= models.CharField(max_length=8, default='', verbose_name='매핑 해시')
    updated_at= models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table= 'lol_info_item'
        verbose_name = 'LoL 아이템 정보'
        ordering= ['item_type', '-gold']

    def __str__(self):
        return f'{self.name} (#{self.item_id}, {self.item_type})'

    def to_dict(self) -> dict:
        return {
            'id' : self.item_id,
            'name': self.name,
            'type': self.item_type,
            'stats': self.stats,
            'stats_detail': self.stats_detail,
            'desc': self.desc,
            'full_desc': self.full_desc,
            'gold': self.gold,
            'gold_sell': self.gold_sell,
            'img': self.img_url,
            'from_ids': self.from_ids,
            'into_ids': self.into_ids,
        }
class VAL_infoAgentTable(models.Model):
    """
    Valorant 에이전트 정보 테이블.
    """
    ROLE_CHOICES = [
        ('duelist',    '듀얼리스트'),
        ('initiator',  '개시자'),
        ('controller', '컨트롤러'),
        ('sentinel',   '파수꾼'),
    ]

    agent_uuid     = models.CharField(max_length=50, unique=True, db_index=True,
                                      verbose_name='에이전트 UUID')
    name           = models.CharField(max_length=50, verbose_name='에이전트 이름')
    role           = models.CharField(max_length=20, choices=ROLE_CHOICES,
                                      blank=True, verbose_name='역할군')
    description    = models.TextField(blank=True, verbose_name='설명')
    portrait_url   = models.CharField(max_length=300, blank=True, verbose_name='포트레이트 URL')
    icon_url       = models.CharField(max_length=300, blank=True, verbose_name='아이콘 URL')
    # 스킬 4개를 JSON으로 저장 (C/Q/E/X)
    abilities      = models.JSONField(default=list, verbose_name='스킬 목록')
    updated_at     = models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table     = 'val_info_agent'
        verbose_name = 'Valorant 에이전트 정보'
        ordering     = ['name']

    def __str__(self):
        return f'{self.name} ({self.role})'

    def to_dict(self) -> dict:
        return {
            'id'         : self.agent_uuid,
            'name'       : self.name,
            'role'       : self.role,
            'description': self.description,
            'portrait'   : self.portrait_url,
            'icon'       : self.icon_url,
            'abilities'  : self.abilities,
        }


class Val_infoGunTable(models.Model):
    CATEGORY_CHOICES = [
        ('sidearm', '보조무기'),
        ('smg',     'SMG'),
        ('rifle',   '소총'),
        ('sniper',  '저격총'),
        ('shotgun', '샷건'),
        ('heavy',   '중화기'),
        ('melee',   '근접무기'),
    ]

    gun_uuid  = models.CharField(max_length=50, unique=True, db_index=True,
                                     verbose_name='총기 UUID')
    name = models.CharField(max_length=50, verbose_name='총기 이름')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES,
                                     blank=True, verbose_name='카테고리')
    cost = models.IntegerField(default=0, verbose_name='가격')
    fire_rate = models.FloatField(default=0, verbose_name='연사속도')
    magazine_size = models.IntegerField(default=0, verbose_name='탄창')
    damage_ranges = models.JSONField(default=list, verbose_name='데미지 정보')
    icon_url= models.CharField(max_length=300, blank=True, verbose_name='아이콘 URL')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table = 'val_info_gun'
        verbose_name = 'Valorant 총기 정보'
        ordering = ['category', 'cost']

    def __str__(self):
        return f'{self.name} ({self.category}, {self.cost}크레딧)'

    def to_dict(self) -> dict:
        return {
            'id': self.gun_uuid,
            'name': self.name,
            'category': self.category,
            'cost': self.cost,
            'fireRate': self.fire_rate,
            'magazineSize': self.magazine_size,
            'damageRanges': self.damage_ranges,
            'icon': self.icon_url,
        }


class TFT_infoChampionTable(models.Model):
    api_name = models.CharField(max_length=80, unique=True, db_index=True,
                                  verbose_name='apiName (CDragon)')
    name = models.CharField(max_length=50, verbose_name='챔피언 이름')
    cost = models.PositiveSmallIntegerField(verbose_name='코스트')  # 1~5, 7=특수
    traits= models.JSONField(default=list, verbose_name='시너지 목록')
    img_url= models.CharField(max_length=300, blank=True, verbose_name='아이콘 URL')
    set_number= models.PositiveSmallIntegerField(default=16, verbose_name='시즌 세트 번호')
    updated_at= models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table     = 'tft_info_champion'
        verbose_name = 'TFT 챔피언 정보'
        ordering     = ['cost', 'name']

    def __str__(self):
        return f'{self.name} (코스트 {self.cost})'

    def to_dict(self) -> dict:
        return {
            'id': self.api_name,
            'name': self.name,
            'cost': self.cost,
            'traits': self.traits,
            'img': self.img_url,
        }


class TFT_infoItemTable(models.Model):

    ITEM_TYPE_CHOICES = [
        ('component','기본 부품'),
        ('combined', '조합 아이템'),
        ('radiant', '찬란한 아이템'),
        ('emblem', '시너지 상징'),
        ('artifact','아티팩트'),
    ]

    api_name = models.CharField(max_length=100, unique=True, db_index=True,
                                   verbose_name='apiName (CDragon)')
    name = models.CharField(max_length=100, verbose_name='아이템 이름')
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, verbose_name='아이템 종류')
    stats = models.CharField(max_length=300, blank=True, verbose_name='스탯 텍스트')
    desc = models.TextField(blank=True, verbose_name='설명')
    img_url = models.CharField(max_length=300, blank=True, verbose_name='아이콘 URL')
    comp = models.JSONField(default=list, verbose_name='조합 재료')
    trait_name = models.CharField(max_length=50, blank=True, verbose_name='시너지 이름 (emblem)')
    trait_icon = models.CharField(max_length=300, blank=True, verbose_name='시너지 아이콘 (emblem)')
    set_number = models.PositiveSmallIntegerField(default=16, verbose_name='시즌 세트 번호')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table= 'tft_info_item'
        verbose_name = 'TFT 아이템 정보'
        ordering = ['item_type', 'name']

    def __str__(self):
        return f'{self.name} ({self.item_type})'

    def to_dict(self) -> dict:
        return {
            'id' : self.api_name,
            'name' : self.name,
            'type' : self.item_type,
            'stats': self.stats,
            'desc': self.desc,
            'img' : self.img_url,
            'comp': self.comp,
            'traitName': self.trait_name,
            'traitIcon': self.trait_icon,
        }


class TFT_infoSynergeTable(models.Model):
    api_name = models.CharField(max_length=100, unique=True, db_index=True,
                                   verbose_name='apiName (CDragon)')
    name = models.CharField(max_length=50, verbose_name='시너지 이름')
    desc = models.TextField(blank=True, verbose_name='시너지 설명')
    icon_url = models.CharField(max_length=300, blank=True, verbose_name='아이콘 URL')
    tiers = models.JSONField(default=list, verbose_name='발동 단계')
    set_number = models.PositiveSmallIntegerField(default=16, verbose_name='시즌 세트 번호')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최근 갱신')

    class Meta:
        db_table = 'tft_info_synerge'
        verbose_name = 'TFT 시너지 정보'
        ordering = ['name']

    def __str__(self):
        return self.name

    def to_dict(self) -> dict:
        return {
            'id': self.api_name,
            'name': self.name,
            'desc': self.desc,
            'icon': self.icon_url,
            'tiers': self.tiers,
        }