from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class Message(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: Optional[bool] = False
    stop: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None


class KeyValidationResult(BaseModel):
    key_id: str
    key_suffix: str
    status_before: str
    status_after: str
    validation_success: bool
    error_message: Optional[str] = None


class OpenAIKeyDisplay(BaseModel):
    id: str
    api_key_masked: str
    status: str
    name: Optional[str] = None
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    total_requests: Optional[int] = 0


class NewOpenAIKeyPayload(BaseModel):
    api_key: str
    name: Optional[str] = None


class BulkOpenAIKeysPayload(BaseModel):
    api_keys: str  # 包含多个key的字符串，每行一个key


class AddKeyResult(BaseModel):
    success: bool
    key_suffix: str
    error_message: Optional[str] = None
    key_id: Optional[str] = None


class BulkAddKeysResponse(BaseModel):
    results: List[AddKeyResult]
    success_count: int
    error_count: int


class KeyStatusUpdatePayload(BaseModel):
    status: str


class KeyNameUpdatePayload(BaseModel):
    name: str


class CategorizedOpenAIKeys(BaseModel):
    valid_keys: List[OpenAIKeyDisplay]
    invalid_keys: List[OpenAIKeyDisplay]


class Token(BaseModel):
    access_token: str
    token_type: str


class ResetKeysResponse(BaseModel):
    message: str
    count: int


class GlobalStats(BaseModel):
    grand_total_requests_all_time: int
    grand_total_usage_last_1m: int
    grand_total_usage_last_1h: int
    grand_total_usage_last_24h: int
    active_keys_count: int
    inactive_keys_count: int
    revoked_keys_count: int
    total_keys_count: int


class GlobalStatsResponse(BaseModel):
    global_stats: GlobalStats
