from django.urls import path
from . import views
from . import riot_apiViews
from . import riot_apiValorant
from . import riot_apiTFT
from . import riot_info
from . import riot_ranking

import urllib.request
import urllib.error
import urllib.parse

urlpatterns = [
    path("",views.index_, name='index'),
    path("login/",views.login_,name='Login'),
    path("register/",views.register_, name='register'),
    path("selectGame/", views.selection_page,name='selectGames'),
    path("Deai_main/",views.Main_rq,name='Deai_main'),
    path("aboutDeai/", views.aboutDeai, name='aboutDeai'),
    path("createAuthor/", views.createAuthor , name="createAuthor"),
    path("RiotInfo/" , riot_info.infoPageRender , name="RiotInfo"),
    
    ## API space
    
    path("logout/",views.logout_, name='logout'),
    path("api/auth/register/",views.api_register,name='api_register'), 
    path("api/auth/login/", views.api_login, name='api_login'),
    path("api/game/save/", views.save_prefer_game,name='save_prefer_game'),
    path("api/game/my/", views.get_my_games,name='get_my_games'),
    path("api/post/create/", views.api_post_create, name='api_post_create'),
    path("api/post/list/",views.api_post_list,name='api_post_list'),
    path("api/post/delete/<int:post_id>/", views.api_post_delete, name='api_post_delete'), 
    path("api/post/join/<int:post_id>/",   views.api_post_join,name='api_post_join'),
    path("api/post/leave/<int:post_id>/", views.api_post_leave, name='api_post_leave'),
    path("api/user/search/", views.api_user_search, name='api_user_search'),
    path("api/friend/request/", views.api_friend_request,name='api_friend_request'),
    path("api/friend/requests/received/", views.api_friend_requests_received, name='api_friend_requests_received'),
    path("api/friend/respond/", views.api_friend_respond, name='api_friend_respond'),
    path("api/friend/list/", views.api_friend_list, name='api_friend_list'),
    path("api/friend/delete/<int:friendship_id>/", views.api_friend_delete,  name='api_friend_delete'),
    path("api/post/members/<int:post_id>/", views.api_post_members, name='api_post_members'),
    path("api/user/profile/<str:username>/", views.api_user_profile, name='api_user_profile'),
    path("api/chat/history/<int:post_id>/", views.api_chat_history, name='api_chat_history'), 
    path("api/join/respond/",views.api_join_respond,name='api_join_respond'),
    path("api/notifications/",views.api_notifications, name='api_notifications'),
    path("api/notifications/read/",views.api_notifications_read,name='api_notifications_read'),
    path("api/dm/send/", views.api_dm_send,name='api_dm_send'),
    path("api/dm/history/<str:username>/", views.api_dm_history, name='api_dm_history'),
    path("api/notifications/clear/", views.api_notifications_clear,name='api_notifications_clear'),
    path("api/report/", views.api_report, name='api_report'),
    path("admin_panel/",views.admin_panel, name='admin_panel'),
    path("api/admin/reports/",views.api_admin_reports, name='api_admin_reports'),
    path("api/admin/report/action/", views.api_admin_report_action, name='api_admin_report_action'),
    path("api/admin/user/", views.api_admin_user_lookup,name='api_admin_user_lookup'),
    path("api/admin/analytics/", views.api_admin_analytics, name='api_admin_analytics'),
    path("api/admin/unblock/",    views.api_admin_unblock,name='api_admin_unblock'),
    path("api/auth/send-code/",   views.api_send_verify_code, name='api_send_verify_code'),
    path("api/auth/verify-code/", views.api_verify_code, name='api_verify_code'),
    path("api/game/stats/" , views.api_game_stats, name="api/game/stats/"),

    ## cache
    path('api/info/cache/clear/', riot_info.info_cache_clear),

    ## riot api space
    # riot/lol/ + user
    path('api/riot/refresh/', riot_apiViews.riot_api_refreshMatches, name='riot_refresh'),
    path("RiotSearch/", riot_apiViews.riotSearchPage_rendering,name='riot_lol_search'),
    path("RiotUserPage/", riot_apiViews.riotUserPage_rendering, name='riot_lol_user'),
    path("riot/lol/user/", riot_apiViews.riotUserPage_rendering, name='riot_lol_user2'),
    path("api/riot/account/", riot_apiViews.riot_api_search_user, name='riot_api_account'),
    path("api/riot/rank/", riot_apiViews.riot_api_rankInfo, name='riot_api_rank'),
    path("api/riot/mastery/", riot_apiViews.riot_api_getChampionMastery, name='riot_api_mastery'),
    path("api/riot/matches/", riot_apiViews.riot_api_getMatchIDs,name='riot_api_matches'),
    path("api/riot/match/<str:match_id>/", riot_apiViews.riot_api_matchDetail, name='riot_api_match_detail'),
    path("api/riot/dd-version/", riot_apiViews.riot_api_ddVersion, name='riot_api_dd_version'),
    path("api/riot/champions/", riot_apiViews.riot_api_champions, name='riot_api_champions'),
    path("api/riot/dd-spell/", riot_apiViews.riot_api_ddSpell, name='riot_api_dd_spell'),
    path('api/riot/matches/more/', riot_apiViews.riot_api_loadMoreMatches, name='riot_load_more'),

    path('api/riot/debug/ping/', riot_apiViews.riot_api_debug_ping, name='riot_debug_ping'),

    ## riot api
    ## valorant 
    # riot/val/ + userinfo
    path("ValorantSearch/", riot_apiValorant.riot_api_VRTUserPageRendering,name='ValorantSearch'),
    path("riot/val/user/",riot_apiValorant.riot_api_VRTUserPageRendering, name='riot_val_user'),
    path("api/val/account/", riot_apiValorant.val_api_search_account, name='val_api_account'),
    path("api/val/matches/", riot_apiValorant.val_api_getMatchIDs, name='val_api_matches'),
    path("api/val/match/<str:match_id>/", riot_apiValorant.val_api_matchDetail,name='val_api_match_detail'),
    path("api/val/rank/", riot_apiValorant.val_api_getRank, name='val_api_rank'),
    

    ## riot api
    ## tft
    ## riot/tft + user
    path("riot/tft/user/", riot_apiTFT.tft_page_rendering, name="riot_tft_user"),
    path("api/tft/account/", riot_apiTFT.tft_api_search_account,name="tft_api_account"),
    path("api/tft/rank/", riot_apiTFT.tft_api_getRank, name="tft_api_rank"),
    path("api/tft/matches/", riot_apiTFT.tft_api_getMatchIDs, name="tft_api_matches"),
    path("api/tft/match/<str:match_id>/", riot_apiTFT.tft_api_matchDetail, name="tft_api_match_detail"),
    path('api/tft/ranks/bulk/', riot_apiTFT.tft_api_bulk_ranks, name='tft_bulk_ranks'),


    ## ddragon 
    ## all games
    # riot info
    path('riot/info/', riot_info.infoPageRender, name='info_page'),
    path('api/info/version/', riot_info.info_dd_version,name='info_version'),

    path('api/info/lol/champions/',riot_info.info_lol_champions,name='info_lol_champs'),
    path('api/info/lol/items/', riot_info.info_lol_items, name='info_lol_items'),

    path('api/info/tft/champions/', riot_info.info_tft_champions,name='info_tft_champs'),
    path('api/info/tft/items/', riot_info.info_tft_items,name='info_tft_items'),
    path('api/info/tft/augments/', riot_info.info_tft_augments),

    ## riot api 
    ## riot ranking s
    ## c ,g .. valorant
    path('api/ranking/lol/', riot_ranking.info_lol_ranking),
    path('api/ranking/val/', riot_ranking.info_val_ranking),
    path('api/ranking/tft/', riot_ranking.info_tft_ranking),
    path('RiotRanking/',     riot_ranking.riot_api_rankRendering, name='RiotRanking'),
    path('api/ranking/lol/debug/', riot_ranking.info_lol_ranking_debug),
    path('api/ranking/cache/clear/', riot_ranking.info_ranking_cache_clear),
    path('api/ranking/mastery/', riot_ranking.info_mastery_by_puuid),

    ## ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ
    path("DestroyTeemo/", views.teemo , name="DestroyTeemo"),

]
    