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


@router.post("/validate_keys", response_model=List[schemas.KeyValidationResult])
async def validate_openai_keys_endpoint():  # 现在通过路由器依赖项传递 JWT 令牌
    results: List[schemas.KeyValidationResult] = []
    all_keys = db.get_all_api_keys()
    inactive_keys = [key for key in all_keys if key['status'] == config.KEY_STATUS_INACTIVE]

    if not inactive_keys:
        return results

    print(f"Attempting to validate {len(inactive_keys)} inactive keys.")

    async with httpx.AsyncClient() as client:
        for key_data in inactive_keys:
            key_id = key_data['id']
            api_key_value = key_data['api_key']
            key_suffix = utils.mask_api_key_for_display(api_key_value)
            key_name = key_data.get("name", "N/A")
            result = schemas.KeyValidationResult(
                key_id=key_id,
                key_suffix=key_suffix,
                status_before=config.KEY_STATUS_INACTIVE,
                status_after=config.KEY_STATUS_INACTIVE,
                validation_success=False,
            )
            headers = {"Authorization": f"Bearer {api_key_value}", "Content-Type": "application/json"}
            try:
                response = await client.get(config.OPENAI_VALIDATION_ENDPOINT, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE)
                    result.status_after = config.KEY_STATUS_ACTIVE
                    result.validation_success = True
                    print(
                        f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validated successfully. Status set to '{config.KEY_STATUS_ACTIVE}'."
                    )
                else:
                    result.error_message = f"Validation failed with status {response.status_code}: {response.text}"
                    print(
                        f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validation failed: {result.error_message}"
                    )
            except httpx.RequestError as e:
                result.error_message = f"Validation request error: {str(e)}"
                print(f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validation request error: {e}")
            except Exception as e_gen:
                result.error_message = f"Unexpected error during validation: {str(e_gen)}"
                print(
                    f"Key ID {key_id} (Name: {key_name}, Suffix: {key_suffix}) re-validation unexpected error: {e_gen}"
                )

            results.append(result)

    utils.update_openai_key_cycle()
    return results


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


@router.post("/keys/bulk", response_model=schemas.BulkAddKeysResponse, status_code=201)
async def add_bulk_openai_keys_endpoint(payload: schemas.BulkOpenAIKeysPayload):
    """批量添加OpenAI API Keys。每行一个key，使用换行分隔。"""
    keys_string = payload.api_keys.strip()
    keys_array = keys_string.split("\n")
    keys_array = [key.strip() for key in keys_array if key.strip()]

    if not keys_array:
        raise HTTPException(status_code=400, detail="No valid keys provided.")

    results = []
    success_count = 0
    error_count = 0

    for key in keys_array:
        result = schemas.AddKeyResult(
            success=False,
            key_suffix=utils.mask_api_key_for_display(key),
        )

        if not key.startswith("sk-"):
            result.error_message = "Invalid OpenAI API Key format. Must start with 'sk-'."
            results.append(result)
            error_count += 1
            continue

        try:
            existing_key = db.get_api_key_by_key_value(key)
            if existing_key:
                result.error_message = f"API key already exists with ID {existing_key['id']}."
                results.append(result)
                error_count += 1
                continue

            key_id = db.add_api_key(api_key=key, status=config.KEY_STATUS_ACTIVE)
            result.success = True
            result.key_id = key_id
            success_count += 1
        except Exception as e:
            result.error_message = str(e)
            error_count += 1
        
        results.append(result)

    if success_count > 0:
        utils.update_openai_key_cycle()
    
    return schemas.BulkAddKeysResponse(
        results=results,
        success_count=success_count,
        error_count=error_count
    )


@router.delete("/keys/{key_id}", status_code=204)
async def delete_openai_key_endpoint(key_id: str):
    key_to_delete = db.get_api_key_by_id(key_id)
    if not key_to_delete:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")

    if db.delete_api_key(key_id):
        print(f"API Key ID '{key_id}' (Name: {key_to_delete.get('name', 'N/A')}) deleted successfully.")
        if key_id in utils.api_key_usage:
            del utils.api_key_usage[key_id]
            print(f"Removed usage tracking for deleted key ID '{key_id}'.")
        utils.update_openai_key_cycle()
        return
    else:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete API Key with ID '{key_id}' from database, though it was found."
        )


