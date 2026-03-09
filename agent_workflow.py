"""Agent 工作流入口：基于 LangGraph + Skills 的独立实现。"""

from typing import Any, Dict, Optional

from agent_framework import ContractSkills
from agent_framework.graph_workflow import run_contract_graph


class AgentContractWorkflow:
    """Agent 版工作流，对外接口与 ContractWorkflow 保持一致。"""

    def __init__(
        self,
        mcp_url: str = "http://localhost:7001",
        llm_api_key: Optional[str] = None,
        llm_api_base_url: Optional[str] = None,
        llm_model_name: Optional[str] = None,
    ):
        self.skills = ContractSkills(
            mcp_url=mcp_url,
            llm_api_key=llm_api_key,
            llm_api_base_url=llm_api_base_url,
            llm_model_name=llm_model_name,
        )

    def process_contract(
        self,
        file_path: str,
        original_file_name: Optional[str] = None,
        markdown_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        inputs: Dict[str, Any] = {
            "file_path": file_path,
            "original_file_name": original_file_name,
            "markdown_text": markdown_text,
        }
        return run_contract_graph(self.skills, inputs)

    def generate_highlighted_document(self, file_path: str, issues: Any):
        """高亮能力在 Agent 模式下由独立 Skill 提供。"""
        return self.skills.highlight_document_skill(file_path, issues)
