# Celery配置
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "jq_eval",
    broker=f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/1",
    backend=f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/2",
)

# Celery配置
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30分钟超时
    task_soft_time_limit=25 * 60,  # 25分钟软超时
    worker_prefetch_multiplier=1,  # 每次只取一个任务
    worker_max_tasks_per_child=100,  # 每个worker处理100个任务后重启
    imports=[
        "app.tasks.evaluation_tasks",
        "app.tasks.dataset_tasks",
        "app.tasks.sync_tasks",
        "app.tasks.health_tasks",
        "app.tasks.crawler_tasks",
    ],
)

# Celery Beat定时任务配置
celery_app.conf.beat_schedule = {
    # 每小时爬取所有活跃新闻源
    "crawl-hot-news-hourly": {
        "task": "crawl_all_active_sources",
        "schedule": crontab(minute=0),  # 每小时执行
    },
}