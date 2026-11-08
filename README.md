# PayGuard AI

一个用于学习 PayPal Sandbox 集成的 Streamlit 项目：完成测试付款后，使用规则分析订单金额相对于**用户输入的模拟消费基准**的比例，并可通过 AI 生成简短解释。

**规则评分不是欺诈概率，也不是 PayPal 的风控结论。** 本项目不读取真实历史消费来计算基准，不训练欺诈检测模型，不在付款前拦截交易。AI 只解释已有规则结果，不参与打分或支付决策。

## 功能与评分

- Sandbox OAuth、创建订单、买家批准、Capture，以及 SQLite 持久化。
- 创建超时后复用已保存的请求键和金额；Capture 防重复，结果不确定时先查询状态。
- Webhook 验签、事件去重、未匹配事件暂存及订单入库后的自动补处理。
- 对已完成订单进行规则评分；What-if 只模拟金额变化，不修改订单或发起付款。
- 可选的 AI 英文解释；发送金额、币种、模拟基准和规则指标，不发送订单 ID、邮箱或 PayPal 密钥。

比例 = 订单金额 ÷ 模拟消费基准：

| 比例 | 规则分数 | 显示等级 |
| --- | --- | --- |
| 小于 2 | 10/100 | Low Risk |
| 大于等于 2、小于 5 | 50/100 | Medium Risk |
| 大于等于 5 | 80/100 | High Risk |

## 验证状态

- **正常 Sandbox 流程已人工验证**：本地创建订单、买家批准、Capture、订单记录及真实 Webhook 接收；包括订单已完成时收到通知并返回 `processed: false` 的情况。这是维护者的手工验证，不是每次运行的自动端到端验证。
- **异常场景主要由离线测试覆盖**：超时重试、重复事件、事件早于订单、事务回滚、容量限制、旧库迁移，以及退款／撤销状态保护。
- **Webhook Simulator 投递尚未确认**。离线模拟事件不等于 Simulator 投递，也不等于真实签名验证。不要为了测试关闭验签。

## 环境与安装

以下命令适用于 macOS／Linux，从项目根目录执行。需要 Python 3.9+ 和 pip；现有本地测试环境使用 Python 3.9。依赖未完整锁定版本，新环境仍需运行测试确认兼容性。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

依赖包括 Streamlit、requests、FastAPI、Uvicorn、toml 和 OpenAI Python SDK。即使不使用 AI，也需要安装 SDK，因为应用启动时会导入该模块。ngrok 是独立工具，不包含在 Python 依赖中。

## 本地配置

```sh
mkdir -p .streamlit
cp -n .streamlit/secrets.toml.example .streamlit/secrets.toml
```

`cp -n` 不覆盖已有配置。只在自己的电脑上编辑 `.streamlit/secrets.toml`，不要提交或粘贴真实密钥。

| 字段 | 用途 |
| --- | --- |
| `paypal.client_id` | Sandbox 商家应用的 Client ID |
| `paypal.client_secret` | 同一 Sandbox 应用的 Secret |
| `paypal.webhook_id` | 为该应用注册接收地址后获得的 Webhook ID；不是事件 ID 或订单 ID |
| `openai.api_key` | 可选，仅生成 AI 解释时需要 |
| `openai.model` | 替换为账户可用且兼容当前调用的模型 ID |

PayPal 配置来自 Sandbox 商家应用；批准订单时使用单独的 Sandbox 买家账户，不使用真实买家账号。Webhook ID 可在完成下方接收地址注册后填入。

AI 使用 Responses API，代码包含 `reasoning={"effort": "none"}`；不是所有模型都兼容该参数。示例中的模型名是占位符，必须替换；不使用 AI 时可省略整个 `[openai]` 配置。应用不会自动读取 `.env`。

真实配置被 `.gitignore` 排除，`secrets.toml.example` 可以纳入 Git。数据库、数据库附属文件、日志和虚拟环境也被排除。

## 启动服务

在三个终端中运行，前两个终端均进入同一项目目录并执行 `source .venv/bin/activate`，以共用项目旁的 `payguard.db`。

### 1. Streamlit 网页

```sh
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

打开 http://localhost:8501 。现有 PayPal 返回／取消地址固定为这个地址，因此本说明面向同一台电脑上的本地操作。

### 2. Webhook 接收服务

```sh
python -m uvicorn webhook_server:app --host 127.0.0.1 --port 8000
```

健康检查：

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8501/_stcore/health
```

