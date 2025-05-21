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


# 将 /admin/token 端点从 routers.admin 移至 main.py 以避免路由级别的认证依赖
@app.post("/token", response_model=schemas.Token, tags=["Admin Auth"])
async def login_for_access_token_main(request: Request):  # 重命名以避免在 admin 路由仍然导入时发生冲突
    """
    管理员使用代理 API 密钥作为密码登录。
    返回一个 JWT 访问令牌。
    在 main.py 中定义以绕过 admin 路由的默认 JWT 保护。
    """
    print("DEBUG (main.py): /token endpoint CALLED!")  # 调试信息：/token 端点被调用！

    proxy_api_key_candidate: Optional[str] = None
    try:
        form_data = await request.form()
        print(f"DEBUG (main.py): Raw form data received: {form_data}")  # 调试信息：接收到原始表单数据

        raw_password_field = form_data.get("password")
        if isinstance(raw_password_field, str):
            proxy_api_key_candidate = raw_password_field
            print(
                f"DEBUG (main.py): Extracted password/key candidate: '{proxy_api_key_candidate}'"
            )  # 调试信息：提取的密码/密钥候选者
        elif raw_password_field is None:
            print(
                "DEBUG (main.py): 'password' field not found in form data."
            )  # 调试信息：在表单数据中未找到 'password' 字段
            raise HTTPException(status_code=400, detail="Missing 'password' in form data")
        else:
            print(
                f"DEBUG (main.py): 'password' field was not a string. Type: {type(raw_password_field)}, Value: {raw_password_field}"
            )  # 调试信息：'password' 字段不是字符串
            raise HTTPException(status_code=400, detail="'password' field must be a string.")

    except Exception as e:
        print(f"DEBUG (main.py): Error processing request form data: {e}")  # 调试信息：处理请求表单数据时出错
        raise HTTPException(status_code=400, detail=f"Could not process form data: {e}")

    if proxy_api_key_candidate is None:
        print(
            "DEBUG (main.py): proxy_api_key_candidate is None after form processing."
        )  # 调试信息：表单处理后 proxy_api_key_candidate 为 None
        raise HTTPException(status_code=400, detail="Password not provided or error in processing.")

    print(
        f"DEBUG (main.py): Current config.PROXY_API_KEYS: {config.PROXY_API_KEYS}"
    )  # 调试信息：当前的 config.PROXY_API_KEYS

    if proxy_api_key_candidate not in config.PROXY_API_KEYS:
        print(
            f"DEBUG (main.py): Authentication failed. Candidate '{proxy_api_key_candidate}' not in {config.PROXY_API_KEYS}"
        )  # 调试信息：认证失败
        raise HTTPException(
            status_code=401,
            detail="Incorrect proxy API key (password)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    print(
        f"DEBUG (main.py): Authentication successful for candidate: '{proxy_api_key_candidate}'"
    )  # 调试信息：认证成功
    access_token_expires = timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = utils.create_access_token(data={"sub": "admin_user"}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}


# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 如果使用 Jinja2 模板
# templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
async def startup_event():
    """应用启动：初始化数据库。"""
    # db.init_db() # 数据库现在在 database.py 导入时初始化。
    print("Application startup: Database initialized on module import.")  # 应用启动：数据库在模块导入时初始化。

    print("Application startup: Updating OpenAI key cycle from DB.")  # 应用启动：从数据库更新 OpenAI 密钥周期。
    utils.api_key_usage.clear()  # 清除任何旧的内存中使用情况
    utils.update_openai_key_cycle()  # 从数据库填充

    print(
        "Application startup: Proxy API Keys are loaded from config module on import."
    )  # 应用启动：代理 API 密钥在导入配置模块时加载。
    # load_proxy_api_keys_from_config() # 此函数现在在 config.py 导入时调用


# --- 辅助函数 ---


# --- API 端点 ---
# 原来的根路径端点被移除，因为现在根路径显示管理页面


# 如果您在本地运行此文件 (例如 uvicorn main:app --reload)
# 请确保已安装 uvicorn, httpx, python-multipart (如果将来使用表单):
# pip install fastapi uvicorn httpx python-multipart
