# ui_workflow.py

import os
import json
import time
import warnings
import urllib3
import streamlit as st
from contract_workflow import ContractWorkflow
from ui_utils import (
    initialize_session_state,
    load_latest_result_by_filename,
    save_uploaded_file,
    get_sample_files,
    copy_sample_file,
    preview_file_content,
    load_cached_parse_result,
)
from ui_workflow_processor import process_contract_workflow
from ui_rendering import (
    render_preview_panel,
    generate_html_layout,
    filter_issues_by_risk,
    render_suggestions,
)
from ui_ocr_utils import call_online_parse_api

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="合同审查系统 - 工作流版",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)
warnings.filterwarnings("ignore")
import logging

logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)

st.markdown(
    """
<style>
    /* 主容器样式 */
    .main-container {
        padding: 1px 2px;
        background-color: #f8f9fa;
    }
    
    div:has(> #left-preview-anchor),
    div:has(> #right-panel-anchor) {
        border: 1px solid #dee2e6;
        border-radius: 8px;
        background-color: #fff;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }
    
    div:has(> #left-preview-anchor) {
        height: 860px;
        overflow: auto;
    }
    
    div:has(> #right-panel-anchor) {
        height: 860px;
        overflow-y: visible;  /* 改为visible，让内部组件自己处理滚动 */
        display: flex;
        flex-direction: column;
    }
    
    /* 确保tabs不占用太多空间，让文本框对齐 */
    div:has(> #right-panel-anchor) > div[data-testid="stTabs"] {
        flex-shrink: 0;
        margin-bottom: 0;
    }
    
    /* 确保右侧文本框与左侧对齐 */
    div:has(> #right-panel-anchor) textarea {
        flex: 1;
        min-height: 780px;
    }
    
    /* 确保Markdown的iframe有正确的大小和边框 */
    div:has(> #right-panel-anchor) iframe {
        border: none;
        height: 780px !important;  /* 确保iframe高度为780px */
    }
    
    /* 确保HTML组件内容可以正常显示 */
    div:has(> #right-panel-anchor) > div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] {
        flex: 1;
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
    
    /* 确保文本区域有滚动条 */
    textarea {
        overflow-y: auto !important;
    }
    
    /* 特别针对右侧OCR识别对照区域的文本区域 - 设置为白色背景 */
    div[data-testid="stTextArea"] textarea,
    textarea.stTextArea {
        background-color: white !important;
    }
    
    /* 针对所有禁用的文本区域（通常用于显示） */
    textarea:disabled {
        background-color: white !important;
        opacity: 1 !important;
    }
    
    /* 同步滚动容器样式 */
    .sync-scroll-container {
        max-height: 780px;
        overflow-y: auto;
        overflow-x: hidden;
    }
    
    /* 减小metric组件中数字的字体大小 */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
    }
    
</style>
""",
    unsafe_allow_html=True,
)


