# ui_workflow_processor.py
# 工作流处理相关函数

import streamlit as st
from contract_workflow import ContractWorkflow


def process_contract_workflow(file_path: str):
    """处理合同工作流"""
    try:
        st.session_state.processing_status = "processing"

        # 创建工作流实例
        workflow = ContractWorkflow(
            llm_api_base_url=st.session_state.get("llm_api_base_url"),
            llm_api_key=st.session_state.get("llm_api_key"),
            llm_model_name=st.session_state.get("llm_model_name"),
        )

        # 步骤1: 文档解析/分析
        with st.spinner("正在解析文档并分析..."):
            md_for_analysis = None
            if st.session_state.get("ocr_parse_result") and isinstance(st.session_state.ocr_parse_result, dict):
                _md = st.session_state.ocr_parse_result.get("markdown_text")
                if isinstance(_md, str) and _md.strip():
                    md_for_analysis = _md
            result = workflow.process_contract(
                file_path, original_file_name=st.session_state.file_name, markdown_text=md_for_analysis
            )

        if "error" in result:
            st.session_state.processing_status = "error"
            st.error(f"处理失败: {result['error']}")
            return

        st.session_state.workflow_result = result
        st.session_state.processing_status = "completed"
        st.session_state.view_mode = "analysis"

        st.success("合同分析完成！")

    except Exception as e:
        st.session_state.processing_status = "error"
        st.error(f"处理过程中发生错误: {str(e)}")

