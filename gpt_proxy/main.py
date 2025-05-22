from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm  # 用于处理移动过来的 token 端点逻辑
from typing import Optional
import os
from datetime import timedelta  # 用于 token 过期时间

# 数据库导入
from . import database as db
from . import schemas  # 用于 schemas.Token
from . import config
from . import dependencies
from . import utils
from .routers import chat, admin
from . import logger


# --- 应用设置 ---
app = FastAPI()
app.include_router(chat.router)  # 包含 chat 路由
app.include_router(admin.router)  # 包含 admin 路由

# 获取当前文件所在的目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# TEMPLATES_DIR = os.path.join(BASE_DIR, "templates") # 如果使用 Jinja2


# 管理员 HTML 页面路由 (在 main中定义以绕过 admin_router 的默认认证)
@app.get("/", response_class=HTMLResponse, tags=["Admin UI"])
async def get_admin_page_html(
    proxy_api_key_from_header: Optional[str] = Header(None, alias=config.PROXY_API_KEY_HEADER)
):
    """
    提供 index.html 页面。
    允许可选的 X-Proxy-API-Key 请求头以便在已知密钥时直接访问，
    但主要设计为页面加载后使用 JavaScript 提交 API 密钥。
    """
    index_html_path = os.path.join(STATIC_DIR, "index.html")
    try:
        with open(index_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"在静态目录中未找到管理页面 (index.html): {index_html_path}")


# 将 /token 端点从 routers.admin 移至 main.py 以避免路由级别的认证依赖
@app.post("/token", response_model=schemas.Token, tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    管理员登录用于获取 JWT 令牌的端点。
    基于代理 API Key（在 config.ini 的 [proxy_auth] 部分的 api_keys 中配置）进行验证。
    """
    logger.debug("DEBUG (main.py): /token endpoint CALLED!")  # 调试信息：/token 端点被调用！
    
    # 用于调试日志
    try:
        logger.debug(f"DEBUG (main.py): Raw form data received: {form_data}")  # 调试信息：接收到原始表单数据
    except Exception as e:
        logger.error(f"DEBUG (main.py): Could not log form_data: {e}")  # 调试信息：无法记录 form_data

    try:
        username = form_data.username
        password = form_data.password
        
        logger.debug(f"DEBUG (main.py): Attempted login with username: {username}")  # 调试信息：尝试使用用户名登录
        
        if password not in config.PROXY_API_KEYS:
            logger.warning(f"DEBUG (main.py): Invalid credentials for user: {username}")  # 调试信息：用户的凭据无效
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password",  # 用户名或密码不正确
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        logger.debug(f"DEBUG (main.py): Successful login for user: {username}")  # 调试信息：用户登录成功
        
        # 创建 access_token（访问令牌）
        access_token_expires = timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = utils.create_access_token(
            data={"sub": username}, expires_delta=access_token_expires
        )
        
        logger.info(f"DEBUG (main.py): Generated token for user: {username}")  # 调试信息：为用户生成令牌
        
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"DEBUG (main.py): Error processing request form data: {e}")  # 调试信息：处理请求表单数据时出错
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error processing login: {str(e)}",  # 处理登录时发生内部服务器错误
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理程序，用于记录未处理的异常并返回友好的错误消息。
    """
    logger.error(f"未处理的异常: {exc}", exc_info=True)  # 使用 exc_info=True 记录堆栈跟踪
    
    # 对于调试，通常希望在开发环境中看到完整错误；
    # 在生产环境中，可能希望隐藏技术详细信息。
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器错误: {str(exc)}"}
    )


# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 如果使用 Jinja2 模板
# templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
async def startup_event():
    """应用启动：初始化数据库。"""
    # db.init_db() # 数据库现在在 database.py 导入时初始化。
    logger.info("Application startup: Database initialized on module import.")  # 应用启动：数据库在模块导入时初始化。

    logger.info("Application startup: Updating OpenAI key cycle from DB.")  # 应用启动：从数据库更新 OpenAI 密钥周期。
    utils.api_key_usage.clear()  # 清除任何旧的内存中使用情况
    utils.update_openai_key_cycle()  # 从数据库填充

    logger.info(
        "Application startup: Proxy API Keys are loaded from config module on import."
    )  # 应用启动：代理 API 密钥在导入配置模块时加载。
    # load_proxy_api_keys_from_config() # 此函数现在在 config.py 导入时调用


# --- 辅助函数 ---


# --- API 端点 ---
# 原来的根路径端点被移除，因为现在根路径显示管理页面


# 如果您在本地运行此文件 (例如 uvicorn main:app --reload)
# 请确保已安装 uvicorn, httpx, python-multipart (如果将来使用表单):
# pip install fastapi uvicorn httpx python-multipart
