import os
import configparser
from typing import List, Optional

# 密钥状态
KEY_STATUS_ACTIVE = "active"
KEY_STATUS_INACTIVE = "inactive"
KEY_STATUS_REVOKED = "revoked"

# OpenAI API 端点
OPENAI_API_ENDPOINT: str = "https://api.openai.com/v1/chat/completions"  # Default, will be overridden by config.ini
OPENAI_VALIDATION_ENDPOINT: str = "https://api.openai.com/v1/models"  # Default, will be overridden by config.ini

# 代理认证
PROXY_API_KEYS: List[str] = []
PROXY_API_KEY_HEADER: str = "X-Proxy-API-Key"  # Default, will be overridden by config.ini

# JWT 配置
JWT_SECRET_KEY: Optional[str] = None
JWT_ALGORITHM: str = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 默认为 1 小时

# 应用特定配置
APP_CONFIG_MAX_RETRIES: int = 5  # 默认值，会被 config.ini 中的配置覆盖

# OpenAI API 密钥轮换配置 (从 config.ini 加载)
MAX_CALLS_PER_KEY_PER_WINDOW: int = 1000  # 默认值
USAGE_WINDOW_SECONDS: int = 3600  # 默认值 (1 小时)

# 配置文件路径
# 假设 config.ini 文件位于 'gpt_proxy' 包的父目录中
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "config.ini")


