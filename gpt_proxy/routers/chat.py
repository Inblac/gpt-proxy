from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from typing import Optional, Dict, Any
import httpx
import asyncio

from .. import schemas
from .. import config
from .. import utils
from .. import database as db
from .. import dependencies

router = APIRouter()


@router.post("/v1/chat/completions", tags=["Chat Completions"])
async def chat_completions_proxy(
    request_data: schemas.OpenAIChatRequest, proxy_api_key: str = Depends(dependencies.verify_proxy_api_key)
):
    """
    代理 OpenAI Chat Completions API 请求。
    实现了 API Key 轮询和重试机制，并添加了自定义 API Key 访问验证。
    """
    headers = {
        "Content-Type": "application/json",
    }

    payload = request_data.model_dump(exclude_none=True)
    is_stream = payload.get("stream", False)

    async with httpx.AsyncClient() as client:  # 主 HTTP 客户端，用于非流式请求
        for attempt in range(config.APP_CONFIG_MAX_RETRIES):
            current_key_config: Optional[Dict[str, Any]] = None
            try:
                current_key_config = await utils.get_next_api_key_config()
                if current_key_config is None:
                    # 无可用 API Key
                    print(f"尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}: 无可用 OpenAI API Key。")
                    if attempt == 0:
                        raise HTTPException(status_code=503, detail="无可用 OpenAI API Key，请添加或激活。")
                    raise HTTPException(status_code=503, detail="此尝试未能获取到可用的 API Key。")

                current_api_key = current_key_config["api_key"]
                key_id_for_db = current_key_config["id"]

                headers["Authorization"] = f"Bearer {current_api_key}"  # 设置当前尝试的 API Key
                key_short = utils.mask_api_key_for_display(current_api_key)
                _name_from_config = current_key_config.get("name")
                key_name_for_log = _name_from_config if _name_from_config else key_short

                print(
                    f"Attempt {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES} using key ID: {key_id_for_db} (Name: {key_name_for_log}, Suffix: {key_short})"
                )

                if is_stream:
                    # 定义流式响应的异步生成器
                    async def stream_openai_response_generator(
                        target_url: str,
                        request_payload: dict,
                        request_headers: dict,  # 包含当前尝试的 API Key 的 Authorization header
                        key_id: int,  # 用于日志和数据库更新
                        key_name_log: str,
                        key_short_log: str,
                    ):
                        str_key_id = str(key_id)
                        # 为流式请求创建并管理独立的 HTTP 客户端
                        async with httpx.AsyncClient() as stream_client:
                            try:
                                # 使用当前尝试的 headers (包含 API Key) 发起流式请求
                                async with stream_client.stream(
                                    "POST", target_url, json=request_payload, headers=request_headers, timeout=30.0
                                ) as response:
                                    if response.status_code == 200:
                                        print(
                                            f"流式请求成功启动，使用 Key ID: {str_key_id} (名称: {key_name_log}, 后缀: {key_short_log})。"
                                        )
                                        # 流式请求成功启动后，记录 API Key 使用情况
                                        utils.record_api_key_usage(str_key_id)
                                        db.update_api_key_last_used_at(str_key_id)
                                        db.increment_api_key_requests(str_key_id)  # 新增：增加请求计数

                                        async for chunk in response.aiter_bytes():
                                            yield chunk
                                        print(
                                            f"流式请求数据接收完毕，使用 Key ID: {str_key_id} (名称: {key_name_log}, 后缀: {key_short_log})。"
                                        )
                                    else:
                                        # 处理流式请求初始化时的错误
                                        error_content = await response.aread()
                                        error_text = (
                                            error_content.decode('utf-8', errors='replace')
                                            if isinstance(error_content, bytes)
                                            else str(error_content)
                                        )
                                        print(
                                            f"流式请求初始化错误，Key ID: {str_key_id} (名称: {key_name_log}, 后缀: {key_short_log}): {response.status_code} - {error_text}"
                                        )
                                        if response.status_code in [401, 403, 429]:  # 特定错误码，禁用 Key
                                            db.update_api_key_status(str_key_id, config.KEY_STATUS_INACTIVE)
                                            print(
                                                f"Key ID {str_key_id} (名称: {key_name_log}) 因 API 错误 {response.status_code} 被设为 '{config.KEY_STATUS_INACTIVE}'。"
                                            )
                                            utils.update_openai_key_cycle()
                                        # 抛出异常，由主重试循环捕获
                                        raise HTTPException(status_code=response.status_code, detail=error_text)

                            except httpx.RequestError as e_req:  # 网络请求错误
                                print(
                                    f"流式请求发生 httpx.RequestError，Key ID: {str_key_id} (名称: {key_name_log}, 后缀: {key_short_log}): {str(e_req)}"
                                )
                                raise e_req  # 重新抛出，由主重试循环处理

                            except Exception as e_gen:  # 其他通用异常
                                print(
                                    f"流式处理中发生通用异常，Key ID: {str_key_id} (名称: {key_name_log}, 后缀: {key_short_log}): {str(e_gen)}"
                                )
                                raise  # 重新抛出

                    generator_instance = stream_openai_response_generator(
                        target_url=config.OPENAI_API_ENDPOINT,
                        request_payload=payload,
                        request_headers=headers,  # 包含当前尝试的 API Key
                        key_id=key_id_for_db,
                        key_name_log=key_name_for_log,
                        key_short_log=key_short,
                    )

                    return StreamingResponse(generator_instance, media_type="text/event-stream")

                else:  # 非流式请求
                    response = await client.post(
                        config.OPENAI_API_ENDPOINT, json=payload, headers=headers, timeout=30.0
                    )
                    if response.status_code == 200:
                        utils.record_api_key_usage(str(key_id_for_db))
                        db.update_api_key_last_used_at(str(key_id_for_db))
                        db.increment_api_key_requests(str(key_id_for_db))  # 新增：增加请求计数
                        print(
                            f"非流式请求成功，使用 Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short})."
                        )
                        return response.json()
                    else:
                        error_content = response.text
                        print(
                            f"非流式请求错误，Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short}): {response.status_code} - {error_content}"
                        )
                        if response.status_code in [401, 403, 429] and key_id_for_db:
                            db.update_api_key_status(str(key_id_for_db), config.KEY_STATUS_INACTIVE)
                            print(
                                f"Key ID {key_id_for_db} (名称: {key_name_for_log}) 因 API 错误 {response.status_code} 被设为 '{config.KEY_STATUS_INACTIVE}'。"
                            )
                            utils.update_openai_key_cycle()
                        raise HTTPException(status_code=response.status_code, detail=error_content)

            except httpx.RequestError as e:  # OpenAI 连接或请求错误
                key_id_for_db_error = current_key_config.get("id") if current_key_config else None
                key_name_for_error_log = key_name_for_log if current_key_config else "N/A"
                key_short_for_error = key_short if current_key_config else "N/A"

                log_key_id_display = key_id_for_db_error if key_id_for_db_error is not None else "N/A"
                print(
                    f"RequestError (Key ID: {log_key_id_display}, 名称: {key_name_for_error_log}, 后缀: {key_short_for_error}): {e}"
                )
                if key_id_for_db_error:  # 如果获取到了 Key，则禁用
                    db.update_api_key_status(str(key_id_for_db_error), config.KEY_STATUS_INACTIVE)  # 确保是字符串
                    print(
                        f"Key ID {key_id_for_db_error} (名称: {key_name_for_error_log}) 因 RequestError 被设为 '{config.KEY_STATUS_INACTIVE}'。"
                    )
                    utils.update_openai_key_cycle()
                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试下一个 Key
                else:  # 所有尝试失败
                    raise HTTPException(status_code=500, detail=f"连接 OpenAI 多次尝试失败: {e}")

            except HTTPException as e:  # 其他 HTTP 异常 (例如之前抛出的无可用 Key 的 503)
                key_id_display = current_key_config.get("id") if current_key_config else "N/A"
                print(
                    f"OpenAI 调用期间发生 HTTPException (Key ID: {key_id_display}, 尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}): {e.status_code} - {e.detail}"
                )

                # 如果是初次尝试就因无可用 Key 而失败 (503)，则直接抛出
                if e.status_code == 503 and "No active OpenAI API keys available" in e.detail and attempt == 0:
                    raise

                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试
                else:  # 所有尝试失败或遇到不可重试的错误
                    raise

        raise HTTPException(status_code=500, detail=f"所有 {config.APP_CONFIG_MAX_RETRIES} 次尝试均失败。")


