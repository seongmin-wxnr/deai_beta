import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name       = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        txt_json = json.loads(text_data)
        message  = txt_json.get('message', '')
        username = txt_json.get('username', '익명')
        post_id  = txt_json.get('post_id')

        if post_id:
            saved_time = await self.save_message(post_id, username, message)
        else:
            from django.utils import timezone
            saved_time = timezone.now().strftime('%H:%M')

        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'chat_message', 'message': message, 'username': username, 'time': saved_time}
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message' : event['message'],
            'username': event['username'],
            'time'    : event.get('time', ''),
        }))

    @sync_to_async
    def save_message(self, post_id, username, message):
        from deai_project.models import Post_Community, BaseUserInformation_data, ChatMessage
        from django.utils import timezone
        try:
            post = Post_Community.objects.get(id=post_id)
            user = BaseUserInformation_data.objects.get(username=username)
            msg  = ChatMessage.objects.create(post=post, user=user, message=message)
            return msg.sent_at.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
        except Exception as e:
            print(f'[파티채팅 저장 오류] {e}')
            return timezone.now().strftime('%H:%M')


class DMConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name       = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'dm_{self.room_name}'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        txt_json    = json.loads(text_data)
        message     = txt_json.get('message', '')
        sender_name = txt_json.get('sender', '')
        recv_name   = txt_json.get('receiver', '')

        saved_time = await self.save_dm(sender_name, recv_name, message)

        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'dm_message', 'message': message, 'username': sender_name, 'time': saved_time}
        )

    async def dm_message(self, event):
        await self.send(text_data=json.dumps({
            'message' : event['message'],
            'username': event['username'],
            'time'    : event.get('time', ''),
        }))

    @sync_to_async
    def save_dm(self, sender_name, receiver_name, message):
        from deai_project.models import BaseUserInformation_data, DirectMessage
        from django.utils import timezone
        try:
            sender   = BaseUserInformation_data.objects.get(username=sender_name)
            receiver = BaseUserInformation_data.objects.get(username=receiver_name)
            msg      = DirectMessage.objects.create(sender=sender, receiver=receiver, message=message)
            return msg.sent_at.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
        except Exception as e:
            print(f'[DM 저장 오류] {e}')
            return timezone.now().strftime('%H:%M')
