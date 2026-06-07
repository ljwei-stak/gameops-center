# GameOps Center

GameOps Center 是一个游戏服务器运维开发项目，面向“区服监控、告警、发布、日志、流量调度”的日常场景。项目不依赖第三方包，使用 Python 标准库提供后端 API，前端使用原生 HTML/CSS/JavaScript。

## 功能

- 游戏区服监控：在线玩家、容量水位、CPU、内存、P95 延迟、丢包率、版本号。
- 实时告警：根据 CPU、内存、延迟、丢包、容量、维护状态生成告警。
- 发布编排：支持金丝雀、滚动发布、故障热修三种策略。
- 运维动作：支持重启游戏服务器、调整战区流量权重。
- 日志中心：查看发布、告警、路由、网关等操作日志。
- 趋势看板：前端 Canvas 绘制在线玩家与延迟趋势。

## 运行

```powershell
cd E:\program_file\Shell_project\gameops-center
python app.py
```

浏览器打开：

```text
http://127.0.0.1:8018
```

如果 8018 端口被占用，可以指定端口：

```powershell
python app.py 8020
```

## 测试

```powershell
cd E:\program_file\Shell_project\gameops-center
python -m unittest discover -s tests
```

## API 示例

```powershell
Invoke-RestMethod http://127.0.0.1:8018/api/overview
Invoke-RestMethod http://127.0.0.1:8018/api/servers
Invoke-RestMethod http://127.0.0.1:8018/api/alerts
```

发布一个版本：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8018/api/deploy `
  -ContentType 'application/json' `
  -Body '{"region":"cn-east","version":"v1.9.0","strategy":"canary","operator":"ops-admin"}'
```

## 项目结构

```text
gameops-center/
  app.py                 # HTTP API 和静态资源服务
  gameops/
    data.py              # 游戏区服模拟数据
    engine.py            # 运维规则、发布、告警、日志逻辑
  web/
    index.html           # 前端页面
    styles.css           # 控制台样式
    app.js               # 前端交互和 API 调用
  tests/
    test_engine.py       # 后端核心逻辑单元测试
```

## 可扩展方向

- 接入 Prometheus 指标格式：暴露 `/metrics`，把模拟指标替换成真实采集数据。
- 接入 Docker 或 Kubernetes：把重启、发布动作改成调用容器编排接口。
- 增加用户登录与 RBAC：区分 SRE、发布负责人、只读观察员。
- 增加数据库：用 SQLite 或 MySQL 持久化发布记录、操作日志、告警历史。
- 增加告警通知：对接企业微信、钉钉、邮件或 Webhook。

