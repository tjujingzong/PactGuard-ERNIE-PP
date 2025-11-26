[English](README.md) | [中文](README_CN.md)

# PactGuard-ERNIE-PP

PactGuard-ERNIE-PP is an intelligent contract review tool: upload PDF/scanned documents/images → complete layout restoration and text structure extraction using PP-StructureV3/local parsing → call ERNIE 4.5 to identify high-risk, missing, and non-standard clauses and generate modification suggestions with source text positioning, ultimately outputting rich text reports. This repository provides an end-to-end workflow application from "upload contract → automatic parsing → risk identification → suggestion generation → export report", including Streamlit Web UI, pluggable MCP document parsing service, and extensible LLM capability configuration.

![System Interface Example](pics/demo.png)

## Core Capabilities

- **Multi-format Parsing**: Focus on PDF / scanned documents / images, combining local parsing with online OCR parsing, and implementing layout reconstruction in `ui_ocr_utils.py` to preserve paragraph, table, and coordinate information.
- **End-to-End Workflow**: `ui_workflow.py` + `contract_workflow.py` split "parsing → risk analysis → suggestion generation → result rendering" into four observable stages.
- **AI Risk Insights**: Output risk levels, scores, matched contract clauses, and itemized revision suggestions from both legal and business dimensions, with source text positions marked in reports.
- **History Retention and Reuse**: Analysis results and intermediate products are automatically written to `contract_analysis_results/`, `jsons/`, `mds/` for secondary verification or playback.
- **One-Click Startup Experience**: Run `python -m streamlit run ui_workflow.py` to automatically detect/launch `mcp_service.py` and start the Streamlit UI.
- **Customizable LLM/OCR**: Switch LLM API Base, API Key, and OCR interfaces at any time through environment variables, enabling flexible cloud/local combinations.

## System Architecture Overview

- **UI Layer**: `ui_workflow.py` is based on Streamlit, responsible for file upload, sample selection, real-time preview, and result visualization (including highlighted HTML, risk panels, suggestion lists).
- **Workflow Engine**: `ContractWorkflow` defines the ordered steps of parsing, analysis, and report generation; `ui_workflow_processor.py` decouples UI events from workflow execution.
- **Document Processing Service (MCP)**: `mcp_service.py` provides local parsing, layout analysis, and OCR capabilities, decoupled from UI through HTTP health checks.
- **Rendering and Utilities**: Modules like `ui_rendering.py`, `ui_utils.py`, `ui_ocr_utils.py` encapsulate caching, sample processing, UI beautification, and online parsing utility functions.
- **Asset Directories**:
  - `contracts/`: Sample contracts
  - `contract_analysis_results/`: Structured JSON
  - `jsons/`, `mds/`: Intermediate data and Markdown summaries
  - `pics/`: Interface screenshots (including `demo.png`)

## Directory Structure

```
pp-contract/
├── contract_workflow.py          # Core workflow
├── ui_workflow.py                # Streamlit UI
├── ui_workflow_processor.py      # UI-triggered scheduler
├── ui_rendering.py               # Risk cards/HTML highlighting
├── ui_utils.py                   # Caching, samples, session management
├── ui_ocr_utils.py               # OCR/online parsing utilities
├── mcp_service.py                # Document parsing/OCR backend
├── contract_analysis_results/    # Historical results
├── contracts/                    # Demo contracts
├── pics/demo.png                 # README screenshot
└── requirements.txt              # Dependencies
```

## Workflow Stages

1. **📄 Document Parsing**  
   - Call MCP service to complete layout parsing, OCR, and structured extraction; supports cache hits and online OCR (`ui_ocr_utils.call_online_parse_api`).
2. **🔍 Risk Analysis**  
   - `ContractWorkflow` internally calls LLM to perform multi-dimensional analysis of contract semantics, merging historical cache with real-time detection.
3. **💡 Suggestion Generation**  
   - Output risk levels, problem locations, modification suggestions, and signing recommendations, written to `contract_analysis_results/contract_analysis_*.json`.
4. **📊 Result Display**  
   - `ui_rendering.generate_html_layout` is responsible for generating highlighted HTML; the right panel simultaneously renders structured risk cards, suggestions, and source text comparison.

## Environment Setup

- Python 3.10+ (recommended to align with `requirements.txt`)
- Installed `pip`, `virtualenv`, or Conda
- Accessible LLM / OCR API

```bash
git clone https://github.com/tjujingzong/PactGuard-ERNIE-PP
cd PactGuard-ERNIE-PP
python -m venv .venv
.venv\Scripts\activate  # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Startup

```bash
python -m streamlit run ui_workflow.py
```

The system will automatically:
1. Check if `mcp_service.py` is already running at `http://localhost:7001`;
2. If not running, automatically start the MCP service in the background and wait for health checks;
3. Start the Streamlit UI (default port 8501, you can specify a different port using `--server.port` when starting).

The browser will automatically open or you can access the displayed address (usually `http://localhost:8501`).

## Usage Guide

1. **Upload/Select File**: Support drag-and-drop upload or select samples from `contracts/`, the system will instantly generate text preview.
2. **Configuration Options**: Configure APIs in the sidebar.
3. **Start Analysis**: Click "Start Analysis", the interface will display a four-stage progress bar; if analysis fails, check the error message for the corresponding stage.
4. **View Results**: The left side displays the highlighted contract, the right side contains:
   - Risk cards
   - LLM suggestion source text
   - Signing recommendations/summary
5. **Download/Reuse**: All results are written in JSON/Markdown format to `contract_analysis_results/`, uploading the same file again will directly read the latest cache.

## Development and Debugging

- **Logging and Health Checks**: `mcp_service.py` provides a `/health` endpoint; the UI side will automatically detect and start the MCP service for easy fault tolerance.
- **Samples and Caching**: `ui_utils.initialize_session_state` controls cache keys; during debugging, you can delete `contract_analysis_results/` to ensure a fresh run.
- **UI Customization**: `ui_workflow.py` contains extensive CSS, supporting custom layouts, dark themes, etc.; `ui_rendering.py` is the unified export for highlighting and risk cards.
- **Extending LLM**: When integrating new models/pipelines in `ContractWorkflow`, just follow the unified input/output format to decouple from the UI.

## FAQ

- **MCP Service Cannot Start**: Confirm port 7001 is free; manually execute `python mcp_service.py` to view error logs.
- **OCR Failure**: Check `OCR_API_URL` and `OCR_API_TOKEN`; you can also temporarily disable online OCR and use only local parsing.
- **LLM Call Timeout**: Set up a proxy for `requests` or change networks; if necessary, reduce uploaded file size.
- **Cache Hit But Interface Not Refreshing**: Click "Force Re-parse" or clear the corresponding file in `contract_analysis_results/`.

---

For contributions or secondary development, please feel free to submit PRs / Issues, or replicate more features in the UI shown in the README screenshot.
