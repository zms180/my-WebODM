# GeoModel 部署包

此目录包含 GeoModel 系统私有部署所需的所有配置文件。

## 📁 文件清单

```
deploy-package/
├── 私有部署指南.md              # 完整部署文档
├── Dockerfile.webapp           # webapp 镜像构建文件
├── Dockerfile.nodeodx          # nodeodx 镜像构建文件
├── docker-compose.yml          # 主服务编排文件
├── docker-compose.nodeodx.yml  # NodeODX 处理节点配置
├── .env.example                # 配置文件示例
├── geomodel.sh                 # 启动脚本
└── README.md                   # 本文件
```

## 🚀 快速开始

### 开发服务器（构建镜像）

```bash
# 1. 在项目根目录构建镜像
cd /d/外部项目/WebODM

# 2. 构建 webapp 镜像
docker build \
  --platform linux/amd64 \
  --pull=false \
  -t geomodel_webapp:v1.0 \
  -f deploy-package/Dockerfile.webapp \
  .

# 3. 构建 nodeodx 镜像
docker build \
  --platform linux/amd64 \
  --pull=false \
  -t geomodel_nodeodx:v1.0 \
  -f deploy-package/Dockerfile.nodeodx \
  .

# 4. 重命名 db 镜像
docker tag webodm/webodm_db:latest geomodel_db:v1.0

# 5. 导出镜像
docker save \
  geomodel_webapp:v1.0 \
  geomodel_db:v1.0 \
  geomodel_nodeodx:v1.0 \
  redis:7.0.10 \
  -o geomodel-images.tar
```

### 准备客户端部署包

```bash
# 1. 创建部署目录
mkdir -p geomodel-deploy
cd geomodel-deploy

# 2. 复制配置文件
cp ../deploy-package/docker-compose.yml .
cp ../deploy-package/docker-compose.nodeodx.yml .
cp ../deploy-package/.env.example .env
cp ../deploy-package/geomodel.sh .
cp ../deploy-package/私有部署指南.md .

# 3. 编辑配置（可选，也可以在客户服务器上修改）
nano .env

# 4. 打包配置
cd ..
tar -czf geomodel-deploy.tar.gz geomodel-deploy/
```

### 传输文件到客户服务器

需要传输的文件：
- `geomodel-images.tar` (约 7 GB)
- `geomodel-deploy.tar.gz` (约 5 KB)

### 客户服务器部署

```bash
# 1. 导入镜像
docker load -i geomodel-images.tar

# 2. 解压配置
tar -xzf geomodel-deploy.tar.gz
cd geomodel-deploy/

# 3. 修改配置
nano .env
# 必须修改：
# - WO_HOST（改为服务器 IP）
# - WO_SECRET_KEY（改为随机字符串）

# 4. 启动服务
chmod +x geomodel.sh
./geomodel.sh

# 5. 创建管理员账户
docker exec -it webapp python manage.py createsuperuser
```

## 📖 详细文档

完整部署步骤请查看：[私有部署指南.md](私有部署指南.md)

## ❓ 常用命令

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f webapp

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 进入容器
docker exec -it webapp bash
```

## 🔧 故障排查

### 服务无法启动

```bash
# 检查端口占用
netstat -tuln | grep 8000

# 检查磁盘空间
df -h

# 查看详细错误
docker-compose logs webapp
```

### GPU 不可用

如果服务器没有 GPU，只启动基础服务：

```bash
docker-compose -f docker-compose.yml up -d
```

## 📞 支持

如有问题，请查看：
1. [私有部署指南.md](私有部署指南.md) - 完整文档
2. Docker 日志 - `docker-compose logs`
3. 系统日志 - `/var/log/`
