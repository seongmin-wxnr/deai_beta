from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import datetime, timedelta
import json, re, random

from .models import (
    BaseUserInformation_data, UserPreferGame, Post_Community,
    PostParticipant, Friendship, ChatMessage, Notification,
    JoinRequest, DirectMessage, UserReport
)

def teemo(request):
    return render(request, "teemo.html")
def riotAuth(request):
    return HttpResponse("c863ea78-32df-4a34-8d88-a8b24b310446", content_type="text/plain")

def createAuthor(request):
    return render(request, "create_.html")

def aboutDeai(request):
    return render(request, "aboutDeai.html")
    
def selection_page(request):
    if not request.session.get('username'):
        try:

            return render(request , 'login.html')
        
        except Exception as e:
            print(f"Except {e}")
    else:

        username = request.session.get('username')
        username = request.session.get('username', '게스트')
        return render(request, "selectGame.html", {
            'username': username 
        })

def index_(request):
    return render(request, "index.html")

# fix -> 2026.03.02
def Main_rq(request):
    if not request.session.get('user_id'):
        return render(request, 'login.html')

    games = UserPreferGame.objects.filter(
        user_id=request.session['user_id']
    ).values('game_id', 'name_tag', 'tier', 'score_best', 'score_current', 'sub_info')

    return render(request, "Main.html", {
        'username'  : request.session.get('username', ''),
        'email'     : request.session.get('email', ''),
        'games_json': json.dumps(list(games)),
    })

def get_my_games(request):
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    games = UserPreferGame.objects.filter(
        user_id=request.session['user_id']
    ).values('game_id','name_tag','tier','score_best','score_current','sub_info')
    return JsonResponse({'success': True, 'games': list(games)})

def login_(request):
    if request.method == "GET":
        return render(request, "login.html")

    if request.method == "POST":
        try:
            data     = json.loads(request.body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()

            if not username or not password:
                return JsonResponse({
                    'success': False,
                    'message': '유저 이름, 비밀번호를 확인해주세요.'
                }, status=400)

            user = BaseUserInformation_data.objects.filter(username=username).first()

            if not user:
                return JsonResponse({
                    'success': False,
                    'message': '존재하지 않는 닉네임입니다.'
                }, status=404)

            if not check_password(password, user.password):
                return JsonResponse({
                    'success': False,
                    'message': '비밀번호가 틀렸습니다.'
                }, status=401)

            # 차단 여부 확인
            if user.blocked_until and user.blocked_until > timezone.now():
                remaining = user.blocked_until - timezone.now()
                hours   = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                return JsonResponse({
                    'success': False,
                    'message': f'계정이 차단되었습니다. ({hours}시간 {minutes}분 후 해제)'
                }, status=403)

            request.session['user_id']  = user.id
            request.session['username'] = user.username
            request.session['email']    = user.email

            # admin 전용 패널
            if username == 'admin':
                return JsonResponse({
                    'success'     : True,
                    'message'     : '관리자 로그인 성공!',
                    'username'    : user.username,
                    'redirect_url': '/admin_panel/',
                })

            has_game = UserPreferGame.objects.filter(user=user).exists()
            redirect_url = '/Deai_main/' if has_game else '/selectGame/'

            return JsonResponse({
                'success'     : True,
                'message'     : '로그인 성공!',
                'username'    : user.username,
                'redirect_url': redirect_url, 
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'서버 오류: {str(e)}'
            }, status=500)

def register_(request):
    if request.method == "GET":
        return render(request, "register.html")

    if request.method == "POST":
        try:
            data     = json.loads(request.body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            email    = data.get('email',    '').strip()

            if not email or not username or not password:
                return JsonResponse({
                    'success': False,
                    'message': '모든 항목을 입력해주세요.'
                }, status=400)

            if BaseUserInformation_data.objects.filter(email=email).exists():  # ← 버그 수정
                return JsonResponse({
                    'success': False,
                    'message': '이미 사용중인 이메일입니다.'
                }, status=409)

            if BaseUserInformation_data.objects.filter(username=username).exists():
                return JsonResponse({
                    'success': False,
                    'message': '이미 사용중인 닉네임입니다.'
                }, status=409)

            BaseUserInformation_data.objects.create(
                email    = email,
                username = username,
                password = make_password(password),
            )
            print("registerd -> " + str(username))
            return JsonResponse({
                'success': True,
                'message': f'회원가입 성공! {username}님 환영합니다.'
            }, status=201)  # ← 버그 수정 (400 → 201)

        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'회원가입에 실패했습니다. {e}'
            }, status=500)