@router.put("/keys/{key_id}/status", response_model=schemas.OpenAIKeyDisplay)
async def update_openai_key_status_endpoint_admin(key_id: str, payload: schemas.KeyStatusUpdatePayload):
    new_status = payload.status.strip().lower()
    if new_status not in [config.KEY_STATUS_ACTIVE, config.KEY_STATUS_INACTIVE, config.KEY_STATUS_REVOKED]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be '{config.KEY_STATUS_ACTIVE}', '{config.KEY_STATUS_INACTIVE}', or '{config.KEY_STATUS_REVOKED}'.",
        )

    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")

    if db.update_api_key_status(key_id, new_status):
        print(f"API Key ID '{key_id}' (Name: {key_to_update.get('name', 'N/A')}) status updated to '{new_status}'.")
        utils.update_openai_key_cycle()

        updated_key_data = db.get_api_key_by_id(key_id)
        if not updated_key_data:
            raise HTTPException(status_code=500, detail="Failed to retrieve key after status update.")

        return schemas.OpenAIKeyDisplay(
            id=updated_key_data["id"],
            api_key_masked=utils.mask_api_key_for_display(updated_key_data["api_key"]),
            status=updated_key_data["status"],
            name=updated_key_data.get("name"),
            created_at=updated_key_data.get("created_at"),
            last_used_at=updated_key_data.get("last_used_at"),
            total_requests=updated_key_data.get("total_requests", 0),
        )
    else:
        raise HTTPException(status_code=500, detail=f"Failed to update status for API Key ID '{key_id}'.")


@router.put("/keys/{key_id}/name", response_model=schemas.OpenAIKeyDisplay)
async def update_openai_key_name_endpoint_admin(key_id: str, payload: schemas.KeyNameUpdatePayload):
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Key name cannot be empty.")

    key_to_update = db.get_api_key_by_id(key_id)
    if not key_to_update:
        raise HTTPException(status_code=404, detail=f"API Key with ID '{key_id}' not found.")

    if db.update_api_key_name(key_id, new_name):
        print(f"API Key ID '{key_id}' (Old Name: {key_to_update.get('name', 'N/A')}) name updated to '{new_name}'.")

        updated_key_data = db.get_api_key_by_id(key_id)
        if not updated_key_data:
            raise HTTPException(status_code=500, detail="Failed to retrieve key after name update.")

        return schemas.OpenAIKeyDisplay(
            id=updated_key_data["id"],
            api_key_masked=utils.mask_api_key_for_display(updated_key_data["api_key"]),
            status=updated_key_data["status"],
            name=updated_key_data.get("name"),
            created_at=updated_key_data.get("created_at"),
            last_used_at=updated_key_data.get("last_used_at"),
            total_requests=updated_key_data.get("total_requests", 0),
        )
    else:
        raise HTTPException(status_code=500, detail=f"Failed to update name for API Key ID '{key_id}'.")


@router.post("/keys/reset_invalid_to_valid", response_model=schemas.ResetKeysResponse)
async def reset_invalid_keys_to_valid_endpoint():
    """
    将所有状态为"invalid"的 API 密钥重置为"active"。
    """
    all_keys = db.get_all_api_keys()
    invalid_keys = [
        key
        for key in all_keys
        if key['status'] == config.KEY_STATUS_REVOKED or key['status'] == config.KEY_STATUS_INACTIVE
    ]  # 假设 'revoked' 和 'inactive' 被视为无效状态

    if not invalid_keys:
        return schemas.ResetKeysResponse(message="No invalid keys found to reset.", count=0)

    reset_count = 0
    for key_data in invalid_keys:
        key_id = key_data['id']
        if db.update_api_key_status(key_id, config.KEY_STATUS_ACTIVE):
            reset_count += 1
            print(
                f"Key ID {key_id} (Name: {key_data.get('name', 'N/A')}) status reset to '{config.KEY_STATUS_ACTIVE}'."
            )
        else:
            # 如果特定密钥更新失败，则记录错误，但继续处理其他密钥
            print(f"Failed to reset status for key ID {key_id}. It might have been deleted or another issue occurred.")

    if reset_count > 0:
        utils.update_openai_key_cycle()  # 如果有任何密钥被更改，则更新密钥周期

    return schemas.ResetKeysResponse(
        message=f"Successfully reset {reset_count} key(s) to active status.", count=reset_count
    )
