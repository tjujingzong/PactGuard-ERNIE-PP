import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI

from ui_utils import compute_file_md5

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

logger = logging.getLogger(__name__)


def _is_debug_enabled() -> bool:
    return os.environ.get("AGENT_DEBUG", "").lower() in {"1", "true", "yes", "on"}


def _dbg(message: str) -> None:
    if _is_debug_enabled():
        print(f"[AgentSkills] {message}", flush=True)
        logger.info(message)


class ContractSkills:
    """Agent 模式下的独立 Skill 实现（不复用 ContractWorkflow 内部私有逻辑）。"""

    def __init__(
        self,
        mcp_url: str = "http://localhost:7001",
        llm_api_key: Optional[str] = None,
        llm_api_base_url: Optional[str] = None,
        llm_model_name: Optional[str] = None,
    ):
        self.mcp_url = mcp_url
        api_key = (llm_api_key or os.environ.get("LLM_API_KEY", "")).strip()
        base_url = (llm_api_base_url or os.environ.get("LLM_API_BASE_URL", "")).strip()
        default_model = "ernie-4.5-turbo-128k"
        self.llm_model_name = (
            (llm_model_name or os.environ.get("LLM_MODEL_NAME", "")).strip()
            or default_model
        )

        if not api_key or not base_url:
            raise ValueError("未配置大模型接口，请在界面或环境变量中设置后重试")

        self.request_timeout = float(os.environ.get("AGENT_LLM_TIMEOUT", "120"))
        self.llm_client = OpenAI(api_key=api_key, base_url=base_url)
        _dbg(
            f"初始化完成: mcp_url={self.mcp_url}, model={self.llm_model_name}, timeout={self.request_timeout}s"
        )

    # ---------- Skill: 规划 ----------
    def plan_analysis_skill(self) -> List[str]:
        return [
            "parse_document",
            "analyze_legal_risks",
            "analyze_business_risks",
            "aggregate_statistics",
            "generate_suggestions",
            "integrate_and_save",
        ]

    # ---------- Skill: 解析 ----------
    def parse_contract_skill(self, file_path: str) -> Optional[str]:
        _dbg(f"调用parse_contract_skill: file={file_path}")
        try:
            response = requests.post(
                f"{self.mcp_url}/tools/parse_contract",
                json={"file_path": file_path},
                timeout=60,
            )

            if response.status_code != 200:
                _dbg(f"解析失败: MCP状态码={response.status_code}")
                return None

            payload = response.json()
            if "error" in payload:
                _dbg(f"解析失败: MCP返回error={payload.get('error')}")
                return None

            raw_content = payload.get("content", "")

            def extract_text_from_item(item: Any) -> str:
                if isinstance(item, dict):
                    for key in ("text", "content", "message"):
                        if key in item and isinstance(item[key], str):
                            return item[key]
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        return item["text"]
                    return str(item)
                if isinstance(item, (list, tuple)):
                    return "\n".join(extract_text_from_item(x) for x in item)
                if isinstance(item, str):
                    return item
                return str(item)

            if isinstance(raw_content, list):
                content = "\n".join(extract_text_from_item(x) for x in raw_content)
            elif isinstance(raw_content, dict):
                content = extract_text_from_item(raw_content)
            else:
                content = extract_text_from_item(raw_content)

            if not content or content.isspace():
                _dbg("解析失败: 内容为空")
                return None

            _dbg(f"解析成功: 文本长度={len(content)}")
            return content
        except Exception as e:
            _dbg(f"解析异常: {e}")
            return None

    # ---------- Skill: 风险分析 ----------
    def legal_risk_skill(self, text: str) -> List[Dict[str, Any]]:
        _dbg(f"调用legal_risk_skill: text_len={len(text)}")
        system_prompt = """
你是一位专业的法律顾问，负责审查合同中的法律风险。你需要：
1. 仔细阅读合同文本，识别潜在的法律风险点
2. 评估每个风险的等级（高/中/低）
3. 提供相关的法律依据
4. 给出具体的修改建议

输出必须是JSON对象，包含字段 legal_risks，类型为数组。
数组中每个元素格式：
{
  "类型": "法律风险",
  "条款": "具体条款原文",
  "问题描述": "风险描述",
  "风险等级": "高/中/低",
  "法律依据": "相关法律条文",
  "修改建议": "具体修改建议"
}
"""
        parsed = self._call_llm_json(system_prompt, f"请分析以下合同文本：\n\n{text}")
        if isinstance(parsed, dict) and isinstance(parsed.get("legal_risks"), list):
            _dbg(f"legal_risk_skill完成: count={len(parsed['legal_risks'])}")
            return parsed["legal_risks"]
        if isinstance(parsed, list):
            _dbg(f"legal_risk_skill完成: count={len(parsed)}")
            return parsed

        fallback = self._fallback_legal_risks(text)
        _dbg(f"legal_risk_skill回退规则命中: count={len(fallback)}")
        return fallback

    def business_risk_skill(self, text: str) -> List[Dict[str, Any]]:
        _dbg(f"调用business_risk_skill: text_len={len(text)}")
        system_prompt = """
你是一位资深的商业顾问，负责审查合同中的商业风险。你需要：
1. 仔细阅读合同文本，识别潜在的商业风险点
2. 评估每个风险的等级（高/中/低）
3. 分析可能的商业影响
4. 给出具体的修改建议

输出必须是JSON对象，包含字段 business_risks，类型为数组。
数组中每个元素格式：
{
  "类型": "商业风险",
  "条款": "具体条款原文",
  "问题描述": "风险描述",
  "风险等级": "高/中/低",
  "影响分析": "商业影响分析",
  "修改建议": "具体修改建议",
  "商业优化": "商业优化建议"
}
"""
        parsed = self._call_llm_json(system_prompt, f"请分析以下合同文本：\n\n{text}")
        if isinstance(parsed, dict) and isinstance(parsed.get("business_risks"), list):
            _dbg(f"business_risk_skill完成: count={len(parsed['business_risks'])}")
            return parsed["business_risks"]
        if isinstance(parsed, list):
            _dbg(f"business_risk_skill完成: count={len(parsed)}")
            return parsed

        fallback = self._fallback_business_risks(text)
        _dbg(f"business_risk_skill回退规则命中: count={len(fallback)}")
        return fallback

    def risk_statistics_skill(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        stats = {
            "total_issues": len(issues),
            "by_level": {"高": 0, "中": 0, "低": 0},
            "by_type": {"法律风险": 0, "商业风险": 0},
            "illegal_clauses": 0,
        }

        for issue in issues:
            risk_level = issue.get("风险等级", "低")
            if risk_level in stats["by_level"]:
                stats["by_level"][risk_level] += 1

            issue_type = (issue.get("类型", "") or "").split()[0]
            if issue_type in stats["by_type"]:
                stats["by_type"][issue_type] += 1

            issue_text = f"{issue.get('类型', '')}{issue.get('问题描述', '')}"
            if "违法" in issue_text or "违规" in issue_text:
                stats["illegal_clauses"] += 1

        stats["risk_score"] = self._calculate_risk_score(issues)
        score = stats["risk_score"]
        stats["risk_level"] = "高" if score >= 70 else "中" if score >= 40 else "低"
        return stats

    # ---------- Skill: 建议 ----------
    def generate_suggestions_skill(
        self, text: str, risk_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        _dbg(
            f"调用generate_suggestions_skill: text_len={len(text)}, issues={len(risk_analysis.get('all_issues', []))}"
        )
        system_prompt = """
你是一位专业的合同分析专家。请基于合同文本与已识别风险，输出整体建议。

输出必须是JSON对象，结构如下：
{
  "summary": {
    "risk_score": "风险评分(0-100)",
    "risk_level": "风险等级(高/中/低)",
    "total_issues": "问题数",
    "high_risk": "高风险问题数",
    "medium_risk": "中风险问题数",
    "low_risk": "低风险问题数",
    "illegal_clauses": "违法条款数"
  },
  "analysis": {
    "key_risks": ["主要风险点列表"],
    "impact_analysis": "整体影响分析",
    "optimization_suggestions": ["优化建议列表"]
  },
  "recommendation": {
    "signing_advice": "签约建议",
    "negotiation_points": ["谈判要点列表"],
    "risk_mitigation": ["风险缓解措施"]
  }
}
"""

        user_content = {
            "合同文本": text,
            "问题列表": risk_analysis.get("all_issues", []),
            "风险统计": risk_analysis.get("statistics", {}),
        }
        parsed = self._call_llm_json(
            system_prompt, json.dumps(user_content, ensure_ascii=False)
        )
        if isinstance(parsed, dict):
            _dbg(f"generate_suggestions_skill完成: keys={list(parsed.keys())}")
            return parsed
        _dbg("generate_suggestions_skill失败，回退默认建议")
        return self._default_suggestions(risk_analysis.get("statistics", {}))

    # ---------- Skill: 汇总/持久化 ----------
    def integrate_result_skill(
        self,
        file_path: str,
        document_text: str,
        risk_analysis: Dict[str, Any],
        suggestions: Dict[str, Any],
        original_file_name: Optional[str] = None,
        base_markdown_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "file_path": file_path,
            "file_content_hash": compute_file_md5(file_path),
            "original_file_name": original_file_name
            if original_file_name
            else os.path.basename(file_path),
            "document_text": document_text,
            "base_markdown_text": base_markdown_text,
            "risk_analysis": risk_analysis,
            "suggestions": suggestions,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "processing_time": time.time(),
        }

    def save_result_skill(self, result: Dict[str, Any]) -> str:
        _dbg("调用save_result_skill")
        output_dir = "contract_analysis_results"
        os.makedirs(output_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"contract_analysis_{timestamp}.json")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        _dbg(f"结果已保存: {output_file}")
        return output_file

    def highlight_document_skill(self, file_path: str, issues: List[Dict[str, Any]]):
        try:
            response = requests.post(
                f"{self.mcp_url}/tools/highlight_contract",
                json={"original_path": file_path, "issues": issues},
                timeout=180,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    # ---------- 内部工具 ----------
    def _call_llm_json(self, system_prompt: str, user_prompt: str) -> Any:
        _dbg(f"调用LLM: model={self.llm_model_name}")
        try:
            chat_completion = self.llm_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.llm_model_name,
                temperature=0.4,
                response_format={"type": "json_object"},
                timeout=self.request_timeout,
            )
            content = (chat_completion.choices[0].message.content or "").strip()
            parsed = self._safe_json_loads(content)
            _dbg(f"LLM返回解析结果类型: {type(parsed).__name__}")
            return parsed
        except Exception as e:
            _dbg(f"调用LLM异常: {e}")
            return None

    @staticmethod
    def _safe_json_loads(content: str) -> Any:
        if not content:
            return None

        text = content.strip()
        if text.startswith("```"):
            text = text[3:]
            first_line_break = text.find("\n")
            if first_line_break != -1:
                text = text[first_line_break + 1 :]
        if text.endswith("```"):
            text = text[:-3]

        try:
            return json.loads(text.strip())
        except Exception:
            return None

    @staticmethod
    def _extract_clause_by_keyword(text: str, keyword: str, max_len: int = 120) -> str:
        idx = text.find(keyword)
        if idx == -1:
            return keyword
        start = max(0, idx - 20)
        end = min(len(text), idx + max_len)
        return text[start:end].strip().replace("\n", " ")

    def _fallback_legal_risks(self, text: str) -> List[Dict[str, Any]]:
        rules = [
            ("违约责任", "违约责任描述不明确或不对等", "中", "《民法典》合同编"),
            ("解除", "合同解除条件可能不清晰", "中", "《民法典》合同编"),
            ("争议解决", "争议解决条款可能缺失或不明确", "中", "《民事诉讼法》"),
            ("不可抗力", "不可抗力条款可能缺失", "低", "《民法典》"),
            ("保密", "保密义务边界可能不清晰", "低", "《反不正当竞争法》"),
        ]
        risks: List[Dict[str, Any]] = []
        for kw, desc, level, law in rules:
            if kw in text:
                risks.append(
                    {
                        "类型": "法律风险",
                        "条款": self._extract_clause_by_keyword(text, kw),
                        "问题描述": desc,
                        "风险等级": level,
                        "法律依据": law,
                        "修改建议": f"建议补充或细化“{kw}”条款的权责边界与触发条件。",
                    }
                )
        return risks

    def _fallback_business_risks(self, text: str) -> List[Dict[str, Any]]:
        rules = [
            ("付款", "付款条件与节点可能不够明确", "中"),
            ("交付", "交付标准或验收条件可能不完整", "中"),
            ("发票", "发票开具责任与时点可能不清晰", "低"),
            ("违约金", "违约金比例或计算口径可能存在争议", "中"),
            ("期限", "履约期限与里程碑约束可能不足", "低"),
        ]
        risks: List[Dict[str, Any]] = []
        for kw, desc, level in rules:
            if kw in text:
                risks.append(
                    {
                        "类型": "商业风险",
                        "条款": self._extract_clause_by_keyword(text, kw),
                        "问题描述": desc,
                        "风险等级": level,
                        "影响分析": "可能导致执行成本上升或履约争议。",
                        "修改建议": f"建议补充“{kw}”的量化标准、时间节点和责任划分。",
                        "商业优化": "引入可量化的验收与结算条件。",
                    }
                )
        return risks

    @staticmethod
    def _calculate_risk_score(issues: List[Dict[str, Any]]) -> float:
        if not issues:
            return 0.0

        weights = {"高": 1.0, "中": 0.6, "低": 0.3}
        type_weights = {"法律风险": 1.0, "商业风险": 0.8}

        total_score = 0.0
        max_possible_score = 0.0

        for issue in issues:
            risk_weight = weights.get(issue.get("风险等级", "低"), 0.3)
            type_weight = type_weights.get((issue.get("类型", "") or "").split()[0], 0.5)
            total_score += risk_weight * type_weight * 100
            max_possible_score += 100

        if max_possible_score <= 0:
            return 0.0

        base_score = (total_score / max_possible_score) * 100
        return round(min(base_score * 1.5, 100.0), 2)

    @staticmethod
    def _default_suggestions(statistics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "summary": {
                "risk_score": statistics.get("risk_score", 0),
                "risk_level": statistics.get("risk_level", "低"),
                "total_issues": statistics.get("total_issues", 0),
                "high_risk": statistics.get("by_level", {}).get("高", 0),
                "medium_risk": statistics.get("by_level", {}).get("中", 0),
                "low_risk": statistics.get("by_level", {}).get("低", 0),
                "illegal_clauses": statistics.get("illegal_clauses", 0),
            },
            "analysis": {
                "key_risks": ["需要进一步分析"],
                "impact_analysis": "建议进行详细审查",
                "optimization_suggestions": ["建议咨询专业律师"],
            },
            "recommendation": {
                "signing_advice": "建议谨慎签约",
                "negotiation_points": ["需要进一步协商"],
                "risk_mitigation": ["建议采取风险缓解措施"],
            },
        }