def main():
    """主函数"""
    initialize_session_state()

    title_col, button_col = st.columns([2, 1])
    with title_col:
        st.title("📄 合同审查系统")
    button_placeholder = button_col.empty()

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
                    st.session_state.workflow_result = None
                    st.session_state.processing_status = "idle"
                    st.session_state.loaded_from_history = False
                    st.session_state.view_mode = "preview"

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
                            st.session_state.workflow_result = None
                            st.session_state.processing_status = "idle"
                            st.session_state.loaded_from_history = False
                            st.session_state.view_mode = "preview"

                            st.session_state.saved_file_path = temp_path
                            st.session_state.file_name = file_name
                            st.session_state.preview_content = preview_file_content(
                                temp_path
                            )
                            st.success(f"已选择: {file_name}")
                            st.rerun()
            else:
                st.info("contracts目录下没有样例文件")

    if (
        hasattr(st.session_state, "saved_file_path")
        and st.session_state.saved_file_path
    ):
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
                st.session_state.view_mode = "analysis"
                st.success("已加载历史最新分析结果")
                st.rerun()
        
        with button_placeholder.container():
            if st.session_state.processing_status == "processing":
                st.info("处理中...")
            elif (
                st.session_state.processing_status == "completed"
                and st.session_state.workflow_result
            ):
                if st.session_state.get("view_mode") == "preview":
                    btn1, btn2 = st.columns(2)
                    
                    with btn1:
                        if st.button("▶ 调用OCR解析", type="primary", use_container_width=True):
                            ocr_result = call_online_parse_api(st.session_state.saved_file_path)
                            st.session_state.ocr_parse_result = ocr_result
                            if ocr_result:
                                st.session_state.ocr_parsed_file_path = st.session_state.saved_file_path
                                st.session_state.ocr_parsed_original_file_name = st.session_state.get("file_name")
                            else:
                                st.session_state.ocr_parsed_file_path = None
                                st.session_state.ocr_parsed_original_file_name = None
                            st.rerun()
                    
                    with btn2:
                        if st.button("📊 查看结果", use_container_width=True):
                            st.session_state.view_mode = "analysis"
                            st.rerun()
                else:
                    btn1, btn2, btn3 = st.columns(3)
                    
                    with btn1:
                        if st.button("🔁 重新提交", type="primary", use_container_width=True):
                            process_contract_workflow(st.session_state.saved_file_path)
                            st.rerun()
                    
                    with btn2:
                        result = st.session_state.workflow_result
                        json_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode(
                            "utf-8"
                        )
                        st.download_button(
                            label="📥 下载结果",
                            data=json_bytes,
                            file_name=f"contract_analysis_{int(time.time())}.json",
                            mime="application/json",
                            use_container_width=True,
                        )
                    
                    with btn3:
                        if st.button("⬅️ 返回预览", use_container_width=True):
                            st.session_state.view_mode = "preview"
                            st.rerun()
            elif st.session_state.processing_status == "idle":
                if st.session_state.get("view_mode") == "preview":
                    btn1, btn2 = st.columns(2)
                    
                    with btn1:
                        if st.button("▶ 调用OCR解析", type="primary", use_container_width=True):
                            ocr_result = call_online_parse_api(st.session_state.saved_file_path)
                            st.session_state.ocr_parse_result = ocr_result
                            if ocr_result:
                                st.session_state.ocr_parsed_file_path = st.session_state.saved_file_path
                                st.session_state.ocr_parsed_original_file_name = st.session_state.get("file_name")
                            else:
                                st.session_state.ocr_parsed_file_path = None
                                st.session_state.ocr_parsed_original_file_name = None
                            st.rerun()
                    
                    with btn2:
                        if st.button("🚀 开始分析", use_container_width=True):
                            process_contract_workflow(st.session_state.saved_file_path)
                            st.rerun()
                else:
                    if st.button("🚀 开始分析", type="primary", use_container_width=True):
                        process_contract_workflow(st.session_state.saved_file_path)
                        st.rerun()

        if st.session_state.processing_status == "processing":
            st.info("正在处理中，请稍候...")

        if (
            st.session_state.processing_status == "completed"
            and st.session_state.workflow_result
            and st.session_state.get("view_mode") == "analysis"
        ):
            result = st.session_state.workflow_result
            risk_analysis = result.get("risk_analysis", {})
            all_issues = risk_analysis.get("all_issues", [])

            # 创建左右分栏布局
            col1, col2 = st.columns([6, 4], gap="small")

            with col1:
                st.markdown(f"**{st.session_state.file_name}**")

                document_text = result.get("document_text", "")
                if document_text:
                    json_result = None

                    current_file_path = result.get(
                        "file_path", st.session_state.get("saved_file_path")
                    )
                    current_file_name = result.get(
                        "original_file_name", st.session_state.get("file_name")
                    )

                    def _is_same_source(parsed_path, parsed_name):
                        """判断当前OCR缓存是否与结果对应"""
                        if parsed_path and current_file_path:
                            try:
                                if os.path.abspath(parsed_path) == os.path.abspath(
                                    current_file_path
                                ):
                                    return True
                            except Exception:
                                if parsed_path == current_file_path:
                                    return True
                        if parsed_name and current_file_name:
                            return parsed_name == current_file_name
                        return False

                    ocr_result = st.session_state.get("ocr_parse_result")
                    parsed_path = st.session_state.get("ocr_parsed_file_path")
                    parsed_name = st.session_state.get("ocr_parsed_original_file_name")
                    if (
                        ocr_result
                        and isinstance(ocr_result, dict)
                        and _is_same_source(parsed_path, parsed_name)
                    ):
                        json_result = ocr_result.get("json_result")

                    if not json_result and current_file_path:
                        cached_result = load_cached_parse_result(
                            current_file_path, current_file_name
                        )
                        if cached_result:
                            json_result = cached_result.get("json_result")
                            st.session_state.ocr_parse_result = cached_result
                            st.session_state.ocr_parsed_file_path = current_file_path
                            st.session_state.ocr_parsed_original_file_name = (
                                current_file_name
                            )
                    if json_result:
                        html_content = generate_html_layout(json_result, all_issues)
                        st.components.v1.html(html_content, height=840, scrolling=True)
                    else:
                        st.warning(
                            "⚠️ 未找到OCR解析结果，无法进行版面恢复。请在预览界面先调用OCR解析。"
                        )
                        st.info(
                            "💡 提示：切换到预览界面，点击「调用OCR解析」按钮，然后再查看分析结果。"
                        )
                else:
                    st.warning("未获取到文档内容")

            with col2:
                st.markdown("### 🔍 审查结果")

                view = st.radio(
                    "选择查看内容",
                    ["风险点", "综合建议"],
                    horizontal=True,
                    key="result_view_switch",
                    label_visibility="collapsed",
                )

                suggestions = result.get("suggestions", {})
                statistics = risk_analysis.get("statistics", {})

                if view == "风险点":
                    risk_levels = ["全部", "重大风险", "一般风险", "低风险"]
                    selected_level = st.radio(
                        "选择风险等级", risk_levels, horizontal=True, key="risk_filter", label_visibility="collapsed"
                    )

                    filtered_issues = filter_issues_by_risk(all_issues, selected_level)

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
                    if not suggestions:
                        st.info("暂无综合建议")
                    else:
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
                        render_suggestions(suggestions)

        if (
            st.session_state.preview_content
            and st.session_state.get("view_mode") == "preview"
        ):
            render_preview_panel(
                st.session_state.saved_file_path, st.session_state.preview_content
            )

    else:
        st.info("请上传合同文件或选择样例文件开始分析")

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
