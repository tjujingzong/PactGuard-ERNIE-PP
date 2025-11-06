# ui_workflow.py
# 基于工作流的合同审查系统UI界面

import os
import json
import time
import tempfile
import base64
import logging
from typing import Dict, List, Optional, Any
import streamlit as st
from contract_workflow import ContractWorkflow
import requests
import urllib
import warnings

# 页面配置
st.set_page_config(
    page_title="合同审查系统 - 工作流版",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)
warnings.filterwarnings("ignore")
# 降低触发空 label 提示的模块日志级别（双保险）
logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)

# 自定义CSS样式
st.markdown(
    """
<style>
    /* 主容器样式 */
    .main-container {
        padding: 1px 2px;
        background-color: #f8f9fa;
    }
    
    /* 减少页面顶部空白 */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    
    /* 减少标题间距和调整大小 */
    h1, h2, h3 {
        margin-top: 0.5rem;
        margin-bottom: 0.5rem;
    }
    
    /* 调整主标题大小 */
    h1 {
        font-size: 1.8rem !important;
        font-weight: 600 !important;
    }
    
    /* 隐藏或调小右上角的rerun按钮 */
    .stApp > header {
        visibility: hidden;
    }
    
    /* 隐藏Streamlit的菜单按钮 */
    .stApp > div[data-testid="stToolbar"] {
        visibility: hidden;
    }
    
    /* 隐藏右上角的菜单 */
    .stApp > div[data-testid="stHeader"] {
        visibility: hidden;
    }
    
    /* 工作流步骤样式 */
    .workflow-step {
        background-color: white;
        border-radius: 8px;
        padding: 20px;
        margin: 10px 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-left: 4px solid #007bff;
    }
    
    .workflow-step.completed {
        border-left-color: #28a745;
        background-color: #f8fff9;
    }
    
    .workflow-step.current {
        border-left-color: #ffc107;
        background-color: #fffdf0;
    }
    
    .workflow-step.error {
        border-left-color: #dc3545;
        background-color: #fff5f5;
    }
    
    /* 风险卡片样式 */
    .risk-card {
        background-color: #fff;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
    }
    
    .risk-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    
    /* 风险等级标签样式 */
    .risk-high {
        background-color: #f44336;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    
    .risk-medium {
        background-color: #ff9800;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    
    .risk-low {
        background-color: #4caf50;
        color: white;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    
</style>
""",
    unsafe_allow_html=True,
)


def initialize_session_state():
    """初始化session state"""
    if "workflow_result" not in st.session_state:
        st.session_state.workflow_result = None
    if "processing_status" not in st.session_state:
        st.session_state.processing_status = (
            "idle"  # idle, processing, completed, error
        )
    if "file_name" not in st.session_state:
        st.session_state.file_name = None
    if "preview_content" not in st.session_state:
        st.session_state.preview_content = None
    if "loaded_from_history" not in st.session_state:
        st.session_state.loaded_from_history = False
    if "ocr_parse_result" not in st.session_state:
        # 用于右侧对照面板的在线解析结果缓存
        st.session_state.ocr_parse_result = None


