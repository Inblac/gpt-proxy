import os
import configparser
from typing import List, Optional
from . import logger

# 密钥状态常量
KEY_STATUS_ACTIVE = "active"
KEY_STATUS_INACTIVE = "inactive"
KEY_STATUS_REVOKED = "revoked"

# 数据库配置
DB_TYPE = "sqlite"  # 默认使用sqlite
DB_CONNECTION_PARAMS = {}  # 默认连接参数为空

# OpenAI API 端点
OPENAI_API_ENDPOINT: str = "https://api.openai.com/v1/chat/completions"
OPENAI_VALIDATION_ENDPOINT: str = "https://api.openai.com/v1/models"

# 代理认证
PROXY_API_KEYS: List[str] = []
PROXY_API_KEY_HEADER: str = "X-Proxy-API-Key"

# JWT 配置
JWT_SECRET_KEY: Optional[str] = None
JWT_ALGORITHM: str = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1小时

# 应用配置
APP_CONFIG_MAX_RETRIES: int = 5
APP_LOG_LEVEL: str = "info"  # 默认日志级别

# OpenAI API 密钥轮换配置
MAX_CALLS_PER_KEY_PER_WINDOW: int = 1000
USAGE_WINDOW_SECONDS: int = 3600  # 1小时
# 查询活跃API密钥时返回的最大数量
MAX_ACTIVE_KEYS_LIMIT: int = 100

# 配置文件路径（在'gpt_proxy'包的父目录中）
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "config.ini")


