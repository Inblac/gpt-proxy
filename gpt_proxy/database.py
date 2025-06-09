"""
数据库连接池和操作模块
"""
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, TypeVar
from pathlib import Path
import urllib.parse

from databases import Database
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, DateTime, select, func
from sqlalchemy.ext.declarative import declarative_base

from . import logger
from .config import DB_TYPE, DB_CONNECTION_PARAMS, MAX_ACTIVE_KEYS_LIMIT

# 数据库路径
DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).joinpath("data")
DATA_DIR.mkdir(exist_ok=True)
DATABASE_NAME = str(DATA_DIR.joinpath("gpt_proxy.db"))

# 构建数据库连接URL
if DB_TYPE in ["postgresql", "postgres"]:
    password = urllib.parse.quote_plus(DB_CONNECTION_PARAMS.get('password', ''))
    DATABASE_URL = f"postgresql://{DB_CONNECTION_PARAMS.get('user', 'postgres')}:{password}@{DB_CONNECTION_PARAMS.get('host', 'localhost')}:{DB_CONNECTION_PARAMS.get('port', 5432)}/{DB_CONNECTION_PARAMS.get('database', 'gpt_proxy')}"
else:  # 默认使用SQLite
    DATABASE_URL = f"sqlite:///{DATABASE_NAME}"

# 创建数据库引擎
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 创建元数据对象
metadata = MetaData()

# 定义OpenAI Keys表
openai_keys = Table(
    "openai_keys",
    metadata,
    Column("id", String, primary_key=True),
    Column("api_key", String, unique=True, nullable=False),
    Column("status", String, nullable=False, default="active"),
    Column("created_at", DateTime, nullable=False),
    Column("last_used_at", DateTime, nullable=True),
    Column("name", String, nullable=True),
    Column("total_requests", Integer, nullable=False, default=0),
)

# 定义API请求日志表
api_request_logs = Table(
    "api_request_logs",
    metadata,
    Column("id", String, primary_key=True),
    Column("key_id", String, nullable=False),
    Column("timestamp", DateTime, nullable=False),
    Column("model", String, nullable=True),
    Column("status", String, nullable=True),
)

# 创建基类
Base = declarative_base(metadata=metadata)

# 配置数据库连接池
if DB_TYPE in ["postgresql", "postgres"]:
    database = Database(DATABASE_URL, min_size=2, max_size=5)
else:  # SQLite
    database = Database(DATABASE_URL)

# 定义通用的行类型
RowType = TypeVar('RowType', bound=Dict[str, Any])

async def connect_to_db():
    """连接到数据库"""
    try:
        await database.connect()
        logger.info(f"已连接到{DB_TYPE}数据库")
    except Exception as e:
        logger.error(f"连接数据库失败: {str(e)}")
        raise

async def disconnect_from_db():
    """断开数据库连接"""
    try:
        await database.disconnect()
        logger.info(f"已从{DB_TYPE}数据库断开连接")
    except Exception as e:
        logger.error(f"断开数据库连接失败: {str(e)}")

def init_db():
    """初始化数据库，创建表（如果不存在）"""
    try:
        metadata.create_all(engine)
        logger.info(f"数据库已初始化，如果不存在则创建了必要的表。使用数据库类型: {DB_TYPE}")
    except Exception as e:
        logger.error(f"初始化数据库失败: {str(e)}")
        raise

async def add_api_key(api_key: str, name: Optional[str] = None, status: str = "active") -> str:
    """添加一个新的 API Key 到数据库。"""
    key_id = str(uuid.uuid4())
    created_at = datetime.now()
    
    try:
        query = openai_keys.insert().values(
            id=key_id,
            api_key=api_key,
            status=status,
            created_at=created_at,
            name=name,
            total_requests=0
        )
        await database.execute(query)
        return key_id
    except Exception as e:
        logger.error(f"添加API密钥失败: {str(e)}")
        raise ValueError(f"API密钥 {api_key} 已存在或添加失败。")