def load_latest_result_by_filename(file_name: str) -> Optional[Dict[str, Any]]:
    """根据文件名加载该文件的最新分析结果。

    优先匹配 result["original_file_name"] == file_name；
    兼容旧结果：若无 original_file_name，则用 basename(result["file_path"]) 比对。
    """
    results_dir = "contract_analysis_results"
    if not os.path.exists(results_dir):
        return None

    candidates: List[Dict[str, Any]] = []
    for fname in os.listdir(results_dir):
        if not fname.lower().endswith(".json"):
            continue
        fpath = os.path.join(results_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 匹配逻辑
            match = False
            ori = data.get("original_file_name")
            if ori and ori == file_name:
                match = True
            else:
                # 兼容旧数据
                fp = data.get("file_path")
                if isinstance(fp, str) and os.path.basename(fp) == file_name:
                    match = True
            if match:
                # 以 processing_time 为主，退化到文件名时间戳排序
                ts = data.get("processing_time")
                candidates.append(
                    {
                        "_ts": float(ts) if isinstance(ts, (int, float)) else 0.0,
                        "_path": fpath,
                        "data": data,
                    }
                )
        except Exception:
            continue

    if not candidates:
        return None

    # 若 processing_time 都为 0，则使用文件名中的时间戳进行排序作为兜底
    def extract_name_ts(p: str) -> float:
        base = os.path.basename(p)
        # 形如 contract_analysis_YYYYmmdd_HHMMSS.json
        try:
            stem = os.path.splitext(base)[0]
            parts = stem.split("_")
            if len(parts) >= 3:
                dt = parts[-2] + parts[-1]  # YYYYmmdd + HHMMSS
                # 转换为结构化时间
                import datetime

                d = datetime.datetime.strptime(dt, "%Y%m%d%H%M%S")
                return d.timestamp()
        except Exception:
            pass
        return 0.0

    for c in candidates:
        if not c["_ts"]:
            c["_ts"] = extract_name_ts(c["_path"]) or 0.0

    candidates.sort(key=lambda x: x["_ts"], reverse=True)
    return candidates[0]["data"]


def save_uploaded_file(uploaded_file) -> Optional[str]:
    """保存上传的文件"""
    if not uploaded_file:
        return None
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        return tmp.name


def get_sample_files() -> List[str]:
    """获取样例文件列表"""
    contracts_dir = "contracts"
    if not os.path.exists(contracts_dir):
        return []

    sample_files = []
    for file in os.listdir(contracts_dir):
        file_path = os.path.join(contracts_dir, file)
        if os.path.isfile(file_path) and file.lower().endswith(
            (".pdf", ".docx", ".txt", ".doc")
        ):
            sample_files.append(file_path)

    return sample_files


def copy_sample_file(sample_path: str) -> Optional[str]:
    """复制样例文件到临时目录"""
    try:
        suffix = os.path.splitext(sample_path)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            with open(sample_path, "rb") as src:
                tmp.write(src.read())
            return tmp.name
    except Exception as e:
        st.error(f"复制样例文件失败: {str(e)}")
        return None


def preview_file_content(file_path: str) -> str:
    """预览文件内容"""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()

        if file_ext == ".txt":
            encodings = ["utf-8", "gbk", "gb2312", "gb18030"]
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        content = f.read()
                    return content[:2000] + "..." if len(content) > 2000 else content
                except UnicodeDecodeError:
                    continue
            return "无法读取文件内容"

        elif file_ext == ".docx":
            try:
                import docx

                doc = docx.Document(file_path)
                content = "\n".join([para.text for para in doc.paragraphs])
                return content[:2000] + "..." if len(content) > 2000 else content
            except Exception as e:
                return f"读取Word文档失败: {str(e)}"

        elif file_ext == ".pdf":
            try:
                from pdfminer.high_level import extract_text

                content = extract_text(file_path)
                return content[:2000] + "..." if len(content) > 2000 else content
            except Exception as e:
                return f"读取PDF文件失败: {str(e)}"

        else:
            return f"不支持预览 {file_ext} 格式文件"

    except Exception as e:
        return f"预览文件失败: {str(e)}"


def _read_file_as_base64(file_path: str) -> Optional[str]:
    """读取文件并返回base64（用于内嵌PDF预览）。"""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def render_file_preview(file_path: str, height: int = 840):
    """左侧源文件预览。

    - PDF: 按页渲染为图片进行展示（基于 PyMuPDF）
    - 其他: 以文本方式展示（前2K字符）
    """
    file_ext = os.path.splitext(file_path)[1].lower()
    st.markdown("#### 源文件预览")

    if file_ext == ".pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            if doc.page_count == 0:
                st.warning("PDF 无页面可预览")
                return

            # 当前页（仅展示单页）
            page_key = f"pdf_page_{os.path.basename(file_path)}"
            current_page = int(st.session_state.get(page_key, 1))
            if current_page < 1:
                current_page = 1
            if current_page > doc.page_count:
                current_page = doc.page_count

            page = doc.load_page(current_page - 1)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            st.image(
                img_bytes,
                caption=f"第{int(current_page)}页 / 共{doc.page_count}页",
                width='stretch',
            )

            # 控件放在图片正下方：上一页/页码输入/下一页
            ctrl_left, ctrl_mid, ctrl_right = st.columns([1, 2, 1])
            with ctrl_left:
                if st.button("上一页", width='stretch', key=f"prev_{page_key}"):
                    new_page = max(1, current_page - 1)
                    if new_page != current_page:
                        st.session_state[page_key] = new_page
                        st.rerun()
            with ctrl_mid:
                new_val = st.number_input(
                    "页码",
                    min_value=1,
                    max_value=doc.page_count,
                    value=current_page,
                    step=1,
                    key=f"num_{page_key}",
                    label_visibility="collapsed",
                )
                if int(new_val) != current_page:
                    st.session_state[page_key] = int(new_val)
                    st.rerun()
            with ctrl_right:
                if st.button("下一页", width='stretch', key=f"next_{page_key}"):
                    new_page = min(doc.page_count, current_page + 1)
                    if new_page != current_page:
                        st.session_state[page_key] = new_page
                        st.rerun()
        except Exception:
            # 兜底：回退到文本模式
            st.warning("图片预览失败，已切换为文本模式。")
            st.text_area(
                "文件内容",
                preview_file_content(file_path),
                height=height,
                disabled=True,
            )
    else:
        st.text_area(
            "文件内容", preview_file_content(file_path), height=height, disabled=True
        )


def render_preview_panel(file_path: str, preview_text: str):
    """两栏预览：左侧源文件，右侧识别结果对照（参考示例UI）。"""
    left, right = st.columns([1, 1], gap="large")
    with left:
        render_file_preview(file_path)

    with right:
        st.markdown("#### 解析结果对照")
        tabs = st.tabs(["OCR识别对照", "Markdown", "JSON"])

        with tabs[0]:
            # 在线API调用：百度文档解析（需要设置环境变量 BAIDU_PARSER_AUTH）
            colA, colB = st.columns([1, 1])
            with colA:
                if st.button("▶ 调用OCR解析", key="btn_call_ocr"):
                    st.session_state.ocr_parse_result = call_online_parse_api(file_path)
                    st.rerun()
            with colB:
                if st.session_state.ocr_parse_result:
                    st.success("已获取在线解析结果")

            # 展示解析文本（若无在线结果，回退到本地预览文本）
            ocr_text = None
            if st.session_state.ocr_parse_result and isinstance(
                st.session_state.ocr_parse_result, dict
            ):
                ocr_text = st.session_state.ocr_parse_result.get(
                    "markdown_text"
                ) or st.session_state.ocr_parse_result.get("raw_text")
            st.text_area(
                "识别文本",
                ocr_text if ocr_text else preview_text,
                height=780,
                disabled=True,
                label_visibility="collapsed",
            )

            # 若有在线解析的原始返回，提供调试输出
            if st.session_state.ocr_parse_result and isinstance(
                st.session_state.ocr_parse_result, dict
            ):
                with st.expander("API 调试输出", expanded=False):
                    st.json(st.session_state.ocr_parse_result)

        with tabs[1]:
            # 将预览文本按markdown渲染（若非MD也可正常显示）
            st.markdown(
                preview_text if isinstance(preview_text, str) else str(preview_text)
            )

        with tabs[2]:
            # 若有外部解析JSON，可在此处填充；当前给出提示占位
            if (
                hasattr(st.session_state, "workflow_result")
                and st.session_state.workflow_result
                and isinstance(st.session_state.workflow_result, dict)
            ):
                st.json(st.session_state.workflow_result)
            elif st.session_state.ocr_parse_result and isinstance(
                st.session_state.ocr_parse_result, dict
            ):
                st.json(st.session_state.ocr_parse_result.get("json_result", {}))
            else:
                st.info("暂无JSON结果。启动分析后将在此展示结构化数据。")


def call_online_parse_api(file_path: str) -> Optional[Dict[str, Any]]:
    """调用百度文档解析在线API，并返回解析文本/JSON/下载链接。"""
    try:
        create_url = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task"
        query_url = (
            "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task/query"
        )

        params = {
            "file_data": _read_file_as_base64(file_path) or "",
            "file_name": os.path.basename(file_path),
            "recognize_formula": "True",
            "analysis_chart": "True",
            "angle_adjust": "True",
            "parse_image_layout": "True",
            "language_type": "CHN_ENG",
            "switch_digital_width": "auto",
        }
        payload = urllib.parse.urlencode(params)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": "Bearer bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f",
        }

        resp = requests.post(create_url, headers=headers, data=payload.encode("utf-8"))
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        task_id = (
            (data.get("result", {}) or {}).get("task_id")
            if isinstance(data, dict)
            else None
        )
        if not task_id:
            st.error("创建在线解析任务失败")
            return None

        # 轮询
        max_retries = 30
        interval = 2
        result_json: Optional[Dict[str, Any]] = None
        for _ in range(max_retries):
            q = requests.post(
                query_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "Authorization": "Bearer bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f",
                },
                data=f"task_id={task_id}".encode("utf-8"),
            )
            try:
                result_json = q.json()
            except Exception:
                result_json = None
            status = (result_json or {}).get("result", {}).get("status")
            if status == "success":
                break
            if status in ("failed", "error"):
                break
            time.sleep(interval)

        if not result_json:
            st.error("在线解析任务无返回")
            return None

        r = result_json.get("result", {}) if isinstance(result_json, dict) else {}
        parse_result_url = r.get("parse_result_url")
        markdown_url = r.get("markdown_url")

        json_result: Dict[str, Any] = {}
        markdown_text: Optional[str] = None
        try:
            if parse_result_url:
                jr = requests.get(parse_result_url, timeout=20)
                json_result = jr.json() if jr.ok else {}
        except Exception:
            json_result = {}
        try:
            if markdown_url:
                mr = requests.get(markdown_url, timeout=20)
                markdown_text = mr.text if mr.ok else None
        except Exception:
            markdown_text = None

        result_payload = {
            "task_id": task_id,
            "parse_result_url": parse_result_url,
            "markdown_url": markdown_url,
            "json_result": json_result,
            "markdown_text": markdown_text,
            # 回退的原始文本
            "raw_text": preview_file_content(file_path),
            # 额外暴露一次核心 API 返回，便于打印/调试
            "_api_create_resp": data,
            "_api_query_resp": result_json,
        }

        # 打印到控制台（开发期需求）
        print(
            "[call_online_parse_api] create_resp:", json.dumps(data, ensure_ascii=False)
        )
        print(
            "[call_online_parse_api] query_resp:",
            json.dumps(result_json or {}, ensure_ascii=False),
        )

        return result_payload
    except Exception as e:
        st.error(f"调用在线解析API失败: {e}")
        return None


