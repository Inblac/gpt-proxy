import itertools
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Any, Optional, Deque
from jose import JWTError, jwt
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import database as db
from . import config  # 用于 JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES

# --- API 密钥轮换和使用情况跟踪的全局状态 ---
_active_key_configs_cycle = itertools.cycle([])
api_key_usage: Dict[str, Deque[datetime]] = {}
MAX_TIMESTAMPS_PER_KEY = 10000
USAGE_WINDOW_SECONDS = 24 * 60 * 60
# MAX_RETRIES 现在在 config.py (APP_CONFIG_MAX_RETRIES) 中配置，并从 config.ini 读取


def update_openai_key_cycle() -> int:
    """
    从数据库更新活动的 OpenAI API 密钥循环。
    返回找到的活动密钥数量。
    """
    global _active_key_configs_cycle
    active_keys = db.get_active_api_keys()
    active_key_count = len(active_keys)

    if active_keys:
        _active_key_configs_cycle = itertools.cycle(active_keys)
        print(f"Updated OpenAI key cycle. {active_key_count} active keys found.")
    else:
        _active_key_configs_cycle = itertools.cycle([])
        print("No active OpenAI keys found in the database for the cycle.")
    return active_key_count


async def get_next_api_key_config() -> Optional[Dict[str, Any]]:
    """
    从循环中检索下一个活动的 API 密钥配置。
    该循环直接包含来自数据库的字典对象。
    """
    global _active_key_configs_cycle
    try:
        key_config = next(_active_key_configs_cycle)
        return key_config
    except StopIteration:  # 如果 _active_key_configs_cycle 是用空列表创建的，则会引发此异常
        print("API 密钥循环为空。正在尝试刷新。")
        active_count_after_refresh = update_openai_key_cycle()  # 刷新循环
        if active_count_after_refresh > 0:
            try:
                key_config = next(_active_key_configs_cycle)
                return key_config
            except StopIteration:
                # 如果 active_count_after_refresh > 0，这种情况应该很少见，
                # 但意味着循环在刷新后立即变空。
                print("API 密钥循环在刷新后立即变空。")
                return None  # 表示没有可用的密钥
        else:
            # 这意味着刷新也没有找到任何密钥
            print("即使刷新后也没有找到活动的 OpenAI API 密钥。")
            return None  # 表示没有可用的密钥


def record_api_key_usage(key_id: str):
    """记录 API Key (identified by key_id) 的使用时间戳，并清理旧记录。"""
    now = datetime.utcnow()
    if key_id not in api_key_usage:
        api_key_usage[key_id] = deque()

    api_key_usage[key_id].append(now)

    cutoff_time = now - timedelta(seconds=USAGE_WINDOW_SECONDS)
    while api_key_usage[key_id] and api_key_usage[key_id][0] < cutoff_time:
        api_key_usage[key_id].popleft()

    while len(api_key_usage[key_id]) > MAX_TIMESTAMPS_PER_KEY:
        api_key_usage[key_id].popleft()


def mask_api_key_for_display(api_key: str) -> str:
    """
    将 API 密钥遮罩以便显示，固定长度为10个字符。
    - 对于 "sk-" 类型的密钥 (例如："sk-xxxxxxxxxxxxABCD"):
        - 如果足够长 (>= 7 个字符): "sk-...ABCD"
        - 如果较短: "sk-...[剩余部分]" 填充到10个字符，例如："sk-...123 "
    - 对于其他类型的密钥 (例如："MYKEYISTHIS"):
        - 如果足够长 (>= 7 个字符): "MYK...THIS"
        - 如果较短 (1-6 个字符): "M...S" (首字符...末字符) 或 "M..." (如果长度为1), 填充到10个字符。
    - 对于 None 或空密钥，返回 "N/A       "。
    """
    target_len = 10
    placeholder = "..."

    if not isinstance(api_key, str) or not api_key:
        return "N/A".ljust(target_len)

    key_len = len(api_key)

    if api_key.startswith("sk-"):
        prefix = "sk-"
        # 需要 3 (前缀) + 3 (占位符) + 4 (后缀) = 10
        if key_len >= (len(prefix) + 4):  # 例如："sk-1234" (长度=7)
            suffix = api_key[-4:]
            return f"{prefix}{placeholder}{suffix}"
        else:  # 比 "sk-XXXX" 短
            rest_of_key = api_key[len(prefix) :]
            masked_key = f"{prefix}{placeholder}{rest_of_key}"
            return masked_key.ljust(target_len)
    else:  # 非 "sk-"
        # 需要 3 (前缀) + 3 (占位符) + 4 (后缀) = 10
        if key_len >= 7:  # 允许前缀3个字符，后缀4个字符
            prefix = api_key[:3]
            suffix = api_key[-4:]
            return f"{prefix}{placeholder}{suffix}"
        else:  # 短于7个字符 (长度 0 到 6)
            if key_len == 0:  # 应该在第一个检查中被捕获
                return "N/A".ljust(target_len)
            if key_len == 1:
                masked_key = f"{api_key[0]}{placeholder}"  # 例如："1..."
            else:  # 长度 2 到 6
                masked_key = f"{api_key[0]}{placeholder}{api_key[-1]}"  # 例如："1...6"
            return masked_key.ljust(target_len)


# 导入此模块时初始化密钥循环。
# main.py 中的 FastAPI 启动事件也会调用此函数，
# 确保在应用程序开始处理请求时它是最新的。
update_openai_key_cycle()


# --- JWT 令牌工具 ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建一个新的 JWT 访问令牌。
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    if not config.JWT_SECRET_KEY:
        # 如果配置加载稳健，理想情况下不应发生这种情况
        raise ValueError("JWT_SECRET_KEY 未设置。无法创建令牌。")

    encoded_jwt = jwt.encode(to_encode, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
    return encoded_jwt