async def get_api_key_by_id(key_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取 API Key。"""
    query = openai_keys.select().where(openai_keys.c.id == key_id)
    result = await database.fetch_one(query)
    if result is None:
        return None
    return dict(result)

async def get_api_key_by_key_value(api_key_value: str) -> Optional[Dict[str, Any]]:
    """根据 API Key 的值获取 API Key。"""
    query = openai_keys.select().where(openai_keys.c.api_key == api_key_value)
    result = await database.fetch_one(query)
    if result is None:
        return None
    return dict(result)

async def get_all_api_keys() -> List[Dict[str, Any]]:
    """获取所有 API Keys。"""
    query = openai_keys.select().order_by(openai_keys.c.created_at.desc())
    results = await database.fetch_all(query)
    return [dict(record) for record in results]

async def get_api_keys_paginated(
    page: int = 1, page_size: int = 10, status: Optional[str] = None
) -> tuple[List[Dict[str, Any]], int]:
    """获取分页的 API Keys。"""
    # 构建条件
    conditions = []
    if status:
        conditions.append(openai_keys.c.status == status)
    
    # 创建查询基础
    base_query = select(openai_keys)
    if conditions:
        for condition in conditions:
            base_query = base_query.where(condition)
    
    # 计算总记录数
    count_query = select(func.count()).select_from(openai_keys)
    if conditions:
        for condition in conditions:
            count_query = count_query.where(condition)
    
    total_count = await database.fetch_val(count_query)
    
    # 查询分页数据
    offset = (page - 1) * page_size
    query = base_query.order_by(
        openai_keys.c.last_used_at.desc()
    ).limit(page_size).offset(offset)
    
    results = await database.fetch_all(query)
    return [dict(record) for record in results], int(total_count)

async def get_active_api_keys() -> List[Dict[str, Any]]:
    """获取所有状态为 'active' 的 API Keys，最多返回配置的结果数量（默认200）。"""
    query = openai_keys.select().where(
        openai_keys.c.status == 'active'
    ).order_by(openai_keys.c.last_used_at).limit(MAX_ACTIVE_KEYS_LIMIT)
    results = await database.fetch_all(query)
    return [dict(record) for record in results]

async def get_inactive_api_keys() -> List[Dict[str, Any]]:
    """获取所有状态为 'inactive' 的 API Keys。"""
    query = openai_keys.select().where(
        openai_keys.c.status == 'inactive'
    ).order_by(openai_keys.c.last_used_at)
    results = await database.fetch_all(query)
    return [dict(record) for record in results]

async def update_api_key_status(key_id: str, status: str) -> bool:
    """更新 API Key 的状态。"""
    query = openai_keys.update().where(
        openai_keys.c.id == key_id
    ).values(status=status)
    result = await database.execute(query)
    return result is not None

async def update_api_key_last_used_at(key_id: str) -> bool:
    """更新 API Key 的 last_used_at 时间戳。"""
    query = openai_keys.update().where(
        openai_keys.c.id == key_id
    ).values(last_used_at=datetime.now())
    result = await database.execute(query)
    return result is not None

async def update_api_key_name(key_id: str, name: str) -> bool:
    """更新 API Key 的名称。"""
    query = openai_keys.update().where(
        openai_keys.c.id == key_id
    ).values(name=name)
    result = await database.execute(query)
    return result is not None

async def delete_api_key(key_id: str) -> bool:
    """删除 API Key。"""
    query = openai_keys.delete().where(openai_keys.c.id == key_id)
    result = await database.execute(query)
    return result is not None

async def increment_api_key_requests(key_id: str) -> bool:
    """将指定 API Key 的 total_requests 计数加 1。"""
    try:
        query = f"""
        UPDATE openai_keys 
        SET total_requests = total_requests + 1 
        WHERE id = :key_id
        """
        result = await database.execute(query=query, values={"key_id": key_id})
        return result is not None
    except Exception as e:
        logger.error(f"增加API密钥请求计数时发生错误，密钥ID {key_id}: {e}")
        return False

# API请求日志相关函数
async def log_api_request(key_id: str, model: Optional[str] = None, status: Optional[str] = None) -> str:
    """记录API请求到日志表"""
    log_id = str(uuid.uuid4())
    timestamp = datetime.now()
    
    try:
        query = api_request_logs.insert().values(
            id=log_id,
            key_id=key_id,
            timestamp=timestamp,
            model=model,
            status=status
        )
        await database.execute(query)
        return log_id
    except Exception as e:
        logger.error(f"记录API请求日志失败: {str(e)}")
        return ""

async def get_api_stats() -> Dict[str, Any]:
    """获取API使用统计数据"""
    try:
        # 获取所有时间的请求总数(从openai_keys表的total_requests字段求和)
        total_all_time_query = select(func.sum(openai_keys.c.total_requests)).select_from(openai_keys)
        total_all_time = await database.fetch_val(total_all_time_query)
        
        # 获取最近24小时的请求总数
        cutoff_24h = datetime.now() - timedelta(hours=24)
        total_24h_query = select(func.count()).select_from(api_request_logs).where(
            api_request_logs.c.timestamp >= cutoff_24h
        )
        total_24h = await database.fetch_val(total_24h_query)
        
        # 获取最近1小时的请求总数
        cutoff_1h = datetime.now() - timedelta(hours=1)
        total_1h_query = select(func.count()).select_from(api_request_logs).where(
            api_request_logs.c.timestamp >= cutoff_1h
        )
        total_1h = await database.fetch_val(total_1h_query)
        
        # 获取最近1分钟的请求总数
        cutoff_1m = datetime.now() - timedelta(minutes=1)
        total_1m_query = select(func.count()).select_from(api_request_logs).where(
            api_request_logs.c.timestamp >= cutoff_1m
        )
        total_1m = await database.fetch_val(total_1m_query)
        
        # 获取各状态的密钥数量
        active_keys_query = select(func.count()).select_from(openai_keys).where(
            openai_keys.c.status == 'active'
        )
        active_keys_count = await database.fetch_val(active_keys_query)
        
        inactive_keys_query = select(func.count()).select_from(openai_keys).where(
            openai_keys.c.status == 'inactive'
        )
        inactive_keys_count = await database.fetch_val(inactive_keys_query)
        
        revoked_keys_query = select(func.count()).select_from(openai_keys).where(
            openai_keys.c.status == 'revoked'
        )
        revoked_keys_count = await database.fetch_val(revoked_keys_query)
        
        total_keys_query = select(func.count()).select_from(openai_keys)
        total_keys_count = await database.fetch_val(total_keys_query)
        
        return {
            "grand_total_requests_all_time": int(total_all_time) if total_all_time is not None else 0,
            "grand_total_usage_last_24h": int(total_24h) if total_24h is not None else 0,
            "grand_total_usage_last_1h": int(total_1h) if total_1h is not None else 0,
            "grand_total_usage_last_1m": int(total_1m) if total_1m is not None else 0,
            "active_keys_count": int(active_keys_count) if active_keys_count is not None else 0,
            "inactive_keys_count": int(inactive_keys_count) if inactive_keys_count is not None else 0,
            "revoked_keys_count": int(revoked_keys_count) if revoked_keys_count is not None else 0,
            "total_keys_count": int(total_keys_count) if total_keys_count is not None else 0
        }
    except Exception as e:
        logger.error(f"获取API统计数据失败: {str(e)}")
        return {
            "grand_total_requests_all_time": 0,
            "grand_total_usage_last_24h": 0,
            "grand_total_usage_last_1h": 0,
            "grand_total_usage_last_1m": 0,
            "active_keys_count": 0,
            "inactive_keys_count": 0,
            "revoked_keys_count": 0,
            "total_keys_count": 0
        }

async def clean_old_api_request_logs(days_to_keep: int = 30) -> int:
    """清理超过指定天数的API请求日志
    
    Args:
        days_to_keep: 要保留的天数，默认30天
        
    Returns:
        删除的记录数量
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        query = api_request_logs.delete().where(api_request_logs.c.timestamp < cutoff_date)
        result = await database.execute(query)
        
        if result:
            logger.info(f"已清理 {result} 条超过 {days_to_keep} 天的API请求日志记录")
        return int(result) if result else 0
    except Exception as e:
        logger.error(f"清理旧API请求日志时出错: {str(e)}")
        return 0

# 模块导入时初始化数据库并创建表（如果不存在）
init_db()