def add_highlights_to_text(text: str, issues: List[Dict]) -> str:
    """为文本添加简单标记 - 所有问题都标记显示"""
    if not issues:
        return text

    highlighted_text = text
    for issue in issues:
        clause = issue.get("条款", "")
        risk_level = issue.get("风险等级", "低")
        issue_type = issue.get("类型", "问题")

        if clause and clause in highlighted_text:
            # 根据风险等级选择标记符号
            if risk_level == "高":
                marker = "🔴【重大风险】"
            elif risk_level == "中":
                marker = "🟡【一般风险】"
            else:
                marker = "🟢【低风险】"

            # 添加简单标记
            marked_text = f"{marker} {clause}"
            highlighted_text = highlighted_text.replace(clause, marked_text)

    return highlighted_text


def filter_issues_by_risk(issues: List[Dict], risk_level: str) -> List[Dict]:
    """根据风险等级筛选问题"""
    if risk_level == "全部":
        return issues

    level_mapping = {"重大风险": "高", "一般风险": "中", "低风险": "低"}

    target_level = level_mapping.get(risk_level, "低")
    return [issue for issue in issues if issue.get("风险等级") == target_level]


def render_risk_analysis(risk_analysis: Dict[str, Any]):
    """渲染风险分析结果"""
    st.markdown("### 🔍 风险分析结果")

    statistics = risk_analysis.get("statistics", {})
    all_issues = risk_analysis.get("all_issues", [])

    # 风险统计
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总问题数", statistics.get("total_issues", 0))
    with col2:
        st.metric("高风险", statistics.get("by_level", {}).get("高", 0))
    with col3:
        st.metric("中风险", statistics.get("by_level", {}).get("中", 0))
    with col4:
        st.metric("低风险", statistics.get("by_level", {}).get("低", 0))

    # 风险评分
    risk_score = statistics.get("risk_score", 0)
    risk_level = statistics.get("risk_level", "低")

    st.markdown("### 📊 风险评分")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("风险评分", f"{risk_score}/100")
    with col2:
        level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
        st.metric("风险等级", f"{level_color} {risk_level}")

    # 问题详情
    if all_issues:
        st.markdown("### 📋 问题详情")

        # 按风险等级分类
        high_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "高"
        ]
        medium_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "中"
        ]
        low_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "低"
        ]

        # 显示高风险问题
        if high_risk_issues:
            st.markdown("#### 🔴 高风险问题")
            for i, issue in enumerate(high_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=True,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
                    if issue.get("法律依据"):
                        st.write(f"**法律依据:** {issue['法律依据']}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")

        # 显示中风险问题
        if medium_risk_issues:
            st.markdown("#### 🟡 中风险问题")
            for i, issue in enumerate(medium_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=False,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")

        # 显示低风险问题
        if low_risk_issues:
            st.markdown("#### 🟢 低风险问题")
            for i, issue in enumerate(low_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=False,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
    else:
        st.info("未发现问题")


def render_suggestions(suggestions: Dict[str, Any]):
    """渲染建议和推荐"""
    st.markdown("### 💡 综合建议")

    summary = suggestions.get("summary", {})
    analysis = suggestions.get("analysis", {})
    recommendation = suggestions.get("recommendation", {})

    # 摘要信息
    st.markdown("#### 📊 分析摘要")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("风险评分", f"{summary.get('risk_score', 0)}/100")
    with col2:
        st.metric("总问题数", summary.get("total_issues", 0))
    with col3:
        st.metric("违法条款", summary.get("illegal_clauses", 0))

    # 主要风险点
    if analysis.get("key_risks"):
        st.markdown("#### 🔴 主要风险点")
        for risk in analysis["key_risks"]:
            st.write(f"• {risk}")

    # 影响分析
    if analysis.get("impact_analysis"):
        st.markdown("#### 📈 影响分析")
        st.write(analysis["impact_analysis"])

    # 优化建议
    if analysis.get("optimization_suggestions"):
        st.markdown("#### 🛠️ 优化建议")
        for suggestion in analysis["optimization_suggestions"]:
            st.write(f"• {suggestion}")

    # 签约建议
    if recommendation.get("signing_advice"):
        st.markdown("#### 📝 签约建议")
        signing_advice = recommendation["signing_advice"]
        if "不建议" in signing_advice or "❌" in signing_advice:
            st.error(f"**{signing_advice}**")
        elif "谨慎" in signing_advice or "⚠️" in signing_advice:
            st.warning(f"**{signing_advice}**")
        elif "可以" in signing_advice or "✅" in signing_advice:
            st.success(f"**{signing_advice}**")
        else:
            st.info(f"**{signing_advice}**")

    # 谈判要点
    if recommendation.get("negotiation_points"):
        st.markdown("#### 🤝 谈判要点")
        for point in recommendation["negotiation_points"]:
            st.write(f"• {point}")

    # 风险缓解措施
    if recommendation.get("risk_mitigation"):
        st.markdown("#### 🛡️ 风险缓解措施")
        for measure in recommendation["risk_mitigation"]:
            st.write(f"• {measure}")


def process_contract_workflow(file_path: str):
    """处理合同工作流"""
    try:
        st.session_state.processing_status = "processing"

        # 创建工作流实例
        workflow = ContractWorkflow()

        # 步骤1: 文档解析/分析
        with st.spinner("正在解析文档并分析..."):
            result = workflow.process_contract(
                file_path, original_file_name=st.session_state.file_name
            )

        if "error" in result:
            st.session_state.processing_status = "error"
            st.error(f"处理失败: {result['error']}")
            return

        st.session_state.workflow_result = result
        st.session_state.processing_status = "completed"

        st.success("合同分析完成！")

    except Exception as e:
        st.session_state.processing_status = "error"
        st.error(f"处理过程中发生错误: {str(e)}")


def main():
    """主函数"""
    initialize_session_state()

    # 页面标题
    st.title("📄 合同审查系统")

    # 侧边栏 - 文件上传
    with st.sidebar:
        st.markdown("### 📁 文件选择")

        # 创建选项卡
        tab1, tab2 = st.tabs(["📤 上传文件", "📋 选择样例"])

        with tab1:
            uploaded_file = st.file_uploader(
                "上传合同文件",
                type=["pdf", "docx", "txt", "doc"],
                help="支持PDF、DOCX、TXT、DOC格式",
            )

            if uploaded_file:
                saved_path = save_uploaded_file(uploaded_file)
                if saved_path:
                    # 切换文件时清空历史分析状态，回到预览态
                    st.session_state.workflow_result = None
                    st.session_state.processing_status = "idle"
                    st.session_state.loaded_from_history = False

                    st.session_state.saved_file_path = saved_path
                    st.session_state.file_name = uploaded_file.name
                    st.session_state.preview_content = preview_file_content(saved_path)

        with tab2:
            sample_files = get_sample_files()
            if sample_files:
                st.write("选择样例文件：")
                for i, sample_path in enumerate(sample_files):
                    file_name = os.path.basename(sample_path)
                    if st.button(f"📄 {file_name}", key=f"sample_{i}"):
                        temp_path = copy_sample_file(sample_path)
                        if temp_path:
                            # 切换样例时清空历史分析状态，回到预览态
                            st.session_state.workflow_result = None
                            st.session_state.processing_status = "idle"
                            st.session_state.loaded_from_history = False

                            st.session_state.saved_file_path = temp_path
                            st.session_state.file_name = file_name
                            st.session_state.preview_content = preview_file_content(
                                temp_path
                            )
                            st.success(f"已选择: {file_name}")
                            st.rerun()
            else:
                st.info("contracts目录下没有样例文件")

    # 主界面
    if (
        hasattr(st.session_state, "saved_file_path")
        and st.session_state.saved_file_path
    ):

        # 文件信息
        st.markdown("### 📄 当前文件")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**文件名:** {st.session_state.file_name}")
        with col2:
            # 顶部右侧不再受状态限制，按钮位置将下移到自动加载逻辑之后
            pass

        # 若选择了文件，尝试自动加载历史最新分析结果
        if (
            st.session_state.processing_status == "idle"
            and st.session_state.file_name
            and not st.session_state.loaded_from_history
        ):
            cached = load_latest_result_by_filename(st.session_state.file_name)
            if cached:
                st.session_state.workflow_result = cached
                st.session_state.processing_status = "completed"
                st.session_state.loaded_from_history = True
                st.success("已加载历史最新分析结果")

        # 操作按钮：idle 显示“开始分析”；completed 显示“重新提交模型分析”
        if st.session_state.processing_status in ("idle", "completed"):
            if st.session_state.processing_status == "completed":
                label = "🔁 重新提交模型分析"
            else:
                label = "🚀 开始分析"
            if st.button(label, type="primary", width='stretch'):
                process_contract_workflow(st.session_state.saved_file_path)
                st.rerun()

        # 显示处理状态
        if st.session_state.processing_status == "processing":
            st.info("正在处理中，请稍候...")

        # 显示分析结果
        if (
            st.session_state.processing_status == "completed"
            and st.session_state.workflow_result
        ):
            result = st.session_state.workflow_result
            risk_analysis = result.get("risk_analysis", {})
            all_issues = risk_analysis.get("all_issues", [])

            # 创建左右分栏布局
            col1, col2 = st.columns([1, 1], gap="large")

            with col1:
                # 左侧：合同内容区域
                st.markdown("### 📄 合同文档")

                # 合同标题（移除重复按钮，仅展示文件名）
                st.markdown(f"**{st.session_state.file_name}**")

                # 显示合同内容（带高亮）
                document_text = result.get("document_text", "")
                if document_text:
                    # 为问题添加高亮标记
                    highlighted_text = add_highlights_to_text(document_text, all_issues)

                    # 显示标记后的文本
                    st.markdown("### 📄 合同内容（已标记问题）")
                    st.text_area(
                        "合同内容（已标记）",
                        value=highlighted_text,
                        height=800,
                        disabled=True,
                        label_visibility="collapsed",
                    )
                else:
                    st.warning("未获取到文档内容")

            with col2:
                # 右侧：风险分析区域
                st.markdown("### 🔍 审查结果")

                # 视图切换：风险点 / 综合建议
                view = st.radio(
                    "选择查看内容",
                    ["风险点", "综合建议"],
                    horizontal=True,
                    key="result_view_switch",
                )

                suggestions = result.get("suggestions", {})
                statistics = risk_analysis.get("statistics", {})

                if view == "风险点":
                    # 风险等级筛选
                    st.markdown("**风险等级**")
                    risk_levels = ["全部", "重大风险", "一般风险", "低风险"]
                    selected_level = st.radio(
                        "选择风险等级", risk_levels, horizontal=True, key="risk_filter"
                    )

                    # 筛选问题
                    filtered_issues = filter_issues_by_risk(all_issues, selected_level)

                    # 风险统计
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("总问题数", len(filtered_issues))
                    with col2:
                        risk_score = statistics.get("risk_score", 0)
                        st.metric("风险评分", f"{risk_score}/100")
                    with col3:
                        risk_level = statistics.get("risk_level", "低")
                        level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(
                            risk_level, "⚪"
                        )
                        st.metric("风险等级", f"{level_color} {risk_level}")

                    # 风险项目列表
                    if filtered_issues:
                        st.markdown("---")
                        for i, issue in enumerate(filtered_issues, 1):
                            risk_level = issue.get("风险等级", "低")
                            issue_type = issue.get("类型", "未知类型")

                            if risk_level == "高":
                                risk_color = "🔴"
                                risk_label = "重大风险"
                            elif risk_level == "中":
                                risk_color = "🟡"
                                risk_label = "一般风险"
                            else:
                                risk_color = "🟢"
                                risk_label = "低风险"

                            with st.container():
                                col1, col2 = st.columns([3, 1])

                                with col1:
                                    st.markdown(f"**{risk_color} {issue_type}**")
                                with col2:
                                    st.markdown(f"**{risk_label}**")

                                with st.expander("详细信息", expanded=True):
                                    st.write(
                                        f"**条款位置：** {issue.get('条款', 'N/A')}"
                                    )
                                    st.write(
                                        f"**问题描述：** {issue.get('问题描述', 'N/A')}"
                                    )
                                    st.write(
                                        f"**修改建议：** {issue.get('修改建议', 'N/A')}"
                                    )
                                    if issue.get("法律依据"):
                                        st.write(
                                            f"**法律依据：** {issue.get('法律依据', 'N/A')}"
                                        )
                                    if issue.get("影响分析"):
                                        st.write(
                                            f"**影响分析：** {issue.get('影响分析', 'N/A')}"
                                        )
                                    if issue.get("商业优化"):
                                        st.write(
                                            f"**商业优化：** {issue.get('商业优化', 'N/A')}"
                                        )

                                st.markdown("---")
                    else:
                        st.info("未发现问题")
                else:
                    # 综合建议视图
                    if not suggestions:
                        st.info("暂无综合建议")
                    else:
                        # 显示核心摘要与建议
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric(
                                "风险评分", f"{statistics.get('risk_score', 0)}/100"
                            )
                        with col2:
                            st.metric(
                                "总问题数",
                                statistics.get("total_issues", len(all_issues)),
                            )
                        with col3:
                            risk_level = statistics.get("risk_level", "低")
                            level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(
                                risk_level, "⚪"
                            )
                            st.metric("风险等级", f"{level_color} {risk_level}")

                        st.markdown("---")
                        # 直接复用现有渲染函数
                        render_suggestions(suggestions)

                # 下载结果按钮（直接下载）
                st.markdown("---")
                json_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode(
                    "utf-8"
                )
                st.download_button(
                    label="📥 下载结果",
                    data=json_bytes,
                    file_name=f"contract_analysis_{int(time.time())}.json",
                    mime="application/json",
                    width='stretch',
                )

        # 显示文件预览（重构为左右对照布局）
        if (
            st.session_state.processing_status == "idle"
            and st.session_state.preview_content
        ):
            st.markdown("### 👀 文件预览与识别对照")
            render_preview_panel(
                st.session_state.saved_file_path, st.session_state.preview_content
            )

    else:
        st.info("请上传合同文件或选择样例文件开始分析")

        # 显示使用说明
        st.markdown("### 📖 使用说明")
        st.markdown(
            """
        1. **上传文件**: 在左侧边栏上传您的合同文件（支持PDF、DOCX、TXT、DOC格式）
        2. **选择样例**: 或者从样例文件中选择一个进行测试
        3. **开始分析**: 点击"开始分析"按钮，系统将依次执行以下步骤：
           - 📄 解析文档：提取合同文本内容
           - 🔍 风险分析：识别法律、商业、格式风险
           - 💡 建议生成：生成综合分析和修改建议
           - 📊 结果展示：展示详细的分析结果
        4. **查看结果**: 在结果页面查看风险分析、修改建议和签约建议
        """
        )


if __name__ == "__main__":
    main()
