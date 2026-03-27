import json as _json

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, mark_safe

from .models import (
    BaseUserInformation_data, UserPreferGame, Post_Community, PostParticipant,
    Friendship, ChatMessage, JoinRequest, Notification, DirectMessage, UserReport,
    Riot_UserINFO, Riot_MatchInfo,
    RiotDataCache, RankingSnapshot, RankingEntry,
    LOL_infoChampionTable, LOL_infoItemTable,
    VAL_infoAgentTable, Val_infoGunTable,
    TFT_infoChampionTable, TFT_infoItemTable, TFT_infoSynergeTable,
)

@admin.register(BaseUserInformation_data)
class UserAdmin(admin.ModelAdmin):
    list_display    = ('id', 'username', 'email', 'created_at', 'is_active')
    search_fields   = ('username', 'email')
    list_filter     = ('is_active',)
    ordering        = ('-created_at',)


@admin.register(UserPreferGame)
class UserPreferGameAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'game_id', 'name_tag', 'tier', 'score_current', 'sub_info')
    search_fields   = ('user__username', 'name_tag')
    list_filter     = ('game_id',)
    ordering        = ('-created_at',)


@admin.register(Post_Community)
class PostAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'game_id', 'post_title', 'current_member',
                       'total_member', 'tier_condition', 'is_open', 'post_upload_at')
    search_fields   = ('user__username', 'post_title')
    list_filter     = ('game_id', 'is_open')
    ordering        = ('-post_upload_at',)


@admin.register(PostParticipant)
class PostParticipantAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'post', 'joined_at')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display    = ('id', 'post', 'user', 'message', 'sent_at')
    list_filter     = ('post',)
    search_fields   = ('user__username', 'message')
    ordering        = ('-sent_at',)
    readonly_fields = ('sent_at',)


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'post', 'status', 'created_at')
    list_filter     = ('status',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user', 'type', 'message', 'is_read', 'created_at')
    list_filter     = ('type', 'is_read')


@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display    = ('id', 'from_user', 'to_user', 'status', 'created_at')
    list_filter     = ('status',)
    search_fields   = ('from_user__username', 'to_user__username')
    ordering        = ('-created_at',)


@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display    = ('id', 'sender', 'receiver', 'message', 'sent_at')
    search_fields   = ('sender__username', 'receiver__username', 'message')
    ordering        = ('-sent_at',)


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display    = ('id', 'reporter', 'reported', 'category', 'status', 'created_at')
    list_filter     = ('status', 'category')
    search_fields   = ('reporter__username', 'reported__username', 'detail')
    ordering        = ('-created_at',)


# ── Riot 유저 / 전적 캐시 ────────────────────────────────────────────

class Riot_MatchInfoInline(admin.TabularInline):
    """유저 상세 페이지에서 게임별 큐 목록을 인라인으로 표시."""
    model           = Riot_MatchInfo
    extra           = 0
    can_delete      = True
    show_change_link = True
    readonly_fields = ('game', 'queue_type', 'last_match_id', 'data_size', 'updated_at')
    fields          = ('game', 'queue_type', 'last_match_id', 'data_size', 'updated_at')

    @admin.display(description='캐시 크기')
    def data_size(self, obj):
        import json as _j
        try:
            size = len(_j.dumps(obj.cached_data, ensure_ascii=False).encode())
            if size >= 1024:
                return f'{size / 1024:.1f} KB'
            return f'{size} B'
        except Exception:
            return '—'


@admin.register(Riot_UserINFO)
class RiotUserINFOAdmin(admin.ModelAdmin):
    list_display    = ('id', 'username_tag', 'region', 'game_count', 'last_searched_at')
    search_fields   = ('username', 'tag', 'puuid')
    list_filter     = ('region',)
    ordering        = ('-last_searched_at',)
    readonly_fields = ('puuid', 'last_searched_at')
    inlines         = [Riot_MatchInfoInline]
    fields          = ('puuid', 'username', 'tag', 'region', 'last_searched_at')

    @admin.display(description='소환사')
    def username_tag(self, obj):
        return f'{obj.username}#{obj.tag}'

    @admin.display(description='등록 게임 수')
    def game_count(self, obj):
        count = obj.match_infos.values('game').distinct().count()
        games = obj.match_infos.values_list('game', flat=True).distinct()
        label = ' / '.join(g.upper() for g in sorted(games))
        return format_html(
            '<span title="{}">{} 종</span>',
            label, count,
        )

    actions = ['delete_match_cache']

    @admin.action(description='선택 유저의 전적 캐시 전체 삭제')
    def delete_match_cache(self, request, queryset):
        count = Riot_MatchInfo.objects.filter(user__in=queryset).delete()[0]
        self.message_user(request, f'전적 캐시 {count}건을 삭제했습니다.')


@admin.register(Riot_MatchInfo)
class RiotMatchInfoAdmin(admin.ModelAdmin):
    list_display    = ('id', 'user_tag', 'game_badge', 'queue_type_display',
                       'last_match_id', 'data_size', 'updated_at')
    list_filter     = ('game', 'queue_type')
    search_fields   = ('user__username', 'user__tag', 'last_match_id')
    ordering        = ('-updated_at',)
    readonly_fields = ('user', 'game', 'queue_type', 'last_match_id',
                       'updated_at', 'data_preview')
    fields          = ('user', 'game', 'queue_type', 'last_match_id',
                       'updated_at', 'data_preview')

    @admin.display(description='소환사')
    def user_tag(self, obj):
        return f'{obj.user.username}#{obj.user.tag}'

    @admin.display(description='게임')
    def game_badge(self, obj):
        color = {'lol': '#c89b3c', 'tft': '#0bc4c4', 'val': '#ff4655'}.get(obj.game, '#888')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-weight:700;font-size:11px;">{}</span>',
            color, obj.game.upper(),
        )

    @admin.display(description='큐 타입')
    def queue_type_display(self, obj):
        return obj.get_queue_type_display()

    @admin.display(description='캐시 크기')
    def data_size(self, obj):
        try:
            size = len(_json.dumps(obj.cached_data, ensure_ascii=False).encode())
            if size >= 1024:
                return f'{size / 1024:.1f} KB'
            return f'{size} B'
        except Exception:
            return '—'

    @admin.display(description='캐시 데이터 미리보기')
    def data_preview(self, obj):
        try:
            preview = _json.dumps(obj.cached_data, ensure_ascii=False, indent=2)
            if len(preview) > 2000:
                preview = preview[:2000] + '\n...(생략)...'
            return format_html(
                '<pre style="background:#1a1a2e;color:#e0e0e0;padding:12px;'
                'border-radius:4px;font-size:11px;max-height:400px;overflow:auto;">'
                '{}</pre>',
                preview,
            )
        except Exception:
            return '미리보기 불가'

    actions = ['flush_selected']

    @admin.action(description='선택 캐시 데이터 초기화 (빈 dict로)')
    def flush_selected(self, request, queryset):
        count = queryset.update(cached_data={}, last_match_id='')
        self.message_user(request, f'{count}건의 캐시 데이터를 초기화했습니다.')