def api_register(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)
    try:
        data     = json.loads(request.body)
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        email    = data.get('email',    '').strip()

        if not email or not username or not password:
            return JsonResponse({'success': False, 'message': '모든 항목을 입력해주세요.'}, status=400)

        # 유저이름: 영문+숫자만, 3자 이상
        if not re.match(r'^[a-zA-Z0-9]{3,}$', username):
            return JsonResponse({'success': False, 'message': '유저 이름은 영문과 숫자만 사용할 수 있습니다. (3자 이상)'}, status=400)

        # 비밀번호: 8자 이상 + 특수문자 필수
        if len(password) < 8:
            return JsonResponse({'success': False, 'message': '비밀번호는 8자 이상이어야 합니다.'}, status=400)
        if not re.search(r'[^A-Za-z0-9]', password):
            return JsonResponse({'success': False, 'message': '비밀번호에 특수문자를 1개 이상 포함해주세요.'}, status=400)

        if BaseUserInformation_data.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': '이미 사용중인 이메일입니다.'}, status=409)

        if BaseUserInformation_data.objects.filter(username=username).exists():
            return JsonResponse({'success': False, 'message': '이미 사용중인 닉네임입니다.'}, status=409)

        BaseUserInformation_data.objects.create(
            email    = email,
            username = username,
            password = make_password(password),
        )
        print(f"[회원가입] {username} ({email})", flush=True)
        return JsonResponse({'success': True, 'message': f'{username}님 환영합니다!'}, status=201)

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)


def api_login(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)
    try:
        data     = json.loads(request.body)
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return JsonResponse({'success': False, 'message': '닉네임과 비밀번호를 입력해주세요.'}, status=400)

        user = BaseUserInformation_data.objects.filter(username=username).first()

        if not user:
            return JsonResponse({'success': False, 'message': '존재하지 않는 닉네임입니다.'}, status=404)

        if not check_password(password, user.password):
            return JsonResponse({'success': False, 'message': '비밀번호가 틀렸습니다.'}, status=401)

        # 차단 여부 확인
        if user.blocked_until and user.blocked_until > timezone.now():
            remaining = user.blocked_until - timezone.now()
            hours   = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return JsonResponse({
                'success': False,
                'message': f'계정이 차단되었습니다. ({hours}시간 {minutes}분 후 해제)'
            }, status=403)

        request.session['user_id']  = user.id
        request.session['username'] = user.username
        request.session['email']    = user.email

        # admin 전용 패널
        if username == 'admin':
            return JsonResponse({
                'success'     : True,
                'message'     : '관리자 로그인 성공!',
                'username'    : user.username,
                'redirect_url': '/admin_panel/',
                
            })

        has_game = UserPreferGame.objects.filter(user=user).exists()
        redirect_url = '/Deai_main/' if has_game else '/selectGame/'

        return JsonResponse({
            'success'     : True,
            'message'     : '로그인 성공!',
            'username'    : user.username,
            'redirect_url': redirect_url,
        })

        

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)
    
def logout_(request):
    request.session.flush()  # 세션 전체 삭제
    return JsonResponse({'success': True})

def Add_usergamedata(request):
    if request.method == 'POST':
        data  = json.loads(request.body)
        games = data.get('games', [])  # selectGame.html 에서 넘어온 배열

        user = BaseUserInformation_data.objects.get(
            id=request.session['user_id']
        )

        for g in games:
            UserPreferGame.objects.update_or_create(
                user    = user,
                game_id = g['gameId'],   # 'lol', 'val' 등
                defaults = {
                    'name_tag'      : f"{g['name']}#{g['tag']}",
                    'tier'          : g.get('lol_tier') or g.get('val_tier') or g.get('ow_tier') or '',
                    'score_best'    : g.get('lol_lp_best') or g.get('val_rr_best') or 0,
                    'score_current' : g.get('lol_lp_current') or g.get('val_rr_current') or 0,
                    'sub_info'      : g.get('lol_pos') or g.get('val_role') or g.get('ow_role') or '',
                }
            )
        print("update user game data at -> ")
        return JsonResponse({'success': True})