分别应返回 `{"status":"ok"}` 和 `ok`。`/health` 正常只说明服务可响应，不证明密钥、PayPal 连接或验签已成功。

### 3. ngrok HTTPS 隧道

如果已经有指向本机 8000 端口的隧道，复用现有隧道，不更改其配置。否则，安装并按 ngrok 自身要求完成本机认证后运行：

```sh
ngrok http 8000
```

将显示的 HTTPS 域名加上 `/webhooks/paypal`，例如 `https://YOUR_NGROK_DOMAIN/webhooks/paypal`。在 PayPal Sandbox 商家应用中注册这个完整接收地址，订阅：

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.REFUNDED`
- `PAYMENT.CAPTURE.REVERSED`

把注册得到的 Webhook ID 填入本地配置。若隧道域名改变，也要更新注册的接收地址。ngrok 在此暴露的是 Webhook 服务，不是 Streamlit 网页。

## 手工操作顺序

1. 完成配置并启动服务。可用 `Get Sandbox Access Token` 检查 Sandbox 认证。
2. 输入 CAD 金额，点击 `Create Sandbox Order`，通过批准链接使用 Sandbox 买家账户批准，再点击 `Capture Approved Order`。
3. 等待本地订单显示 `COMPLETED` 和 Capture ID。选择已完成订单，输入模拟消费基准，再点击 `Analyze Selected Order`。
4. 用 What-if 比较假设金额；配置好 OpenAI 后可点击 `Generate AI Explanation`。生成 AI 解释会调用外部 API，可能产生费用。

创建结果不确定时，使用 `Retry Same Order Creation`，它复用原键和原金额；只有明确需要另一订单时才点击 `Create New Sandbox Order`。刷新后保留 URL 的 `create_attempt` 参数和本地数据库，才能恢复该创建尝试。Capture 不确定时使用 `Check PayPal Order Status`，不要把超时当成付款失败。

Webhook 返回 `received: true` 表示验签后已接受该事件；`processed: true` 表示这次改变了订单状态。`processed: false` 可能是等待订单匹配、重复投递、同状态无需更新或状态转换被拒绝，不等于验签失败。

## 离线测试

安装依赖后，在项目根目录运行；不需要真实配置、运行中的服务或 PayPal 连接：

```sh
python -B -m unittest discover -s tests -v
```

测试使用临时 SQLite 数据库、模拟凭据与模拟响应，不操作项目的真实数据库。当前包含 26 个测试方法；测试数目不等于真实 Sandbox 验证次数。终端可能打印 `risk.py` 的学习示例及环境警告，以 unittest 的最终 `OK`／`FAILED` 为结果。

## 当前限制

- 这是本地学习原型，缺少多用户隔离和生产部署方案；只配置了 Sandbox、CAD 和本机返回地址。
- 分数是人为设定的规则，模拟消费基准不代表真实历史；AI 文本也不构成欺诈判断。
- Webhook 仅持久化事件 ID、类型、订单／Capture 关联、处理状态和时间，不保存完整请求、付款人资料或签名头，因此没有完整的验签审计快照。
- 待处理事件上限为 1,000 条，总事件上限为 100,000 条，保存的字符串字段最多 255 字符。容量不足时返回 503，不静默删除待处理事件；目前没有自动清理或告警。
- 旧事件迁移为 `LEGACY` 并保留去重身份；缺失的关联信息不能凭空恢复。现有事件关联和状态模型不覆盖所有支付／退款情形。
- 本地创建记录不能保证超出 PayPal 幂等键保留期限后的重试仍能去重；丢失数据库或尝试 URL 也会影响恢复。
- 依赖版本未完全锁定；本地 Git 备份不包含密钥或运行数据，也不能代替磁盘备份。

## 主要文件

| 文件 | 职责 |
| --- | --- |
| `app.py` | Streamlit 界面与操作流程 |
| `paypal_auth.py` | Sandbox OAuth、Orders、Capture、订单查询与远程验签 |
| `order_store.py` | SQLite、创建尝试、状态转换与待处理事件补处理 |
| `webhook_server.py` | FastAPI 健康检查及 Webhook 接收 |
| `risk.py` | 规则评分及早期学习示例 |
| `ai_explanation.py` | 可选 AI 解释 |
| `tests/` | 离线回归测试 |
