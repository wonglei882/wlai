"""统一日志配置模块 - Uvicorn风格"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


class UvicornFormatter(logging.Formatter):
    """Uvicorn风格的日志格式化器"""

    # 日志级别颜色（ANSI转义码）
    COLORS = {
        'DEBUG': '\033[36m',  # 青色
        'INFO': '\033[32m',  # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',  # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'

    def __init__(self, use_colors: bool = True):
        """
        初始化格式化器

        Args:
            use_colors: 是否使用颜色（控制台输出使用，文件输出不使用）
        """
        super().__init__()
        self.use_colors = use_colors

    def format(self, record):
        """格式化日志记录为 Uvicorn 风格"""
        # 获取日志级别名称
        levelname = record.levelname

        # 添加颜色（如果启用且终端支持）
        colored_level = f'{self.COLORS.get(levelname, "")}{levelname}{self.RESET}' if self.use_colors and sys.stderr.isatty() else levelname

        # 添加请求追踪ID（如果存在）
        request_id = getattr(record, 'request_id', None)
        request_id_str = f' [{request_id}]' if request_id else ''

        # 格式化时间戳 (YYYY-MM-DD HH:MM:SS)
        timestamp = self.formatTime(record, self.datefmt)

        # Uvicorn风格格式: INFO:     [2024-01-01 12:00:00] module_name - message [request_id]
        # 注意：INFO后面有5个空格，保持对齐
        return f'{colored_level}:     [{timestamp}] {record.name}{request_id_str} - {record.getMessage()}'


# 全局标志，防止重复初始化
_logging_configured = False


def setup_logging(
    level: str = 'INFO', log_to_file: bool = False, log_file_path: str | None = None, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 30
):
    """
    配置统一的 Uvicorn 风格日志系统

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: 是否输出到文件
        log_file_path: 日志文件路径
        max_bytes: 单个日志文件最大字节数（默认10MB）
        backup_count: 保留的备份文件数量（默认30个）
    """
    global _logging_configured

    # 如果已经配置过，直接返回
    if _logging_configured:
        return logging.getLogger()

    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除已有的处理器，避免重复
    root_logger.handlers.clear()

    # 1. 创建控制台处理器（带颜色）
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_formatter = UvicornFormatter(use_colors=True)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 2. 创建文件处理器（如果启用）
    if log_to_file and log_file_path:
        # 确保日志目录存在
        log_file = Path(log_file_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # 使用RotatingFileHandler实现日志轮转
        file_handler = RotatingFileHandler(filename=log_file_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
        file_handler.setLevel(getattr(logging, level.upper()))

        # 文件日志不使用颜色
        file_formatter = UvicornFormatter(use_colors=False)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        # 记录日志配置信息
        root_logger.info(f'日志文件输出已启用: {log_file_path}')
        root_logger.info(f'日志轮转配置: 单文件最大{max_bytes / 1024 / 1024:.1f}MB, 保留{backup_count}个备份')

    # 配置第三方库的日志级别
    _configure_third_party_loggers()

    # 标记为已配置
    _logging_configured = True

    return root_logger


def _configure_third_party_loggers():
    """配置第三方库的日志级别"""
    # SQLAlchemy - 禁用SQL日志
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)

    # aiosqlite - 异步SQLite，禁用DEBUG日志
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)

    # Watchfiles - 开发时的文件监控，降低级别
    logging.getLogger('watchfiles').setLevel(logging.WARNING)

    # httpx/httpcore - HTTP客户端，禁用DEBUG日志
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)

    # openai/anthropic - AI客户端库
    logging.getLogger('openai').setLevel(logging.WARNING)
    logging.getLogger('anthropic').setLevel(logging.WARNING)

    # 应用模块 - AI 统计日志需要保留 INFO 级别输出
    logging.getLogger('app.services.ai_service').setLevel(logging.INFO)
    logging.getLogger('app.api.wizard').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器

    Args:
        name: 日志器名称，通常使用 __name__

    Returns:
        配置好的日志器实例
    """
    return logging.getLogger(name)


# ============================================================================
# 结构化日志扩展（P2-5）
# ============================================================================

from app.core import json_utils as _json
import contextvars
from datetime import datetime as _dt


_correlation_id_var = contextvars.ContextVar('correlation_id', default='')


def _get_correlation_id() -> str:
    """从当前上下文中获取 correlation_id"""
    return _correlation_id_var.get('')


_correlation_id_var_dup = True


def set_correlation_id(cid: str):
    """设置当前上下文的 correlation_id（用于追踪一次生成的全链路）"""
    _correlation_id_var.set(cid)


def get_correlation_id() -> str:
    return _correlation_id_var.get('')


class JSONFormatter(logging.Formatter):
    """JSON 结构化日志格式化器（适合生产环境日志采集）"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化

        Args:
            self:
            record:

        Returns:
            str
        """
        log_entry = {
            'timestamp': _dt.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'correlation_id': getattr(record, 'correlation_id', None) or _get_correlation_id(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = self.formatException(record.exc_info)
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        return _json.dumps(log_entry, ensure_ascii=False)


class CorrelationLoggerAdapter(logging.LoggerAdapter):
    """LoggerAdapter，自动给日志附加 correlation_id"""

    def process(self, msg, kwargs):
        """处理

        Args:
            self:
            msg:
            kwargs:

        Returns:
            None
        """
        extra = kwargs.get('extra', {})
        cid = _get_correlation_id()
        if cid:
            extra['correlation_id'] = cid
        kwargs['extra'] = extra
        return msg, kwargs


def enable_json_logging(json_file_path: str = None):
    """启用 JSON 结构化日志输出（保留控制台彩色日志不变）

    Args:
        json_file_path: JSON 日志文件路径，None 时自动生成
    """
    root = logging.getLogger()
    # 添加 JSON 文件处理器
    if json_file_path:
        _fp = Path(json_file_path)
        _fp.parent.mkdir(parents=True, exist_ok=True)
        jh = RotatingFileHandler(
            filename=str(_fp),
            maxBytes=50 * 1024 * 1024,
            backupCount=10,
            encoding='utf-8',
        )
        jh.setLevel(logging.INFO)
        jh.setFormatter(JSONFormatter())
        root.addHandler(jh)
        root.info(f'JSON结构化日志已启用: {json_file_path}')


def patch_logger(logger_obj):
    """将普通 logger 包装为 CorrelationLoggerAdapter"""
    if not isinstance(logger_obj, CorrelationLoggerAdapter):
        return CorrelationLoggerAdapter(logger_obj, {})
    return logger_obj
