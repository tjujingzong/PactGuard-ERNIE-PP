# ui_workflow.py
# 基于工作流的合同审查系统UI界面

import os
import json
import time
import tempfile
import base64
from typing import Dict, List, Optional, Any
import streamlit as st
from contract_workflow import ContractWorkflow

# 页面配置
st.set_page_config(
    page_title="合同审查系统 - 工作流版",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

        # 步骤1: 文档解析
        with st.spinner("正在解析文档..."):
            result = workflow.process_contract(file_path)

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
            if st.button("🔄 重新选择文件"):
                # 清除状态
                for key in [
                    "saved_file_path",
                    "file_name",
                    "preview_content",
                    "workflow_result",
                    "processing_status",
                ]:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()

        # 开始分析按钮
        if st.session_state.processing_status == "idle":
            if st.button("🚀 开始分析", type="primary", use_container_width=True):
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

                # 合同标题和上传按钮
                header_col1, header_col2 = st.columns([3, 1])
                with header_col1:
                    st.markdown(f"**{st.session_state.file_name}**")
                with header_col2:
                    if st.button("📤 重新选择", key="upload_contract"):
                        # 清除状态
                        for key in [
                            "saved_file_path",
                            "file_name",
                            "preview_content",
                            "workflow_result",
                            "processing_status",
                        ]:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.rerun()

                # 显示合同内容（带高亮）
                document_text = result.get("document_text", "")
                if document_text:
                    # 为问题添加高亮标记
                    highlighted_text = add_highlights_to_text(document_text, all_issues)

                    # 显示标记后的文本
                    st.markdown("### 📄 合同内容（已标记问题）")
                    st.text_area("", value=highlighted_text, height=800, disabled=True)
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
                                    st.write(f"**条款位置：** {issue.get('条款', 'N/A')}")
                                    st.write(f"**问题描述：** {issue.get('问题描述', 'N/A')}")
                                    st.write(f"**修改建议：** {issue.get('修改建议', 'N/A')}")
                                    if issue.get("法律依据"):
                                        st.write(f"**法律依据：** {issue.get('法律依据', 'N/A')}")
                                    if issue.get("影响分析"):
                                        st.write(f"**影响分析：** {issue.get('影响分析', 'N/A')}")
                                    if issue.get("商业优化"):
                                        st.write(f"**商业优化：** {issue.get('商业优化', 'N/A')}")

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
                            st.metric("风险评分", f"{statistics.get('risk_score', 0)}/100")
                        with col2:
                            st.metric("总问题数", statistics.get("total_issues", len(all_issues)))
                        with col3:
                            risk_level = statistics.get("risk_level", "低")
                            level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
                            st.metric("风险等级", f"{level_color} {risk_level}")

                        st.markdown("---")
                        # 直接复用现有渲染函数
                        render_suggestions(suggestions)

                # 下载结果按钮（直接下载）
                st.markdown("---")
                json_bytes = json.dumps(
                    result, ensure_ascii=False, indent=2
                ).encode("utf-8")
                st.download_button(
                    label="📥 下载结果",
                    data=json_bytes,
                    file_name=f"contract_analysis_{int(time.time())}.json",
                    mime="application/json",
                    use_container_width=True,
                )

        # 显示文件预览
        if (
            st.session_state.processing_status == "idle"
            and st.session_state.preview_content
        ):
            with st.expander("📄 文件预览", expanded=True):
                st.text_area(
                    "文件内容",
                    st.session_state.preview_content,
                    height=800,
                    disabled=True,
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