def save_prefer_game(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        data = json.loads(request.body)
        user = BaseUserInformation_data.objects.get(id=request.session['user_id'])

        UserPreferGame.objects.update_or_create(
            user    = user,
            game_id = data['game_id'],
            defaults = {
                'name_tag'      : data.get('name_tag', ''),
                'tier'          : data.get('tier', ''),
                'score_best'    : data.get('score_best', 0),
                'score_current' : data.get('score_current', 0),
                'sub_info'      : data.get('sub_info', ''),
            }
        )
        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_posts(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)
    try:
        mainRQ_data = json.load(request.body)
        ingameDataSets = UserPreferGame.objects.get(id=request.session['user_id'])
        print("reading -> " + str(mainRQ_data) + " " + str(ingameDataSets))

    except Exception as e:
        return JsonResponse({'success' : False ,'message' : str(e)}, status=500)

def api_post_create(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        data = json.loads(request.body)
        user = BaseUserInformation_data.objects.get(id=request.session['user_id'])

        # 필수값 검사
        if not data.get('post_title'):
            return JsonResponse({'success': False, 'message': '제목을 입력해주세요.'}, status=400)
        if not data.get('game_id'):
            return JsonResponse({'success': False, 'message': '게임을 선택해주세요.'}, status=400)

        post = Post_Community.objects.create(
            user           = user,
            game_id        = data['game_id'],
            post_title     = data['post_title'],
            post_body      = data.get('post_body', ''),
            current_member = int(data.get('current_member', 1)),
            total_member   = int(data.get('total_member', 5)),
            tier_condition = data.get('tier_condition', '무관'),
            is_open        = True,
        )
        print("Data save at -> post_")
        return JsonResponse({
            'success': True,
            'post': {
                'id'            : post.id,
                'game_id'       : post.game_id,
                'post_title'    : post.post_title,
                'post_body'     : post.post_body,
                'current_member': post.current_member,
                'total_member'  : post.total_member,
                'tier_condition': post.tier_condition,
                'is_open'       : post.is_open,
                'author'        : user.username,
                'uploaded_at'   : '방금 전',
            }
        }, status=201)
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def api_post_list(request):
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)
    try:
        game_id = request.GET.get('game_id', '')
        posts = Post_Community.objects.select_related('user')
        if game_id:
            posts = posts.filter(game_id=game_id)

        def time_ago(dt):
            from django.utils import timezone
            diff = timezone.now() - dt
            s = int(diff.total_seconds())
            if s < 60:    return '방금 전'
            if s < 3600:  return f'{s//60}분 전'
            if s < 86400: return f'{s//3600}시간 전'
            return f'{s//86400}일 전'

        user_id = request.session.get('user_id')

        # 현재 유저가 어떤 파티에든 참여 중인지 (전체)
        already_in_party = PostParticipant.objects.filter(
            user_id=user_id,
            post__is_open=True
        ).exists() if user_id else False

        result = []
        for p in posts:
            # 작성자의 해당 게임 정보 조회
            game_info = UserPreferGame.objects.filter(
                user=p.user, game_id=p.game_id
            ).first()

            # 현재 유저가 이 게시글에 참여했는지
            joined_by_me = PostParticipant.objects.filter(
                post=p, user_id=user_id
            ).exists() if user_id else False

            joined_by_me = PostParticipant.objects.filter(
                post=p, user_id=user_id
            ).exists() if user_id else False

            pending_by_me = JoinRequest.objects.filter(
            post=p, user_id=user_id, status='pending'
            ).exists() if user_id else False

            result.append({
                'id'             : p.id,
                'game_id'        : p.game_id,
                'post_title'     : p.post_title,
                'post_body'      : p.post_body,
                'current_member' : p.current_member,
                'total_member'   : p.total_member,
                'tier_condition' : p.tier_condition,
                'is_open'        : p.is_open,
                'author'         : p.user.username,
                'uploaded_at'    : time_ago(p.post_upload_at),
                # 작성자 게임 정보
                'author_name_tag': game_info.name_tag  if game_info else '',
                'author_tier'    : game_info.tier      if game_info else '',
                'author_sub_info': game_info.sub_info  if game_info else '',
                # 참여 여부
                'joined_by_me'   : joined_by_me,
                'already_in_party': already_in_party,

                ## request nonfictin
                'joined_by_me'    : joined_by_me,
                'already_in_party': already_in_party,
                'pending_by_me'   : pending_by_me,
            })
        print("Data read at -> post_")
        return JsonResponse({'success': True, 'posts': result})

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    

def api_post_join(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        user = BaseUserInformation_data.objects.get(id=request.session['user_id'])
        post = Post_Community.objects.get(id=post_id)

        # 1. 본인 글 참여 불가
        if post.user.id == user.id:
            return JsonResponse({'success': False, 'message': '본인 글에는 참여할 수 없습니다.'}, status=400)

        # 2. 모집 완료된 글
        if not post.is_open:
            return JsonResponse({'success': False, 'message': '이미 모집이 완료된 글입니다.'}, status=400)

        # 3. 중복 참여 방지
        if PostParticipant.objects.filter(post=post, user=user).exists():
            return JsonResponse({'success': False, 'message': '이미 참여한 게시글입니다.'}, status=400)

        # 4. 다른 게시글 이미 참여 중인지 확인 (게임 무관)
        already_joined = PostParticipant.objects.filter(
            user=user,
            post__is_open=True
        ).exists()
        if already_joined:
            return JsonResponse({'success': False, 'message': '이미 다른 파티에 참여 중입니다. 파티를 탈퇴한 후 참여해주세요.'}, status=400)
        # 5. 참여 처리
        PostParticipant.objects.create(post=post, user=user)
        post.current_member += 1
        if post.current_member >= post.total_member:
            post.is_open = False
        post.save()

        return JsonResponse({
            'success'       : True,
            'current_member': post.current_member,
            'total_member'  : post.total_member,
            'is_open'       : post.is_open,
        })

    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False, 'message': '존재하지 않는 게시글입니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
def api_post_delete(request, post_id):
    if request.method != 'DELETE':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        post = Post_Community.objects.get(id=post_id)

        if post.user.id != request.session['user_id']:
            return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)

        post.delete()
        return JsonResponse({'success': True})

    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False, 'message': '존재하지 않는 게시글입니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
## 미완성 구현부 -> api
def api_post_leave(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '허용되지 않는 메서드'}, status=405)

    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        user = BaseUserInformation_data.objects.get(id=request.session['user_id'])
        post = Post_Community.objects.get(id=post_id)

        # 참여 기록 확인
        participant = PostParticipant.objects.filter(post=post, user=user).first()
        if not participant:
            return JsonResponse({'success': False, 'message': '참여 중인 게시글이 아닙니다.'}, status=400)

        # 탈퇴 처리
        participant.delete()
        post.current_member = max(1, post.current_member - 1)  # 최소 1명 (작성자)
        post.is_open = True  # 자리 생겼으니 다시 모집 중
        post.save()

        return JsonResponse({
            'success'       : True,
            'current_member': post.current_member,
            'total_member'  : post.total_member,
            'is_open'       : post.is_open,
        })

    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False, 'message': '존재하지 않는 게시글입니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_user_search(request):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)

    query   = request.GET.get('q', '').strip()
    user_id = request.session.get('user_id')

    if not query:
        return JsonResponse({'success': False, 'message': '검색어를 입력해주세요.'})

    user = BaseUserInformation_data.objects.filter(username=query).first()

    if not user:
        return JsonResponse({'success': False, 'message': '존재하지 않는 유저입니다.'})

    if user.id == user_id:
        return JsonResponse({'success': False, 'message': '자신은 추가할 수 없어요.'})

    # 이미 친구 요청 상태 확인
    existing = Friendship.objects.filter(
        from_user_id=user_id, to_user=user
    ).first() or Friendship.objects.filter(
        from_user=user, to_user_id=user_id
    ).first()

    status = existing.status if existing else None

    return JsonResponse({
        'success' : True,
        'username': user.username,
        'status'  : status,   # None / 'pending' / 'accepted'
    })

