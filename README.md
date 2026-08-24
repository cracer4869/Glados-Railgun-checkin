# Glados自动签到

## 食用方式：

### 注册一个GLaDOS的账号([注册地址](https://glados.space/landing/0A58E-NV28S-6U3QV-33VMG))

#### 我的邀请码：([0A58E-NV28S-6U3QV-33VMG](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

#### 我的优惠码（9折）：([DEVILSTORE](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

### **Fork**本仓库

![图片加载失败](imgs/1.png)

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`GLADOS_COOKIES`，其值对应GLaDOS账号的cookie值中的有效部分（获取方式如下）

- 在GLaDOS的签到页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- 多账号请在 `COOKIES` 中 添加多个 `cookies` 中间使用 `&`连接即可。（例如： `c1&c3&c3...`）

3. 配置积分兑换策略（非必须）

- 在`Settings`->`Secrets and variables`->`Actions`->`Variables`页签下添加1个`repository variable`，命名为`GLADOS_EXCHANGE_PLAN`，配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 | 单天成本 |
|---|---------|---------|---------|
| `plan100` | 100 积分 | 10 天 | 10 积分/天 |
| `plan200` | 200 积分 | 30 天 | 6.7 积分/天 |
| `plan500` | 500 积分 | 100 天 (默认) | 5 积分/天 |

> 不配置时默认为 `plan500`，即积分达到 500 时自动兑换 100 天
>
> 脚本只在**积分达标时**才会调用兑换接口，未达标只记录 `积分未达标: x/y`，不会产生无意义的失败请求。
> 因此按每天约 10 积分计算：`plan100` 约 10 天兑换一次，`plan200` 约 20 天一次，`plan500` 约 50 天一次。
> 积分利用率上 `plan500` 最划算（5 积分/天），`plan100` 最贵（10 积分/天）。
>
> 该项属于非敏感配置，放在 `Variables` 里 Actions 日志不会打码成 `***`，方便排查问题；
> 放在 `Secrets` 里同样生效（`Variables` 优先）。

4. 指定签到域名（非必须）

- 添加1个`repository variable`，命名为`GLADOS_DOMAINS`，多个域名用 `,` 分隔，例如 `glados.cloud,railgun.info`。

> 不配置时默认同时签到 `glados.cloud` 和 `railgun.info`。
> 如果账号只存在于其中一个站点，另一个站点会每次都返回"签到失败"造成推送噪音，
> 此时只填写实际使用的域名即可（例如仅 `glados.cloud`）。

5. 消息推送（非必须，两种可同时配置）

**飞书（推荐）**

- 在飞书群里点 `设置` -> `群机器人` -> `添加机器人` -> `自定义机器人`，复制 Webhook 地址

- 添加1个`repository secret`，命名为`FEISHU_WEBHOOK`，值为该 Webhook 地址

  > 参考格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

- 推送内容为飞书交互式卡片，标题栏颜色代表整体状态：

| 颜色 | 含义 |
|---|---|
| 🟩 绿色 | 签到全部正常（成功或重复），兑换无失败 |
| 🟧 橙色 | 签到正常，但兑换接口返回失败 |
| 🟥 红色 | 存在签到失败，或脚本执行出错 |

- 卡片内包含：签到成功/重复/失败数量、兑换成功/未达标/失败数量、当前兑换策略、每个账号的获得积分、总积分、剩余天数与兑换结果。

**PushDeer**

- 添加1个`repository secret`，命名为`PUSHDEER_SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### **star**自己的仓库

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 更新日志

- **2026-01**: 重构代码，添加log输出方便定位，支持新版网址，支持配置积分兑换策略。
- **2026-04**: 优化代码逻辑，优化日志输出，支持[新版域名](https://railgun.info) ，在 GLADOS_COOKIES 中添加新版域名下的 cookies 即可使用。
- **2026-08**: 新增飞书机器人推送（`FEISHU_WEBHOOK`）；兑换改为积分达标才触发，避免每次运行都产生失败请求；新增 `GLADOS_DOMAINS` 用于指定签到域名。


## 问题排查与定位
- 大家可以通过查询 actions 中的 running checkin 日志快速定位问题，有其他问题提交issue。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份







