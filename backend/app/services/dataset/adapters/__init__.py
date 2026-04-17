# 文档适配器模块
from .base import DocumentAdapter, AdapterFactory
from .file_upload_adapter import FileUploadAdapter
from .text_input_adapter import TextInputAdapter
from .existing_doc_adapter import ExistingDocAdapter

__all__ = [
    "DocumentAdapter",
    "AdapterFactory",
    "FileUploadAdapter",
    "TextInputAdapter",
    "ExistingDocAdapter",
]