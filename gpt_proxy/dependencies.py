from fastapi import HTTPException, Header, Depends
from fastapi.security import OAuth2PasswordBearer  # 用于提取 JWT 令牌
from typing import Optional
from jose import JWTError, jwt  # 用于 JWT 解码

from . import config
from . import logger

# 此 OAuth2 方案可供 Depends 用于从 Authorization: Bearer 标头中提取令牌
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/token")  # tokenUrl 是客户端获取令牌的地址


async def verify_proxy_api_key(authorization: Optional[str] = Header(None)):
    """
    验证在Authorization标头中提供的代理API密钥（Bearer令牌）。
    如果密钥缺失、格式错误或无效，则抛出HTTPException。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少Authorization标头")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization标头格式无效。期望 'Bearer <token>'")

    token = parts[1]
    if token not in config.PROXY_API_KEYS:
        raise HTTPException(status_code=403, detail="无效的代理API密钥")
    return token


async def get_current_admin_user(token: str = Depends(oauth2_scheme)):
    """
    用于验证 JWT 令牌并获取当前管理员用户（或仅验证令牌）的依赖项。
    对于管理面板，我们可能没有复杂的用户模型，因此仅验证令牌
    及其 'sub'（主题，可以是一个固定值或密钥本身）可能就足够了。
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        if not config.JWT_SECRET_KEY:
            # 这个问题应该更早被发现，但作为安全措施：
            logger.critical("严重：JWT_SECRET_KEY未配置。身份验证将失败。")
            raise credentials_exception

        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        # 对于此代理，'sub' 可以是一个通用标识符，甚至是用于登录的代理密钥。
        # 目前假设有效令牌的存在就足够了。
        # 如果需要审计，我们可以将用于登录的 proxy_api_key 存储在令牌的 'sub' 中。
        username: Optional[str] = payload.get("sub")
        if username is None:  # 或对 payload 进行任何其他验证
            raise credentials_exception
        # 如果有用户模型，可以在这里加载，例如从 payload.get("sub")
        # 目前，仅返回 True 或用户名（主题）即可。
        return {"username": username}  # 或者如果不需要从令牌中获取用户数据，则简单返回 True
    except JWTError as e:
        logger.error(f"JWT解码期间发生JWTError: {e}")
        raise credentials_exception
    except Exception as e_gen:
        logger.error(f"JWT解码期间发生意外错误: {e_gen}")
        raise credentials_exception
