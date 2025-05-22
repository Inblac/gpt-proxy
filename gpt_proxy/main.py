from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
import os
from datetime import timedelta

# 导入模块
from . import database as db
from . import schemas
from . import config
from . import dependencies
from . import utils
from .routers import chat, admin
from . import logger


# 应用设置
app = FastAPI()
app.include_router(chat.router)
app.include_router(admin.router)

# 获取目录路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


# 管理员HTML页面路由
@app.get("/", response_class=HTMLResponse, tags=["Admin UI"])
async def get_admin_page_html(
    proxy_api_key_from_header: Optional[str] = Header(None, alias=config.PROXY_API_KEY_HEADER)
):
    """提供管理界面HTML页面"""
    index_html_path = os.path.join(STATIC_DIR, "index.html")
    try:
        with open(index_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"在静态目录中未找到管理页面 (index.html): {index_html_path}")


# JWT令牌认证端点
@app.post("/token", response_model=schemas.Token, tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """管理员登录获取JWT令牌的端点"""
    logger.debug("DEBUG (main.py): /token endpoint CALLED!")
    
    try:
        logger.debug(f"DEBUG (main.py): Raw form data received: {form_data}")
    except Exception as e:
        logger.error(f"DEBUG (main.py): Could not log form_data: {e}")

    try:
        username = form_data.username
        password = form_data.password
        
        logger.debug(f"DEBUG (main.py): Attempted login with username: {username}")
        
        if password not in config.PROXY_API_KEYS:
            logger.warning(f"DEBUG (main.py): Invalid credentials for user: {username}")
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        logger.debug(f"DEBUG (main.py): Successful login for user: {username}")
        
        # 创建访问令牌
        access_token_expires = timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = utils.create_access_token(
            data={"sub": username}, expires_delta=access_token_expires
        )
        
        logger.info(f"DEBUG (main.py): Generated token for user: {username}")
        
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"DEBUG (main.py): Error processing request form data: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error processing login: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理，记录未处理的异常并返回友好的错误消息"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器错误: {str(exc)}"}
    )


# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_event():
    """应用启动：初始化数据库和加载配置"""
    logger.info("Application startup: Database initialized on module import.")

    logger.info("Application startup: Updating OpenAI key cycle from DB.")
    utils.api_key_usage.clear()
    utils.update_openai_key_cycle()

    logger.info(
        "Application startup: Proxy API Keys are loaded from config module on import."
    )


# --- 辅助函数 ---


# --- API 端点 ---
# 原来的根路径端点被移除，因为现在根路径显示管理页面


# 如果您在本地运行此文件 (例如 uvicorn main:app --reload)
# 请确保已安装 uvicorn, httpx, python-multipart (如果将来使用表单):
# pip install fastapi uvicorn httpx python-multipart
