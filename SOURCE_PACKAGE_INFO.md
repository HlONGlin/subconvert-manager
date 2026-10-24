# 纯净源码包说明

- 来源：监听端口 33183 的项目 /opt/subconvert-manager
- 已排除：.git、.venv、Python 字节码缓存、运行时真实数据和真实配置
- 配置模板：复制 config.env.example 为 config.env 后填写部署参数
- 数据模板：data/sources.json.example，部署时由应用生成或导入真实数据
- 本包不包含真实订阅链接、认证口令、token、会话密钥或服务器运行状态
