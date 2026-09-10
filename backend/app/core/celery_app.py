# Celery配置
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from celery.schedules import crontab
from app.core.config import settings

# URL 单一来源为 settings（此前此处硬编码 /1 /2 与 config 的 /1 /1、.env.example 的 /0 三处打架）
celery_app = Celery(
    "jq_eval",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Redis 连接池配置 - 提高连接稳定性（Windows 平台优化）
celery_app.conf.broker_transport_options = {
    "socket_timeout": 120,  # socket 操作超时时间(秒)
    "socket_connect_timeout": 30,  # 连接超时时间(秒)
    "visibility_timeout": 7200,  # 消息可见性超时(秒)，应大于最长任务执行时间
    "max_connections": 50,  # 连接池最大连接数
    "health_check_interval": 15,  # 健康检查间隔(秒) - 更频繁检查
    "socket_keepalive": True,  # 启用 TCP keepalive（基础选项）
}

# Redis backend 连接配置
celery_app.conf.result_backend_transport_options = {
    "socket_timeout": 120,
    "socket_connect_timeout": 30,
    "retry_on_timeout": True,  # 超时时自动重试
    "max_connections": 50,
    "socket_keepalive": True,
}

# Broker 连接重试配置
celery_app.conf.broker_connection_retry = True  # 启用连接重试
celery_app.conf.broker_connection_max_retries = None  # 无限重试，避免长时间空闲后连接丢失
# 注：曾有一行 broker_connection_retry_delay=5——非法键（不在 SETTING_KEYS），静默无效；
# 真实重试节奏由 kombu transport 层控制，勿再臆造键名（test_celery_config.py 有自省兜底）
celery_app.conf.broker_connection_retry_on_startup = True  # 启动时连接重试

# 结果后端重试配置
# 注意：result_backend_connection_* 系列并非 Celery 合法键（5.6 实测不在 SETTING_KEYS，
# 配置了也会被静默忽略、形同没配）。合法键为 result_backend_always_retry（重试至
# result_backend_max_retries，None=无限）；连接超时层重试已由上方 transport options 的
# retry_on_timeout 覆盖。键名有效性由 tests/test_celery_config.py 自省兜底。
celery_app.conf.result_backend_always_retry = True
celery_app.conf.result_backend_max_retries = None


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
    worker_cancel_long_running_tasks_on_connection_loss=True,  # 连接丢失时取消长时间运行的任务
    # Windows 平台建议使用 solo 模式，启动命令：
    # celery -A app.core.celery_app worker --pool=solo -l info
    imports=[
        "app.tasks.evaluation_tasks",
        "app.tasks.invocation_tasks",
        "app.tasks.dataset_tasks",
        "app.tasks.sync_tasks",
        "app.tasks.health_tasks",
        "app.tasks.crawler_tasks",
        "app.tasks.load_test_tasks",
        "app.tasks.doc_explanation_tasks",
        "app.tasks.training_data_eval_tasks",
        "app.tasks.doc_parse_tasks",
    ],
)

# Celery Beat定时任务配置
# 任务名拼写错误在运行时只会静默不执行，故由 test_beat_schedule_tasks_registered 兜底
celery_app.conf.beat_schedule = {
    # 每小时爬取所有活跃新闻源
    "crawl-hot-news-hourly": {
        "task": "crawl_all_active_sources",
        "schedule": crontab(minute=0),  # 每小时执行
    },
    # 每 15 分钟巡检中间件健康，组件降级时向 worker 日志输出 WARNING（监控预警）
    "health-check-15min": {
        "task": "health_check_task",
        "schedule": crontab(minute="*/15"),
    },
    # 每日凌晨清理过期失败记录与 MinIO temp 对象
    "cleanup-nightly": {
        "task": "cleanup_task",
        "schedule": crontab(hour=3, minute=17),
        "kwargs": {"days": 30},
    },
}