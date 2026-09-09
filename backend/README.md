# 合同管理系统 - 后端服务

全新搭建的后端服务，配置简洁、运行稳定。

## 技术栈

- **FastAPI** - 现代化的Python Web框架
- **PostgreSQL** - 数据库
- **SQLAlchemy** - ORM
- **JWT** - 身份认证
- **Pydantic** - 数据验证

## 项目结构

```
contract-system-new/
├── app/
│   ├── core/           # 核心配置
│   │   ├── config.py   # 配置管理
│   │   ├── database.py # 数据库连接
│   │   └── security.py # JWT和密码加密
│   ├── models/         # 数据库模型
│   │   └── user.py
│   ├── routes/         # API路由
│   │   └── auth.py     # 认证API
│   ├── schemas/        # Pydantic模型
│   │   └── auth.py
│   ├── services/       # 业务逻辑
│   │   └── auth_service.py
│   └── main.py         # 应用入口
├── .env                # 环境配置
├── requirements.txt    # Python依赖
└── start.bat           # 启动脚本
```

## 快速开始

### 1. 启动后端

直接双击 `start.bat` 或在命令行运行：

```bash
cd C:\Users\gdy\Desktop\contract-system-new
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 访问API文档

启动后访问：
- Swagger文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

## API端点

### 认证相关

#### 登录
```
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "password123"
}
```

**响应示例：**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "username": "admin",
    "full_name": "管理员",
    "email": "admin@example.com",
    "role": "ceo"
  }
}
```

#### 刷新令牌
```
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "your_refresh_token_here"
}
```

## 测试用户

| 用户名  | 密码        | 角色   |
|---------|-------------|--------|
| admin   | password123 | CEO    |
| legal   | password123 | 法务   |
| manager | password123 | 经理   |

## 环境配置

`.env` 文件包含以下配置：

```env
# 数据库
DATABASE_URL=postgresql+pg8000://postgres:123456@localhost:5432/contractsystem

# JWT密钥
JWT_SECRET_KEY=8KxZ_vYNm4pQ2wR-jL5sT9fH3nE7cB6uA1dG0iX
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# API配置
API_V1_PREFIX=/api/v1
PROJECT_NAME=Contract Management System
```

## 特点

✅ **配置加载正常** - .env文件正确解析  
✅ **数据库连接稳定** - PostgreSQL连接池配置  
✅ **JWT认证完整** - 访问令牌 + 刷新令牌  
✅ **错误处理完善** - 详细的日志记录  
✅ **API文档自动生成** - Swagger UI  
✅ **CORS配置** - 支持跨域请求  

## 故障排除

### 端口被占用

如果8000端口被占用，先关闭所有Python进程：

```bash
taskkill /F /IM python.exe
```

### 数据库连接失败

确保PostgreSQL服务正在运行，并且数据库`contractsystem`已创建。

## 开发

### 安装依赖

```bash
pip install -r requirements.txt
```

### 本地 BGE 向量模型

BGE 不提交到代码仓库。先安装可选依赖，再从魔塔社区下载：

```bash
pip install -r requirements-bge.txt
python scripts/download_bge.py --output ./models/bge-small-zh-v1.5
```

下载完成后，将 `.env` 中的 `BGE_MODEL_PATH` 指向脚本输出目录。未配置或模型不可用时，系统会明确使用 `hash_fallback`，不会伪造为 BGE。

### 运行开发服务器

```bash
uvicorn app.main:app --reload
```

## 日志

应用日志会输出到控制台，包括：
- 请求信息
- 认证成功/失败
- 数据库查询
- 错误堆栈

## 下一步

后续可以添加：
- 合同管理API
- 客户管理API
- 文件上传
- 数据分析
- 权限控制

---

**创建日期:** 2026-08-24  
**状态:** ✅ 测试通过，可正常使用
