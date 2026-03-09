# 股票助手（C 端散户版 MVP）

面向散户用户的股票分析助手，目标是：

- 降低决策噪音，优先控制风险
- 提供可解释的智能分析与执行建议
- 用统一仪表板串联“发现机会 → 风险判断 → 交易计划”

技术栈：

- 前端：React + TypeScript + Ant Design
- 后端：FastAPI + MySQL（`mysql+pymysql`）

## 当前功能

### 1) 仪表板与导航
- 路由：`/home`、`/dashboard`、`/stocks`、`/stocks/:symbol`、`/admin/feedbacks`
- 菜单：`首页 / 仪表板 / 股票池 / 通知 / 设置 / 登录注册 / 我的资产 / 反馈管理`
- 访问策略：仅 `股票池`（含个股详情）支持未登录访问，其他页面需登录
- 首页保留 Slogan 与快捷入口，仪表板聚合风险与机会

### 2) 股票池交互优化
- 支持筛选：`已分析/未分析`、`市场`、`板块`、`交易所`、`行业`、`概念板块`、`标签`、`建议动作`、`评分区间`、`涨跌幅区间`、`关键词`
- 支持排序：`评分`、`涨跌幅`、`价格`
- 提供结果概览：数量、机会标的、平均评分、上涨占比、中位评分
- 提供量化分布看板：市场/板块/建议动作分布、Top 行业、Top 概念板块、Top 标签
- 提供板块轮动分析：样本门槛、广谱概念降权、相对全市场强弱、板块扩散率与下一潜力板块推理
- 股票池来源升级为交易所全量数据：
  - A股（主板/创业板/科创板/北交所）
  - 港股
- 支持分页查询与手动同步全量股票池
- 每只股票展示标签，可按标签快速筛选同类标的

### 3) 智能分析与个股详情
- 后端内置规则引擎，输出：
  - 综合评分（0-100）
  - 建议动作（buy/watch/hold_cautious/avoid）
  - 风险等级（low/medium/high）
  - 置信度与五维因子评分（基本面/估值/动量/情绪/风控）
  - 优势、风险、执行动作清单
  - 持续监控清单与情景推演
  - 交易计划（入场区间、止损位、目标位、仓位建议）
- 个股深度资料整合：
  - 官网、投资者关系、交易所资料、行情页直达链接
  - 公司档案（上市日期、总部、法定代表人、员工规模、主营业务）
  - 历年财报摘要（营收/净利润/ROE/负债率/经营现金流）
  - 估值历史与分红历史
  - 股东结构、同行对比、新闻舆情要点、催化事件与关键风险
- 前端详情页展示：
  - 数据可信度（来源、覆盖率、更新时间、可信度评分、风险提示）
  - 分析依据与适配提示（方法论、证据点、适合的风险偏好）
  - 行情与估值快照（价格、换手率、振幅、支撑/压力位）
  - 公司画像、研究主线、近期跟踪事件与深度资料看板
  - 五维因子评分、风险提示、交易与监控清单

### 4) 反馈闭环
- 全局反馈抽屉（任意页面可提反馈）
- 支持反馈类型、影响范围、内容校验
- 自动携带上下文：path/query/symbol/device_id/user_agent
- 管理页支持筛选与状态流转：`new -> triaged -> done`

### 5) 反馈限流
- 同一身份（IP + device_id/user_id）：
  - 3 秒内最多 1 次
  - 60 秒最多 5 次
- 超限返回 `429`

### 6) 全量详情数据补齐引擎
- 新增逐股联网补齐：官网、投资者关系、交易所资料、财报摘要、分红、股东、舆情等
- 支持批量执行与进度统计（覆盖率、已补齐数量、最新补齐时间）
- 数据源：`yfinance + akshare + 交易所公开页面`

### 7) 平台化能力（多用户）
- 默认管理员：`tianyuyezi / 88888888`（可通过环境变量覆盖）
- 账号体系：注册、登录、鉴权、用户信息
- 找回密码：验证码重置密码（当前为站内演示模式）
- 个人自选：分组、标签、备注、目标仓位、价格提醒阈值
- 个人持仓：持仓记录、浮盈亏、仓位权重、集中度与风险提示
- 持仓跟进：跟进状态、阶段、行动项、到期提醒（复盘闭环）
- 个股跟进复盘：登录后可见且按用户隔离，仅展示当前账号自己的记录
- 管理员可在个股跟进复盘中查看全体用户记录（含归属用户名）
- 通知中心：价格预警、财报提醒、跟进到期提醒（支持开关与已读）
- 管理员控制：反馈管理接口鉴权、用户角色与启用状态管理

## API 概览

### 健康检查
- `GET /api/v1/health`

### 股票与仪表板
- `GET /api/v1/stocks?analyzed=&market=&board=&exchange=&industry=&tag=&recommendation=&score_min=&score_max=&change_pct_min=&change_pct_max=&q=&sort_by=&page=&page_size=`
- `GET /api/v1/stocks/sectors/rotation?market=&top_n=`
- `POST /api/v1/stocks/sync?force=`
- `POST /api/v1/stocks/enrich?force=&market=&limit=&sleep_ms=`
- `GET /api/v1/stocks/enrich/status`
- `GET /api/v1/stocks/{symbol}`
- `GET /api/v1/stocks/{symbol}/analysis`
- `GET /api/v1/dashboard/summary`