def load_app_config():
    """从 config.ini 文件加载应用配置。"""
    global PROXY_API_KEYS, JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, APP_CONFIG_MAX_RETRIES, OPENAI_API_ENDPOINT, OPENAI_VALIDATION_ENDPOINT, PROXY_API_KEY_HEADER, MAX_CALLS_PER_KEY_PER_WINDOW, USAGE_WINDOW_SECONDS

    config_parser = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE_PATH):
        print(f"警告: 配置文件 '{CONFIG_FILE_PATH}' 不存在。")
        PROXY_API_KEYS = []
        # 如果未找到配置文件，则生成临时密钥并提示用户
        import secrets

        JWT_SECRET_KEY = secrets.token_urlsafe(32)
        print(f"警告: 未找到配置文件或 JWT_SECRET_KEY。已生成临时 JWT_SECRET_KEY: {JWT_SECRET_KEY}")
        print("请将其添加到您的 config.ini 文件中的 [jwt] 部分，例如: secret_key = YOUR_GENERATED_KEY")
        return

    try:
        config_parser.read(CONFIG_FILE_PATH)

        # 加载代理 API 密钥
        if 'proxy_auth' in config_parser and 'api_keys' in config_parser['proxy_auth']:
            keys_str = config_parser['proxy_auth']['api_keys']
            PROXY_API_KEYS = [key.strip() for key in keys_str.split(',') if key.strip()]
            if PROXY_API_KEYS:
                print(f"从 '{CONFIG_FILE_PATH}' 加载了 {len(PROXY_API_KEYS)} 个代理 API Key。")
            else:
                print(f"警告: 在 '{CONFIG_FILE_PATH}' 的 [proxy_auth] 部分找到了 'api_keys'，但值为空或格式不正确。")
                PROXY_API_KEYS = []

            PROXY_API_KEY_HEADER = config_parser['proxy_auth'].get('proxy_api_key_header', PROXY_API_KEY_HEADER)
            print(f"Proxy API Key Header 设置为: '{PROXY_API_KEY_HEADER}'")
        else:
            print(f"警告: 在 '{CONFIG_FILE_PATH}' 中未找到 [proxy_auth] 部分或 'api_keys' 键。")
            PROXY_API_KEYS = []

        # 加载 JWT 设置
        if 'jwt' in config_parser:
            JWT_SECRET_KEY = config_parser['jwt'].get('secret_key', None)
            JWT_ALGORITHM = config_parser['jwt'].get('algorithm', 'HS256')
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES = config_parser['jwt'].getint('access_token_expire_minutes', 60)

            if not JWT_SECRET_KEY:
                import secrets

                JWT_SECRET_KEY = secrets.token_urlsafe(32)
                print(
                    f"警告: 在 '{CONFIG_FILE_PATH}' 的 [jwt] 部分未找到 'secret_key'。已生成临时 JWT_SECRET_KEY: {JWT_SECRET_KEY}"
                )
                print("强烈建议您在 config.ini 中设置一个持久的 secret_key。")

            print(f"JWT 配置已加载: 算法='{JWT_ALGORITHM}', Token有效期={JWT_ACCESS_TOKEN_EXPIRE_MINUTES}分钟。")
        else:
            print(f"警告: 在 '{CONFIG_FILE_PATH}' 中未找到 [jwt] 部分。将使用默认 JWT 设置和生成的密钥。")
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)  # Ensure secret key is set
            print(f"已生成临时 JWT_SECRET_KEY: {JWT_SECRET_KEY}。请添加到 config.ini。")

        # 加载应用设置
        if 'App' in config_parser:
            APP_CONFIG_MAX_RETRIES = config_parser['App'].getint('max_retries', 5)
            if APP_CONFIG_MAX_RETRIES <= 0:
                print(f"警告: [App] max_retries 配置值 ({APP_CONFIG_MAX_RETRIES}) 无效。将使用默认值 1。")
                APP_CONFIG_MAX_RETRIES = 1  # Ensure at least 1 attempt
            else:
                print(f"[App] max_retries 配置已加载: {APP_CONFIG_MAX_RETRIES}")
        else:
            # 如果未找到 [App] 部分或 max_retries，APP_CONFIG_MAX_RETRIES 将保持其默认值 (5)
            print(
                f"警告: 在 '{CONFIG_FILE_PATH}' 中未找到 [App] 部分或 'max_retries' 键。将使用默认 max_retries: {APP_CONFIG_MAX_RETRIES}。"
            )

        # 加载 OpenAI API 端点配置
        if 'OpenAI_Endpoints' in config_parser:
            OPENAI_API_ENDPOINT = config_parser['OpenAI_Endpoints'].get('chat_completions_url', OPENAI_API_ENDPOINT)
            OPENAI_VALIDATION_ENDPOINT = config_parser['OpenAI_Endpoints'].get(
                'validation_url', OPENAI_VALIDATION_ENDPOINT
            )
            print(f"OpenAI API Endpoints: Chat='{OPENAI_API_ENDPOINT}', Validation='{OPENAI_VALIDATION_ENDPOINT}'")
        else:
            print(f"警告: 在 '{CONFIG_FILE_PATH}' 中未找到 [OpenAI_Endpoints] 部分。将使用默认端点。")

        # 加载 OpenAI API 密钥轮换配置
        if 'OpenAI_API_Keys_Config' in config_parser:
            MAX_CALLS_PER_KEY_PER_WINDOW = config_parser['OpenAI_API_Keys_Config'].getint(
                'max_calls_per_key_per_window', MAX_CALLS_PER_KEY_PER_WINDOW
            )
            USAGE_WINDOW_SECONDS = config_parser['OpenAI_API_Keys_Config'].getint(
                'usage_window_seconds', USAGE_WINDOW_SECONDS
            )
            print(
                f"OpenAI Keys Config: MaxCallsPerWindow={MAX_CALLS_PER_KEY_PER_WINDOW}, UsageWindowSeconds={USAGE_WINDOW_SECONDS}"
            )
        else:
            print(f"警告: 在 '{CONFIG_FILE_PATH}' 中未找到 [OpenAI_API_Keys_Config] 部分。将使用默认轮换配置。")

    except configparser.Error as e:
        print(f"错误: 解析配置文件 '{CONFIG_FILE_PATH}' 失败: {e}")
        PROXY_API_KEYS = []
        if not JWT_SECRET_KEY:  # 即使在解析错误时也确保设置了密钥
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)
            print(f"配置文件解析错误。已生成临时 JWT_SECRET_KEY: {JWT_SECRET_KEY}。请检查 config.ini。")
    except Exception as e:
        print(f"错误: 加载应用配置时发生未知错误: {e}")
        PROXY_API_KEYS = []
        if not JWT_SECRET_KEY:  # 即使在其他错误时也确保设置了密钥
            import secrets

            JWT_SECRET_KEY = secrets.token_urlsafe(32)
            print(f"未知配置错误。已生成临时 JWT_SECRET_KEY: {JWT_SECRET_KEY}。")


# 模块加载时初始化配置
load_app_config()
