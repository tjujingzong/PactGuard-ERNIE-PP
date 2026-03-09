from typing import Any, Dict, List, Optional, TypedDict


class AgentContractState(TypedDict, total=False):
    """LangGraph 运行状态。"""

    # 输入
    file_path: str
    original_file_name: Optional[str]
    markdown_text: Optional[str]

    # 规划
    analysis_plan: List[str]

    # 解析
    document_text: str

    # 分析
    legal_risks: List[Dict[str, Any]]
    business_risks: List[Dict[str, Any]]
    all_issues: List[Dict[str, Any]]
    risk_statistics: Dict[str, Any]

    # 生成
    suggestions: Dict[str, Any]

    # 输出
    result: Dict[str, Any]
    saved_result_path: Optional[str]

    # 错误
    error: Optional[str]