### 账号与个人资产
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/password/forgot`
- `POST /api/v1/auth/password/reset`
- `GET /api/v1/auth/me`
- `GET /api/v1/me/watchlist`
- `POST /api/v1/me/watchlist`
- `PATCH /api/v1/me/watchlist/{item_id}`
- `DELETE /api/v1/me/watchlist/{item_id}`
- `GET /api/v1/me/positions`
- `POST /api/v1/me/positions`
- `PATCH /api/v1/me/positions/{position_id}`
- `DELETE /api/v1/me/positions/{position_id}`
- `GET /api/v1/me/positions/analysis`
- `GET /api/v1/me/followups`
- `POST /api/v1/me/followups`
- `PATCH /api/v1/me/followups/{follow_up_id}`
- `DELETE /api/v1/me/followups/{follow_up_id}`
- `GET /api/v1/me/notification-settings`
- `PATCH /api/v1/me/notification-settings`
- `POST /api/v1/me/notifications/refresh`
- `GET /api/v1/me/notifications?unread_only=`
- `POST /api/v1/me/notifications/{notification_id}/read`

### 管理员
- `GET /api/v1/admin/users?limit=&q=`
- `PATCH /api/v1/admin/users/{user_id}`

### 反馈
- `POST /api/v1/feedbacks`
- `GET /api/v1/feedbacks?status=&type=&scope=&limit=`（管理员）
- `PATCH /api/v1/feedbacks/{id}/status`（管理员）

## 本地运行

### 推荐方式（前台常驻，最稳）

```bash
bash scripts/dev_run.sh
```

说明：
- 该模式会在一个终端里持续运行前后端。
- 看到 `服务运行中...` 后，直接打开浏览器即可。
- 停止服务按 `Ctrl+C`。

### 守护方式（后台启动）

```bash
bash scripts/dev_up.sh
```

查看状态：

```bash
bash scripts/dev_status.sh
```

停止：

```bash
bash scripts/dev_down.sh
```

### 手动方式（分别启动）

1) 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

2) 启动前端

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

### 常用地址
- 前端首页：[http://127.0.0.1:5173/home](http://127.0.0.1:5173/home)
- 前端仪表板：[http://127.0.0.1:5173/dashboard](http://127.0.0.1:5173/dashboard)
- 前端股票池：[http://127.0.0.1:5173/stocks](http://127.0.0.1:5173/stocks)
- 前端反馈管理：[http://127.0.0.1:5173/admin/feedbacks](http://127.0.0.1:5173/admin/feedbacks)
- 后端健康检查：[http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

### 全量股票池同步（可选手动执行）

启动后端后，可以手动执行：

```bash
python3 scripts/sync_universe.py
```

或调用接口：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/stocks/sync?force=true"
```

### 全量个股详情补齐（逐股联网抓取）

启动后端后，可以执行：

```bash
python3 scripts/enrich_universe.py --force --sleep-ms 120
```

仅先跑一部分（例如先 300 只）：

```bash
python3 scripts/enrich_universe.py --limit 300 --sleep-ms 120
```

也可直接调用接口：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/stocks/enrich?force=true&sleep_ms=120"
curl "http://127.0.0.1:8000/api/v1/stocks/enrich/status"
```

推荐后台常驻执行（screen，不怕终端关闭）：

```bash
bash scripts/enrich_up.sh
bash scripts/enrich_status.sh
```

### 全量数据一致性校验（建议补齐后执行）

执行结构与业务一致性检查（覆盖每只股票）：

```bash
python3 scripts/verify_universe_data.py
```

产出文件：
- 汇总：`.run/verification_summary.json`
- 明细：`.run/verification_issues.csv`

示例（先抽样 300 只验证规则）：

```bash
python3 scripts/verify_universe_data.py --limit 300
```

### 常见问题：前端“动不动无法访问”
- 如果你是在受控命令会话里启动（例如某些自动化/代理执行环境），命令结束后后台进程可能被系统回收。
- 这种情况下优先用 `scripts/dev_run.sh`，保持该终端不退出。

## 自动优化脚本（Codex 循环）

脚本：`scripts/codex_optimize_loop.py`

示例（有限轮次）：

```bash
python3 scripts/codex_optimize_loop.py \
  --goal "持续提升散户侧体验、风控能力、分析可解释性与交易指导质量" \
  --max-rounds 6 \
  --check "cd backend && python3 -m compileall app" \
  --check "cd frontend && npm run build"
```

示例（长循环）：

```bash
python3 scripts/codex_optimize_loop.py \
  --goal "持续提升散户侧体验、风控能力、分析可解释性与交易指导质量" \
  --max-rounds 100000 \
  --check "cd backend && python3 -m compileall app" \
  --check "cd frontend && npm run build"
```

停止方式：

```bash
touch .codex-loop/STOP
```