@admin.register(RiotDataCache)
class RiotDataCacheAdmin(admin.ModelAdmin):
    list_display    = ('cache_key', 'version', 'data_size', 'status_badge',
                       'updated_at', 'expires_at')
    list_filter     = ('version',)
    search_fields   = ('cache_key',)
    readonly_fields = ('cache_key', 'version', 'created_at', 'updated_at',
                       'expires_at', 'data_preview', 'status_badge_detail')  # ← 메서드는 반드시 readonly_fields에 등록
    ordering        = ('cache_key',)
    fields          = ('cache_key', 'version', 'status_badge_detail',
                       'created_at', 'updated_at', 'expires_at', 'data_preview')

    @admin.display(description='데이터 크기')
    def data_size(self, obj):
        try:
            size = len(_json.dumps(obj.data, ensure_ascii=False).encode('utf-8'))
            if size >= 1024 * 1024:
                return f'{size / 1024 / 1024:.1f} MB'
            elif size >= 1024:
                return f'{size / 1024:.1f} KB'
            return f'{size} B'
        except Exception:
            return '—'

    @admin.display(description='상태')
    def status_badge(self, obj):
        # format_html은 placeholder가 없으면 TypeError → mark_safe 사용
        if obj.expires_at is None:
            return mark_safe('<span style="color:#2196f3;font-weight:700;">♾ 영구</span>')
        if obj.is_expired():
            return mark_safe('<span style="color:#f44336;font-weight:700;">✗ 만료됨</span>')
        remaining = obj.expires_at - timezone.now()
        hours   = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return format_html(
            '<span style="color:#4caf50;font-weight:700;">✓ 유효 ({}h {}m 남음)</span>',
            hours, minutes,
        )

    @admin.display(description='상태')
    def status_badge_detail(self, obj):
        return self.status_badge(obj)

    @admin.display(description='데이터 미리보기')
    def data_preview(self, obj):
        try:
            preview = _json.dumps(obj.data, ensure_ascii=False, indent=2)
            if len(preview) > 2000:
                preview = preview[:2000] + '\n...(생략)...'
            return format_html(
                '<pre style="background:#1a1a2e;color:#e0e0e0;padding:12px;'
                'border-radius:4px;font-size:11px;max-height:400px;overflow:auto;">'
                '{}</pre>',
                preview,
            )
        except Exception:
            return '미리보기 불가'

    actions = ['force_expire', 'delete_selected_cache']

    @admin.action(description='선택한 캐시 즉시 만료 처리')
    def force_expire(self, request, queryset):
        count = queryset.update(expires_at=timezone.now())
        self.message_user(request, f'{count}개 캐시를 만료 처리했습니다.')

    @admin.action(description='선택한 캐시 삭제 (Django cache + DB)')
    def delete_selected_cache(self, request, queryset):
        from django.core.cache import cache as djcache
        keys = list(queryset.values_list('cache_key', flat=True))
        for key in keys:
            djcache.delete(key)
        count = queryset.delete()[0]
        self.message_user(request, f'{count}개 캐시를 삭제했습니다. (키: {", ".join(keys)})')

