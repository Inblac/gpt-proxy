from datetime import datetime, timedelta
import httpx
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse

from .. import schemas
from .. import config
from .. import utils
from .. import database as db
from .. import dependencies
from .. import logger

router = APIRouter(
    prefix="/api",
    tags=["Admin"],
    dependencies=[Depends(dependencies.get_current_admin_user)],
)

# 注意: /token端点和根路径的HTML页面已移至main.py


@router.post("/validate_keys", tags=["Admin API Keys Management"])
async def revalidate_all_inactive_keys(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """重新验证所有标记为无效的API Key - 使用聊天接口验证"""
    # 获取所有无效的密钥
    inactive_keys = [key for key in db.get_all_api_keys() if key["status"] == config.KEY_STATUS_INACTIVE]
    logger.info(f"尝试使用聊天接口验证 {len(inactive_keys)} 个无效密钥。")

    # 使用客户端测试每个API密钥
    validation_results = []
    async with httpx.AsyncClient() as client:
        for key in inactive_keys:
            key_id = key["id"]
            key_name = key.get("name", "无名称")
            key_value = key["api_key"]
            key_suffix = key_value[-4:] if key_value else "N/A"  # 用于展示密钥末尾，保持隐私
            try:
                # 使用聊天接口验证API密钥
                chat_payload = {
                    "model": "gpt-4.1-mini",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 10,
                    "temperature": 0.1,
                }

                resp = await client.post(
                    config.OPENAI_API_ENDPOINT,
                    headers={"Authorization": f"Bearer {key_value}", "Content-Type": "application/json"},
                    json=chat_payload,
                    timeout=15.0,
                )

                if resp.status_code == 200:
                    # 密钥有效，将其设置为活动状态
                    db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
                    logger.info(
                        f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 使用聊天接口重新验证成功。状态已更新为 '{config.KEY_STATUS_ACTIVE}'。"
                    )
                    validation_results.append(
                        {
                            "key_id": key_id,
                            "name": key_name,
                            "suffix": key_suffix,
                            "success": True,
                            "new_status": config.KEY_STATUS_ACTIVE,
                            "validation_method": "chat_interface",
                        }
                    )
                else:
                    # 密钥无效
                    try:
                        error_detail = resp.json().get("error", {}).get("message", "未知错误")
                    except:
                        error_detail = f"HTTP {resp.status_code}"

                    logger.warning(
                        f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 验证失败，状态码 {resp.status_code}。错误: {error_detail}"
                    )
                    validation_results.append(
                        {
                            "key_id": key_id,
                            "name": key_name,
                            "suffix": key_suffix,
                            "success": False,
                            "status_code": resp.status_code,
                            "error": error_detail,
                            "validation_method": "chat_interface",
                        }
                    )
            except Exception as e:
                logger.error(f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 重新验证请求错误: {e}")
                validation_results.append(
                    {
                        "key_id": key_id,
                        "name": key_name,
                        "suffix": key_suffix,
                        "success": False,
                        "error": str(e),
                        "validation_method": "chat_interface",
                    }
                )

    # 更新OpenAI密钥循环以反映新的有效密钥
    utils.update_openai_key_cycle()
    return {"message": f"验证了 {len(inactive_keys)} 个无效的密钥", "results": validation_results}


@router.post("/validate_key/{key_id}", tags=["Admin API Keys Management"])
async def validate_single_key(key_id: str, current_user: dict = Depends(dependencies.get_current_admin_user)):
    """验证单个API Key的有效性 - 使用聊天接口验证"""
    # 获取指定的密钥
    key = db.get_api_key_by_id(key_id)
    if not key:
        raise HTTPException(status_code=404, detail=f"未找到ID为 {key_id} 的API Key")
    
    key_name = key.get("name", "无名称")
    key_value = key["api_key"]
    key_suffix = key_value[-4:] if key_value else "N/A"
    logger.info(f"开始验证密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix})")

    try:
        async with httpx.AsyncClient() as client:
            # 使用聊天接口验证API密钥
            chat_payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
                "temperature": 0.1,
            }

            resp = await client.post(
                config.OPENAI_API_ENDPOINT,
                headers={"Authorization": f"Bearer {key_value}", "Content-Type": "application/json"},
                json=chat_payload,
                timeout=15.0,
            )

            if resp.status_code == 200:
                # 密钥有效，将其设置为活动状态
                db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
                logger.info(
                    f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 验证成功。状态已更新为 '{config.KEY_STATUS_ACTIVE}'。"
                )
                # 更新OpenAI密钥循环以反映新的有效密钥
                utils.update_openai_key_cycle()
                
                return {
                    "success": True,
                    "message": "API Key验证成功，状态已更新为有效",
                    "key_id": key_id,
                    "name": key_name,
                    "suffix": key_suffix,
                    "new_status": config.KEY_STATUS_ACTIVE,
                    "validation_method": "chat_interface",
                }
            else:
                # 密钥无效，确保状态为无效
                if key["status"] != config.KEY_STATUS_INACTIVE:
                    db.update_api_key_status(key_id, config.KEY_STATUS_INACTIVE)
                    utils.update_openai_key_cycle()
                
                try:
                    error_detail = resp.json().get("error", {}).get("message", "未知错误")
                except:
                    error_detail = f"HTTP {resp.status_code}"

                logger.warning(
                    f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 验证失败，状态码 {resp.status_code}。错误: {error_detail}"
                )
                
                return {
                    "success": False,
                    "message": f"API Key验证失败: {error_detail}",
                    "key_id": key_id,
                    "name": key_name,
                    "suffix": key_suffix,
                    "status_code": resp.status_code,
                    "error": error_detail,
                    "validation_method": "chat_interface",
                }
                
    except Exception as e:
        logger.error(f"密钥ID {key_id} (名称: {key_name}, 后缀: {key_suffix}) 验证请求错误: {e}")
        return {
            "success": False,
            "message": f"验证请求失败: {str(e)}",
            "key_id": key_id,
            "name": key_name,
            "suffix": key_suffix,
            "error": str(e),
            "validation_method": "chat_interface",
        }


@router.get("/stats", response_model=schemas.GlobalStatsResponse)
async def get_api_key_stats_endpoint():
    all_db_keys = db.get_all_api_keys()
    now = datetime.utcnow()
    one_minute_ago = now - timedelta(minutes=1)
    one_hour_ago = now - timedelta(hours=1)
    twenty_four_hours_ago = now - timedelta(hours=24)

    grand_total_requests_all_time = 0
    grand_total_usage_last_1m = 0
    grand_total_usage_last_1h = 0
    grand_total_usage_last_24h = 0
    active_keys_count = 0
    inactive_keys_count = 0
    revoked_keys_count = 0

    # 如果密钥已从数据库中删除，则从内存中清除过时的使用数据
    valid_key_ids_from_db = {key["id"] for key in all_db_keys}
    current_usage_key_ids = list(utils.api_key_usage.keys())
    for kid_to_clean in current_usage_key_ids:
        if kid_to_clean not in valid_key_ids_from_db:
            if kid_to_clean in utils.api_key_usage:
                del utils.api_key_usage[kid_to_clean]
                print(f"已清理已删除密钥ID的过期使用数据: {kid_to_clean}")

    for key_data in all_db_keys:
        key_id = key_data["id"]

        grand_total_requests_all_time += key_data.get("total_requests", 0)

        if key_id in utils.api_key_usage:
            timestamps: utils.Deque[datetime] = utils.api_key_usage[key_id]

            # 清理旧数据，防止双端队列无限增长
            cutoff_24h = now - timedelta(seconds=utils.USAGE_WINDOW_SECONDS)
            while timestamps and timestamps[0] < cutoff_24h:
                timestamps.popleft()
            while len(timestamps) > utils.MAX_TIMESTAMPS_PER_KEY:
                timestamps.popleft()

            # 统计不同时间窗口的使用次数
            for ts in timestamps:
                if ts >= twenty_four_hours_ago:
                    grand_total_usage_last_24h += 1
                    if ts >= one_hour_ago:
                        grand_total_usage_last_1h += 1
                        if ts >= one_minute_ago:
                            grand_total_usage_last_1m += 1

        status = key_data.get("status")
        if status == config.KEY_STATUS_ACTIVE:
            active_keys_count += 1
        elif status == config.KEY_STATUS_INACTIVE:
            inactive_keys_count += 1
        elif status == config.KEY_STATUS_REVOKED:
            revoked_keys_count += 1

    total_keys_count = len(all_db_keys)

    global_stats_data = schemas.GlobalStats(
        grand_total_requests_all_time=grand_total_requests_all_time,
        grand_total_usage_last_1m=grand_total_usage_last_1m,
        grand_total_usage_last_1h=grand_total_usage_last_1h,
        grand_total_usage_last_24h=grand_total_usage_last_24h,
        active_keys_count=active_keys_count,
        inactive_keys_count=inactive_keys_count,
        revoked_keys_count=revoked_keys_count,
        total_keys_count=total_keys_count,
    )

    return schemas.GlobalStatsResponse(global_stats=global_stats_data)


@router.get("/keys", response_model=schemas.CategorizedOpenAIKeys)
async def get_all_openai_keys_endpoint():
    all_keys_from_db = db.get_all_api_keys()
    valid_keys = []
    invalid_keys = []
    for key_data in all_keys_from_db:
        key_display = schemas.OpenAIKeyDisplay(
            id=key_data["id"],
            api_key_masked=utils.mask_api_key_for_display(key_data["api_key"]),
            status=key_data["status"],
            name=key_data.get("name"),
            created_at=key_data.get("created_at"),
            last_used_at=key_data.get("last_used_at"),
            total_requests=key_data.get("total_requests", 0),
        )
        if key_data["status"] == config.KEY_STATUS_ACTIVE:
            valid_keys.append(key_display)
        else:
            invalid_keys.append(key_display)

    return schemas.CategorizedOpenAIKeys(valid_keys=valid_keys, invalid_keys=invalid_keys)


@router.get("/keys/paginated", response_model=schemas.PaginatedOpenAIKeys)
async def get_paginated_openai_keys_endpoint(page_params: schemas.PageParams = Depends()):
    """获取分页的API Keys列表"""
    keys_data, total_count = db.get_api_keys_paginated(
        page=page_params.page, page_size=page_params.page_size, status=page_params.status
    )

    items = []
    for key_data in keys_data:
        items.append(
            schemas.OpenAIKeyDisplay(
                id=key_data["id"],
                api_key_masked=utils.mask_api_key_for_display(key_data["api_key"]),
                status=key_data["status"],
                name=key_data.get("name"),
                created_at=key_data.get("created_at"),
                last_used_at=key_data.get("last_used_at"),
                total_requests=key_data.get("total_requests", 0),
            )
        )

    total_pages = (total_count + page_params.page_size - 1) // page_params.page_size

    page_info = schemas.PageInfo(
        total=total_count, page=page_params.page, page_size=page_params.page_size, total_pages=total_pages
    )

    return schemas.PaginatedOpenAIKeys(items=items, page_info=page_info)


@router.post("/keys", response_model=schemas.OpenAIKeyDisplay, status_code=201)
async def add_openai_key_endpoint(payload: schemas.NewOpenAIKeyPayload):
    new_key_value = payload.api_key.strip()
    key_name = payload.name.strip() if payload.name else None

    if not new_key_value.startswith("sk-"):
        raise HTTPException(status_code=400, detail="无效的OpenAI API密钥格式。必须以'sk-'开头。")

    existing_key_by_val = db.get_api_key_by_key_value(new_key_value)
    if existing_key_by_val:
        raise HTTPException(
            status_code=409,
            detail=f"以...{new_key_value[-4:]}结尾的API密钥已存在，ID为 {existing_key_by_val['id']}。",
        )

    try:
        key_id = db.add_api_key(api_key=new_key_value, name=key_name, status=config.KEY_STATUS_ACTIVE)
        utils.update_openai_key_cycle()

        added_key_data = db.get_api_key_by_id(key_id)
        if not added_key_data:
            raise HTTPException(status_code=500, detail="添加后无法检索密钥。")

        return schemas.OpenAIKeyDisplay(
            id=added_key_data["id"],
            api_key_masked=utils.mask_api_key_for_display(added_key_data["api_key"]),
            status=added_key_data["status"],
            name=added_key_data.get("name"),
            created_at=added_key_data.get("created_at"),
            last_used_at=added_key_data.get("last_used_at"),
            total_requests=added_key_data.get("total_requests", 0),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        print(f"添加API密钥时出错: {e}")
        raise HTTPException(status_code=500, detail=f"添加密钥时发生意外错误: {str(e)}")


@router.post("/keys/bulk", tags=["Admin API Keys Management"])
async def create_api_keys_bulk(
    keys: schemas.APIKeysBulkCreate, current_user: dict = Depends(dependencies.get_current_admin_user)
):
    """批量添加API密钥"""
    results = []

    for line in keys.keys.split("\n"):
        line = line.strip()
        if not line:
            continue  # 跳过空行

        parts = line.split(",", 1)  # 最多分割一次，格式：api_key 或 api_key,name
        api_key = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else None

        try:
            key_id = db.add_api_key(api_key, name=name)
            results.append({"key": api_key[-4:], "id": key_id, "name": name, "success": True})
        except ValueError as e:
            logger.error(f"添加API密钥时出错: {e}")
            results.append({"key": api_key[-4:], "error": str(e), "success": False})

    # 更新OpenAI密钥循环
    utils.update_openai_key_cycle()
    return {"message": f"处理了 {len(results)} 个API密钥", "results": results}


@router.delete("/keys/{key_id}", tags=["Admin API Keys Management"])
async def delete_api_key(key_id: str, current_user: dict = Depends(dependencies.get_current_admin_user)):
    """删除API密钥"""
    # 先检查密钥是否存在
    key_to_delete = db.get_api_key_by_id(key_id)
    if not key_to_delete:
        raise HTTPException(status_code=404, detail=f"未找到ID为'{key_id}'的API密钥。")

    # 尝试删除密钥
    success = db.delete_api_key(key_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"虽然找到了ID为'{key_id}'的API密钥，但无法从数据库中删除。")

    logger.info(f"API密钥ID '{key_id}' (名称: {key_to_delete.get('name', 'N/A')}) 删除成功。")

    # 清除内存中的使用情况跟踪
    if key_id in utils.api_key_usage:
        del utils.api_key_usage[key_id]
        logger.info(f"已移除已删除密钥ID '{key_id}' 的使用跟踪。")

    # 更新OpenAI密钥循环
    utils.update_openai_key_cycle()
    return {"message": f"API密钥ID '{key_id}' 删除成功。"}


@router.put("/keys/{key_id}/status", tags=["Admin API Keys Management"])
async def update_api_key_status(
    key_id: str,
    status_update: schemas.APIKeyStatusUpdate,
    current_user: dict = Depends(dependencies.get_current_admin_user),
):
    """更新API密钥状态"""
    # 验证新状态是否有效
    new_status = status_update.status
    if new_status not in [config.KEY_STATUS_ACTIVE, config.KEY_STATUS_INACTIVE, config.KEY_STATUS_REVOKED]:
        raise HTTPException(
            status_code=400, detail=f"无效状态: {new_status}。必须是以下之一: active, inactive, revoked。"
        )

    # 检查密钥是否存在
    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"未找到ID为'{key_id}'的API密钥。")

    # 更新状态
    success = db.update_api_key_status(key_id, new_status)
    if not success:
        raise HTTPException(status_code=500, detail=f"无法更新ID为'{key_id}'的API密钥状态。")

    logger.info(f"API密钥ID '{key_id}' (名称: {key_to_update.get('name', 'N/A')}) 状态已更新为 '{new_status}'。")

    # 更新OpenAI密钥循环
    utils.update_openai_key_cycle()
    return {"message": f"API密钥ID '{key_id}' 状态已更新为 '{new_status}'。"}


@router.put("/keys/{key_id}/name", tags=["Admin API Keys Management"])
async def update_api_key_name(
    key_id: str,
    name_update: schemas.APIKeyNameUpdate,
    current_user: dict = Depends(dependencies.get_current_admin_user),
):
    """更新API密钥名称"""
    new_name = name_update.name

    # 检查密钥是否存在
    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"未找到ID为'{key_id}'的API密钥。")

    # 更新名称
    success = db.update_api_key_name(key_id, new_name)
    if not success:
        raise HTTPException(status_code=500, detail=f"无法更新ID为'{key_id}'的API密钥名称。")

    logger.info(f"API密钥ID '{key_id}' (旧名称: {key_to_update.get('name', 'N/A')}) 名称已更新为 '{new_name}'。")
    return {"message": f"API密钥ID '{key_id}' 的名称已更新为 '{new_name}'。"}


