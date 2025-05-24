import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 日志级别映射
LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# 默认日志级别
DEFAULT_LOG_LEVEL = "info"

# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# 确保日志目录存在
def ensure_log_dir():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    return log_dir


# 创建并配置根日志记录器
def setup_logger(name=None, level=None):
    """
    设置应用日志记录器

    Args:
        name: 日志记录器名称，默认为根记录器
        level: 日志级别字符串，默认为 info

    Returns:
        配置好的日志记录器实例
    """
    log_level = LOG_LEVELS.get(level or DEFAULT_LOG_LEVEL, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    console_handler.setFormatter(console_format)

    # 创建文件处理器
    log_dir = ensure_log_dir()
    file_name = name or "gpt_proxy"
    log_file = os.path.join(log_dir, f"{file_name}.log")
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)  # 10 MB
    file_handler.setLevel(log_level)
    file_format = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler.setFormatter(file_format)

    # 添加处理器到记录器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# 创建默认记录器
default_logger = setup_logger()


# 快捷函数，便于模块级导入和使用
def get_logger(name=None, level=None):
    """获取或创建指定名称的日志记录器"""
    if not name:
        return default_logger
    return setup_logger(name, level)


def debug(msg, *args, **kwargs):
    """记录DEBUG级别日志"""
    default_logger.debug(msg, *args, **kwargs)


def info(msg, *args, **kwargs):
    """记录INFO级别日志"""
    default_logger.info(msg, *args, **kwargs)


def warning(msg, *args, **kwargs):
    """记录WARNING级别日志"""
    default_logger.warning(msg, *args, **kwargs)


def error(msg, *args, **kwargs):
    """记录ERROR级别日志"""
    default_logger.error(msg, *args, **kwargs)


def critical(msg, *args, **kwargs):
    """记录CRITICAL级别日志"""
    default_logger.critical(msg, *args, **kwargs)
