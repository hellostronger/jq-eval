# Celery配置
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "jq_eval",
    broker=f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/1",
    backend=f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/2",
)


@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """在 worker 进程初始化时创建数据库引擎

    这解决了 prefork 模式下 asyncpg 连接池的问题：
    - prefork 模式会在父进程 fork 出子进程
    - asyncpg 连接不能跨进程使用
    - 需要在每个子进程初始化时重新创建连接池
    """
    from app.core.database import _create_celery_engine
    _create_celery_engine()


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs):
    """在 worker 进程退出时清理数据库连接"""
    from app.core.database import dispose_celery_engine
    dispose_celery_engine()


# Celery配置
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,  # 任务完成后再确认，避免worker崩溃时任务丢失
    task_reject_on_worker_lost=True,  # worker丢失时拒绝任务，使其重新入队
    task_time_limit=30 * 60,  # 30分钟超时
    task_soft_time_limit=25 * 60,  # 25分钟软超时
    worker_prefetch_multiplier=1,  # 每次只取一个任务
    worker_max_tasks_per_child=100,  # 每个worker处理100个任务后重启
    imports=[
        "app.tasks.evaluation_tasks",
        "app.tasks.invocation_tasks",
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