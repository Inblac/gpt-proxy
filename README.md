# GPT Proxy

A simple OpenAI API key management platform for efficiently managing and optimizing API key pools, implementing proxy requests and key rotation.

## Features

### Key Management
- **Bulk Key Addition**: Add multiple OpenAI API keys at once
- **Key Status Management**: Maintain valid/invalid status of keys
- **Automatic Validation**: Automatically validate the validity of keys
- **Batch Reset**: Reset all invalid keys to valid status with one click

### Request Proxy and Load Balancing
- **Intelligent Proxy**: Automatically route requests to valid API keys
- **Load Balancing**: Evenly distribute requests to optimize key usage

### Data Statistics and Monitoring
- **Real-time Statistics**: Display call statistics for the last 1 minute, 1 hour, 24 hours, and total
- **Key Usage Tracking**: Record the number of uses and last used time for each key
- **Key Pool Status**: Display valid/invalid key count statistics

### User Interface
- **Responsive Design**: Adapt to different device screen sizes
- **Paginated Browsing**: Efficiently browse and manage large numbers of keys
- **Intuitive Operation**: Clear and straightforward operation interface

## Installation and Setup

### Requirements
- Python 3.8+
- FastAPI
- SQLAlchemy
- Other dependencies (see requirements.txt)

### Installation Steps

1. Clone the repository
   ```bash
   git clone https://github.com/Inblac/gpt-proxy.git
   cd gpt-proxy
   ```

2. Create a virtual environment and install dependencies
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Create a data directory and configure config.ini
   ```bash
   mkdir data
   cp config.ini.example data/config.ini
   # Edit data/config.ini as needed
   ```

4. Initialize the database (will be created as ./data/gpt_proxy.db)
   ```bash
   python -m gpt_proxy.database.init_db
   # This will create data/gpt_proxy.db if it does not exist
   ```

5. Start the service
   ```bash
   uvicorn gpt_proxy.main:app --host 0.0.0.0 --port 8000
   ```

### Docker & Docker Compose

- Both `config.ini` and `gpt_proxy.db` must be placed in the `./data` directory.
- When using Docker or docker-compose, mount the host's `./data` directory to the container's `/data` directory:

```yaml
docker-compose.yml example:

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

This ensures all configuration and data are persistent and easy to manage.

## Usage Instructions

### Admin Login
1. Visit the system homepage `http://localhost:8000/`
2. Log in using the admin API Key

### Adding API Keys
1. In the admin interface, find the "Add New OpenAI API Key" section
2. Enter one or more API keys (one per line)
3. Click the "Add Keys" button

### Managing Key Status
- Click "Set Invalid" or "Set Valid" in the key list to toggle key status
- Use the "Revalidate All Invalid Keys" button to verify key validity
- Use the "Reset All Invalid Keys to Valid Status" feature to batch restore keys

### Viewing Statistics
- The dashboard displays call statistics and key pool status
- Statistics automatically refresh every 30 seconds

## API Interface Description

### Proxy Requests
- `POST /v1/*` - Proxy all requests to the OpenAI API

### Management Interfaces
- `POST /token` - Admin authentication
- `GET /api/stats` - Get statistics data
- `GET /api/keys/paginated` - Get paginated key list
- `POST /api/keys/bulk` - Bulk add keys
- `DELETE /api/keys/{key_id}` - Delete specified key
- `PUT /api/keys/{key_id}/status` - Update key status
- `POST /api/validate_keys` - Trigger key validation

## Security Considerations

- Use a strong password as the admin API Key
- Regularly rotate the admin API Key
- Run the system in a protected network environment
- Avoid exposing the admin interface in public environments

## Contributing

Bug reports and feature requests are welcome. If you want to contribute code, please open an issue to discuss your ideas first, then submit a PR.

## License

[MIT License](LICENSE)

## 数据库配置

GPT-Proxy默认使用SQLite数据库存储API密钥和相关数据。现在也支持使用PostgreSQL作为替代选项。

### 配置数据库类型

在`data/config.ini`文件中，添加或修改`[Database]`部分来配置数据库：

```ini
[Database]
# 数据库类型: sqlite (默认) 或 postgresql
type = sqlite

# 以下配置仅在 type = postgresql 时使用
host = localhost
port = 5432
database = gpt_proxy
user = postgres
password = your_password
```

### PostgreSQL支持

如果要使用PostgreSQL，需要安装psycopg2库：

```bash
pip install psycopg2-binary
```

然后修改配置文件，将`type`设置为`postgresql`，并配置正确的连接参数。 