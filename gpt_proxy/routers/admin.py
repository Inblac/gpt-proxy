from datetime import datetime, timedelta  # timedelta 在 get_api_key_stats 中使用
import httpx
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Header

# from fastapi.security import OAuth2PasswordRequestForm # 此相关的 token 端点逻辑已移动
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
    dependencies=[Depends(dependencies.get_current_admin_user)],  # 管理员路由的默认依赖项已更新
)

# 注意: 用于提供 HTML 的根路径 GET 路由不使用路由器的默认依赖项，
# 因为它需要可访问以允许用户在页面上输入 API 密钥。
# 如果需要不同的身份验证，我们会在 main.py 中为其创建一个单独的路由器或直接使用 app.get。
# 为简单起见，我们将为此特定路由覆盖依赖项或在内部处理身份验证。

# 为了提供 HTML 页面，我们可能需要一种方法来绕过路由器的默认依赖项。
# 或者，依赖项本身可以更灵活（例如，如果路径是根路径且尚无密钥，则允许）。
# 目前，我们假设 verify_proxy_api_key 用于 API 调用，HTML 服务则以不同方式处理，
# 或者 admin.html 上的客户端 JS 处理初始密钥输入，后续 API 调用使用该密钥。

# 如果初始页面加载时存在问题，让我们调整根路径 GET 路由，使其不使用路由器级别的依赖项。
# 我们可以在主应用程序或不同的路由器上定义它。
# 目前，我将其包含在此处，并假设客户端处理流程。
# 如果直接加载根路径页面需要 HTML 本身在请求头中没有密钥的情况下工作，
# 则此特定端点将需要 `dependencies=[]` 来覆盖路由器的默认设置。
# 然而，最初的 main.py 为 GET 根路径路由设置了 `proxy_api_key_from_header`，
# 这意味着它*可以*接收密钥，但并未对 HTML 响应本身严格强制执行。

# get_admin_page_html 及其 @router.get("") 已移至 main.py
# /token 端点已移至 main.py


