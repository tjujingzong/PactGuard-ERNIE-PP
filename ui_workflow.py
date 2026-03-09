# ui_workflow.py

import os
import json
import time
import warnings
import urllib3
import streamlit as st
import subprocess
import sys
import requests
import atexit
import threading
from pathlib import Path
from dotenv import load_dotenv
from contract_workflow import ContractWorkflow

# 加载 .env 文件中的环境变量（相对项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
from ui_utils import (
    initialize_session_state,
    load_latest_result_by_filename,
    save_uploaded_file,
    get_sample_files,
    get_uploaded_files,
    copy_sample_file,
    preview_file_content,
    load_cached_parse_result,
    compute_file_md5,
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

# MCP 服务管理
_mcp_process = None
_mcp_lock = threading.Lock()


def check_mcp_service():
    """检查MCP服务是否运行"""
    try:
        response = requests.get("http://localhost:7001/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def start_mcp_service():
    """启动MCP服务（仅启动一次）"""
    global _mcp_process
    
    with _mcp_lock:
        # 如果进程已存在且正在运行，直接返回
        if _mcp_process is not None and _mcp_process.poll() is None:
            return True
        
        # 检查服务是否已在运行
        if check_mcp_service():
            return True
        
        # 启动MCP服务
        try:
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
            # Windows 上隐藏控制台窗口
            if sys.platform == "win32":
                try:
                    popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                except AttributeError:
                    pass  # 如果常量不存在，忽略
            
            _mcp_process = subprocess.Popen(
                [sys.executable, "mcp_service.py"],
                **popen_kwargs
            )
            
            # 等待服务启动
            for i in range(30):
                if check_mcp_service():
                    return True
                time.sleep(1)
            
            return False
        except Exception as e:
            print(f"启动MCP服务失败: {e}")
            return False


def cleanup_mcp_service():
    """清理MCP服务进程"""
    global _mcp_process
    with _mcp_lock:
        if _mcp_process is not None:
            try:
                _mcp_process.terminate()
                _mcp_process.wait(timeout=5)
            except:
                try:
                    _mcp_process.kill()
                except:
                    pass
            _mcp_process = None


# 注册退出时的清理函数
atexit.register(cleanup_mcp_service)

# 在模块加载时自动启动MCP服务
if not check_mcp_service():
    # 使用线程异步启动，避免阻塞Streamlit
    def start_mcp_async():
        if start_mcp_service():
            print("✅ MCP服务已启动")
        else:
            print("⚠️ MCP服务启动失败，请手动启动: python mcp_service.py")
    
    thread = threading.Thread(target=start_mcp_async, daemon=True)
    thread.start()

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
    
    /* 减少风险点expander之间的间距 - 更全面的选择器 */
    div[data-testid="stExpander"] {
        margin-top: 0.3px !important;
        margin-bottom: 0.3px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 减少expander内部按钮的间距 */
    div[data-testid="stExpander"] > div {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 减少expander按钮的间距 */
    div[data-testid="stExpander"] button {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
        padding-top: 4px !important;
        padding-bottom: 4px !important;
    }
    
    /* 减少expander内容区域的间距 */
    div[data-testid="stExpander"] > div[data-testid="stVerticalBlock"] {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 减少风险点容器之间的间距 - 更具体的选择器 */
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        margin-top: 0.3px !important;
        margin-bottom: 0.3px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 减少container内部的间距 */
    div[data-testid="stContainer"] {
        margin-top: 0px !important;
        margin-bottom: 0px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 减少VerticalBlock之间的间距 */
    div[data-testid="stVerticalBlock"] {
        gap: 0.3px !important;
    }
    
    /* 减少VerticalBlock内部元素的间距 */
    div[data-testid="stVerticalBlock"] > * {
        margin-top: 0.3px !important;
        margin-bottom: 0.3px !important;
    }
    
    /* 减少hr分隔线的间距 */
    hr {
        margin-top: 0.3px !important;
        margin-bottom: 0.3px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    
    /* 针对风险点区域的特殊处理 - 减少所有可能的间距 */
    div[data-testid="stVerticalBlock"]:has(div[data-testid="stExpander"]) {
        gap: 0.3px !important;
    }
    
    div[data-testid="stVerticalBlock"]:has(div[data-testid="stExpander"]) > * {
        margin-top: 0.3px !important;
        margin-bottom: 0.3px !important;
    }
    
</style>
""",
    unsafe_allow_html=True,
)


def _is_same_source(
    parsed_path,
    parsed_name,
    parsed_hash,
    current_file_path,
    current_file_name,
    current_file_hash,
):
    """判断OCR缓存是否与当前文件来源一致"""
    if parsed_hash and current_file_hash and parsed_hash == current_file_hash:
        return True
    if parsed_path and current_file_path:
        try:
            if os.path.abspath(parsed_path) == os.path.abspath(current_file_path):
                return True
        except Exception:
            if parsed_path == current_file_path:
                return True
    if parsed_name and current_file_name:
        return parsed_name == current_file_name
    return False


def _ensure_current_file_ocr_result(
    current_file_path: str | None, current_file_name: str | None
):
    """确保会话中保存了当前文件的OCR结果，如没有则尝试从缓存加载"""
    if not current_file_path or not current_file_name:
        return None

    ocr_result = st.session_state.get("ocr_parse_result")
    parsed_path = st.session_state.get("ocr_parsed_file_path")
    parsed_name = st.session_state.get("ocr_parsed_original_file_name")
    parsed_hash = st.session_state.get("ocr_parsed_file_hash")
    current_hash = st.session_state.get("file_hash")

    if (
        ocr_result
        and isinstance(ocr_result, dict)
        and _is_same_source(
            parsed_path,
            parsed_name,
            parsed_hash,
            current_file_path,
            current_file_name,
            current_hash,
        )
    ):
        return ocr_result

    cached_result = load_cached_parse_result(current_file_path, current_file_name)
    if cached_result:
        st.session_state.ocr_parse_result = cached_result
        st.session_state.ocr_parsed_file_path = current_file_path
        st.session_state.ocr_parsed_original_file_name = current_file_name
        st.session_state.ocr_parsed_file_hash = current_hash or compute_file_md5(
            current_file_path
        )
        return cached_result

    return None


def main():
    """主函数"""
    initialize_session_state()

    saved_path = st.session_state.get("saved_file_path")
    if saved_path and not st.session_state.get("file_hash"):
        st.session_state.file_hash = compute_file_md5(saved_path)

    title_col, button_col = st.columns([2, 1])
    with title_col:
        st.title("📄 合同审查系统")
    button_placeholder = button_col.empty()

    with st.sidebar:
        st.markdown("### 🔧 接口配置")
        st.text_input(
            "大模型接口地址",
            key="llm_api_base_url",
            placeholder="https://qianfan.baidubce.com/****",
            help="填写兼容OpenAI协议的大模型HTTP地址(https://cloud.baidu.com/product-s/qianfan_home)",
        )
        st.text_input(
            "大模型 API Key",
            key="llm_api_key",
            placeholder="bce-v3/***",
            type="password",
            help="只保存在当前会话内，请勿泄露",
        )
        st.text_input(
            "大模型 Model 名称",
            key="llm_model_name",
            placeholder="ernie-4.5-turbo-128k",
            help="用于调用大模型的具体模型名，如 ernie-4.5-turbo-128k",
        )
        st.text_input(
            "OCR 接口地址",
            key="ocr_api_url",
            placeholder="https://*****.aistudio-app.com/layout-parsing",
            help="支持自定义布局解析服务HTTP地址,如 (https://aistudio.baidu.com/paddleocr/task)",
        )
        st.text_input(
            "OCR 访问令牌",
            key="ocr_api_token",
            placeholder="token",
            type="password",
            help="如果接口需要鉴权，请填写对应token (https://aistudio.baidu.com/account/accessToken)",
        )

        st.markdown("### 🤖 运行模式")
        st.radio(
            "选择工作流模式",
            options=["经典模式", "Agent模式（LangGraph）"],
            key="agent_mode",
            help="经典模式使用原始串行流程；Agent模式使用 LangGraph + Skills。",
        )
        st.caption(
            "提示：也可通过环境变量 AGENT_FRAMEWORK=langgraph 启用 Agent 模式。"
        )

        env_mode = os.environ.get("AGENT_FRAMEWORK", "").lower()
        selected_mode = st.session_state.get("agent_mode", "经典模式")
        expected_runtime_mode = (
            "Agent"
            if (selected_mode == "Agent模式（LangGraph）" or env_mode == "langgraph")
            else "Classic"
        )

        runtime_mode = st.session_state.get("runtime_mode", expected_runtime_mode)
        workflow_result = st.session_state.get("workflow_result")
        if (
            isinstance(workflow_result, dict)
            and isinstance(workflow_result.get("agent_metadata"), dict)
            and workflow_result.get("agent_metadata", {}).get("framework") == "langgraph"
        ):
            runtime_mode = "Agent"

        runtime_mode_label = "Agent（LangGraph）" if runtime_mode == "Agent" else "Classic（原流程）"
        st.info(f"当前实际运行模式：{runtime_mode_label}")
        st.divider()

        st.markdown("### 📁 文件选择")

        # 创建选项卡
        tab1, tab2 = st.tabs(["📤 上传文件", "📋 选择样例"])

        with tab1:
            uploaded_file = st.file_uploader(
                "上传合同文件",
                type=["pdf", "docx", "txt", "doc"],
                help="支持PDF、DOCX、TXT、DOC格式",
                key="uploaded_contract_file",
            )

            if st.session_state.get("skip_uploaded_file_once"):
                st.session_state.skip_uploaded_file_once = False
            elif uploaded_file:
                # 检查是否已经处理过这个文件（通过文件名和大小判断）
                file_name = uploaded_file.name
                file_size = uploaded_file.size
                last_name = st.session_state.get("last_processed_upload_name")
                last_size = st.session_state.get("last_processed_upload_size")
                
                # 只有当文件名或大小不同时，才认为是新文件
                if file_name != last_name or file_size != last_size:
                    saved_path = save_uploaded_file(uploaded_file)
                    if saved_path:
                        # 记录已处理的上传文件信息
                        st.session_state.last_processed_upload_name = file_name
                        st.session_state.last_processed_upload_size = file_size
                        
                        st.session_state.workflow_result = None
                        st.session_state.processing_status = "idle"
                        st.session_state.loaded_from_history = False
                        st.session_state.view_mode = "preview"
                        # 切换新文件时清空旧的 OCR 状态，避免误用
                        st.session_state.ocr_parse_result = None
                        st.session_state.ocr_parsed_file_path = None
                        st.session_state.ocr_parsed_original_file_name = None
                        st.session_state.ocr_parsed_file_hash = None

                        st.session_state.saved_file_path = saved_path
                        st.session_state.file_name = file_name
                        st.session_state.file_hash = compute_file_md5(saved_path)
                        st.session_state.preview_content = preview_file_content(saved_path)
                        st.success(f"已上传并选中: {file_name}")
                        st.rerun()

            uploaded_history_files = get_uploaded_files()
            if uploaded_history_files:
                st.divider()
                st.write("已上传文件（可点击快速切换）：")
                current_file_path = st.session_state.get("saved_file_path")
                for i, history_path in enumerate(uploaded_history_files):
                    file_name = os.path.basename(history_path)
                    is_current = current_file_path and os.path.abspath(history_path) == os.path.abspath(current_file_path)
                    
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        button_label = f"📄 {file_name}"
                        if is_current:
                            button_label = f"✅ {file_name} (当前)"
                        if st.button(button_label, key=f"uploaded_{i}", use_container_width=True):
                            st.session_state.workflow_result = None
                            st.session_state.processing_status = "idle"
                            st.session_state.loaded_from_history = False
                            st.session_state.view_mode = "preview"
                            st.session_state.ocr_parse_result = None
                            st.session_state.ocr_parsed_file_path = None
                            st.session_state.ocr_parsed_original_file_name = None
                            st.session_state.ocr_parsed_file_hash = None

                            st.session_state.saved_file_path = history_path
                            st.session_state.file_name = file_name
                            st.session_state.file_hash = compute_file_md5(history_path)
                            st.session_state.preview_content = preview_file_content(
                                history_path
                            )
                            st.session_state.skip_uploaded_file_once = True
                            st.success(f"已切换: {file_name}")
                            st.rerun()
                    with col2:
                        if st.button("🗑️", key=f"delete_uploaded_{i}", help="删除此文件", use_container_width=True):
                            try:
                                if os.path.exists(history_path):
                                    os.remove(history_path)
                                    st.success(f"已删除: {file_name}")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"删除文件失败: {str(e)}")

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
                            # 切换样例文件时同样清空 OCR 状态
                            st.session_state.ocr_parse_result = None
                            st.session_state.ocr_parsed_file_path = None
                            st.session_state.ocr_parsed_original_file_name = None
                            st.session_state.ocr_parsed_file_hash = None

                            st.session_state.saved_file_path = temp_path
                            st.session_state.file_name = file_name
                            st.session_state.file_hash = compute_file_md5(temp_path)
                            st.session_state.preview_content = preview_file_content(
                                temp_path
                            )
                            st.session_state.skip_uploaded_file_once = True
                            st.success(f"已选择: {file_name}")
                            st.rerun()
            else:
                st.info("contracts目录下没有样例文件")

    if (
        hasattr(st.session_state, "saved_file_path")
        and st.session_state.saved_file_path
    ):
        # 如果存在历史分析结果，自动加载但保持在预览模式，由用户手动决定是否查看结果
        if (
            st.session_state.processing_status == "idle"
            and st.session_state.file_name
            and not st.session_state.loaded_from_history
        ):
            cached = load_latest_result_by_filename(
                st.session_state.file_name,
                file_path=st.session_state.saved_file_path,
                file_hash=st.session_state.file_hash,
            )
            if cached:
                st.session_state.workflow_result = cached
                st.session_state.processing_status = "completed"
                st.session_state.loaded_from_history = True
                # 不再强制切换到分析视图，也不立即 rerun，避免跳过预览页
                # 保持 view_mode 为 "preview"，并在按钮区域提示用户可以直接查看历史结果
                st.info("已自动加载历史最新分析结果，可在预览页点击「📊 查看结果」直接查看，或重新分析。")
        
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
                            # 校验 OCR 配置
                            ocr_url = (st.session_state.get("ocr_api_url") or "").strip()
                            ocr_token = (st.session_state.get("ocr_api_token") or "").strip()
                            if not ocr_url or not ocr_token:
                                st.warning("请先在左侧『接口配置』中填写 OCR 接口地址和访问令牌，再调用 OCR 解析。")
                            else:
                                ocr_result = call_online_parse_api(st.session_state.saved_file_path)
                                st.session_state.ocr_parse_result = ocr_result
                                if ocr_result:
                                    st.session_state.ocr_parsed_file_path = st.session_state.saved_file_path
                                    st.session_state.ocr_parsed_original_file_name = st.session_state.get("file_name")
                                    st.session_state.ocr_parsed_file_hash = st.session_state.get("file_hash")
                                else:
                                    st.session_state.ocr_parsed_file_path = None
                                    st.session_state.ocr_parsed_original_file_name = None
                                    st.session_state.ocr_parsed_file_hash = None
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
                            # 校验 OCR 配置
                            ocr_url = (st.session_state.get("ocr_api_url") or "").strip()
                            ocr_token = (st.session_state.get("ocr_api_token") or "").strip()
                            if not ocr_url or not ocr_token:
                                st.warning("请先在左侧『接口配置』中填写 OCR 接口地址和访问令牌，再调用 OCR 解析。")
                            else:
                                ocr_result = call_online_parse_api(st.session_state.saved_file_path)
                                st.session_state.ocr_parse_result = ocr_result
                                if ocr_result:
                                    st.session_state.ocr_parsed_file_path = st.session_state.saved_file_path
                                    st.session_state.ocr_parsed_original_file_name = st.session_state.get("file_name")
                                    st.session_state.ocr_parsed_file_hash = st.session_state.get("file_hash")
                                else:
                                    st.session_state.ocr_parsed_file_path = None
                                    st.session_state.ocr_parsed_original_file_name = None
                                    st.session_state.ocr_parsed_file_hash = None
                                st.rerun()
                    
                    with btn2:
                        current_file_path = st.session_state.get("saved_file_path")
                        current_file_name = st.session_state.get("file_name")

                        # 优先使用内存中的结果，如果没有，则根据是否存在历史JSON结果来判断
                        existing_result = st.session_state.get("workflow_result")
                        if not existing_result and current_file_name:
                            cached = load_latest_result_by_filename(
                                current_file_name,
                                file_path=current_file_path,
                                file_hash=st.session_state.get("file_hash"),
                            )
                            if cached:
                                existing_result = cached
                                st.session_state.workflow_result = cached
                                st.session_state.processing_status = "completed"
                                st.session_state.loaded_from_history = True

                        if existing_result:
                            if st.button("📊 查看结果", use_container_width=True):
                                st.session_state.view_mode = "analysis"
                                st.rerun()
                        else:
                            # 只有当前文件已经完成 OCR 解析后，才允许开始分析（根据是否存在 OCR JSON 判断）
                            ocr_result = _ensure_current_file_ocr_result(
                                current_file_path, current_file_name
                            )
                            has_valid_ocr = ocr_result is not None

                            if st.button(
                                "🚀 开始分析",
                                use_container_width=True,
                                disabled=not has_valid_ocr,
                                help=(
                                    "请先点击左侧「调用OCR解析」，完成当前文件的版面解析后再开始分析。"
                                    if not has_valid_ocr
                                    else None
                                ),
                            ):
                                # 校验 LLM 接口配置
                                llm_url = (st.session_state.get("llm_api_base_url") or "").strip()
                                llm_key = (st.session_state.get("llm_api_key") or "").strip()
                                if not llm_url or not llm_key:
                                    st.warning("请先在左侧『接口配置』中填写大模型接口地址和 API Key，再开始分析。")
                                else:
                                    process_contract_workflow(st.session_state.saved_file_path)
                                    st.rerun()
                else:
                    if st.button("🚀 开始分析", type="primary", use_container_width=True):
                        # 校验 LLM 接口配置
                        llm_url = (st.session_state.get("llm_api_base_url") or "").strip()
                        llm_key = (st.session_state.get("llm_api_key") or "").strip()
                        if not llm_url or not llm_key:
                            st.warning("请先在左侧『接口配置』中填写大模型接口地址和 API Key，再开始分析。")
                        else:
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

                    ocr_result = _ensure_current_file_ocr_result(
                        current_file_path, current_file_name
                    )
                    if ocr_result:
                        json_result = ocr_result.get("json_result")
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

                agent_metadata = result.get("agent_metadata", {}) if isinstance(result, dict) else {}
                if isinstance(agent_metadata, dict) and agent_metadata.get("framework") == "langgraph":
                    with st.expander("🧭 Agent执行轨迹", expanded=False):
                        analysis_plan = agent_metadata.get("analysis_plan", [])
                        execution_trace = agent_metadata.get("execution_trace", [])
                        st.write("**分析计划（Plan）**")
                        if analysis_plan:
                            st.write(" → ".join(analysis_plan))
                        else:
                            st.write("暂无")
                        st.write("**图节点执行轨迹（Trace）**")
                        if execution_trace:
                            st.write(" → ".join(execution_trace))
                        else:
                            st.write("暂无")

                if view == "风险点":
                    risk_levels = ["全部", "重大风险", "一般风险", "低风险"]
                    selected_level = st.radio(
                        "选择风险等级", risk_levels, horizontal=True, key="risk_filter", label_visibility="collapsed"
                    )

                    filtered_issues = filter_issues_by_risk(all_issues, selected_level)

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("问题数", len(filtered_issues))
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

                            # 将风险类型和风险等级合并到expander标题中
                            expander_title = f"{risk_color} {issue_type} {risk_label}"
                            
                            with st.expander(expander_title):
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
                                "问题数",
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
