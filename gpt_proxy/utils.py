import itertools
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Any, Optional, Deque
from jose import jwt
from datetime import datetime, timedelta
import asyncio

from . import database as db
from . import config
from . import logger

# API密钥轮换和使用情况跟踪的全局状态
_active_key_configs_cycle = itertools.cycle([])
api_key_usage: Dict[str, Deque[datetime]] = {}
MAX_TIMESTAMPS_PER_KEY = 10000
USAGE_WINDOW_SECONDS = 24 * 60 * 60
_key_cycle_lock = asyncio.Lock()  # 添加异步锁用于保护key循环访问


async def update_openai_key_cycle() -> int:
    """从数据库更新活动的OpenAI API密钥循环，返回找到的活动密钥数量"""
    global _active_key_configs_cycle
    
    # 首先获取活动的API密钥
    active_keys = await db.get_active_api_keys()
    active_key_count = len(active_keys)
    
    # 然后更新循环，使用锁保护以确保线程安全
    async with _key_cycle_lock:
        if active_keys:
            _active_key_configs_cycle = itertools.cycle(active_keys)
            logger.info(f"已更新OpenAI密钥循环。找到 {active_key_count} 个活动密钥。")
        else:
            _active_key_configs_cycle = itertools.cycle([])
            logger.warning("在数据库中未找到用于循环的活动OpenAI密钥。")
    
    return active_key_count


async def get_next_openai_key_config() -> Optional[Dict[str, Any]]:
    """获取下一个可用的OpenAI API密钥配置，无可用密钥时返回None"""
    global _active_key_configs_cycle
    
    # 先尝试获取一个密钥，使用锁以确保线程安全
    async with _key_cycle_lock:
        try:
            next_key = next(_active_key_configs_cycle, None)
            if next_key is not None:
                return next_key
        except (StopIteration, IndexError, ValueError):
            # 迭代器为空或出现问题
            logger.warning("API密钥循环为空或出错，将尝试刷新。")
    
    # 如果没有可用的密钥，尝试从数据库刷新
    # 注意：此处释放了锁，所以update_openai_key_cycle可以安全地获取锁
    active_key_count = await update_openai_key_cycle()
    
    if active_key_count > 0:
        # 刷新后，尝试再次获取密钥
        async with _key_cycle_lock:
            try:
                return next(_active_key_configs_cycle, None)
            except (StopIteration, IndexError, ValueError):
                logger.error("即使刷新后也没有找到活动的OpenAI API密钥。")
                return None
    else:
        logger.warning("数据库中没有活动的OpenAI密钥。")
        return None


async def record_api_key_usage(key_id: str, model: Optional[str] = None, status: Optional[str] = None):
    """记录API Key使用信息到数据库"""
    try:
        # 增加内存中的计数器（兼容现有代码）
        now = datetime.utcnow()
        if key_id not in api_key_usage:
            api_key_usage[key_id] = deque()
        
        api_key_usage[key_id].append(now)
        
        cutoff_time = now - timedelta(seconds=USAGE_WINDOW_SECONDS)
        while api_key_usage[key_id] and api_key_usage[key_id][0] < cutoff_time:
            api_key_usage[key_id].popleft()
        
        while len(api_key_usage[key_id]) > MAX_TIMESTAMPS_PER_KEY:
            api_key_usage[key_id].popleft()
            
        # 记录到数据库
        await db.log_api_request(key_id, model, status)
        
        # 增加该密钥的total_requests计数
        await db.increment_api_key_requests(key_id)
    except Exception as e:
        logger.error(f"记录API密钥使用情况时出错: {str(e)}")


def mask_api_key_for_display(api_key: str) -> str:
    """
    将API密钥遮罩以便显示，固定长度为10个字符。
    - 对于"sk-"类型密钥: "sk-...ABCD"
    - 对于其他类型密钥: "MYK...THIS"
    - 对于None或空密钥，返回"N/A"
    """
    target_len = 10
    placeholder = "..."

    if not isinstance(api_key, str) or not api_key:
        return "N/A".ljust(target_len)

    key_len = len(api_key)

    if api_key.startswith("sk-"):
        prefix = "sk-"
        if key_len >= (len(prefix) + 4):
            suffix = api_key[-4:]
            return f"{prefix}{placeholder}{suffix}"
        else:
            rest_of_key = api_key[len(prefix) :]
            masked_key = f"{prefix}{placeholder}{rest_of_key}"
            return masked_key.ljust(target_len)
    else:
        if key_len >= 7:
            prefix = api_key[:3]
            suffix = api_key[-4:]
            return f"{prefix}{placeholder}{suffix}"
        else:
            if key_len == 0:
                return "N/A".ljust(target_len)
            if key_len == 1:
                masked_key = f"{api_key[0]}{placeholder}"
            else:
                masked_key = f"{api_key[0]}{placeholder}{api_key[-1]}"
            return masked_key.ljust(target_len)


# JWT令牌工具
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建新的JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    if not config.JWT_SECRET_KEY:
        raise ValueError("JWT_SECRET_KEY未设置。无法创建令牌。")

    encoded_jwt = jwt.encode(to_encode, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
    return encoded_jwt