@router.post("/validate_keys", tags=["Admin API Keys Management"])
async def revalidate_all_inactive_keys(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """重新验证所有标记为无效的 API Key"""
    # 获取所有无效的密钥
    inactive_keys = [key for key in db.get_all_api_keys() if key["status"] == config.KEY_STATUS_INACTIVE]
    logger.info(f"Attempting to validate {len(inactive_keys)} inactive keys.")

    # 使用客户端测试每个 API 密钥
    validation_results = []
    async with httpx.AsyncClient() as client:
        for key in inactive_keys:
            key_id = key["id"]
            key_name = key.get("name", "无名称")
            key_value = key["api_key"]
            key_suffix = key_value[-4:] if key_value else "N/A"  # 用于展示密钥末尾，保持隐私
            try:
                # 调用 OpenAI 验证端点
                resp = await client.get(
                    config.OPENAI_VALIDATION_ENDPOINT,
                    headers={"Authorization": f"Bearer {key_value}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    # 密钥有效，将其设置为活动状态
                    db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
                    logger.info(
                        f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validated successfully. Status updated to '{config.KEY_STATUS_ACTIVE}'."
                    )
                    validation_results.append(
                        {
                            "key_id": key_id,
                            "name": key_name,
                            "suffix": key_suffix,
                            "success": True,
                            "new_status": config.KEY_STATUS_ACTIVE,
                        }
                    )
                else:
                    # 密钥无效
                    logger.warning(
                        f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) validation failed with status code {resp.status_code}."
                    )
                    validation_results.append(
                        {
                            "key_id": key_id,
                            "name": key_name,
                            "suffix": key_suffix,
                            "success": False,
                            "status_code": resp.status_code,
                            "error": f"API responded with status code {resp.status_code}",
                        }
                    )
            except Exception as e:
                logger.error(f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validation request error: {e}")
                validation_results.append(
                    {
                        "key_id": key_id,
                        "name": key_name,
                        "suffix": key_suffix,
                        "success": False,
                        "error": str(e),
                    }
                )

    # 更新 OpenAI 密钥循环以反映新的有效密钥
    utils.update_openai_key_cycle()
    return {"message": f"验证了 {len(inactive_keys)} 个无效的密钥", "results": validation_results}


@router.get("/stats", response_model=schemas.GlobalStatsResponse)  # 已更新响应模型
async def get_api_key_stats_endpoint():
    all_db_keys = db.get_all_api_keys()
    now = datetime.utcnow()
    one_minute_ago = now - timedelta(minutes=1)
    one_hour_ago = now - timedelta(hours=1)
    twenty_four_hours_ago = now - timedelta(hours=24)  # utils.USAGE_WINDOW_SECONDS 是 24 小时

    grand_total_requests_all_time = 0
    grand_total_usage_last_1m = 0
    grand_total_usage_last_1h = 0
    grand_total_usage_last_24h = 0
    active_keys_count = 0
    inactive_keys_count = 0
    revoked_keys_count = 0

    # 如果密钥已从数据库中删除，则从内存中清除过时的使用数据
    valid_key_ids_from_db = {key['id'] for key in all_db_keys}
    current_usage_key_ids = list(utils.api_key_usage.keys())
    for kid_to_clean in current_usage_key_ids:
        if kid_to_clean not in valid_key_ids_from_db:
            if kid_to_clean in utils.api_key_usage:
                del utils.api_key_usage[kid_to_clean]
                print(f"Cleaned up stale usage data for deleted key_id: {kid_to_clean}")

    for key_data in all_db_keys:
        key_id = key_data['id']

        grand_total_requests_all_time += key_data.get("total_requests", 0)

        if key_id in utils.api_key_usage:
            timestamps: utils.Deque[datetime] = utils.api_key_usage[key_id]

            # 出于常规维护目的，并防止双端队列无限增长，
            # 修剪超过 24 小时前的旧时间戳。
            cutoff_24h = now - timedelta(seconds=utils.USAGE_WINDOW_SECONDS)
            while timestamps and timestamps[0] < cutoff_24h:
                timestamps.popleft()
            while len(timestamps) > utils.MAX_TIMESTAMPS_PER_KEY:  # 每个密钥的最大条目数
                timestamps.popleft()

            # Count for different windows by iterating once
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
    """获取分页的API Keys列表。"""
    keys_data, total_count = db.get_api_keys_paginated(
        page=page_params.page, 
        page_size=page_params.page_size,
        status=page_params.status
    )
    
    items = []
    for key_data in keys_data:
        items.append(schemas.OpenAIKeyDisplay(
            id=key_data["id"],
            api_key_masked=utils.mask_api_key_for_display(key_data["api_key"]),
            status=key_data["status"],
            name=key_data.get("name"),
            created_at=key_data.get("created_at"),
            last_used_at=key_data.get("last_used_at"),
            total_requests=key_data.get("total_requests", 0),
        ))
    
    total_pages = (total_count + page_params.page_size - 1) // page_params.page_size
    
    page_info = schemas.PageInfo(
        total=total_count,
        page=page_params.page,
        page_size=page_params.page_size,
        total_pages=total_pages
    )
    
    return schemas.PaginatedOpenAIKeys(items=items, page_info=page_info)


@router.post("/keys", response_model=schemas.OpenAIKeyDisplay, status_code=201)
async def add_openai_key_endpoint(payload: schemas.NewOpenAIKeyPayload):
    new_key_value = payload.api_key.strip()
    key_name = payload.name.strip() if payload.name else None

    if not new_key_value.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Invalid OpenAI API Key format. Must start with 'sk-'.")

    existing_key_by_val = db.get_api_key_by_key_value(new_key_value)
    if existing_key_by_val:
        raise HTTPException(
            status_code=409,
            detail=f"API key ending with ...{new_key_value[-4:]} already exists with ID {existing_key_by_val['id']}.",
        )

    try:
        key_id = db.add_api_key(api_key=new_key_value, name=key_name, status=config.KEY_STATUS_ACTIVE)
        utils.update_openai_key_cycle()

        added_key_data = db.get_api_key_by_id(key_id)
        if not added_key_data:
            raise HTTPException(status_code=500, detail="Failed to retrieve key after adding.")

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
        print(f"Error adding API key: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while adding the key: {str(e)}")


@router.post("/keys/bulk", tags=["Admin API Keys Management"])
async def create_api_keys_bulk(
    keys: schemas.APIKeysBulkCreate, current_user: dict = Depends(dependencies.get_current_admin_user)
):
    """批量添加 API 密钥"""
    results = []
    
    for line in keys.keys.split('\n'):
        line = line.strip()
        if not line:
            continue  # 跳过空行
        
        parts = line.split(',', 1)  # 最多分割一次，格式：api_key 或 api_key,name
        api_key = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else None
        
        try:
            key_id = db.add_api_key(api_key, name=name)
            results.append({"key": api_key[-4:], "id": key_id, "name": name, "success": True})
        except ValueError as e:
            logger.error(f"Error adding API key: {e}")
            results.append({"key": api_key[-4:], "error": str(e), "success": False})
    
    # 更新 OpenAI 密钥循环以包含新添加的密钥
    utils.update_openai_key_cycle()
    return {"message": f"处理了 {len(results)} 个 API 密钥", "results": results}


@router.delete("/keys/{key_id}", tags=["Admin API Keys Management"])
async def delete_api_key(key_id: str, current_user: dict = Depends(dependencies.get_current_admin_user)):
    """删除 API 密钥"""
    # 先检查密钥是否存在
    key_to_delete = db.get_api_key_by_id(key_id)
    if not key_to_delete:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")
    
    # 尝试删除密钥
    success = db.delete_api_key(key_id)
    if not success:
        # 如果我们找到了密钥，但无法删除它，则出现了一些内部错误
        raise HTTPException(status_code=500, detail=f"Failed to delete API Key with ID '{key_id}' from database, though it was found.")
    
    logger.info(f"API Key ID '{key_id}' (Name: {key_to_delete.get('name', 'N/A')}) deleted successfully.")
    
    # 如果密钥已在内存中跟踪使用情况，则也从中清除
    if key_id in utils.api_key_usage:
        del utils.api_key_usage[key_id]
        logger.info(f"Removed usage tracking for deleted key ID '{key_id}'.")
    
    # 更新 OpenAI 密钥循环以反映删除的密钥
    utils.update_openai_key_cycle()
    return {"message": f"API Key with ID '{key_id}' deleted successfully."}


@router.put("/keys/{key_id}/status", tags=["Admin API Keys Management"])
async def update_api_key_status(
    key_id: str, status_update: schemas.APIKeyStatusUpdate, current_user: dict = Depends(dependencies.get_current_admin_user)
):
    """更新 API 密钥状态"""
    # 验证新状态是否有效
    new_status = status_update.status
    if new_status not in [config.KEY_STATUS_ACTIVE, config.KEY_STATUS_INACTIVE, config.KEY_STATUS_REVOKED]:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}. Must be one of: active, inactive, revoked.")
    
    # 先检查密钥是否存在
    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")
    
    # 尝试更新状态
    success = db.update_api_key_status(key_id, new_status)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to update status for API Key with ID '{key_id}'.")
    
    logger.info(f"API Key ID '{key_id}' (Name: {key_to_update.get('name', 'N/A')}) status updated to '{new_status}'.")
    
    # 更新 OpenAI 密钥循环以反映新的状态
    utils.update_openai_key_cycle()
    return {"message": f"API Key with ID '{key_id}' status updated to '{new_status}'."}


@router.put("/keys/{key_id}/name", tags=["Admin API Keys Management"])
async def update_api_key_name(
    key_id: str, name_update: schemas.APIKeyNameUpdate, current_user: dict = Depends(dependencies.get_current_admin_user)
):
    """更新 API 密钥名称"""
    new_name = name_update.name
    
    # 先检查密钥是否存在
    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")
    
    # 尝试更新名称
    success = db.update_api_key_name(key_id, new_name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to update name for API Key with ID '{key_id}'.")
    
    logger.info(f"API Key ID '{key_id}' (Old Name: {key_to_update.get('name', 'N/A')}) name updated to '{new_name}'.")
    return {"message": f"API Key with ID '{key_id}' name updated to '{new_name}'."}


@router.post("/reset_all_keys", tags=["Admin API Keys Management"])
async def reset_all_inactive_keys_to_active(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """将所有状态为 'inactive' 的密钥重置为 'active'"""
    inactive_keys = [key for key in db.get_all_api_keys() if key["status"] == config.KEY_STATUS_INACTIVE]
    results = []
    
    for key in inactive_keys:
        key_id = key["id"]
        try:
            success = db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
            if success:
                results.append({"key_id": key_id, "name": key.get("name"), "success": True})
                logger.info(
                    f"Reset key ID {key_id} (Name: {key.get('name', 'N/A')}) from '{config.KEY_STATUS_INACTIVE}' to '{config.KEY_STATUS_ACTIVE}'."
                )
            else:
                results.append({"key_id": key_id, "name": key.get("name"), "success": False})
                logger.warning(f"Failed to reset status for key ID {key_id}. It might have been deleted or another issue occurred.")
        except Exception as e:
            results.append({"key_id": key_id, "name": key.get("name"), "success": False, "error": str(e)})
    
    # 更新 OpenAI 密钥循环以反映新的有效密钥
    utils.update_openai_key_cycle()
    return {"message": f"尝试重置 {len(inactive_keys)} 个无效密钥为有效状态", "results": results}


@router.post("/cleanup-usage", tags=["Admin API Keys Management"])
async def cleanup_usage_tracking_data(current_user: dict = Depends(dependencies.get_current_admin_user)):
    """清理内存中的使用情况跟踪数据，删除不再存在于数据库中的密钥的使用情况。"""
    active_keys = {key["id"] for key in db.get_all_api_keys()}  # 现有密钥 ID 的集合
    usage_keys = set(utils.api_key_usage.keys())  # 内存中跟踪的密钥 ID
    
    to_cleanup = usage_keys - active_keys  # 在使用情况中但不在数据库中的密钥
    
    for kid_to_clean in to_cleanup:
        if kid_to_clean in utils.api_key_usage:
            del utils.api_key_usage[kid_to_clean]
            logger.info(f"Cleaned up stale usage data for deleted key_id: {kid_to_clean}")
    
    return {"message": f"清理了 {len(to_cleanup)} 个不存在的密钥的使用情况数据", "cleaned_key_ids": list(to_cleanup)}