def api_friend_request(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    user_id  = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)

    try:
        data     = json.loads(request.body)
        to_name  = data.get('to_username', '').strip()
        to_user  = BaseUserInformation_data.objects.get(username=to_name)
        from_user = BaseUserInformation_data.objects.get(id=user_id)

        if Friendship.objects.filter(from_user=from_user, to_user=to_user).exists():
            return JsonResponse({'success': False, 'message': '이미 요청을 보냈습니다.'})

        Friendship.objects.create(from_user=from_user, to_user=to_user, status='pending')
        return JsonResponse({'success': True, 'message': f'{to_name}님에게 친구 요청을 보냈어요!'})

    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False, 'message': '유저를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_friend_requests_received(request):
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)

    requests = Friendship.objects.filter(
        to_user_id=request.session['user_id'],
        status='pending'
    ).select_related('from_user')

    return JsonResponse({
        'success' : True,
        'requests': [{'id': r.id, 'from_username': r.from_user.username} for r in requests]
    })


def api_friend_respond(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'success': False}, status=401)

    try:
        data       = json.loads(request.body)
        request_id = data.get('request_id')
        action     = data.get('action')  # 'accept' or 'reject'

        friendship = Friendship.objects.get(id=request_id, to_user_id=user_id)

        if action == 'accept':
            friendship.status = 'accepted'
            friendship.save()
            return JsonResponse({'success': True, 'message': '친구 요청을 수락했어요!'})
        elif action == 'reject':
            friendship.delete()
            return JsonResponse({'success': True, 'message': '친구 요청을 거절했어요.'})
        else:
            return JsonResponse({'success': False, 'message': '잘못된 요청입니다.'})

    except Friendship.DoesNotExist:
        return JsonResponse({'success': False, 'message': '요청을 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_friend_list(request):
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)

    user_id = request.session['user_id']

    friends = Friendship.objects.filter(
        status='accepted'
    ).filter(
        Q(from_user_id=user_id) | Q(to_user_id=user_id)
    ).select_related('from_user', 'to_user')

    result = []
    for f in friends:
        friend = f.to_user if f.from_user_id == user_id else f.from_user
        result.append({'id': f.id, 'username': friend.username})

    return JsonResponse({'success': True, 'friends': result})

def api_friend_delete(request, friendship_id):
    if request.method != 'DELETE':
        return JsonResponse({'success': False}, status=405)

    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'success': False}, status=401)

    try:
        from django.db import models as dj_models
        friendship = Friendship.objects.get(
            dj_models.Q(from_user_id=user_id) | dj_models.Q(to_user_id=user_id),
            id=friendship_id
        )
        friendship.delete()
        return JsonResponse({'success': True})
    except Friendship.DoesNotExist:
        return JsonResponse({'success': False}, status=404)

