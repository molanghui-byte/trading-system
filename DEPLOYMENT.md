# 交易系统看板上线说明

## 当前已经具备的上线产物

当前仓库已经包含一个可正式部署的 FastAPI 看板：

- 入口应用：`app.dashboard:app`
- 健康检查：`/healthz`
- 默认端口：`8050`
- 生产启动脚本：
  - `deploy_dashboard.ps1`
  - `deploy_dashboard.bat`
- Docker 产物：
  - `Dockerfile`
  - `docker-compose.yml`
- Nginx 反向代理示例：
  - `deploy/nginx/trading-dashboard.conf`

## 本机直接启动

```powershell
cd c:\Users\Administrator\Desktop\DEV\trading-system
.\deploy_dashboard.ps1
```

本机验证地址：

```text
http://127.0.0.1:8050/
http://127.0.0.1:8050/healthz
```

## 正式上线为公网网站还需要什么

要真正让外网访问，还需要这些外部条件：

1. 一台有公网 IP 的服务器或云主机
2. 一个域名
3. 防火墙放行 80 / 443
4. 反向代理，推荐 Nginx
5. HTTPS 证书，推荐 Let's Encrypt

## Railway 部署

这个仓库现在已经补好了 Railway 所需的关键文件：

- `Dockerfile`
- `railway.toml`
- `/healthz`

按照 Railway 官方文档，平台会读取代码库中的 `railway.toml` 作为本次部署配置，并且健康检查会用你配置的路径；公网服务需要监听 Railway 注入的 `PORT` 变量。当前 Dockerfile 已经按这个要求处理。

### Railway 上线步骤

1. 把仓库推到 GitHub
2. 在 Railway 里新建 Project
3. 选择 `Deploy from GitHub Repo`
4. 选中这个仓库
5. Railway 会检测到：
   - `Dockerfile`
   - `railway.toml`
6. 首次部署成功后，在 Railway 的服务里点击生成域名
7. 打开分配的 `*.up.railway.app` 域名

### Railway 里建议设置的变量

- `APP_MODE=paper`
- 如果你想固定端口，可额外设置：
  - `PORT=8050`

如果你不手动设置 `PORT`，Railway 会自动提供一个端口，当前 Dockerfile 也会正确监听。

### Railway 健康检查

- 路径：`/healthz`
- 成功条件：返回 HTTP `200`

### Railway 域名

Railway 支持：

- 平台分配域名 `*.up.railway.app`
- 你自己的自定义域名

## 方案 A：Windows 服务器直接部署

1. 把整个项目复制到服务器
2. 安装 Python 3.11+
3. 安装依赖：

```powershell
pip install -r requirements.txt
```

4. 启动看板：

```powershell
.\deploy_dashboard.ps1
```

5. 用 IIS、Nginx 或云负载均衡把 80/443 反代到 `127.0.0.1:8050`

## 方案 B：Docker 部署

```powershell
docker compose up -d --build
```

默认会把容器的 `8050` 暴露到宿主机 `8050`。

## Nginx 反代

示例配置见：

`deploy/nginx/trading-dashboard.conf`

核心思路：

- 外部 `80/443`
- 转发到 `127.0.0.1:8050`

## HTTPS

如果你有域名，建议这样做：

1. 域名 A 记录指向服务器公网 IP
2. Nginx 配好 `server_name`
3. 用 Certbot 或云平台证书服务启用 HTTPS

## 当前状态说明

这个仓库现在已经具备“可部署为网站”的代码和脚本，但如果没有：

- 公网服务器
- 域名
- 反向代理
- HTTPS 证书

那它还只是“可上线”，不是“已经对公网正式开放”。

## 上线前建议再补

正式对公网开放前，建议至少再做：

1. 登录鉴权
2. IP 白名单
3. HTTPS
4. 将交易主程序和看板拆成两个独立进程并做守护
5. 备份 `data/trading.db`