@admin.register(RankingSnapshot)
class RankingSnapshotAdmin(admin.ModelAdmin):
    list_display    = ('id', 'game', 'queue', 'collected_at', 'is_active', 'entry_count')
    list_filter     = ('game', 'queue', 'is_active')
    ordering        = ('-collected_at',)
    actions         = ['deactivate_selected']

    @admin.display(description='유저 수')
    def entry_count(self, obj):
        return obj.entries.count()

    @admin.action(description='선택 스냅샷 비활성화')
    def deactivate_selected(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count}개 스냅샷을 비활성화했습니다.')


@admin.register(RankingEntry)
class RankingEntryAdmin(admin.ModelAdmin):
    list_display    = ('rank', 'name', 'tag_line', 'tier', 'lp', 'snapshot')
    list_filter     = ('tier', 'snapshot__game', 'snapshot__queue')
    search_fields   = ('name', 'puuid')
    ordering        = ('snapshot', 'rank')


@admin.register(LOL_infoChampionTable)
class LOLChampionAdmin(admin.ModelAdmin):
    list_display    = ('champion_id', 'name', 'title', 'primary_class', 'patch_version', 'updated_at')
    search_fields   = ('champion_id', 'name', 'title')
    list_filter     = ('primary_class', 'patch_version')
    ordering        = ('name',)
    readonly_fields = ('updated_at',)

    @admin.display(description='태그')
    def tag_list(self, obj):
        return ', '.join(obj.tags) if obj.tags else '—'


@admin.register(LOL_infoItemTable)
class LOLItemAdmin(admin.ModelAdmin):
    list_display    = ('item_id', 'name', 'item_type', 'gold', 'patch_version',
                       'mapping_hash', 'updated_at')
    search_fields   = ('item_id', 'name')
    list_filter     = ('item_type', 'patch_version')
    ordering        = ('item_type', '-gold')
    readonly_fields = ('updated_at',)

    @admin.display(description='골드')
    def gold_display(self, obj):
        return f'{obj.gold:,} ({obj.gold_sell:,} 판매)' if obj.gold else '—'

@admin.register(VAL_infoAgentTable)
class VALAgentAdmin(admin.ModelAdmin):
    list_display    = ('agent_uuid', 'name', 'role', 'ability_count', 'updated_at')
    search_fields   = ('name', 'agent_uuid')
    list_filter     = ('role',)
    ordering        = ('name',)
    readonly_fields = ('updated_at',)

    @admin.display(description='스킬 수')
    def ability_count(self, obj):
        return len(obj.abilities) if obj.abilities else 0


@admin.register(Val_infoGunTable)
class VALGunAdmin(admin.ModelAdmin):
    list_display    = ('gun_uuid', 'name', 'category', 'cost', 'fire_rate',
                       'magazine_size', 'updated_at')
    search_fields   = ('name', 'gun_uuid')
    list_filter     = ('category',)
    ordering        = ('category', 'cost')
    readonly_fields = ('updated_at',)

@admin.register(TFT_infoChampionTable)
class TFTChampionAdmin(admin.ModelAdmin):
    list_display    = ('api_name', 'name', 'cost', 'trait_list', 'set_number', 'updated_at')
    search_fields   = ('api_name', 'name')
    list_filter     = ('cost', 'set_number')
    ordering        = ('cost', 'name')
    readonly_fields = ('updated_at',)

    @admin.display(description='시너지')
    def trait_list(self, obj):
        return ', '.join(obj.traits) if obj.traits else '—'


@admin.register(TFT_infoItemTable)
class TFTItemAdmin(admin.ModelAdmin):
    list_display    = ('api_name', 'name', 'item_type', 'trait_name', 'set_number', 'updated_at')
    search_fields   = ('api_name', 'name', 'trait_name')
    list_filter     = ('item_type', 'set_number')
    ordering        = ('item_type', 'name')
    readonly_fields = ('updated_at',)

    @admin.display(description='조합 재료')
    def comp_preview(self, obj):
        if not obj.comp:
            return '—'
        names = [c.get('name', c.get('apiName', '')) for c in obj.comp]
        return ' + '.join(names)


@admin.register(TFT_infoSynergeTable)
class TFTSynergeAdmin(admin.ModelAdmin):
    list_display    = ('api_name', 'name', 'tier_count', 'set_number', 'updated_at')
    search_fields   = ('api_name', 'name')
    list_filter     = ('set_number',)
    ordering        = ('name',)
    readonly_fields = ('updated_at',)

    @admin.display(description='발동 단계 수')
    def tier_count(self, obj):
        return len(obj.tiers) if obj.tiers else 0