def api_post_members(request, post_id):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)
    try:
        post = Post_Community.objects.get(id=post_id)

        # 방장 (게시글 작성자) 먼저
        host_game = UserPreferGame.objects.filter(
            user=post.user, game_id=post.game_id
        ).first()

        members = [{
            'username': post.user.username,
            'name_tag': host_game.name_tag if host_game else '',
            'is_host' : True,
        }]

        # 참여자 목록
        participants = PostParticipant.objects.filter(
            post=post
        ).select_related('user')

        for p in participants:
            game_info = UserPreferGame.objects.filter(
                user=p.user, game_id=post.game_id
            ).first()
            members.append({
                'username': p.user.username,
                'name_tag': game_info.name_tag if game_info else '',
                'is_host' : False,
            })

        return JsonResponse({'success': True, 'members': members})

    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False, 'message': '게시글을 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_post_members(request, post_id):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)
    try:
        post = Post_Community.objects.get(id=post_id)
        host_game = UserPreferGame.objects.filter(user=post.user, game_id=post.game_id).first()
        members = [{
            'username': post.user.username,
            'name_tag': host_game.name_tag if host_game else '',
            'is_host' : True,
        }]
        for p in PostParticipant.objects.filter(post=post).select_related('user'):
            g = UserPreferGame.objects.filter(user=p.user, game_id=post.game_id).first()
            members.append({
                'username': p.user.username,
                'name_tag': g.name_tag if g else '',
                'is_host' : False,
            })
        return JsonResponse({'success': True, 'members': members})
    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_user_profile(request, username):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)
    try:
        GAME_META = {
            'lol' : {'name': '리그오브레전드', 'icon': '⚔️',  'score_label': 'LP'},
            'val' : {'name': '발로란트',       'icon': '🔫',  'score_label': 'RR'},
            'ow'  : {'name': '오버워치 2',     'icon': '🦸',  'score_label': '점수'},
            'fifa': {'name': '피파온라인 4',   'icon': '⚽',  'score_label': '점수'},
            'gs'  : {'name': '원신',           'icon': '🌿',  'score_label': '점수'},
        }
        user = BaseUserInformation_data.objects.get(username=username)
        games_qs = UserPreferGame.objects.filter(user=user)
        games = []
        for g in games_qs:
            meta = GAME_META.get(g.game_id, {'name': g.game_id, 'icon': '🎮', 'score_label': '점수'})
            games.append({
                'game_id'    : g.game_id,
                'name'       : meta['name'],
                'icon'       : meta['icon'],
                'score_label': meta['score_label'],
                'name_tag'   : g.name_tag,
                'tier'       : g.tier,
                'sub_info'   : g.sub_info,
                'score'      : g.score_current,
                'score_best' : g.score_best,
            })
        return JsonResponse({'success': True, 'username': username, 'games': games})
    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False, 'message': '유저를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
def api_chat_history(request, post_id):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)
    try:
        messages = ChatMessage.objects.filter(
            post_id=post_id
        ).select_related('user').order_by('sent_at')

        def time_fmt(dt):
            from django.utils import timezone
            local = dt.astimezone(timezone.get_current_timezone())
            return local.strftime('%H:%M')

        result = [
            {
                'username': m.user.username,
                'message' : m.message,
                'time'    : time_fmt(m.sent_at),
            }
            for m in messages
        ]
        return JsonResponse({'success': True, 'messages': result})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
