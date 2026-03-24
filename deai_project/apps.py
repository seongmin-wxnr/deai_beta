from django.apps import AppConfig
from .riot_ranking import _start_scheduler

class DeaiProjectConfig(AppConfig):
    name = 'deai_project'

def ready(self):
    _start_scheduler()