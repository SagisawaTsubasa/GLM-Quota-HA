# GLM-Quota-HA

Home Assistant 自定义集成：监控智谱 **GLM Coding Plan**（国内站 open.bigmodel.cn）的 **5 小时窗口限额**与**周限额**。

- **四个实体**：5 小时窗口已用（%）、周限额已用（%）两个传感器 + 自动轮询开关 + 手动查询按钮
- **密文保存**：API Key 经 Fernet 加密后存入 config entry，主密钥放独立 `.storage` 文件，`core.config_entries` 中不落明文
- 订阅信息（套餐名/到期/续费日）与窗口量值（已用/总量/剩余/重置时间）作为实体属性附带

## 巡查模式（自动轮询 / 手动查询，互斥）

集成提供一个开关和一个按钮（挂在同一设备下）：

| 实体 | 行为 |
|---|---|
| `自动轮询` 开关 | 开（默认）= 按轮询间隔自动刷新；关 = 进入**手动模式**，停止定时轮询 |
| `手动查询` 按钮 | 按下立即拉取一次数据；**仅在手动模式下可用**（自动轮询开启时置灰） |

手动模式跨重启保持（重启后仍是上次模式）。没有常驻轮询需求的话，关掉自动轮询、想看的时候按一下「手动查询」即可。

## 实体

实体挂在「GLM Coding Plan (指纹后缀)」设备下，名称如下（entity_id 由 HA 按设备名+实体名自动生成）：

| 实体名 | 读数 | 主要属性 |
|---|---|---|
| 5小时窗口已用 | 已用 % | `used`/`total`/`remaining`（量值）、`remaining_percent`、`reset_time`（下次重置）、`plan_name`/`plan_level`/`plan_valid_until`/`plan_next_renew` |
| 周限额已用 | 已用 % | 同上 |

配置多个账号时，条目标题与设备名会带 key 指纹后缀（如 `GLM Coding Plan (a1b2c3d4e5f6)`）用于区分。

## 安装（HACS）

1. HACS → 自定义存储库 → 仓库 `SagisawaTsubasa/GLM-Quota-HA`，类别「集成」
2. 下载后**重启 Home Assistant**
3. 设置 → 设备与服务 → 添加集成 → 搜索 **GLM Coding Plan Quota**
4. 粘贴 API Key（智谱开放平台控制台获取；需已订阅 GLM Coding Plan）

## 获取 API Key

1. 登录 [智谱开放平台](https://open.bigmodel.cn/) → API Keys
2. 复制形如 `{id}.{secret}` 的密钥（与 Coding Plan 订阅同账号）

## 工作原理与限制

- 数据来自智谱订阅页同源的内部接口 `GET /api/monitor/usage/quota/limit`（Bearer 认证）。**该接口为非官方公开契约**，智谱改版可能导致解析失败——届时实体会转不可用并在日志留下原始响应，请提 issue
- 窗口归属优先按响应中的 `unit`/`number` 判定，旧格式按重置时间距离兜底（≤6h 判 5 小时窗口，≤8 天判周窗口）
- 响应的鉴权错误藏在 HTTP 200 的 body 里（`code=401`），集成按 body 业务码分诊：401 → 自动触发重新认证
- 默认轮询 300 秒，可在集成选项里调整（60–86400 秒）

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| 集成条目提示需要重新认证，日志出现「令牌已过期或验证不正确」 | Key 失效（body code=401），进入集成的「重新认证」重新粘贴 |
| 添加时报「该账号没有有效的 GLM Coding Plan 订阅限额」 | 该账号无 Coding Plan 订阅，或 Key 属于另一账号 |
| 日志出现「API key 解密失败」 | `.storage/glm_quota_master_key` 被删、重建或损坏，走「重新认证」重录 Key 即可恢复 |
| 日志出现「限额响应解析失败」 | 智谱接口改版，请附日志中的原始响应提 issue |
| 日志出现「订阅信息获取失败/鉴权异常」 | 订阅接口临时异常，仅套餐属性缺失，额度实体不受影响 |

## License

MIT