def api_post_join(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False, 'message': '로그인이 필요합니다.'}, status=401)
    try:
        user = BaseUserInformation_data.objects.get(id=request.session['user_id'])
        post = Post_Community.objects.get(id=post_id)

        if post.user.id == user.id:
            return JsonResponse({'success': False, 'message': '본인 글에는 참여할 수 없습니다.'}, status=400)
        if not post.is_open:
            return JsonResponse({'success': False, 'message': '이미 모집이 완료된 글입니다.'}, status=400)

        # 현재 실제로 참여 중인지만 체크 (탈퇴했으면 통과)
        if PostParticipant.objects.filter(post=post, user=user).exists():
            return JsonResponse({'success': False, 'message': '이미 참여한 게시글입니다.'}, status=400)

        # 다른 파티 참여 중
        if PostParticipant.objects.filter(user=user, post__is_open=True).exists():
            return JsonResponse({'success': False, 'message': '이미 다른 파티에 참여 중입니다.'}, status=400)

        # 기존 JoinRequest 처리
        existing = JoinRequest.objects.filter(post=post, user=user).first()

        if existing:
            if existing.status == 'pending':
                return JsonResponse({'success': False, 'message': '이미 가입 신청 중입니다.'}, status=400)
            else:
                # rejected 또는 accepted 후 탈퇴 → 재신청: 기존 요청 재활용
                existing.status = 'pending'
                existing.save()
                join_req = existing

                # 버그2 수정: 이전 알림 중 pending 상태인 것만 남기고
                # 기존 join_request 알림을 삭제하고 새로 생성
                Notification.objects.filter(
                    related_join_request=join_req,
                    type='join_request'
                ).delete()
        else:
            join_req = JoinRequest.objects.create(post=post, user=user, status='pending')

        # 게시글 주인에게 알림 생성
        Notification.objects.create(
            user    = post.user,
            type    = 'join_request',
            message = f'{user.username}님이 [{post.post_title}] 파티에 가입 신청했어요.',
            related_join_request = join_req,
        )

        return JsonResponse({'success': True, 'status': 'pending'})

    except Post_Community.DoesNotExist:
        return JsonResponse({'success': False, 'message': '게시글을 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_join_respond(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    try:
        data      = json.loads(request.body)
        req_id    = data.get('request_id')
        action    = data.get('action')  # 'accept' or 'reject'
        user_id   = request.session['user_id']

        join_req  = JoinRequest.objects.select_related('post', 'user').get(id=req_id)

        # 게시글 주인만 처리 가능
        if join_req.post.user.id != user_id:
            return JsonResponse({'success': False, 'message': '권한이 없습니다.'}, status=403)

        if action == 'accept':
            join_req.status = 'accepted'
            join_req.save()

            # 실제 파티 참여 처리
            PostParticipant.objects.get_or_create(post=join_req.post, user=join_req.user)
            join_req.post.current_member += 1
            if join_req.post.current_member >= join_req.post.total_member:
                join_req.post.is_open = False
            join_req.post.save()

            Notification.objects.create(
                user    = join_req.user,
                type    = 'join_accept',
                message = f'[{join_req.post.post_title}] 파티 가입이 수락되었습니다! 🎉',
                related_join_request = join_req,
            )
            return JsonResponse({'success': True, 'action': 'accept'})

        elif action == 'reject':
            join_req.status = 'rejected'
            join_req.save()

            Notification.objects.create(
                user    = join_req.user,
                type    = 'join_reject',
                message = f'[{join_req.post.post_title}] 파티 가입이 거절되었습니다.',
                related_join_request = join_req,
            )
            return JsonResponse({'success': True, 'action': 'reject'})

        return JsonResponse({'success': False, 'message': '잘못된 동작'}, status=400)

    except JoinRequest.DoesNotExist:
        return JsonResponse({'success': False, 'message': '신청을 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
def api_notifications_read(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    Notification.objects.filter(user_id=request.session['user_id'], is_read=False).update(is_read=True)
    return JsonResponse({'success': True})

def api_notifications(request):
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)

    notifs = Notification.objects.filter(
        user_id=request.session['user_id']
    ).select_related('related_join_request').order_by('-created_at')[:30]

    result = []
    for n in notifs:
        item = {
            'id'        : n.id,
            'type'      : n.type,
            'message'   : n.message,
            'is_read'   : n.is_read,
            'created_at': n.created_at.strftime('%m/%d %H:%M'),
            'request_id': n.related_join_request.id if n.related_join_request else None,
            'request_status': n.related_join_request.status if n.related_join_request else None,
        }
        result.append(item)

    unread = Notification.objects.filter(user_id=request.session['user_id'], is_read=False).count()
    return JsonResponse({'success': True, 'notifications': result, 'unread': unread})

def api_dm_send(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    try:
        data     = json.loads(request.body)
        to_name  = data.get('to_username', '').strip()
        message  = data.get('message', '').strip()
        if not message:
            return JsonResponse({'success': False, 'message': '메시지를 입력해주세요.'})
        sender   = BaseUserInformation_data.objects.get(id=request.session['user_id'])
        receiver = BaseUserInformation_data.objects.get(username=to_name)
        DirectMessage.objects.create(sender=sender, receiver=receiver, message=message)
        return JsonResponse({'success': True})
    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False, 'message': '유저를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def api_dm_history(request, username):
    if request.method != 'GET':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    try:
        from django.db.models import Q
        from django.utils import timezone
        me    = BaseUserInformation_data.objects.get(id=request.session['user_id'])
        other = BaseUserInformation_data.objects.get(username=username)
        msgs  = DirectMessage.objects.filter(
            Q(sender=me, receiver=other) | Q(sender=other, receiver=me)
        ).order_by('sent_at')

        def fmt(dt):
            local = dt.astimezone(timezone.get_current_timezone())
            return local.strftime('%H:%M')

        result = [{'username': m.sender.username, 'message': m.message, 'time': fmt(m.sent_at)} for m in msgs]
        return JsonResponse({'success': True, 'messages': result})
    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_notifications_clear(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    user = BaseUserInformation_data.objects.get(id=request.session['user_id'])
    Notification.objects.filter(user=user).delete()
    return JsonResponse({'success': True})

def api_report(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if not request.session.get('user_id'):
        return JsonResponse({'success': False}, status=401)
    data     = json.loads(request.body)
    reporter = BaseUserInformation_data.objects.get(id=request.session['user_id'])
    reported = BaseUserInformation_data.objects.get(username=data['reported_username'])
    if reporter == reported:
        return JsonResponse({'success': False, 'message': '자기 자신은 신고할 수 없어요.'})
    UserReport.objects.create(
        reporter=reporter, reported=reported,
        category=data['category'], detail=data['detail']
    )
    return JsonResponse({'success': True})

def admin_panel(request):
    if request.session.get('username') != 'admin':
        return render('/deai_main/')
    return render(request, 'AdminPanel.html')

def api_admin_reports(request):
    if request.session.get('username') != 'admin':
        return JsonResponse({'success': False}, status=403)
    reports = UserReport.objects.select_related('reporter','reported').order_by('-created_at')
    return JsonResponse({'success': True, 'reports': [{
        'id'        : r.id,
        'reporter'  : r.reporter.username,
        'reported'  : r.reported.username,
        'category'  : r.category,
        'detail'    : r.detail,
        'status'    : r.status,
        'created_at': r.created_at.strftime('%m/%d %H:%M'),
    } for r in reports]})

def api_admin_report_action(request):
    if request.session.get('username') != 'admin':
        return JsonResponse({'success': False}, status=403)
    data      = json.loads(request.body)
    report    = UserReport.objects.get(id=data['report_id'])
    report.status = data['action']
    report.save()
    if data['action'] == 'blocked':
        from django.utils import timezone
        from datetime import timedelta
        report.reported.blocked_until = timezone.now() + timedelta(hours=24)
        report.reported.save()
    return JsonResponse({'success': True})

def api_admin_user_lookup(request):
    if request.session.get('username') != 'admin':
        return JsonResponse({'success': False}, status=403)

    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'success': False, 'message': '검색어를 입력해주세요.'})

    try:
        user  = BaseUserInformation_data.objects.get(username=q)
        games = list(UserPreferGame.objects.filter(user=user).values(
            'game_id', 'name_tag', 'tier', 'score_best', 'score_current', 'sub_info'
        ))

        # blocked_until 필드가 있는 경우만 처리
        blocked_str = None
        if hasattr(user, 'blocked_until') and user.blocked_until:
            from django.utils import timezone as tz
            if user.blocked_until > tz.now():
                blocked_str = user.blocked_until.strftime('%m/%d %H:%M')

        return JsonResponse({'success': True, 'user': {
            'username'     : user.username,
            'email'        : user.email,
            'password_hash': user.password,
            'joined_at'    : user.created_at.strftime('%Y-%m-%d %H:%M'),
            'blocked_until': blocked_str,
            'games'        : games,
        }})

    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False, 'message': '존재하지 않는 유저입니다.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

def api_admin_analytics(request):
    if request.session.get('username') != 'admin':
        return JsonResponse({'success': False}, status=403)

    from django.db.models import Count

    # ── 유저 통계 ──
    total_users   = BaseUserInformation_data.objects.count()
    active_users  = BaseUserInformation_data.objects.filter(is_active=True).count()
    blocked_users = BaseUserInformation_data.objects.filter(
        blocked_until__gt=timezone.now()
    ).count()

    # ── 게시글 통계 ──
    total_posts  = Post_Community.objects.count()
    open_posts   = Post_Community.objects.filter(is_open=True).count()
    closed_posts = total_posts - open_posts

    # ── 메시지 통계 ──
    party_messages = ChatMessage.objects.count()
    dm_messages    = DirectMessage.objects.count()
    total_messages = party_messages + dm_messages

    # ── 신고 통계 ──
    total_reports   = UserReport.objects.count()
    pending_reports = UserReport.objects.filter(status='pending').count()

    # ── 게임별 유저 분포 ──
    game_dist_qs = UserPreferGame.objects.values('game_id').annotate(cnt=Count('id')).order_by('-cnt')
    game_dist = {row['game_id']: row['cnt'] for row in game_dist_qs}

    # ── 게임별 게시글 수 ──
    post_by_game_qs = Post_Community.objects.values('game_id').annotate(cnt=Count('id')).order_by('-cnt')
    post_by_game = {row['game_id']: row['cnt'] for row in post_by_game_qs}

    # ── 신고 카테고리 분포 ──
    rep_cat_qs = UserReport.objects.values('category').annotate(cnt=Count('id')).order_by('-cnt')
    report_category = {row['category']: row['cnt'] for row in rep_cat_qs}

    # ── TOP 5 게시글 작성자 ──
    top_posters = list(
        Post_Community.objects.values('user__username')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )
    top_posters = [{'username': r['user__username'], 'count': r['count']} for r in top_posters]

    # ── TOP 5 채팅 활성 유저 ──
    top_chatters = list(
        ChatMessage.objects.values('user__username')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )
    top_chatters = [{'username': r['user__username'], 'count': r['count']} for r in top_chatters]

    # ── 최근 활동 타임라인 (최신 10개) ──
    recent_activity = []

    recent_posts = Post_Community.objects.select_related('user').order_by('-post_upload_at')[:4]
    for p in recent_posts:
        recent_activity.append({
            'text' : f'{p.user.username}님이 [{p.post_title}] 게시글 작성',
            'time' : p.post_upload_at.strftime('%m/%d %H:%M'),
            'color': '#c9a84c',
            'sort' : p.post_upload_at,
        })

    recent_reports = UserReport.objects.select_related('reporter', 'reported').order_by('-created_at')[:3]
    for r in recent_reports:
        recent_activity.append({
            'text' : f'{r.reporter.username}님이 {r.reported.username}님 신고 ({r.category})',
            'time' : r.created_at.strftime('%m/%d %H:%M'),
            'color': '#ef4444',
            'sort' : r.created_at,
        })

    recent_joins = PostParticipant.objects.select_related('user', 'post').order_by('-joined_at')[:3]
    for j in recent_joins:
        recent_activity.append({
            'text' : f'{j.user.username}님이 [{j.post.post_title}] 파티 참여',
            'time' : j.joined_at.strftime('%m/%d %H:%M'),
            'color': '#10b981',
            'sort' : j.joined_at,
        })

    recent_activity.sort(key=lambda x: x['sort'], reverse=True)
    for a in recent_activity:
        del a['sort']
    recent_activity = recent_activity[:10]

    return JsonResponse({
        'success'        : True,
        'total_users'    : total_users,
        'active_users'   : active_users,
        'blocked_users'  : blocked_users,
        'total_posts'    : total_posts,
        'open_posts'     : open_posts,
        'closed_posts'   : closed_posts,
        'party_messages' : party_messages,
        'dm_messages'    : dm_messages,
        'total_messages' : total_messages,
        'total_reports'  : total_reports,
        'pending_reports': pending_reports,
        'game_dist'      : game_dist,
        'post_by_game'   : post_by_game,
        'report_category': report_category,
        'top_posters'    : top_posters,
        'top_chatters'   : top_chatters,
        'recent_activity': recent_activity,
    })

def api_admin_unblock(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    if request.session.get('username') != 'admin':
        return JsonResponse({'success': False}, status=403)
    try:
        data     = json.loads(request.body)
        username = data.get('username', '').strip()
        user     = BaseUserInformation_data.objects.get(username=username)
        user.blocked_until = None
        user.save()
        return JsonResponse({'success': True})
    except BaseUserInformation_data.DoesNotExist:
        return JsonResponse({'success': False, 'message': '존재하지 않는 유저입니다.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def api_send_verify_code(request):
    """이메일로 6자리 인증 코드 발송"""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    try:
        data  = json.loads(request.body)
        email = data.get('email', '').strip()
        if not email:
            return JsonResponse({'success': False, 'message': '이메일을 입력해주세요.'})
        if BaseUserInformation_data.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': '이미 사용 중인 이메일입니다.'})

        code = str(random.randint(100000, 999999))
        request.session['email_verify_code']  = code
        request.session['email_verify_email'] = email
        request.session['email_verify_at']    = timezone.now().isoformat()

        send_mail(
            subject        = '[Deai] 이메일 인증 코드',
            message        = f'인증 코드: {code}\n\n이 코드는 5분간 유효합니다.',
            from_email     = settings.DEFAULT_FROM_EMAIL,
            recipient_list = [email],
            fail_silently  = False,
        )
        print(f"[이메일 인증] {email} → 코드 {code} 발송", flush=True)
        return JsonResponse({'success': True})

    except Exception as e:
        print(f"[이메일 인증 오류] {e}", flush=True)
        return JsonResponse({'success': False, 'message': f'이메일 발송 실패: {str(e)}'}, status=500)


def api_verify_code(request):
    """인증 코드 확인 후 회원가입 완료"""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    try:
        data        = json.loads(request.body)
        code_input  = data.get('code', '').strip()
        saved_code  = request.session.get('email_verify_code')
        saved_email = request.session.get('email_verify_email')
        saved_at    = request.session.get('email_verify_at')

        if not saved_code or not saved_email:
            return JsonResponse({'success': False, 'message': '인증 코드를 먼저 요청해주세요.'})

        # 5분 만료 체크
        verified_at = datetime.fromisoformat(saved_at)
        if timezone.is_naive(verified_at):
            from django.utils.timezone import make_aware
            verified_at = make_aware(verified_at)
        if timezone.now() > verified_at + timedelta(minutes=5):
            return JsonResponse({'success': False, 'message': '인증 코드가 만료되었습니다. 다시 요청해주세요.'})

        if code_input != saved_code:
            return JsonResponse({'success': False, 'message': '인증 코드가 올바르지 않습니다.'})

        username  = data.get('username', '').strip()
        password  = data.get('password', '').strip()

        if not username or not password:
            return JsonResponse({'success': False, 'message': '회원 정보가 올바르지 않습니다.'})
        if not re.match(r'^[a-zA-Z0-9]{3,}$', username):
            return JsonResponse({'success': False, 'message': '유저 이름은 영문과 숫자만 사용할 수 있습니다.'})
        if len(password) < 8 or not re.search(r'[^A-Za-z0-9]', password):
            return JsonResponse({'success': False, 'message': '비밀번호 조건을 확인해주세요.'})
        if BaseUserInformation_data.objects.filter(username=username).exists():
            return JsonResponse({'success': False, 'message': '이미 사용 중인 닉네임입니다.'})
        if BaseUserInformation_data.objects.filter(email=saved_email).exists():
            return JsonResponse({'success': False, 'message': '이미 사용 중인 이메일입니다.'})

        user = BaseUserInformation_data.objects.create(
            username  = username,
            email     = saved_email,
            password  = make_password(password),
            is_active = True,
        )
        request.session['user_id']  = user.id
        request.session['username'] = user.username
        request.session['email']    = user.email
        for key in ('email_verify_code', 'email_verify_email', 'email_verify_at'):
            request.session.pop(key, None)

        print(f"[회원가입 완료] {username} ({saved_email})", flush=True)
        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'message': f'서버 오류: {str(e)}'}, status=500)

def api_game_stats(request):
    """게임별 선택 유저 수 반환"""
    from django.db.models import Count
    stats = (
        UserPreferGame.objects
        .values('game_id')
        .annotate(count=Count('id'))
    )
    # game_id가 문자열(lol, val...) 또는 숫자(1~5) 둘 다 대응
    # selectGame.html의 id는 1~5 숫자형
    ID_MAP = {'lol':1, 'val':2, 'ow':3, 'fifa':4, 'genshin':5}
    result = []
    for s in stats:
        gid = s['game_id']
        numeric_id = ID_MAP.get(gid, gid)  # 이미 숫자면 그대로
        try:
            numeric_id = int(numeric_id)
        except (ValueError, TypeError):
            pass
        result.append({'game_id': numeric_id, 'count': s['count']})
    return JsonResponse({'success': True, 'stats': result})