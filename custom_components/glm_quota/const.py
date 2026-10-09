"""Constants for the GLM Coding Plan quota integration."""

DOMAIN = "glm_quota"

# 智谱开放平台（国内站）非官方订阅接口，与 bigmodel.cn 订阅页同源
QUOTA_API_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
SUBSCRIPTION_API_URL = "https://open.bigmodel.cn/api/biz/subscription/list"

CONF_API_KEY = "api_key"  # entry data 里存的是 Fernet 密文，不是明文

REQUEST_TIMEOUT = 15

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 86400

# coordinator.data 里的两个窗口槽位（与 parse.py 保持一致）
FIVE_HOUR = "five_hour"
WEEKLY = "weekly"
