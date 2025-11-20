# PactGuard-ERNIE-PP

PactGuard-ERNIE-PP 是一款智能合同审查工具：上传 PDF/扫描件/图片 → 以 PP-StructureV3/本地解析完成版面恢复与文本结构抽取 → 调用 ERNIE 4.5 识别高风险、缺失、非标准条款并生成定位到原文的修改建议，最终输出富文本报告。该仓库提供"上传合同→自动解析→风险识别→生成建议→导出报告"的端到端工作流应用，包含 Streamlit Web UI、可插拔的 MCP 文档解析服务与可扩展的 LLM 能力配置。

![系统界面示例](pics/demo.png)

## 核心能力

- **多格式解析**：聚焦 PDF / 扫描件 / 图片，结合本地解析与 OCR 在线解析，并在 `ui_ocr_utils.py` 中实现版面恢复（layout reconstruction）以保留段落、表格和坐标信息。
- **全链路工作流**：`ui_workflow.py` + `contract_workflow.py` 将「解析→风险分析→建议生成→结果渲染」拆分为可观测的四大阶段。
- **AI风险洞察**：围绕法律与商业两个维度输出风险等级、评分、命中的合同条款以及逐条修订建议，并在报告中标记原文位置。
- **历史留存与复用**：分析结果与中间产物自动写入 `contract_analysis_results/`、`jsons/`、`mds/`，方便二次核查或回显。
- **一键启动体验**：`start_workflow.py` 负责检测/拉起 `mcp_service.py`，并启动 Streamlit UI。
- **可自定义LLM/OCR**：通过环境变量随时切换 LLM API Base、API Key、OCR接口，实现云端/本地自由组合。

## 系统架构速览

- **UI层**：`ui_workflow.py` 基于 Streamlit，负责文件上传、样例选择、实时预览、结果可视化（含高亮HTML、风险面板、建议列表）。
- **工作流引擎**：`ContractWorkflow` 定义解析、分析、报告生成的有序步骤，`ui_workflow_processor.py` 将 UI 事件与工作流执行解耦。
- **文档处理服务（MCP）**：`mcp_service.py` 提供本地解析、版面分析、OCR能力，可通过 HTTP 健康检查与 UI 解耦。
- **渲染与工具集**：`ui_rendering.py`、`ui_utils.py`、`ui_ocr_utils.py` 等模块封装缓存、样例处理、UI美化与在线解析工具函数。
- **资产目录**：
  - `contracts/`：示例合同
  - `contract_analysis_results/`：结构化JSON
  - `jsons/`、`mds/`：中间数据与Markdown摘要
  - `pics/`：界面截图（含 `demo.png`）

## 目录结构

```
pp-contract/
├── contract_workflow.py          # 核心workflow
├── ui_workflow.py                # Streamlit UI
├── ui_workflow_processor.py      # UI触发的调度器
├── ui_rendering.py               # 风险卡片/HTML高亮
├── ui_utils.py                   # 缓存、样例、会话管理
├── ui_ocr_utils.py               # OCR/在线解析工具
├── mcp_service.py                # 文档解析/OCR后端
├── start_workflow.py             # 一键启动脚本
├── contract_analysis_results/    # 历史结果
├── contracts/                    # Demo合同
├── pics/demo.png                 # README截图
└── requirements.txt              # 依赖
```

## 工作流阶段

1. **📄 文档解析**  
   - 调用 MCP 服务完成版面解析、OCR、结构化提取；支持缓存命中与在线 OCR（`ui_ocr_utils.call_online_parse_api`）。
2. **🔍 风险分析**  
   - `ContractWorkflow` 内部调用 LLM，对合同语义做多维分析，合并历史缓存与实时检测。
3. **💡 建议生成**  
   - 输出风险等级、问题定位、修改建议、签约建议，写入 `contract_analysis_results/contract_analysis_*.json`。
4. **📊 结果展示**  
   - `ui_rendering.generate_html_layout` 负责生成高亮 HTML；右侧面板同步渲染结构化风险卡片、建议、原文对照。

## 环境准备

- Python 3.10+（建议与 `requirements.txt` 对齐）
- 已安装的 `pip`、`virtualenv` 或 Conda
- 必须可访问的 LLM / OCR API

```bash
git clone https://github.com/tjujingzong/PactGuard-ERNIE-PP
cd PactGuard-ERNIE-PP
python -m venv .venv
.venv\Scripts\activate  # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
## 启动方式

```bash
python start_workflow.py
```

脚本会：
1. 检查 `mcp_service.py` 是否已在 `http://localhost:7001` 运行；
2. 未运行则后台拉起 MCP 服务并等待健康检查；
3. 自动执行 `streamlit run ui_workflow.py --server.port 8501`；
4. 退出 UI 时自动关闭 MCP 子进程。

浏览器访问 `http://localhost:8501` 即可。

## 使用指南

1. **上传/选择文件**：支持拖拽上传或从 `contracts/` 选择样例，系统会即时生成文本预览。
2. **配置选项**：可在侧边栏配置API。
3. **启动分析**：点击"开始分析"，界面会展示四阶段进度条；若分析失败可查看对应阶段的错误提示。
4. **查看结果**：左侧显示高亮合同，右侧包含：
   - 风险卡片
   - LLM 建议原文
   - 签约建议/总结
5. **下载/复用**：所有结果以 JSON/Markdown 形式写入 `contract_analysis_results/`，再次上传同名文件可直接读取最新缓存。

## 开发与调试

- **日志与健康检查**：`mcp_service.py` 提供 `/health` 接口；UI 端 `start_workflow.py` 会持续轮询，便于容错。
- **样例与缓存**：`ui_utils.initialize_session_state` 控制缓存键，调试时可删除 `contract_analysis_results/` 以确保全新运行。
- **UI定制**：`ui_workflow.py` 中包含大量 CSS，支持自定义布局、暗色主题等；`ui_rendering.py` 则是高亮与风险卡片的统一出口。
- **扩展LLM**：在 `ContractWorkflow` 中接入新的模型/链路时，只需遵循统一的输入输出格式，即可与 UI 解耦。

## 常见问题

- **MCP 服务无法启动**：确认 7001 端口空闲；手动执行 `python mcp_service.py` 查看错误日志。
- **OCR 失败**：检查 `OCR_API_URL` 与 `OCR_API_TOKEN`；也可以临时关闭在线 OCR，仅使用本地解析。
- **LLM 调用超时**：为 `requests` 设置代理或更换网络；必要时减少上传文件大小。
- **缓存命中但界面不刷新**：点击"强制重新解析"或清空 `contract_analysis_results/` 中的对应文件。

---

如需贡献或二次开发，欢迎直接提交 PR / Issue，或在 README 截图中展示的 UI 中复刻更多功能。

