"""Service layer for PyFlame UI Builder."""

from .code_generator import CodeGenerator
from .project_serializer import ProjectSerializer
from .script_analysis import (
    analyze_create_windows,
    detect_classes,
    extract_create_methods,
    list_create_methods_by_class,
    upsert_create_methods_into_class,
)
from .utils import ai_complete, extract_code_block, load_text_file, to_snake

__all__ = [
    'CodeGenerator',
    'ProjectSerializer',
    'analyze_create_windows',
    'detect_classes',
    'extract_create_methods',
    'list_create_methods_by_class',
    'upsert_create_methods_into_class',
    'to_snake',
    'extract_code_block',
    'load_text_file',
    'ai_complete',
]