@router.post("/keys/reset_all_keys", tags=["Admin API Keys Management"])
async def reset_all_inactive_keys_to_active(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """将所有状态为'inactive'的密钥重置为'active'"""
    inactive_keys = [key for key in db.get_all_api_keys() if key["status"] == config.KEY_STATUS_INACTIVE]
    results = []

    for key in inactive_keys:
        key_id = key["id"]
        try:
            success = db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
            if success:
                results.append({"key_id": key_id, "name": key.get("name"), "success": True})
                logger.info(
                    f"已将密钥ID {key_id} (名称: {key.get('name', 'N/A')}) 从 '{config.KEY_STATUS_INACTIVE}' 重置为 '{config.KEY_STATUS_ACTIVE}'。"
                )
            else:
                results.append({"key_id": key_id, "name": key.get("name"), "success": False})
                logger.warning(f"无法重置密钥ID {key_id} 的状态。可能已被删除或发生其他问题。")
        except Exception as e:
            results.append({"key_id": key_id, "name": key.get("name"), "success": False, "error": str(e)})

    # 更新OpenAI密钥循环
    utils.update_openai_key_cycle()
    return {"message": f"尝试重置 {len(inactive_keys)} 个无效密钥为有效状态", "results": results}


@router.post("/cleanup-usage", tags=["Admin API Keys Management"])
async def cleanup_usage_tracking_data(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """清理内存中的使用情况跟踪数据，删除不再存在于数据库中的密钥的使用情况"""
    active_keys = {key["id"] for key in db.get_all_api_keys()}  # 现有密钥ID的集合
    usage_keys = set(utils.api_key_usage.keys())  # 内存中跟踪的密钥ID

    to_cleanup = usage_keys - active_keys  # 在使用情况中但不在数据库中的密钥

    for kid_to_clean in to_cleanup:
        if kid_to_clean in utils.api_key_usage:
            del utils.api_key_usage[kid_to_clean]
            logger.info(f"已清理已删除密钥ID的过期使用数据: {kid_to_clean}")

    return {"message": f"清理了 {len(to_cleanup)} 个不存在的密钥的使用情况数据", "cleaned_key_ids": list(to_cleanup)}
