import requests
import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
import docx  # 添加docx支持
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# 配置AI Studio API Key
os.environ["AI_STUDIO_API_KEY"] = "6f83207f504098cd644f75618f9ed9507a5dfa7b"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ContractProcessor")

class ContractProcessor:
    """合同处理器类"""
    def __init__(self):
        # 检查API Key
        self.api_key = os.environ.get("AI_STUDIO_API_KEY")
        if not self.api_key:
            raise ValueError("未设置AI Studio API Key")
        
        # Agent端口配置
        self.processor_port = 7005
        self.legal_port = 7002
        self.business_port = 7003
        self.format_port = 7004
        self.integration_port = 7007
        
        # 创建输出目录
        self.output_dir = "contract_analysis_results"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 配置请求会话
        self.session = requests.Session()
        retries = Retry(
            total=3,  # 最大重试次数
            backoff_factor=1,  # 重试间隔
            status_forcelist=[500, 502, 503, 504]  # 需要重试的HTTP状态码
        )
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    def _read_docx(self, file_path: str) -> str:
        """读取docx文件内容"""
        try:
            doc = docx.Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        except Exception as e:
            logger.error(f"读取docx文件失败: {str(e)}")
            return ""

    def _read_file_with_multiple_encodings(self, file_path: str) -> str:
        """使用多种编码尝试读取文件"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
        
        # 如果是docx文件，使用专门的处理方法
        if file_path.lower().endswith('.docx'):
            return self._read_docx(file_path)
            
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"成功使用 {encoding} 编码读取文件")
                return content
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"使用 {encoding} 编码读取文件失败: {str(e)}")
                continue
        
        raise Exception(f"无法使用任何已知编码格式读取文件: {file_path}")

    def _extract_text_from_mcp_response(self, response: dict) -> str:
        """从MCP响应中提取文本内容"""
        try:
            logger.info(f"开始解析MCP响应...")
            
            if not response:
                logger.error("MCP响应为空")
                return ""

            def extract_nested_content(obj):
                """递归提取嵌套的内容"""
                if isinstance(obj, str):
                    try:
                        # 尝试解析JSON字符串
                        parsed = json.loads(obj)
                        return extract_nested_content(parsed)
                    except json.JSONDecodeError:
                        return obj
                
                if isinstance(obj, dict):
                    # 检查常见的内容字段
                    if "text" in obj:
                        return obj["text"]
                    if "content" in obj:
                        return extract_nested_content(obj["content"])
                    # 遍历所有值
                    for value in obj.values():
                        result = extract_nested_content(value)
                        if result:
                            return result
                
                if isinstance(obj, list):
                    # 合并所有文本内容
                    texts = []
                    for item in obj:
                        result = extract_nested_content(item)
                        if result:
                            texts.append(result)
                    return "\n".join(texts) if texts else ""
                
                return ""

            # 从响应中提取文本
            text_content = extract_nested_content(response)
            
            if text_content:
                logger.info(f"成功提取文本，长度: {len(text_content)}")
                return text_content
            
            logger.error("无法从响应中提取文本内容")
            return ""
            
        except Exception as e:
            logger.error(f"解析MCP响应失败: {str(e)}")
            return ""

    def _process_agent_response(self, response: dict) -> Optional[dict]:
        """处理Agent响应"""
        try:
            if "error" in response:
                logger.error(f"Agent响应包含错误: {response['error']}")
                return None
            
            if "artifacts" in response and response["artifacts"]:
                text_content = response["artifacts"][0]["parts"][0]["text"]
                try:
                    parsed_content = json.loads(text_content)
                    # 如果解析后的内容还包含artifacts，继续解析
                    if isinstance(parsed_content, dict) and "artifacts" in parsed_content:
                        inner_text = parsed_content["artifacts"][0]["parts"][0]["text"]
                        try:
                            return json.loads(inner_text)
                        except json.JSONDecodeError:
                            return {"content": inner_text}
                    return parsed_content
                except json.JSONDecodeError as e:
                    logger.error(f"解析Agent响应JSON失败: {str(e)}")
                    return {"content": text_content}
            
            logger.error("Agent响应格式无效")
            return None
        except Exception as e:
            logger.error(f"处理Agent响应失败: {str(e)}")
            return None

    def _call_agent_with_retry(self, port: int, data: dict, max_retries: int = 3, timeout: int = 60) -> dict:
        """带重试机制的Agent调用"""
        for attempt in range(max_retries):
            try:
                if "api_key" not in data:
                    data["api_key"] = self.api_key
                
                response = self.session.post(
                    f"http://localhost:{port}/task",
                    json={"message": {"content": data}},
                    timeout=timeout
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                logger.warning(f"调用Agent超时 (端口 {port})，第{attempt + 1}次重试")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # 指数退避
            except Exception as e:
                logger.error(f"调用Agent失败 (端口 {port}): {str(e)}")
                if attempt == max_retries - 1:
                    return {"error": str(e)}
                time.sleep(2 ** attempt)

    def process_document(self, file_path: str, party_type: str = "甲方") -> dict:
        """处理文档的主流程"""
        try:
            # 1. 调用文档处理Agent
            logger.info(f"开始处理文档: {file_path}")
            doc_response = self._call_agent_with_retry(self.processor_port, {
                "file_path": file_path
            })
            
            logger.info("文档处理Agent已返回响应")
            
            doc_result = self._process_agent_response(doc_response)
            if not doc_result:
                raise Exception("文档处理失败")
            
            # 提取文本内容
            contract_text = self._extract_text_from_mcp_response(doc_result)
            if not contract_text:
                # 尝试直接读取文件
                logger.warning("MCP提取失败，尝试直接读取文件")
                contract_text = self._read_file_with_multiple_encodings(file_path)
                if not contract_text:
                    raise Exception("无法提取文档内容")
            
            logger.info(f"文档处理完成，文本长度: {len(contract_text)}")
            logger.debug(f"提取的文本内容前200字符: {contract_text[:200]}...")

            # 2. 并行调用三个专家Agent
            logger.info("开始专家评审...")
            expert_responses = {}
            all_issues = []
            
            # 法律专家
            logger.info("调用法律专家...")
            legal_response = self._call_agent_with_retry(self.legal_port, {
                "text": contract_text,
                "party_type": party_type
            })
            legal_issues = self._process_agent_response(legal_response)
            expert_responses['legal'] = legal_issues
            if legal_issues:
                all_issues.extend(legal_issues)
            
            # 商业专家
            logger.info("调用商业专家...")
            business_response = self._call_agent_with_retry(self.business_port, {
                "text": contract_text,
                "party_type": party_type
            })
            business_issues = self._process_agent_response(business_response)
            expert_responses['business'] = business_issues
            if business_issues:
                all_issues.extend(business_issues)
            
            # 格式专家
            logger.info("调用格式专家...")
            format_response = self._call_agent_with_retry(self.format_port, {
                "text": contract_text
            })
            format_issues = self._process_agent_response(format_response)
            expert_responses['format'] = format_issues
            if format_issues:
                all_issues.extend(format_issues)
            
            logger.info(f"专家评审完成，发现 {len(all_issues)} 个问题")

            # 3. 调用整合Agent
            logger.info("开始整合分析...")
            integration_response = self._call_agent_with_retry(self.integration_port, {
                "text": contract_text,
                "party_type": party_type,
                "issues": all_issues
            }, timeout=90)  # 给整合Agent更多时间
            
            final_report = self._process_agent_response(integration_response)
            if not final_report:
                raise Exception("生成最终报告失败")
            
            # 处理最终报告格式
            if isinstance(final_report, dict) and "artifacts" in final_report:
                try:
                    final_report = json.loads(final_report["artifacts"][0]["parts"][0]["text"])
                except (json.JSONDecodeError, KeyError, IndexError):
                    logger.warning("无法解析最终报告的嵌套结构")
            
            # 4. 保存结果
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(
                self.output_dir,
                f"contract_analysis_{timestamp}.json"
            )
            
            result = {
                "file_path": file_path,
                "party_type": party_type,
                "expert_responses": expert_responses,
                "issues": all_issues,
                "analysis": final_report
            }
            
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            logger.info(f"分析完成，结果已保存至: {output_file}")
            return result

        except Exception as e:
            logger.error(f"处理失败: {str(e)}")
            return {
                "error": str(e),
                "file_path": file_path,
                "party_type": party_type
            }

def print_issues(issues: List[dict]):
    """打印问题详情"""
    if not issues:
        print("\n未发现问题")
        return
        
    # 确保issues是列表且每个元素都是字典
    if isinstance(issues, str):
        try:
            issues = json.loads(issues)
        except json.JSONDecodeError:
            logger.error("无法解析问题列表")
            print("\n无法解析问题列表")
            return
            
    if not isinstance(issues, list):
        logger.error(f"问题列表格式错误: {type(issues)}")
        print("\n问题列表格式错误")
        return
        
    # 过滤掉非字典元素
    issues = [issue for issue in issues if isinstance(issue, dict)]
    if not issues:
        print("\n没有有效的问题记录")
        return
    
    # 按风险等级分类
    risk_levels = {
        "高": [],
        "中": [],
        "低": []
    }
    
    # 按类型分类
    issue_types = {
        "法律风险": [],
        "商业风险": [],
        "格式问题": []
    }
    
    # 分类统计
    for issue in issues:
        risk_level = issue.get("风险等级", "低")
        issue_type = issue.get("类型", "其他")
        
        if risk_level in risk_levels:
            risk_levels[risk_level].append(issue)
            
        for type_key in issue_types.keys():
            if type_key in issue_type:
                issue_types[type_key].append(issue)
                break
    
    # 打印风险等级统计
    print("\n=== 风险等级分布 ===")
    for level, level_issues in risk_levels.items():
        if level_issues:
            print(f"{level}风险: {len(level_issues)}个")
    
    # 打印问题类型统计
    print("\n=== 问题类型分布 ===")
    for type_name, type_issues in issue_types.items():
        if type_issues:
            print(f"{type_name}: {len(type_issues)}个")
    
    # 打印详细问题列表
    print("\n=== 问题详情 ===")
    for level in ["高", "中", "低"]:
        if risk_levels[level]:
            print(f"\n{level}风险问题:")
            for i, issue in enumerate(risk_levels[level], 1):
                print(f"\n{i}. {issue.get('类型', '未知类型')}")
                print(f"   条款: {issue.get('条款', 'N/A')}")
                print(f"   描述: {issue.get('问题描述', 'N/A')}")
                if "法律依据" in issue:
                    print(f"   法律依据: {issue['法律依据']}")
                if "影响分析" in issue:
                    print(f"   影响分析: {issue['影响分析']}")
                print(f"   修改建议: {issue.get('修改建议', 'N/A')}")

def print_expert_responses(expert_responses: Dict):
    """打印专家回复"""
    if not expert_responses:
        print("\n未获取到专家评审结果")
        return

    expert_names = {
        'legal': '法律专家',
        'business': '商业专家',
        'format': '格式专家'
    }

    print("\n=== 专家评审详情 ===")
    for expert_type, response in expert_responses.items():
        print(f"\n{expert_names.get(expert_type, '未知专家')}评审结果:")
        if not response:
            print("  未返回评审结果")
            continue

        # 处理嵌套的响应格式
        if isinstance(response, dict) and "artifacts" in response:
            try:
                response = json.loads(response["artifacts"][0]["parts"][0]["text"])
            except (json.JSONDecodeError, KeyError, IndexError):
                print("  评审结果格式错误")
                continue

        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                print("  评审结果格式错误")
                continue

        if not isinstance(response, list):
            print("  评审结果格式错误")
            continue

        for i, issue in enumerate(response, 1):
            if not isinstance(issue, dict):
                continue
            print(f"\n  {i}. {issue.get('类型', '未知类型')}")
            print(f"     风险等级: {issue.get('风险等级', 'N/A')}")
            print(f"     条款: {issue.get('条款', 'N/A')}")
            print(f"     问题描述: {issue.get('问题描述', 'N/A')}")
            if "法律依据" in issue:
                print(f"     法律依据: {issue['法律依据']}")
            if "影响分析" in issue:
                print(f"     影响分析: {issue['影响分析']}")
            if "商业优化" in issue:
                print(f"     商业优化: {issue['商业优化']}")
            print(f"     修改建议: {issue.get('修改建议', 'N/A')}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="合同文档处理工具")
    parser.add_argument("file_path", help="合同文件路径")
    parser.add_argument("--party-type", default="甲方", choices=["甲方", "乙方"],
                      help="分析视角 (默认: 甲方)")
    parser.add_argument("--output", "-o", help="输出文件路径")
    
    args = parser.parse_args()
    
    # 检查文件是否存在
    if not os.path.exists(args.file_path):
        print(f"错误: 文件不存在: {args.file_path}")
        return
    
    # 处理文档
    processor = ContractProcessor()
    result = processor.process_document(args.file_path, args.party_type)
    
    # 打印结果摘要
    if "error" in result:
        print(f"\n处理失败: {result['error']}")
        return
        
    print("\n=== 分析结果摘要 ===")
    print(f"文件: {os.path.basename(args.file_path)}")
    print(f"分析视角: {args.party_type}")
    
    issues = result.get("issues", [])
    if isinstance(issues, str):
        try:
            issues = json.loads(issues)
        except json.JSONDecodeError:
            issues = []
    
    print(f"发现问题数量: {len(issues) if isinstance(issues, list) else 0}")
    
    # 打印专家评审详情
    print_expert_responses(result.get("expert_responses", {}))
    
    if "analysis" in result:
        analysis = result["analysis"]
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis)
            except json.JSONDecodeError:
                analysis = {}
                
        print(f"\n=== 风险评估 ===")
        if isinstance(analysis, dict):
            if "summary" in analysis:
                summary = analysis["summary"]
                print(f"风险评分: {summary.get('risk_score', 'N/A')}/100")
                print(f"风险等级: {summary.get('risk_level', 'N/A')}")
                print(f"总问题数: {summary.get('total_issues', 'N/A')}")
                print(f"高风险不利条款: {summary.get('unfavorable_high', 'N/A')}")
                print(f"中风险不利条款: {summary.get('unfavorable_medium', 'N/A')}")
                print(f"低风险不利条款: {summary.get('unfavorable_low', 'N/A')}")
                print(f"有利条款数: {summary.get('favorable_clauses', 'N/A')}")
                print(f"违法条款数: {summary.get('illegal_clauses', 'N/A')}")
            else:
                print(f"风险评分: {analysis.get('risk_score', 'N/A')}/100")
                print(f"风险等级: {analysis.get('risk_level', 'N/A')}")
            
            if "analysis" in analysis:
                analysis_detail = analysis["analysis"]
                print("\n=== 分析详情 ===")
                if "key_risks" in analysis_detail:
                    print("\n主要风险点:")
                    for risk in analysis_detail["key_risks"]:
                        print(f"- {risk}")
                if "favorable_points" in analysis_detail:
                    print("\n有利条款:")
                    for point in analysis_detail["favorable_points"]:
                        print(f"- {point}")
                if "impact_analysis" in analysis_detail:
                    print("\n影响分析:")
                    print(analysis_detail["impact_analysis"])
                if "optimization_suggestions" in analysis_detail:
                    print("\n优化建议:")
                    for suggestion in analysis_detail["optimization_suggestions"]:
                        print(f"- {suggestion}")
            
            if "recommendation" in analysis:
                recommendation = analysis["recommendation"]
                print(f"\n=== 签约建议 ===")
                if isinstance(recommendation, dict):
                    print(f"\n{recommendation.get('signing_advice', 'N/A')}")
                    
                    if "negotiation_points" in recommendation:
                        print("\n谈判要点:")
                        for point in recommendation["negotiation_points"]:
                            print(f"- {point}")
                            
                    if "risk_mitigation" in recommendation:
                        print("\n风险缓解措施:")
                        for measure in recommendation["risk_mitigation"]:
                            print(f"- {measure}")
    
    # 打印问题详情
    if issues:
        print_issues(issues)
    
    # 如果指定了输出文件，保存完整报告
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n完整报告已保存至: {args.output}")
    else:
        print(f"\n完整报告已保存至: {os.path.join(processor.output_dir, 'contract_analysis_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')}")

if __name__ == "__main__":
    main() 