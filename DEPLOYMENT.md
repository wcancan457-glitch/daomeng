# 导梦上线部署说明

这份说明给第一次部署项目的人使用。项目分成两部分：

- 后端 API：负责调用模型、生成素材、保存任务数据。
- 前端网页：别人打开的网址，也就是导梦的使用界面。

生产环境推荐组合：

- 后端部署到 Render，并使用 PostgreSQL 与持久磁盘。
- 前端部署到 Vercel。

> 当前仓库根目录的 `render.yaml` 仍保留免费测试环境配置。免费实例的本地文件会随重启丢失，不能作为真实用户版本。切换生产配置前，请先准备 PostgreSQL 和持久磁盘。

## 1. 部署后端到 Render

1. 打开 <https://render.com/> 并登录。
2. 选择 **New +**。
3. 选择 **Blueprint**。
4. 连接 GitHub，并选择仓库 `wcancan457-glitch/daomeng`。
5. Render 会读取仓库根目录的 `render.yaml`。
6. 创建 PostgreSQL 数据库，并把内部连接地址填写为：

```text
DATABASE_URL=postgresql://...
```

7. 给 Web Service 挂载持久磁盘，挂载路径设为 `/var/data`，然后设置：

```text
RUNTIME_DATA_DIR=/var/data
```

8. 开启真实用户注册登录：

```text
AUTH_MODE=users
AUTH_TOKEN_SECRET=至少32位的随机字符串
REGISTRATION_ENABLED=true
ADMIN_EMAIL=你的管理员邮箱
APP_ACCESS_PASSWORD=管理员初始强密码
AUTH_ACCESS_TOKEN_TTL_SECONDS=900
AUTH_REFRESH_TOKEN_TTL_SECONDS=2592000
MAX_SESSIONS_PER_USER=10
AUTH_RATE_LIMIT_PER_MINUTE=10
MAX_PENDING_TASKS_PER_USER=10
MAX_CONCURRENT_TASKS_PER_USER=1
PIPELINE_WORKER_CONCURRENCY=1
```

`APP_ACCESS_PASSWORD` 在用户模式下只用于首次创建管理员账号。部署成功并确认管理员能登录后，应在 Render 中妥善保管并定期更换。

9. 模型服务至少填写：

```text
SILICONFLOW_API_KEY=你的硅基流动 API Key
```

如果你要生成图片或视频，还需要按模型选择填写：

```text
DASHSCOPE_API_KEY=通义 / DashScope Key
ARK_API_KEY=火山方舟 Key
KLING_ACCESS_KEY=可灵 Access Key
KLING_SECRET_KEY=可灵 Secret Key
```

10. 点击创建并等待部署完成。容器启动时会自动执行数据库迁移。
11. 部署成功后，Render 会给你一个后端地址，类似：

```text
https://daomeng-api.onrender.com
```

12. 依次打开下面两个地址测试：

```text
https://你的后端地址/api/health
https://你的后端地址/api/health/ready
```

第二个地址返回 `status: ready`，才说明数据库、存储和认证配置均可用。

## 2. 部署前端到 Vercel

1. 打开 <https://vercel.com/> 并登录。
2. 选择 **Add New...** → **Project**。
3. 导入 GitHub 仓库 `wcancan457-glitch/daomeng`。
4. Root Directory 选择：

```text
daomeng/daomeng/frontend
```

5. Framework Preset 选择：

```text
Next.js
```

6. 添加环境变量：

```text
NEXT_PUBLIC_API_URL=https://你的后端地址
NEXT_PUBLIC_API_BASE_URL=https://你的后端地址
```

注意不要在地址最后加 `/`。

7. 点击 **Deploy**。
8. 部署成功后，Vercel 会给你一个前端地址，类似：

```text
https://daomeng.vercel.app
```

这个就是可以分享给别人的导梦前端网址。

## 3. 把网址显示到 GitHub 右侧

1. 回到 GitHub 仓库页面。
2. 右侧 **About** 区域点击齿轮图标。
3. Website 填入 Vercel 前端地址。
4. Description 可以填：

```text
导梦：AI 视频创作工作台
```

5. 保存。

之后别人打开你的 GitHub 仓库，就能在右侧看到可访问的网站链接。
