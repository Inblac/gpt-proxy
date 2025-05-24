import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
import os
from . import logger

DATABASE_NAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gpt_proxy.db")


def get_db_connection():
    """创建并返回一个数据库连接。"""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row  # 允许通过列名访问数据（使结果行为类似字典）
    return conn


def init_db():
    """初始化数据库，创建 openai_keys 表（如果尚不存在）。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS openai_keys (
            id TEXT PRIMARY KEY,
            api_key TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'revoked')),
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            name TEXT,
            total_requests INTEGER NOT NULL DEFAULT 0
        )
    """
    )
    # 检查并添加 total_requests 列（如果旧表存在且没有该列），用于向后兼容
    cursor.execute("PRAGMA table_info(openai_keys)")
    columns = [column[1] for column in cursor.fetchall()]
    if "total_requests" not in columns:
        cursor.execute("ALTER TABLE openai_keys ADD COLUMN total_requests INTEGER NOT NULL DEFAULT 0")
        logger.info("已为现有的'openai_keys'表添加'total_requests'列。")
    conn.commit()
    conn.close()
    logger.info(f"数据库 {DATABASE_NAME} 已初始化，如果不存在则创建了openai_keys表。")


def add_api_key(api_key: str, name: Optional[str] = None, status: str = "active") -> str:
    """添加一个新的 API Key 到数据库。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    key_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    try:
        cursor.execute(
            "INSERT INTO openai_keys (id, api_key, status, created_at, name, total_requests) VALUES (?, ?, ?, ?, ?, ?)",
            (key_id, api_key, status, created_at, name, 0),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"API密钥 {api_key} 已存在。")
    finally:
        conn.close()
    return key_id


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """将 sqlite3.Row 转换为字典。"""
    if row is None:
        return None
    return dict(row)


def get_api_key_by_id(key_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取 API Key。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM openai_keys WHERE id = ?", (key_id,))
    key_data = cursor.fetchone()
    conn.close()
    return _row_to_dict(key_data)


def get_api_key_by_key_value(api_key_value: str) -> Optional[Dict[str, Any]]:
    """根据 API Key 的值获取 API Key。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM openai_keys WHERE api_key = ?", (api_key_value,))
    key_data = cursor.fetchone()
    conn.close()
    return _row_to_dict(key_data)


def get_all_api_keys() -> List[Dict[str, Any]]:
    """获取所有 API Keys。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM openai_keys ORDER BY created_at DESC")
    keys_data = cursor.fetchall()
    conn.close()
    return [item for item in (_row_to_dict(row) for row in keys_data) if item is not None]


def get_api_keys_paginated(
    page: int = 1, page_size: int = 10, status: Optional[str] = None
) -> tuple[List[Dict[str, Any]], int]:
    """获取分页的 API Keys。

    Args:
        page: 页码，从1开始
        page_size: 每页数量
        status: 可选的状态过滤，如'active', 'inactive', 'revoked'

    Returns:
        包含两个元素的元组：(分页后的keys列表, 总记录数)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 计算总记录数
    count_sql = "SELECT COUNT(*) FROM openai_keys"
    params = []

    if status:
        count_sql += " WHERE status = ?"
        params.append(status)

    cursor.execute(count_sql, params)
    total_count = cursor.fetchone()[0]

    # 查询分页数据
    sql = "SELECT * FROM openai_keys"
    if status:
        sql += " WHERE status = ?"

    sql += " ORDER BY last_used_at DESC LIMIT ? OFFSET ?"

    offset = (page - 1) * page_size
    params.append(page_size)
    params.append(offset)

    cursor.execute(sql, params)
    keys_data = cursor.fetchall()
    conn.close()

    return [item for item in (_row_to_dict(row) for row in keys_data) if item is not None], total_count


def get_active_api_keys() -> List[Dict[str, Any]]:
    """获取所有状态为 'active' 的 API Keys。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM openai_keys WHERE status = 'active' ORDER BY last_used_at")
    keys_data = cursor.fetchall()
    conn.close()
    return [item for item in (_row_to_dict(row) for row in keys_data) if item is not None]


def update_api_key_status(key_id: str, status: str) -> bool:
    """更新 API Key 的状态。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE openai_keys SET status = ? WHERE id = ?", (status, key_id))
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()
    return updated_rows > 0


