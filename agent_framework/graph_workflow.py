import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from .skills import ContractSkills
from .state import AgentContractState

logger = logging.getLogger(__name__)


def _is_debug_enabled() -> bool:
    return os.environ.get("AGENT_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def _dbg(message: str) -> None:
    if _is_debug_enabled():
        print(f"[AgentGraph] {message}", flush=True)
        logger.info(message)


def _append_trace(state: AgentContractState, node_name: str) -> List[str]:
    trace = list(state.get("execution_trace", []))
    trace.append(node_name)
    return trace


def _plan_node(state: AgentContractState, skills: ContractSkills) -> AgentContractState:
    _dbg("进入节点: plan")
    analysis_plan = skills.plan_analysis_skill()
    _dbg(f"plan输出步骤数: {len(analysis_plan)}")
    return {
        "analysis_plan": analysis_plan,
        "execution_trace": _append_trace(state, "plan"),
    }


def _parse_node(state: AgentContractState, skills: ContractSkills) -> AgentContractState:
    _dbg(f"进入节点: parse, file={state.get('file_path')}")
    document_text = skills.parse_contract_skill(state["file_path"])
    if not document_text:
        _dbg("parse失败: document_text为空")
        return {
            "error": "文档解析失败",
            "execution_trace": _append_trace(state, "parse_failed"),
        }
    _dbg(f"parse成功: 文本长度={len(document_text)}")
    return {
        "document_text": document_text,
        "error": None,
        "execution_trace": _append_trace(state, "parse"),
    }


def _risk_node(state: AgentContractState, skills: ContractSkills) -> AgentContractState:
    _dbg("进入节点: risk")
    base_text = state.get("markdown_text") or state.get("document_text", "")

    use_parallel = os.environ.get("AGENT_PARALLEL_RISK", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if use_parallel:
        _dbg("risk节点启用并行分析: legal + business")
        with ThreadPoolExecutor(max_workers=2) as executor:
            legal_future = executor.submit(skills.legal_risk_skill, base_text)
            business_future = executor.submit(skills.business_risk_skill, base_text)
            legal_risks = legal_future.result()
            business_risks = business_future.result()
    else:
        legal_risks = skills.legal_risk_skill(base_text)
        business_risks = skills.business_risk_skill(base_text)

    all_issues = [*legal_risks, *business_risks]
    risk_statistics = skills.risk_statistics_skill(all_issues)

    _dbg(
        f"risk完成: legal={len(legal_risks)}, business={len(business_risks)}, total={len(all_issues)}"
    )
    return {
        "legal_risks": legal_risks,
        "business_risks": business_risks,
        "all_issues": all_issues,
        "risk_statistics": risk_statistics,
        "execution_trace": _append_trace(state, "risk"),
    }


def _suggest_node(state: AgentContractState, skills: ContractSkills) -> AgentContractState:
    _dbg("进入节点: suggest")
    risk_analysis = {
        "legal_risks": state.get("legal_risks", []),
        "business_risks": state.get("business_risks", []),
        "all_issues": state.get("all_issues", []),
        "statistics": state.get("risk_statistics", {}),
    }
    base_text = state.get("markdown_text") or state.get("document_text", "")
    suggestions = skills.generate_suggestions_skill(base_text, risk_analysis)
    _dbg(f"suggest完成: keys={list(suggestions.keys()) if isinstance(suggestions, dict) else 'N/A'}")
    return {
        "suggestions": suggestions,
        "execution_trace": _append_trace(state, "suggest"),
    }


def _result_node(state: AgentContractState, skills: ContractSkills) -> AgentContractState:
    _dbg("进入节点: result")
    risk_analysis = {
        "legal_risks": state.get("legal_risks", []),
        "business_risks": state.get("business_risks", []),
        "all_issues": state.get("all_issues", []),
        "statistics": state.get("risk_statistics", {}),
    }

    execution_trace = _append_trace(state, "result")
    result = skills.integrate_result_skill(
        file_path=state["file_path"],
        document_text=state.get("document_text", ""),
        risk_analysis=risk_analysis,
        suggestions=state.get("suggestions", {}),
        original_file_name=state.get("original_file_name"),
        base_markdown_text=state.get("markdown_text"),
    )
    result["agent_metadata"] = {
        "framework": "langgraph",
        "analysis_plan": state.get("analysis_plan", []),
        "execution_trace": execution_trace,
    }
    saved_path = skills.save_result_skill(result)
    result["agent_metadata"]["saved_result_path"] = saved_path
    _dbg(f"result完成: 已保存到 {saved_path}")
    return {
        "result": result,
        "saved_result_path": saved_path,
        "execution_trace": execution_trace,
    }


def _route_after_parse(state: AgentContractState) -> str:
    if state.get("error"):
        return "end"
    return "risk"


def build_contract_graph(skills: ContractSkills):
    """构建 Agent 模式 LangGraph。"""
    # 说明：在部分 langgraph 旧版本中，TypedDict 作为 state schema 可能触发编译卡顿。
    # 这里使用 dict 作为运行态 schema，避免编译阶段阻塞。
    graph = StateGraph(dict)

    graph.add_node("plan", lambda s: _plan_node(s, skills))
    graph.add_node("parse", lambda s: _parse_node(s, skills))
    graph.add_node("risk", lambda s: _risk_node(s, skills))
    graph.add_node("suggest", lambda s: _suggest_node(s, skills))
    graph.add_node("result", lambda s: _result_node(s, skills))

    graph.set_entry_point("plan")
    graph.add_edge("plan", "parse")
    graph.add_conditional_edges(
        "parse",
        _route_after_parse,
        {
            "risk": "risk",
            "end": END,
        },
    )
    graph.add_edge("risk", "suggest")
    graph.add_edge("suggest", "result")
    graph.add_edge("result", END)

    return graph.compile()


def run_contract_graph(skills: ContractSkills, inputs: Dict[str, Any]) -> Dict[str, Any]:
    _dbg(f"开始执行Agent图: inputs_keys={list(inputs.keys())}")

    force_linear = os.environ.get("AGENT_FORCE_LINEAR", "").lower() in {"1", "true", "yes", "on"}
    if force_linear:
        _dbg("检测到 AGENT_FORCE_LINEAR=1，使用线性降级执行")
        state: Dict[str, Any] = dict(inputs)
        state.update(_plan_node(state, skills))
        parse_out = _parse_node(state, skills)
        state.update(parse_out)
        if state.get("error"):
            _dbg(f"线性执行失败: {state.get('error')}")
            return {"error": state["error"]}
        state.update(_risk_node(state, skills))
        state.update(_suggest_node(state, skills))
        state.update(_result_node(state, skills))
        result = state.get("result")
        if not isinstance(result, dict):
            _dbg("线性执行异常: result为空")
            return {"error": "Agent流程执行完成但结果为空"}
        _dbg("线性执行成功")
        return result

    _dbg("开始编译LangGraph")
    app = build_contract_graph(skills)
    _dbg("LangGraph编译完成，开始invoke")
    state = app.invoke(inputs)
    _dbg("invoke返回")

    if state.get("error"):
        _dbg(f"Agent图执行失败: {state.get('error')}")
        return {"error": state["error"]}

    result = state.get("result")
    if not isinstance(result, dict):
        _dbg("Agent图执行异常: result为空")
        return {"error": "Agent流程执行完成但结果为空"}

    _dbg("Agent图执行成功")
    return result