def load_app_config():
    """从config.ini文件加载应用配置"""
    global PROXY_API_KEYS, JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, APP_CONFIG_MAX_RETRIES
    global OPENAI_API_ENDPOINT, OPENAI_VALIDATION_ENDPOINT, PROXY_API_KEY_HEADER
    global MAX_CALLS_PER_KEY_PER_WINDOW, USAGE_WINDOW_SECONDS, MAX_ACTIVE_KEYS_LIMIT, DB_TYPE, DB_CONNECTION_PARAMS
    global APP_LOG_LEVEL

    config_parser = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE_PATH):
        logger.warning(f"配置文件 '{CONFIG_FILE_PATH}' 不存在。")
        PROXY_API_KEYS = []
        # 生成临时密钥
        import secrets

        JWT_SECRET_KEY = secrets.token_urlsafe(32)
        logger.warning(f"未找到配置文件或JWT_SECRET_KEY。已生成临时JWT_SECRET_KEY: {JWT_SECRET_KEY}")
        logger.warning("请将其添加到您的config.ini文件中的[jwt]部分，例如: secret_key = YOUR_GENERATED_KEY")
        return

    try:
        config_parser.read(CONFIG_FILE_PATH)

        # 加载代理API密钥
        if "proxy_auth" in config_parser and "api_keys" in config_parser["proxy_auth"]:
            keys_str = config_parser["proxy_auth"]["api_keys"]
            PROXY_API_KEYS = [key.strip() for key in keys_str.split(",") if key.strip()]
            if PROXY_API_KEYS:
                logger.info(f"从 '{CONFIG_FILE_PATH}' 加载了 {len(PROXY_API_KEYS)} 个代理API Key。")
            else:
                logger.warning(f"在 '{CONFIG_FILE_PATH}' 的[proxy_auth]部分找到了'api_keys'，但值为空或格式不正确。")
                PROXY_API_KEYS = []

            PROXY_API_KEY_HEADER = config_parser["proxy_auth"].get("proxy_api_key_header", PROXY_API_KEY_HEADER)
            logger.info(f"代理API密钥头部设置为: '{PROXY_API_KEY_HEADER}'")
        else:
            logger.warning(f"在 '{CONFIG_FILE_PATH}' 中未找到[proxy_auth]部分或'api_keys'键。")
            PROXY_API_KEYS = []

        # 加载JWT设置
        if "jwt" in config_parser:
            JWT_SECRET_KEY = config_parser["jwt"].get("secret_key", None)
            JWT_ALGORITHM = config_parser["jwt"].get("algorithm", "HS256")
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES = config_parser["jwt"].getint("access_token_expire_minutes", 60)

            if not JWT_SECRET_KEY:
                import secrets

                JWT_SECRET_KEY = secrets.token_urlsafe(32)
                logger.warning(
                    f"在 '{CONFIG_FILE_PATH}' 的[jwt]部分未找到'secret_key'。已生成临时JWT_SECRET_KEY: {JWT_SECRET_KEY}"
                )
                logger.warning("强烈建议您在config.ini中设置一个持久的secret_key。")

            logger.info(f"JWT配置已加载: 算法='{JWT_ALGORITHM}', Token有效期={JWT_ACCESS_TOKEN_EXPIRE_MINUTES}分钟。")
        else:
            logger.warning(f"在 '{CONFIG_FILE_PATH}' 中未找到[jwt]部分。将使用默认JWT设置和生成的密钥。")
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)
            logger.warning(f"已生成临时JWT_SECRET_KEY: {JWT_SECRET_KEY}。请添加到config.ini。")

        # 加载应用设置
        if "App" in config_parser:
            APP_CONFIG_MAX_RETRIES = config_parser["App"].getint("max_retries", 5)
            if APP_CONFIG_MAX_RETRIES <= 0:
                logger.warning(f"[App] max_retries配置值({APP_CONFIG_MAX_RETRIES})无效。将使用默认值1。")
                APP_CONFIG_MAX_RETRIES = 1
            else:
                logger.info(f"[App] max_retries配置已加载: {APP_CONFIG_MAX_RETRIES}")
                
            # 加载日志级别设置
            APP_LOG_LEVEL = config_parser["App"].get("log_level", "info").lower()
            valid_log_levels = ["debug", "info", "warning", "error", "critical"]
            if APP_LOG_LEVEL not in valid_log_levels:
                logger.warning(f"[App] log_level配置值('{APP_LOG_LEVEL}')无效。将使用默认值'info'。")
                APP_LOG_LEVEL = "info"
            else:
                logger.info(f"[App] log_level配置已加载: {APP_LOG_LEVEL}")
        else:
            logger.warning(
                f"在 '{CONFIG_FILE_PATH}' 中未找到[App]部分。将使用默认配置。"
            )

        # 加载OpenAI API端点配置
        if "OpenAI_Endpoints" in config_parser:
            OPENAI_API_ENDPOINT = config_parser["OpenAI_Endpoints"].get("chat_completions_url", OPENAI_API_ENDPOINT)
            OPENAI_VALIDATION_ENDPOINT = config_parser["OpenAI_Endpoints"].get(
                "validation_url", OPENAI_VALIDATION_ENDPOINT
            )
            logger.info(f"OpenAI API端点: 聊天='{OPENAI_API_ENDPOINT}', 验证='{OPENAI_VALIDATION_ENDPOINT}'")
        else:
            logger.warning(f"在 '{CONFIG_FILE_PATH}' 中未找到[OpenAI_Endpoints]部分。将使用默认端点。")

        # 加载OpenAI API密钥轮换配置
        if "OpenAI_API_Keys_Config" in config_parser:
            MAX_CALLS_PER_KEY_PER_WINDOW = config_parser["OpenAI_API_Keys_Config"].getint(
                "max_calls_per_key_per_window", MAX_CALLS_PER_KEY_PER_WINDOW
            )
            USAGE_WINDOW_SECONDS = config_parser["OpenAI_API_Keys_Config"].getint(
                "usage_window_seconds", USAGE_WINDOW_SECONDS
            )
            MAX_ACTIVE_KEYS_LIMIT = config_parser["OpenAI_API_Keys_Config"].getint(
                "max_active_keys_limit", MAX_ACTIVE_KEYS_LIMIT
            )
            logger.info(
                f"OpenAI密钥配置: 最大调用次数={MAX_CALLS_PER_KEY_PER_WINDOW}, 使用窗口秒数={USAGE_WINDOW_SECONDS}, 活跃密钥限制={MAX_ACTIVE_KEYS_LIMIT}"
            )
        else:
            logger.warning(f"在 '{CONFIG_FILE_PATH}' 中未找到[OpenAI_API_Keys_Config]部分。将使用默认轮换配置。")
            
        # 加载数据库配置
        if "Database" in config_parser:
            DB_TYPE = config_parser["Database"].get("type", DB_TYPE).lower()
            logger.info(f"数据库类型设置为: '{DB_TYPE}'")
            
            if DB_TYPE in ["postgresql", "postgres"]:
                DB_CONNECTION_PARAMS = {
                    "host": config_parser["Database"].get("host", "localhost"),
                    "port": config_parser["Database"].getint("port", 5432),
                    "database": config_parser["Database"].get("database", "gpt_proxy"),
                    "user": config_parser["Database"].get("user", "postgres"),
                    "password": config_parser["Database"].get("password", ""),
                }
                logger.info(f"已加载PostgreSQL连接参数: 主机={DB_CONNECTION_PARAMS['host']}, 端口={DB_CONNECTION_PARAMS['port']}, 数据库={DB_CONNECTION_PARAMS['database']}")
        else:
            logger.warning(f"在 '{CONFIG_FILE_PATH}' 中未找到[Database]部分。将使用默认SQLite数据库。")

    except configparser.Error as e:
        logger.error(f"解析配置文件 '{CONFIG_FILE_PATH}' 失败: {e}")
        PROXY_API_KEYS = []
        if not JWT_SECRET_KEY:
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)
            logger.error(f"配置文件解析错误。已生成临时JWT_SECRET_KEY: {JWT_SECRET_KEY}。请检查config.ini。")
    except Exception as e:
        logger.error(f"加载应用配置时发生未知错误: {e}")
        PROXY_API_KEYS = []
        if not JWT_SECRET_KEY:
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)
            logger.error(f"未知配置错误。已生成临时JWT_SECRET_KEY: {JWT_SECRET_KEY}。")
    
    # 更新日志级别
    logger.update_logger_level()


# 模块加载时初始化配置
load_app_config()
