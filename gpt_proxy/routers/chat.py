from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, Any
import httpx
import asyncio

from .. import schemas
from .. import config
from .. import utils
from .. import database as db
from .. import dependencies
from .. import logger

router = APIRouter()


@router.post("/v1/chat/completions", tags=["Chat Completions"])
async def chat_completions_proxy(
    request_data: schemas.OpenAIChatRequest, proxy_api_key: str = Depends(dependencies.verify_proxy_api_key)
):
    """代理OpenAI Chat Completions API请求，实现API Key轮询和重试机制"""
    headers = {
        "Content-Type": "application/json",
    }

    payload = request_data.model_dump(exclude_none=True)
    is_stream = payload.get("stream", False)

    async with httpx.AsyncClient() as client:  # 主HTTP客户端
        for attempt in range(config.APP_CONFIG_MAX_RETRIES):
            current_key_config: Optional[Dict[str, Any]] = None
            try:
                current_key_config = await utils.get_next_openai_key_config()
                if current_key_config is None:
                    # 无可用API Key
                    logger.info(f"尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}: 无可用OpenAI API Key。")
                    if attempt == 0:
                        raise HTTPException(status_code=503, detail="无可用OpenAI API Key，请添加或激活。")
                    raise HTTPException(status_code=503, detail="此尝试未能获取到可用的API Key。")

                current_api_key = current_key_config["api_key"]
                key_id_for_db = current_key_config["id"]

                headers["Authorization"] = f"Bearer {current_api_key}"  # 设置当前API Key
                key_short = utils.mask_api_key_for_display(current_api_key)
                _name_from_config = current_key_config.get("name")
                key_name_for_log = _name_from_config if _name_from_config else key_short

                if attempt >0:
                    logger.info(
                        f"重试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES} 使用密钥ID: {key_id_for_db} (后缀: {key_short})"
                    )

                if is_stream:
                    # 流式响应的异步生成器
                    async def stream_openai_response_generator(
                        target_url: str,
                        request_payload: dict,
                        request_headers: dict,
                        key_id: int,
                        key_name_log: str,
                        key_short_log: str,
                    ):
                        str_key_id = str(key_id)
                        # 为流式请求创建独立的HTTP客户端
                        async with httpx.AsyncClient() as stream_client:
                            try:
                                # 发起流式请求
                                async with stream_client.stream(
                                    "POST", target_url, json=request_payload, headers=request_headers, timeout=30.0
                                ) as response:
                                    if response.status_code == 200:
                                        logger.info(
                                            f"流式请求成功启动，使用Key ID: {str_key_id} (后缀: {key_short_log})。"
                                        )
                                        # 记录API Key使用情况 - 使用异步方法
                                        await utils.record_api_key_usage(str_key_id, model=request_payload.get("model"), status="success")
                                        await db.update_api_key_last_used_at(str_key_id)

                                        async for chunk in response.aiter_bytes():
                                            yield chunk
                                        logger.info(
                                            f"流式请求数据接收完毕，使用Key ID: {str_key_id} (后缀: {key_short_log})。"
                                        )
                                    else:
                                        # 处理流式请求错误
                                        error_content = await response.aread()
                                        error_text = (
                                            error_content.decode("utf-8", errors="replace")
                                            if isinstance(error_content, bytes)
                                            else str(error_content)
                                        )
                                        logger.error(
                                            f"流式请求初始化错误，Key ID: {str_key_id} (后缀: {key_short_log}): {response.status_code} - {error_text}"
                                        )
                                        if response.status_code in [401, 403, 429]:  # 特定错误码，禁用Key
                                            await db.update_api_key_status(str_key_id, config.KEY_STATUS_INACTIVE)
                                            logger.info(
                                                f"Key ID {str_key_id} (名称: {key_name_log}) 因API错误{response.status_code}被设为'{config.KEY_STATUS_INACTIVE}'。"
                                            )
                                            await utils.update_openai_key_cycle()
                                        # 抛出异常，由主重试循环捕获
                                        raise HTTPException(status_code=response.status_code, detail=error_text)

                            except httpx.RequestError as e_req:  # 网络请求错误
                                logger.error(
                                    f"流式请求发生httpx.RequestError，Key ID: {str_key_id} (后缀: {key_short_log}): {str(e_req)}"
                                )
                                raise e_req  # 重新抛出，由主重试循环处理

                            except Exception as e_gen:  # 其他通用异常
                                logger.error(
                                    f"流式处理中发生通用异常，Key ID: {str_key_id} (后缀: {key_short_log}): {str(e_gen)}"
                                )
                                raise  # 重新抛出

                    generator_instance = stream_openai_response_generator(
                        target_url=config.OPENAI_API_ENDPOINT,
                        request_payload=payload,
                        request_headers=headers,
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
                        await utils.record_api_key_usage(str(key_id_for_db), model=payload.get("model"), status="success")
                        # 使用异步数据库操作
                        await db.update_api_key_last_used_at(str(key_id_for_db))
                        logger.info(
                            f"非流式请求成功，使用Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short})."
                        )
                        return response.json()
                    else:
                        error_content = response.text
                        logger.error(
                            f"非流式请求错误，Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short}): {response.status_code} - {error_content}"
                        )
                        if response.status_code in [401, 403, 429] and key_id_for_db:
                            # 使用异步方法更新状态
                            await db.update_api_key_status(str(key_id_for_db), config.KEY_STATUS_INACTIVE)
                            logger.info(
                                f"Key ID {key_id_for_db} (名称: {key_name_for_log}) 因API错误{response.status_code}被设为'{config.KEY_STATUS_INACTIVE}'。"
                            )
                            await utils.update_openai_key_cycle()
                        raise HTTPException(status_code=response.status_code, detail=error_content)

            except httpx.RequestError as e:  # OpenAI连接或请求错误
                key_id_for_db_error = current_key_config.get("id") if current_key_config else None
                key_name_for_error_log = key_name_for_log if current_key_config else "N/A"
                key_short_for_error = key_short if current_key_config else "N/A"

                log_key_id_display = key_id_for_db_error if key_id_for_db_error is not None else "N/A"
                logger.error(
                    f"RequestError (Key ID: {log_key_id_display}, 名称: {key_name_for_error_log}, 后缀: {key_short_for_error}): {e}"
                )
                if key_id_for_db_error:  # 如果获取到了Key，则禁用
                    # 使用异步方法更新状态
                    await db.update_api_key_status(str(key_id_for_db_error), config.KEY_STATUS_INACTIVE)
                    logger.info(
                        f"Key ID {key_id_for_db_error} (名称: {key_name_for_error_log}) 因RequestError被设为'{config.KEY_STATUS_INACTIVE}'。"
                    )
                    await utils.update_openai_key_cycle()
                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试下一个Key
                else:  # 所有尝试失败
                    raise HTTPException(status_code=500, detail=f"连接OpenAI多次尝试失败: {e}")

            except HTTPException as e:  # 其他HTTP异常
                key_id_display = current_key_config.get("id") if current_key_config else "N/A"
                logger.error(
                    f"OpenAI调用期间发生HTTPException (Key ID: {key_id_display}, 尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}): {e.status_code} - {e.detail}"
                )

                # 如果是初次尝试就因无可用Key而失败(503)，则直接抛出
                if e.status_code == 503 and "无可用OpenAI API Key" in e.detail and attempt == 0:
                    raise

                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试
                else:  # 所有尝试失败或遇到不可重试的错误
                    raise

        raise HTTPException(status_code=500, detail=f"所有{config.APP_CONFIG_MAX_RETRIES}次尝试均失败。")


@router.get("/v1/models", tags=["Models"])
async def list_models(proxy_api_key: str = Depends(dependencies.verify_proxy_api_key)):
    """代理OpenAI List Models API请求，使用与聊天完成相同的API Key轮询机制"""
    headers = {
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(config.APP_CONFIG_MAX_RETRIES):
            current_key_config: Optional[Dict[str, Any]] = None
            try:
                current_key_config = await utils.get_next_openai_key_config()
                if current_key_config is None:
                    if attempt == 0:  # 初始无可用Key
                        raise HTTPException(status_code=503, detail="Models API无可用OpenAI Key，请添加或激活。")
                    raise HTTPException(status_code=503, detail="Models API此尝试未能获取到可用的API Key。")

                current_api_key = current_key_config["api_key"]
                key_id_for_db = current_key_config["id"]

                headers["Authorization"] = f"Bearer {current_api_key}"
                key_short = utils.mask_api_key_for_display(current_api_key)
                _name_from_config = current_key_config.get("name")
                key_name_for_log = _name_from_config if _name_from_config else key_short

                logger.info(
                    f"尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES} 对/v1/models使用密钥ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short})"
                )

                response = await client.get(config.OPENAI_VALIDATION_ENDPOINT, headers=headers, timeout=30.0)

                if response.status_code == 200:
                    await utils.record_api_key_usage(str(key_id_for_db), model="models", status="success")
                    # 使用异步数据库操作
                    await db.update_api_key_last_used_at(str(key_id_for_db))
                    logger.info(
                        f"/v1/models请求成功，使用Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short})。"
                    )
                    return response.json()
                else:
                    error_content = response.text
                    logger.error(
                        f"/v1/models请求错误，Key ID: {key_id_for_db} (名称: {key_name_for_log}, 后缀: {key_short}): {response.status_code} - {error_content}"
                    )
                    if response.status_code in [401, 403, 429] and key_id_for_db:
                        # 使用异步方法更新状态
                        await db.update_api_key_status(str(key_id_for_db), config.KEY_STATUS_INACTIVE)
                        logger.info(
                            f"Key ID {key_id_for_db} (名称: {key_name_for_log}) 因API错误{response.status_code} (Models API)被设为'{config.KEY_STATUS_INACTIVE}'。"
                        )
                        await utils.update_openai_key_cycle()
                    raise HTTPException(status_code=response.status_code, detail=error_content)

            except httpx.RequestError as e:  # 网络连接错误
                key_id_for_db_error = current_key_config.get("id") if current_key_config else None
                key_name_for_error_log = key_name_for_log if current_key_config else "N/A"
                key_short_for_error = key_short if current_key_config else "N/A"
                
                log_key_id_display = key_id_for_db_error if key_id_for_db_error is not None else "N/A"
                logger.error(
                    f"Models API RequestError (Key ID: {log_key_id_display}, 名称: {key_name_for_error_log}, 后缀: {key_short_for_error}): {e}"
                )
                
                if key_id_for_db_error:  # 如果获取到了Key，则禁用
                    await db.update_api_key_status(str(key_id_for_db_error), config.KEY_STATUS_INACTIVE)
                    logger.info(
                        f"Key ID {key_id_for_db_error} (名称: {key_name_for_error_log}) 因Models API RequestError被设为'{config.KEY_STATUS_INACTIVE}'。"
                    )
                    await utils.update_openai_key_cycle()
                
                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试下一个Key
                else:  # 所有尝试失败
                    raise HTTPException(status_code=500, detail=f"连接OpenAI Models API多次尝试失败: {e}")

            except HTTPException as e:  # 其他HTTP异常
                key_id_display = current_key_config.get("id") if current_key_config else "N/A"
                logger.error(
                    f"Models API调用期间发生HTTPException (Key ID: {key_id_display}, 尝试 {attempt + 1}/{config.APP_CONFIG_MAX_RETRIES}): {e.status_code} - {e.detail}"
                )

                # 如果是初次尝试就因无可用Key而失败(503)，则直接抛出
                if e.status_code == 503 and "无可用OpenAI Key" in e.detail and attempt == 0:
                    raise

                if attempt < config.APP_CONFIG_MAX_RETRIES - 1:
                    await asyncio.sleep(0.1)
                    continue  # 继续尝试
                else:  # 所有尝试失败或遇到不可重试的错误
                    raise

        raise HTTPException(status_code=500, detail=f"所有{config.APP_CONFIG_MAX_RETRIES}次尝试均失败。")
