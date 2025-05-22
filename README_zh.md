# GPT Proxy

一个简陋的 OpenAI API 密钥管理平台，用于高效管理和优化 API 密钥池，实现代理请求和密钥轮换。

## 功能特点

### 密钥管理
- **批量添加密钥**：一次性添加多个 OpenAI API 密钥
- **密钥状态管理**：维护密钥的有效/无效状态
- **自动验证**：自动验证密钥的有效性
- **批量重置**：一键将所有无效密钥重置为有效状态

### 请求代理与负载均衡
- **智能代理**：自动将请求路由至有效的 API 密钥
- **负载均衡**：平均分配请求以优化密钥使用

### 数据统计与监控
- **实时统计**：显示最近 1 分钟、1 小时、24 小时以及总体的调用统计
- **密钥使用跟踪**：记录每个密钥的使用次数和最后使用时间
- **密钥池状态**：显示有效/无效密钥数量统计

### 用户界面
- **响应式设计**：适配不同设备屏幕尺寸
- **分页浏览**：支持大量密钥的高效浏览和管理
- **直观操作**：简洁明了的操作界面

## 安装与设置

### 环境要求
- Python 3.8+
- FastAPI
- SQLAlchemy
- 其他依赖库（见 requirements.txt）

### 安装步骤

1. 克隆仓库
   ```bash
   git clone https://github.com/Inblac/gpt-proxy.git
   cd gpt-proxy
   ```

2. 创建虚拟环境并安装依赖
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. 创建 data 目录并配置 config.ini
   ```bash
   mkdir data
   cp config.ini.example data/config.ini
   # 按需编辑 data/config.ini
   ```

4. 初始化数据库（将在 ./data/gpt_proxy.db 生成）
   ```bash
   python -m gpt_proxy.database.init_db
   # 如果不存在会自动创建 data/gpt_proxy.db
   ```

5. 启动服务
   ```bash
   uvicorn gpt_proxy.main:app --host 0.0.0.0 --port 8000
   ```

### Docker & Docker Compose

- `config.ini` 和 `gpt_proxy.db` 必须都放在项目根目录下的 `./data` 目录。
- 使用 Docker 或 docker-compose 时，需将宿主机的 `./data` 目录挂载到容器的 `/data` 目录：

```yaml
docker-compose.yml 示例：

version: '3.8'
services:
  gpt-proxy:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

这样所有配置和数据都能持久化且易于管理。

## 使用说明

### 管理员登录
1. 访问系统首页 `http://localhost:8000/`
2. 使用管理员 API Key 登录

### 添加 API 密钥
1. 在管理界面，找到"添加新 OpenAI API Key"部分
2. 输入一个或多个 API 密钥（每行一个）
3. 点击"添加密钥"按钮

### 管理密钥状态
- 点击密钥列表中的"设为无效"或"设为有效"来切换密钥状态
- 使用"重新验证所有失效的 Key"按钮验证密钥有效性
- 使用"将所有无效 Key 重置为有效状态"功能批量恢复密钥

### 查看统计数据
- 监控面板显示调用统计和密钥池状态
- 每 30 秒自动刷新统计数据

## API 接口说明

### 代理请求
- `POST /v1/*` - 代理到 OpenAI API 的所有请求

### 管理接口
- `POST /token` - 管理员认证
- `GET /api/stats` - 获取统计数据
- `GET /api/keys/paginated` - 获取分页密钥列表
- `POST /api/keys/bulk` - 批量添加密钥
- `DELETE /api/keys/{key_id}` - 删除指定密钥
- `PUT /api/keys/{key_id}/status` - 更新密钥状态
- `POST /api/validate_keys` - 触发密钥验证

## 安全考虑

- 使用强密码作为管理员 API Key
- 定期轮换管理员 API Key
- 系统运行于受保护的网络环境
- 避免在公共环境暴露管理界面

## 贡献

欢迎提交问题报告和功能请求。如果您想贡献代码，请先开 issue 讨论您的想法，然后提交 PR。

## 许可证

[MIT License](LICENSE) 