# contract_workflow.py
# 基于工作流的合同审查系统

import os
import json
import time
import tempfile
import base64
from typing import Dict, List, Optional, Any
import logging
from openai import OpenAI
import requests

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContractWorkflow:
    """合同审查工作流类"""

    def __init__(self, mcp_url: str = "http://localhost:7001"):
        self.mcp_url = mcp_url
        self.llm_client = OpenAI(
            api_key="bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f",
            base_url="https://qianfan.baidubce.com/v2",
        )

    def process_contract(self, file_path: str) -> Dict[str, Any]:
        """
        主工作流：处理合同文件
        1. 解析文档
        2. 分析风险
        3. 生成建议
        4. 返回结果
        """
        logger.info(f"开始处理合同文件: {file_path}")

        try:
            # 步骤1: 解析文档
            logger.info("步骤1: 解析文档...")
            document_text = self._parse_document(file_path)
            if not document_text:
                return {"error": "文档解析失败"}

            # 步骤2: 分析风险
            logger.info("步骤2: 分析风险...")
            risk_analysis = self._analyze_risks(document_text)

            # 步骤3: 生成建议
            logger.info("步骤3: 生成建议...")
            suggestions = self._generate_suggestions(document_text, risk_analysis)

            # 步骤4: 整合结果
            logger.info("步骤4: 整合结果...")
            result = self._integrate_results(
                file_path, document_text, risk_analysis, suggestions
            )

            # 保存结果
            self._save_results(result)

            logger.info("合同处理完成")
            return result

        except Exception as e:
            logger.error(f"处理合同失败: {str(e)}")
            return {"error": f"处理失败: {str(e)}"}

    def _parse_document(self, file_path: str) -> Optional[str]:
        """步骤1: 解析文档获取文本内容"""
        try:
            # 调用MCP服务解析文档
            response = requests.post(
                f"{self.mcp_url}/tools/parse_contract",
                json={"file_path": file_path},
                timeout=60,
            )

            if response.status_code != 200:
                logger.error(f"MCP服务调用失败: {response.status_code}")
                return None

            result = response.json()

            if "error" in result:
                logger.error(f"文档解析错误: {result['error']}")
                return None

            # 处理MCP服务返回的不同格式
            content = result.get("content", "")

            # 如果content是字典，尝试提取文本
            if isinstance(content, dict):
                # 尝试从字典中提取文本内容
                if "content" in content:
                    content = content["content"]
                elif "text" in content:
                    content = content["text"]
                elif "message" in content:
                    content = content["message"]
                else:
                    # 如果字典中没有文本内容，尝试转换为字符串
                    content = str(content)

            # 确保content是字符串
            if not isinstance(content, str):
                content = str(content)

            # 调试信息
            logger.info(f"MCP返回的content类型: {type(content)}")
            logger.info(
                f"MCP返回的content长度: {len(content) if isinstance(content, str) else 'N/A'}"
            )

            if not content or content.isspace():
                logger.error("解析结果为空")
                return None

            logger.info(f"文档解析成功，文本长度: {len(content)} 字符")
            return content

        except Exception as e:
            logger.error(f"解析文档失败: {str(e)}")
            return None

    def _analyze_risks(self, document_text: str) -> Dict[str, Any]:
        """步骤2: 分析合同风险"""
        logger.info("开始风险分析...")

        # 并行分析三种风险
        legal_risks = self._analyze_legal_risks(document_text)
        business_risks = self._analyze_business_risks(document_text)
        format_issues = self._analyze_format_issues(document_text)

        # 整合所有风险
        all_issues = []
        all_issues.extend(legal_risks)
        all_issues.extend(business_risks)
        all_issues.extend(format_issues)

        # 计算风险统计
        risk_stats = self._calculate_risk_statistics(all_issues)

        return {
            "legal_risks": legal_risks,
            "business_risks": business_risks,
            "format_issues": format_issues,
            "all_issues": all_issues,
            "statistics": risk_stats,
        }

    def _analyze_legal_risks(self, text: str) -> List[Dict]:
        """分析法律风险"""
        system_prompt = """
        你是一位专业的法律顾问，负责审查合同中的法律风险。你需要：
        1. 仔细阅读合同文本，识别潜在的法律风险点
        2. 评估每个风险的等级（高/中/低）
        3. 提供相关的法律依据
        4. 给出具体的修改建议
        
        输出格式必须是JSON数组，每个风险点包含以下字段：
        {
            "类型": "法律风险",
            "条款": "具体条款原文",
            "问题描述": "风险描述",
            "风险等级": "高/中/低",
            "法律依据": "相关法律条文",
            "修改建议": "具体修改建议"
        }
        
        特别注意：
        1. 识别任何违法或违规条款
        2. 评估条款的公平性和合理性
        3. 关注权利义务的平衡
        4. 提供客观的法律建议
        """

        return self._call_llm_for_analysis(system_prompt, text, "法律风险")

    def _analyze_business_risks(self, text: str) -> List[Dict]:
        """分析商业风险"""
        system_prompt = """
        你是一位资深的商业顾问，负责审查合同中的商业风险。你需要：
        1. 仔细阅读合同文本，识别潜在的商业风险点
        2. 评估每个风险的等级（高/中/低）
        3. 分析可能的商业影响
        4. 给出具体的修改建议
        
        输出格式必须是JSON数组，每个风险点包含以下字段：
        {
            "类型": "商业风险",
            "条款": "具体条款原文",
            "问题描述": "风险描述",
            "风险等级": "高/中/低",
            "影响分析": "商业影响分析",
            "修改建议": "具体修改建议",
            "商业优化": "商业优化建议"
        }
        
        特别注意：
        1. 关注付款条件、违约责任等关键商业条款
        2. 评估商业条款的公平性和合理性
        3. 识别潜在的商业机会和风险
        4. 关注成本收益分配的合理性
        5. 评估长期商业影响和潜在风险
        """

        return self._call_llm_for_analysis(system_prompt, text, "商业风险")

    def _analyze_format_issues(self, text: str) -> List[Dict]:
        """分析格式问题"""
        system_prompt = """
        你是一位合同格式规范专家，负责审查合同的格式和完整性。你需要：
        1. 检查合同结构的完整性
        2. 检查章节标题的规范性
        3. 检查条款编号的连续性
        4. 检查格式的一致性
        5. 给出具体的修改建议
        
        输出格式必须是JSON数组，每个问题包含以下字段：
        {
            "类型": "格式问题",
            "条款": "具体位置描述",
            "问题描述": "格式问题描述",
            "风险等级": "高/中/低",
            "修改建议": "具体修改建议"
        }
        """

        return self._call_llm_for_analysis(system_prompt, text, "格式问题")

    def _call_llm_for_analysis(
        self, system_prompt: str, text: str, analysis_type: str
    ) -> List[Dict]:
        """调用大模型进行分析"""
        try:
            chat_completion = self.llm_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model="ernie-4.5-turbo-128k",
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            content = chat_completion.choices[0].message.content.strip()
            logger.info(f"{analysis_type}分析完成")

            # 解析JSON结果
            try:
                result = json.loads(content)
                if isinstance(result, list):
                    return result
                elif isinstance(result, dict):
                    # 如果返回的是字典，尝试提取数组
                    for value in result.values():
                        if isinstance(value, list):
                            return value
                    return [result]
                else:
                    return []
            except json.JSONDecodeError:
                logger.error(f"解析{analysis_type}分析结果失败")
                return []

        except Exception as e:
            logger.error(f"{analysis_type}分析失败: {str(e)}")
            return []

    def _calculate_risk_statistics(self, issues: List[Dict]) -> Dict[str, Any]:
        """计算风险统计信息"""
        stats = {
            "total_issues": len(issues),
            "by_level": {"高": 0, "中": 0, "低": 0},
            "by_type": {"法律风险": 0, "商业风险": 0, "格式问题": 0},
            "illegal_clauses": 0,
        }

        for issue in issues:
            # 按风险等级统计
            risk_level = issue.get("风险等级", "低")
            if risk_level in stats["by_level"]:
                stats["by_level"][risk_level] += 1

            # 按类型统计
            issue_type = issue.get("类型", "").split()[0]
            if issue_type in stats["by_type"]:
                stats["by_type"][issue_type] += 1

            # 统计违法条款
            if "违法" in issue.get("类型", "") or "违规" in issue.get("类型", ""):
                stats["illegal_clauses"] += 1

        # 计算风险评分
        risk_score = self._calculate_risk_score(issues)
        stats["risk_score"] = risk_score
        stats["risk_level"] = (
            "高" if risk_score >= 70 else "中" if risk_score >= 40 else "低"
        )

        return stats

    def _calculate_risk_score(self, issues: List[Dict]) -> float:
        """计算风险评分（0-100，分数越高风险越大）"""
        if not issues:
            return 0.0

        # 风险权重
        weights = {"高": 1.0, "中": 0.6, "低": 0.3}

        # 类型权重
        type_weights = {"法律风险": 1.0, "商业风险": 0.8, "格式问题": 0.5}

        total_score = 0
        max_possible_score = 0

        for issue in issues:
            risk_weight = weights.get(issue.get("风险等级", "低"), 0.3)
            type_weight = type_weights.get(issue.get("类型", "").split()[0], 0.5)

            # 计算该问题的风险分数
            issue_score = risk_weight * type_weight * 100

            total_score += issue_score
            max_possible_score += 100  # 最高可能分数

        # 归一化到0-100范围，并适度上调整体评分
        if max_possible_score > 0:
            base_score = (total_score / max_possible_score) * 100
            # 适度提高评分：放大系数1.25，最高不超过100
            adjusted_score = min(base_score * 1.5, 100.0)
            return round(adjusted_score, 2)
        return 0.0

    def _generate_suggestions(
        self, text: str, risk_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """步骤3: 生成综合建议"""
        logger.info("生成综合建议...")

        all_issues = risk_analysis.get("all_issues", [])
        statistics = risk_analysis.get("statistics", {})

        system_prompt = """
        你是一位专业的合同分析专家，现在需要你对合同进行整体分析。
        
        你需要：
        1. 分析合同中的各类问题和风险
        2. 评估问题的影响程度
        3. 给出具体的优化建议
        4. 提供清晰的签约建议
        
        请特别注意：
        1. 客观分析合同条款的公平性和合理性
        2. 评估风险的整体影响
        3. 提供具体可行的优化方案
        
        输出格式必须是JSON对象，包含以下字段：
        {
            "summary": {
                "risk_score": "风险评分(0-100)",
                "risk_level": "风险等级(高/中/低)",
                "total_issues": "总问题数",
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
            "问题列表": all_issues,
            "风险统计": statistics,
        }

        try:
            chat_completion = self.llm_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_content, ensure_ascii=False),
                    },
                ],
                model="ernie-4.5-turbo-128k",
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            content = chat_completion.choices[0].message.content.strip()

            try:
                suggestions = json.loads(content)
                logger.info("综合建议生成完成")
                return suggestions
            except json.JSONDecodeError:
                logger.error("解析建议结果失败")
                return self._generate_default_suggestions(statistics)

        except Exception as e:
            logger.error(f"生成建议失败: {str(e)}")
            return self._generate_default_suggestions(statistics)

    def _generate_default_suggestions(
        self, statistics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成默认建议"""
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

    def _integrate_results(
        self,
        file_path: str,
        document_text: str,
        risk_analysis: Dict[str, Any],
        suggestions: Dict[str, Any],
    ) -> Dict[str, Any]:
        """步骤4: 整合所有结果"""
        logger.info("整合分析结果...")

        return {
            "file_path": file_path,
            "document_text": document_text,
            "risk_analysis": risk_analysis,
            "suggestions": suggestions,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "processing_time": time.time(),
        }

    def _save_results(self, result: Dict[str, Any]) -> str:
        """保存分析结果到文件"""
        try:
            output_dir = "contract_analysis_results"
            os.makedirs(output_dir, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(
                output_dir, f"contract_analysis_{timestamp}.json"
            )

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger.info(f"分析结果已保存到: {output_file}")
            return output_file

        except Exception as e:
            logger.error(f"保存结果失败: {str(e)}")
            return ""

    def generate_highlighted_document(
        self, file_path: str, issues: List[Dict]
    ) -> Optional[Dict]:
        """生成高亮版本的文档"""
        try:
            response = requests.post(
                f"{self.mcp_url}/tools/highlight_contract",
                json={"original_path": file_path, "issues": issues},
                timeout=180,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"高亮生成失败: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"生成高亮文档失败: {str(e)}")
            return None


def main():
    """主函数，用于测试工作流"""
    import sys

    if len(sys.argv) != 2:
        print("用法: python contract_workflow.py <文件路径>")
        sys.exit(1)

    file_path = sys.argv[1]

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    # 创建工作流实例
    workflow = ContractWorkflow()

    # 处理合同
    result = workflow.process_contract(file_path)

    if "error" in result:
        print(f"处理失败: {result['error']}")
        sys.exit(1)

    print("处理完成！")
    print(f"总问题数: {result['risk_analysis']['statistics']['total_issues']}")
    print(f"风险评分: {result['risk_analysis']['statistics']['risk_score']}")
    print(f"风险等级: {result['risk_analysis']['statistics']['risk_level']}")


if __name__ == "__main__":
    main()