@router.get("/v1/models", tags=["Models"])
async def list_models(proxy_api_key: str = Depends(dependencies.verify_proxy_api_key)):
    """
    代理 OpenAI List Models API 请求。
    使用与聊天完成相同的 API Key 轮询和重试机制。
    """
    headers = {
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:  # 主 HTTP 客户端
        for attempt in range(config.APP_CONFIG_MAX_RETRIES):
            current_key_config: Optional[Dict[str, Any]] = None
            try:
                current_key_config = await utils.get_next_api_key_config()
                if current_key_config is None:
                    if attempt == 0:  # 初始无可用 Key
                        raise HTTPException(status_code=503, detail="Models API 无可用 OpenAI Key，请添加或激活。")
                    raise HTTPException(status_code=503, detail="Models API 此尝试未能获取到可用的 API Key。")

                current_api_key = current_key_config["api_key"]
                key_id_for_db = current_key_config["id"]

                headers["Authorization"] = f"Bearer {current_api_key}"  # 设置当前尝试的 API Key
                key_short = utils.mask_api_key_for_display(current_api_key)
                _name_from_config = current_key_config.get("name")
                key_name_for_log = _name_from_config if _name_from_config else key_short

                print(
                    f"Attempt {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES} for /v1/models using key ID: {key_id_for_db} (Name: {key_name_for_log}, Suffix: {key_short})"
                )

                response = await client.get(config.OPENAI_VALIDATION_ENDPOINT, headers=headers, timeout=30.0)

                if response.status_code == 200:
                    utils.record_api_key_usage(str(key_id_for_db))  # 确保是字符串
                    db.update_api_key_last_used_at(str(key_id_for_db))  # 确保是字符串
                    db.increment_api_key_requests(
                        str(key_id_for_db)
                    )  # 新增：增加请求计数 (虽然 models 接口调用频率较低，但统一记录)
                    print(
                        f"/v1/models 请求成功，使用 Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short})。"
                    )
                    return response.json()
                else:
                    error_content = response.text
                    print(
                        f"/v1/models 请求错误，Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short}): {response.status_code} - {error_content}"
                    )
                    if response.status_code in [401, 403, 429] and key_id_for_db:
                        db.update_api_key_status(str(key_id_for_db), config.KEY_STATUS_INACTIVE)  # 确保是字符串
                        print(
                            f"Key ID {key_id_for_db} (名称: {key_name_for_log}) 因 API 错误 {response.status_code} (Models API) 被设为 '{config.KEY_STATUS_INACTIVE}'。"
                        )
                        utils.update_openai_key_cycle()
                    raise HTTPException(status_code=response.status_code, detail=error_content)

            except httpx.RequestError as e:  # OpenAI 连接或请求错误
                key_id_for_db_error = current_key_config.get("id") if current_key_config else None
                key_name_for_error_log = key_name_for_log if current_key_config else "N/A"
                key_short_for_error = key_short if current_key_config else "N/A"

                log_key_id_display = key_id_for_db_error if key_id_for_db_error is not None else "N/A"
                print(
                    f"Models API RequestError (Key ID: {log_key_id_display}, 名称: {key_name_for_error_log}, 后缀: {key_short_for_error}): {e}"
                )
                if key_id_for_db_error:  # 如果获取到了 Key，则禁用
                    db.update_api_key_status(str(key_id_for_db_error), config.KEY_STATUS_INACTIVE)  # 确保是字符串
                    print(
                        f"Key ID {key_id_for_db_error} (名称: {key_name_for_error_log}) 因 RequestError (Models API) 被设为 '{config.KEY_STATUS_INACTIVE}'。"
                    )
                    utils.update_openai_key_cycle()
                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试下一个 Key
                else:  # 所有尝试失败
                    raise HTTPException(status_code=500, detail=f"连接 OpenAI (Models API) 多次尝试失败: {e}")

            except HTTPException as e:  # 其他 HTTP 异常
                key_id_display = current_key_config.get("id") if current_key_config else "N/A"
                print(
                    f"Models API 调用期间发生 HTTPException (Key ID: {key_id_display}, 尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}): {e.status_code} - {e.detail}"
                )

                if (
                    e.status_code == 503 and "No active OpenAI API keys available" in e.detail and attempt == 0
                ):  # 初次尝试即无 Key
                    raise

                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试
                else:  # 所有尝试失败或遇到不可重试的错误
                    raise

        raise HTTPException(
            status_code=500, detail=f"所有 {config.APP_CONFIG_MAX_RETRIES} 次 Models API 调用尝试均失败。"
        )
