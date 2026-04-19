# 模块导入测试 - 验证所有模块能正确加载
import pytest


def test_import_core():
    """测试核心模块导入"""
    from app.core import settings
    assert settings.APP_NAME is not None


def test_import_database():
    """测试数据库模块导入"""
    from app.core.database import get_db, AsyncSessionLocal
    assert get_db is not None


def test_import_models():
    """测试模型模块导入"""
    from app.models import Model, Dataset, QARecord, RAGSystem
    assert Model is not None
    assert Dataset is not None


def test_import_evaluation_models():
    """测试评估模型导入"""
    from app.models.evaluation import Evaluation, EvaluationStatus, EvalResult
    assert Evaluation is not None
    assert EvaluationStatus is not None


def test_import_sync_models():
    """测试同步模型导入"""
    from app.models.sync import SyncTask, SyncTaskStatus, DataSource
    assert SyncTask is not None
    assert SyncTaskStatus is not None


def test_import_api_datasets():
    """测试数据集 API 导入"""
    from app.api.v1.datasets import router
    assert router is not None


def test_import_api_models():
    """测试模型 API 导入"""
    from app.api.v1.models import router
    assert router is not None


def test_import_api_rag_systems():
    """测试 RAG 系统 API 导入"""
    from app.api.v1.rag_systems import router
    assert router is not None


def test_import_api_evaluations():
    """测试评估 API 导入"""
    from app.api.v1.evaluations import router
    assert router is not None


def test_import_tasks():
    """测试任务模块导入"""
    from app.tasks import evaluation_task, batch_evaluation_task
    from app.tasks.dataset_tasks import generate_dataset_task, import_dataset_task
    assert evaluation_task is not None
    assert generate_dataset_task is not None


def test_import_milvus_service():
    """测试 Milvus 服务导入"""
    from app.services.milvus.client import MilvusService, get_milvus_service, MilvusClient
    assert MilvusService is not None
    assert get_milvus_service is not None
    assert MilvusClient is not None


def test_import_main():
    """测试主应用导入"""
    from app.main import app, create_app
    assert app is not None
    assert create_app is not None