def update_api_key_last_used_at(key_id: str) -> bool:
    """更新 API Key 的 last_used_at 时间戳。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    last_used_at = datetime.now().isoformat()
    cursor.execute("UPDATE openai_keys SET last_used_at = ? WHERE id = ?", (last_used_at, key_id))
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()
    return updated_rows > 0


def update_api_key_name(key_id: str, name: str) -> bool:
    """更新 API Key 的名称。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE openai_keys SET name = ? WHERE id = ?", (name, key_id))
    updated_rows = cursor.rowcount
    conn.commit()
    conn.close()
    return updated_rows > 0


def delete_api_key(key_id: str) -> bool:
    """删除 API Key。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM openai_keys WHERE id = ?", (key_id,))
    deleted_rows = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_rows > 0


def increment_api_key_requests(key_id: str) -> bool:
    """将指定 API Key 的 total_requests 计数加 1。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE openai_keys SET total_requests = total_requests + 1 WHERE id = ?", (key_id,))
        updated_rows = cursor.rowcount
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"增加API密钥请求计数时发生错误，密钥ID {key_id}: {e}")
        conn.rollback()  # 错误时回滚
        return False
    finally:
        conn.close()
    return updated_rows > 0


# 模块导入时初始化数据库并创建表（如果不存在），确保数据库在其他模块访问前准备就绪。
init_db()

if __name__ == "__main__":
    logger.info("数据库已通过模块导入时初始化。此脚本部分用于额外测试。")

    try:
        key_id1 = add_api_key("sk-testkey123", name="测试密钥1")
        logger.info(f"已添加密钥1，ID: {key_id1}")
    except ValueError as e:
        logger.error(str(e))

    try:
        key_id2 = add_api_key("sk-testkey456", name="测试密钥2", status="inactive")
        logger.info(f"已添加密钥2，ID: {key_id2}")
    except ValueError as e:
        logger.error(str(e))

    try:
        key_id3 = add_api_key("sk-testkey789", name="测试密钥3活动")
        logger.info(f"已添加密钥3，ID: {key_id3}")
    except ValueError as e:
        logger.error(str(e))

    logger.info("\n所有密钥:")
    for key in get_all_api_keys():
        logger.info(key)

    logger.info("\n活动密钥:")
    for key in get_active_api_keys():
        logger.info(key)

    key_to_test_ops = get_api_key_by_key_value("sk-testkey123")

    if key_to_test_ops:
        key_id1_ops = key_to_test_ops["id"]
        logger.info(f"\n正在操作ID为{key_id1_ops}的密钥: {key_to_test_ops}")
        update_api_key_status(key_id1_ops, "inactive")
        logger.info(f"已更新密钥ID {key_id1_ops}的状态: {get_api_key_by_id(key_id1_ops)}")
        update_api_key_last_used_at(key_id1_ops)
        logger.info(f"已更新密钥ID {key_id1_ops}的最后使用时间: {get_api_key_by_id(key_id1_ops)}")
        update_api_key_name(key_id1_ops, "我的个人密钥已更新")
        logger.info(f"已更新密钥ID {key_id1_ops}的名称: {get_api_key_by_id(key_id1_ops)}")
    else:
        logger.warning("\n跳过对key_id1的操作，因为未找到或未添加。")

    key_to_delete = get_api_key_by_key_value("sk-testkey456")
    if key_to_delete:
        key_id2_del = key_to_delete["id"]
        logger.info(f"\n删除前ID为{key_id2_del}的密钥: {key_to_delete}")
        delete_api_key(key_id2_del)
        logger.info(f"删除后ID为{key_id2_del}的密钥: {get_api_key_by_id(key_id2_del)}")
    else:
        logger.warning("\n跳过对key_id2的删除，因为未找到或未添加。")

    logger.info("\n操作后所有密钥:")
    for key in get_all_api_keys():
        logger.info(key)

    logger.info("\n操作后活动密钥:")
    for key in get_active_api_keys():
        logger.info(key)

    key_val_search = "sk-testkey789"
    found_key_search = get_api_key_by_key_value(key_val_search)
    if found_key_search:
        logger.info(f"\n通过值'{key_val_search}'找到密钥: {found_key_search}")
    else:
        logger.warning(f"\n未找到值为'{key_val_search}'的密钥。")
