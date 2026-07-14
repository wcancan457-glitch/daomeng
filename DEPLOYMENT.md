# 导梦上线部署说明

这份说明给第一次部署项目的人使用。项目分成两部分：

- 后端 API：负责调用模型、生成素材、保存任务数据。
- 前端网页：别人打开的网址，也就是导梦的使用界面。

推荐组合：

- 后端部署到 Render。
- 前端部署到 Vercel。

## 1. 部署后端到 Render

1. 打开 <https://render.com/> 并登录。
2. 选择 **New +**。
3. 选择 **Blueprint**。
4. 连接 GitHub，并选择仓库 `wcancan457-glitch/daomeng`。
5. Render 会读取仓库根目录的 `render.yaml`。
6. 出现环境变量填写页面时，至少填写：

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

7. 点击创建并等待部署完成。
8. 部署成功后，Render 会给你一个后端地址，类似：

```text
https://daomeng-api.onrender.com
```

9. 打开下面这个地址测试：

```text
https://你的后端地址/api/health
```

如果能看到健康检查返回，就说明后端部署成功。

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
