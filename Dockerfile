FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY gpt_proxy ./gpt_proxy

# 创建挂载目录
RUN mkdir -p /data

# 启动命令，config.ini和gpt_proxy.db通过挂载到/data目录
CMD ["uvicorn", "gpt_proxy.main:app", "--host", "0.0.0.0", "--port", "8000"] 