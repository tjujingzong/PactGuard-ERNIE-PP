from python_a2a import A2AServer, run_server, TaskStatus, TaskState, AgentCard, AgentSkill
import requests
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import List, Dict, Any
import os
from openai import OpenAI
import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import re
import sys

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 服务配置
MCP_SERVER_URL = "http://localhost:7001"
COORDINATOR_PORT = 7000
LEGAL_PORT = 7002
BUSINESS_PORT = 7003
FORMAT_PORT = 7004
PROCESSOR_PORT = 7005
HIGHLIGHTER_PORT = 7006
INTEGRATION_PORT = 7007

try:
    llm_client = OpenAI(
    api_key="bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f",
    base_url="https://qianfan.baidubce.com/v2"
)
    logger.info("AI Studio客户端初始化成功")
except Exception as e:
    logger.error(f"AI Studio客户端初始化失败: {str(e)}")
    raise

class BaseAgent(A2AServer):
    """基础Agent类，提供通用功能"""
    def __init__(self, agent_card: AgentCard, mcp_url: str = MCP_SERVER_URL):
        super().__init__(agent_card=agent_card)
        self.mcp_url = mcp_url
        
        # 使用全局客户端
        self.llm_client = llm_client
        
        self.app = FastAPI()
        self._setup_routes()
        logger.info(f"{self.__class__.__name__} 初始化完成")

    def _setup_routes(self):
        """设置路由"""
        @self.app.post("/task")
        async def handle_task(request: Request):
            try:
                data = await request.json()
                task_result = self.handle_task(data)
                return JSONResponse(content=task_result)
            except Exception as e:
                logger.error(f"处理请求失败: {str(e)}")
                return JSONResponse(
                    content={"error": str(e)},
                    status_code=500
                )

        @self.app.get("/health")
        async def health_check():
            return {"status": "healthy"}

    def _call_mcp_tool(self, tool_name: str, params: dict) -> dict:
        """调用MCP工具"""
        if not self.mcp_url:
            return {"error": "MCP服务地址未配置"}
        
        tool_endpoint = f"{self.mcp_url}/tools/{tool_name}"
        try:
            logger.info(f"调用MCP工具: {tool_endpoint}, 参数: {params}")
            response = requests.post(tool_endpoint, json=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            error_msg = f"调用MCP工具失败: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}

    def handle_task(self, data: dict) -> dict:
        """处理任务请求"""
        try:
            if "message" not in data:
                return {
                    "error": "无效的请求格式",
                    "artifacts": [{"parts": [{"type": "text", "text": "请求中缺少message字段"}]}],
                    "status": {"state": TaskState.FAILED}
                }

            content = data["message"].get("content", {})
            if not content:
                return {
                    "error": "请求中缺少content字段",
                    "artifacts": [{"parts": [{"type": "text", "text": "请求中缺少content字段"}]}],
                    "status": {"state": TaskState.FAILED}
                }

            result = self._process_content(content)
            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }

        except Exception as e:
            logger.error(f"处理任务失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]}],
                "status": {"state": TaskState.FAILED}
            }

    def _process_content(self, content: dict) -> Any:
        """子类需要实现此方法来处理具体内容"""
        raise NotImplementedError

    def _call_llm(self, system_prompt: str, user_content: str) -> Dict:
        """调用大模型"""
        try:
            # 调用大模型
            chat_completion = self.llm_client.chat.completions.create(
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_content}
                ],
                model="ernie-4.5-turbo-128k",
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = chat_completion.choices[0].message.content.strip()
            print(content)
            logger.info(f"大模型返回原始内容: {content[:200]}...")  # 记录部分返回内容
            
            def extract_json(text):
                """智能JSON提取与解析"""
                # 清理和预处理文本
                text = re.sub(r'//.*?\n|/\*.*?\*/', '', text, flags=re.DOTALL)
                text = re.sub(r'(\w+)(?=:)', r'"\1"', text)
                
                # 尝试直接解析
                try:
                    result = json.loads(text)
                    if isinstance(result, dict):
                        for v in result.values():
                            if isinstance(v, list):
                                return v
                        return [result]
                    return result if isinstance(result, list) else [result]
                except json.JSONDecodeError:
                    pass
                
                # 使用正则提取JSON结构
                patterns = [
                    r'\{[\s\S]*?"[\w\u4e00-\u9fa5]+"\s*:\s*\[([\s\S]*?)\]\s*\}',  # 带键的数组
                    r'\[\s*\{[\s\S]*?\}\s*\]',  # 标准数组
                    r'\{[^{}]*\}'  # 简单对象（不包含嵌套）
                ]
                
                for pattern in patterns:
                    matches = re.finditer(pattern, text)
                    for match in matches:
                        try:
                            result = json.loads(match.group())
                            if isinstance(result, dict):
                                for v in result.values():
                                    if isinstance(v, list):
                                        return v
                                return [result]
                            return result if isinstance(result, list) else [result]
                        except:
                            continue
                
                # 最后的回退方案
                return [{
                    "类型": "解析结果",
                    "内容": text.replace('"', "'")
                }]
            
            # 解析并返回结果
            result = extract_json(content)
            return {'content': json.dumps(result, ensure_ascii=False)}
            
        except Exception as e:
            logger.error(f"调用大模型失败: {str(e)}")
            return {'content': '[]'}

class ContractCoordinator(BaseAgent):
    """合同审查协调器Agent"""
    def __init__(self):
        card = AgentCard(
            name="Contract Coordinator",
            description="合同审查多智能体协调器",
            url=f"http://localhost:{COORDINATOR_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Task Distribution",
                    description="分发任务给专业Agent"
                ),
                AgentSkill(
                    name="Result Integration",
                    description="整合各Agent的审查结果"
                ),
                AgentSkill(
                    name="Health Check",
                    description="检查各Agent的健康状态"
                )
            ]
        )
        super().__init__(card)
        self.agent_endpoints = {
            "legal": f"http://localhost:{LEGAL_PORT}",
            "business": f"http://localhost:{BUSINESS_PORT}",
            "format": f"http://localhost:{FORMAT_PORT}",
            "processor": f"http://localhost:{PROCESSOR_PORT}",
            "highlighter": f"http://localhost:{HIGHLIGHTER_PORT}"
        }

    async def _call_agent(self, agent_type: str, content: dict) -> dict:
        """异步调用其他Agent"""
        try:
            endpoint = self.agent_endpoints[agent_type]
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{endpoint}/task", json={"message": {"content": content}}) as response:
                    return await response.json()
        except Exception as e:
            logger.error(f"调用{agent_type} Agent失败: {str(e)}")
            return {"error": str(e)}

    async def _distribute_tasks(self, contract_text: str, file_path: str) -> List[Dict]:
        """并行分发任务给各个专业Agent"""
        tasks = []
        content = {"text": contract_text, "type": "text"}
        
        # 调用专业审查Agent
        for agent_type in ["legal", "business", "format"]:
            tasks.append(self._call_agent(agent_type, content))
        
        results = await asyncio.gather(*tasks)
        return results

    def _process_content(self, content):
        file_path = content.get("file_path", "")
        
        if not file_path:
            return {
                "error": "请提供文件路径",
                "artifacts": [{"parts": [{"type": "text", "text": "请提供文件路径"}]}],
                "status": {"state": TaskState.FAILED}
            }

        try:
            # 1. 调用文档处理Agent解析文档
            processor_response = requests.post(
                f"{self.agent_endpoints['processor']}/task",
                json={"message": {"content": {"file_path": file_path}}},
                timeout=30
            ).json()
            
            # 检查处理器响应
            if "artifacts" not in processor_response:
                logger.error(f"文档处理器响应格式错误: {processor_response}")
                return {
                    "error": "文档处理器响应格式错误",
                    "artifacts": [{"parts": [{"type": "text", "text": "文档处理器响应格式错误"}]}],
                    "status": {"state": TaskState.FAILED}
                }
            
            try:
                # 从处理器响应中提取文本
                processor_text = processor_response["artifacts"][0]["parts"][0]["text"]
                processor_result = json.loads(processor_text)
                
                # 检查是否有错误信息
                if "error" in processor_result:
                    logger.error(f"文档处理失败: {processor_result['error']}")
                    return {
                        "error": f"文档处理失败: {processor_result['error']}",
                        "artifacts": [{"parts": [{"type": "text", "text": f"文档处理失败: {processor_result['error']}"}]}],
                        "status": {"state": TaskState.FAILED}
                    }
                
                contract_text = processor_result.get("content", "")
                if not contract_text or contract_text.isspace():
                    logger.error("文档处理器返回的文本为空")
                    return {
                        "error": "文档处理器返回的文本为空",
                        "artifacts": [{"parts": [{"type": "text", "text": "文档处理器返回的文本为空"}]}],
                        "status": {"state": TaskState.FAILED}
                    }
                
                logger.info(f"成功提取文本，长度: {len(contract_text)} 字符")
                
            except json.JSONDecodeError as e:
                logger.error(f"解析处理器响应失败: {e}")
                return {
                    "error": f"解析处理器响应失败: {str(e)}",
                    "artifacts": [{"parts": [{"type": "text", "text": f"解析处理器响应失败: {str(e)}"}]}],
                    "status": {"state": TaskState.FAILED}
                }

            # 2. 分发任务给各个专业Agent
            combined_issues = []
            
            # 串行调用专业审查Agent
            for agent_type in ["legal", "business", "format"]:
                try:
                    response = requests.post(
                        f"{self.agent_endpoints[agent_type]}/task",
                        json={"message": {"content": {
                            "text": contract_text
                        }}},
                        timeout=30
                    ).json()
                    
                    if "artifacts" in response:
                        for artifact in response["artifacts"]:
                            for part in artifact.get("parts", []):
                                if part.get("type") == "text":
                                    try:
                                        issues = json.loads(part.get("text", "[]"))
                                        if isinstance(issues, list):
                                            combined_issues.extend(issues)
                                        else:
                                            logger.warning(f"{agent_type} Agent返回的不是列表格式")
                                    except json.JSONDecodeError:
                                        logger.error(f"解析{agent_type} Agent响应失败")
                except Exception as e:
                    logger.error(f"调用{agent_type} Agent失败: {str(e)}")

            # 3. 调用整合Agent生成分析报告
            try:
                integrator_response = requests.post(
                    f"{self.agent_endpoints['integrator']}/task",
                    json={
                        "message": {
                            "content": {
                                "text": contract_text,
                                "issues": combined_issues
                            }
                        }
                    },
                    timeout=30
                ).json()
                
                if "error" in integrator_response:
                    logger.error(f"整合分析失败: {integrator_response['error']}")
                    return {
                        "error": f"整合分析失败: {integrator_response['error']}",
                        "artifacts": [{"parts": [{"type": "text", "text": "整合分析失败"}]}],
                        "status": {"state": TaskState.FAILED}
                    }
                
                try:
                    analysis_report = json.loads(integrator_response["artifacts"][0]["parts"][0]["text"])
                except json.JSONDecodeError:
                    logger.error("解析整合分析结果失败")
                    analysis_report = None
                    
            except Exception as e:
                logger.error(f"调用整合Agent失败: {str(e)}")
                analysis_report = None

            # 4. 调用文档高亮Agent生成高亮版本
            try:
                highlighter_response = requests.post(
                    f"{self.agent_endpoints['highlighter']}/task",
                    json={
                        "message": {
                            "content": {
                                "file_path": file_path,
                                "issues": combined_issues
                            }
                        }
                    },
                    timeout=30
                ).json()
            except Exception as e:
                logger.error(f"调用高亮Agent失败: {str(e)}")
                highlighter_response = None

            # 5. 生成最终报告
            final_report = {
                "original_file": file_path,
                "highlighted_file": None,
                "analysis": analysis_report,
                "issues": combined_issues  # 添加原始问题列表
            }

            # 如果高亮成功，添加高亮文件信息
            if highlighter_response and "artifacts" in highlighter_response:
                try:
                    highlighter_result = json.loads(highlighter_response["artifacts"][0]["parts"][0]["text"])
                    if isinstance(highlighter_result, dict) and "content" in highlighter_result:
                        final_report["highlighted_file"] = highlighter_result.get("file_name")
                except:
                    logger.error("解析高亮结果失败")

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(final_report, ensure_ascii=False, indent=2)}]}],
                "status": {"state": TaskState.COMPLETED}
            }

        except Exception as e:
            logger.error(f"协调器处理任务失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": f"处理失败: {str(e)}"}]}],
                "status": {"state": TaskState.FAILED}
            }

class LegalAgent(BaseAgent):
    """法律审查Agent"""
    def __init__(self):
        card = AgentCard(
            name="Legal Review Agent",
            description="法律合规审查专家",
            url=f"http://localhost:{LEGAL_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Legal Risk Analysis",
                    description="识别合同中的法律风险"
                )
            ]
        )
        super().__init__(card)

    def _get_system_prompt(self):
        """生成系统提示"""
        return """
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

    def _process_content(self, content):
        contract_text = content.get("text", "")
        
        if not contract_text:
            return {
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.COMPLETED}
            }

        try:
            # 调用大模型进行分析
            result = self._call_llm(self._get_system_prompt(), contract_text)
            
            # 解析大模型输出
            try:
                issues = json.loads(result['content'])
            except:
                logger.error("解析大模型输出失败，使用空列表")
                issues = []

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(issues, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
        except Exception as e:
            logger.error(f"法律审查失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.FAILED}
            }

class BusinessAgent(BaseAgent):
    """商业审查Agent"""
    def __init__(self):
        card = AgentCard(
            name="Business Review Agent",
            description="商业条款审查专家",
            url=f"http://localhost:{BUSINESS_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Business Risk Analysis",
                    description="识别合同中的商业风险"
                )
            ]
        )
        super().__init__(card)

    def _get_system_prompt(self):
        """生成系统提示"""
        return """
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

    def _process_content(self, content):
        contract_text = content.get("text", "")
        
        if not contract_text:
            return {
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.COMPLETED}
            }

        try:
            # 调用大模型进行分析
            result = self._call_llm(self._get_system_prompt(), contract_text)
            
            # 解析大模型输出
            try:
                issues = json.loads(result['content'])
            except:
                logger.error("解析大模型输出失败，使用空列表")
                issues = []

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(issues, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
        except Exception as e:
            logger.error(f"商业审查失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.FAILED}
            }

class FormatAgent(BaseAgent):
    """格式审查Agent"""
    def __init__(self):
        card = AgentCard(
            name="Format Review Agent",
            description="格式与条款完整性审查专家",
            url=f"http://localhost:{FORMAT_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Format Analysis",
                    description="检查合同格式规范性"
                )
            ]
        )
        super().__init__(card)
        self.system_prompt = """
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

    def _process_content(self, content):
        contract_text = content.get("text", "")
        
        if not contract_text:
            return {
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.COMPLETED}
            }

        try:
            # 调用大模型进行分析
            result = self._call_llm(self.system_prompt, contract_text)
            
            # 解析大模型输出
            try:
                issues = json.loads(result['content'])
            except:
                logger.error("解析大模型输出失败，使用空列表")
                issues = []

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(issues, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
        except Exception as e:
            logger.error(f"格式审查失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": "[]"}]}],
                "status": {"state": TaskState.FAILED}
            }

class DocumentProcessorAgent(BaseAgent):
    """文档处理Agent"""
    def __init__(self):
        card = AgentCard(
            name="Document Processor Agent",
            description="文档处理专家",
            url=f"http://localhost:{PROCESSOR_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Document Processing",
                    description="处理各种格式的文档并提取文本"
                )
            ]
        )
        super().__init__(card)

    def _read_file_with_encoding(self, file_path: str) -> str:
        """使用多种编码尝试读取文件"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
        
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

    def _process_content(self, content):
        file_path = content.get("file_path", "")
        
        if not file_path:
            return {
                "error": "请提供文件路径",
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({"error": "请提供文件路径"}, ensure_ascii=False)}]}],
                "status": {"state": TaskState.FAILED}
            }

        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                return {
                    "error": f"文件不存在: {file_path}",
                    "artifacts": [{"parts": [{"type": "text", "text": json.dumps({"error": f"文件不存在: {file_path}"}, ensure_ascii=False)}]}],
                    "status": {"state": TaskState.FAILED}
                }

            # 读取文件内容进行验证
            try:
                file_content = self._read_file_with_encoding(file_path)
                logger.info(f"成功读取文件，内容长度: {len(file_content)}")
            except Exception as e:
                logger.error(f"读取文件失败: {str(e)}")
                return {
                    "error": f"读取文件失败: {str(e)}",
                    "artifacts": [{"parts": [{"type": "text", "text": json.dumps({"error": f"读取文件失败: {str(e)}"}, ensure_ascii=False)}]}],
                    "status": {"state": TaskState.FAILED}
                }

            # 调用MCP的parse_contract工具
            result = self._call_mcp_tool("parse_contract", {"file_path": file_path})
            logger.info(f"MCP工具返回结果: {json.dumps(result, ensure_ascii=False)}")
            
            # 详细的结果检查
            if "error" in result:
                logger.error(f"解析失败: {result['error']}")
                return {
                    "error": result["error"],
                    "artifacts": [{"parts": [{"type": "text", "text": json.dumps({"error": result["error"]}, ensure_ascii=False)}]}],
                    "status": {"state": TaskState.FAILED}
                }
                
            if not result.get("content"):
                # 如果MCP返回为空，直接使用文件内容
                logger.warning("MCP解析结果为空，使用原始文件内容")
                result = {
                    "content": file_content,
                    "format": os.path.splitext(file_path)[1][1:].lower()
                }
            
            logger.info(f"成功解析文件，内容长度: {len(result.get('content', ''))}")
            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
            
        except Exception as e:
            logger.error(f"处理失败：{str(e)}")
            return {
                "error": f"处理失败：{str(e)}",
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({"error": f"处理失败：{str(e)}"}, ensure_ascii=False)}]}],
                "status": {"state": TaskState.FAILED}
            }

class DocumentHighlighterAgent(BaseAgent):
    """文档高亮Agent"""
    def __init__(self):
        card = AgentCard(
            name="Document Highlighter Agent",
            description="文档高亮处理专家",
            url=f"http://localhost:{HIGHLIGHTER_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Document Highlighting",
                    description="根据审查结果生成高亮版本的文档"
                )
            ]
        )
        super().__init__(card)

    def _process_content(self, content):
        file_path = content.get("file_path", "")
        issues = content.get("issues", [])
        
        if not file_path or not issues:
            return {
                "error": "请提供文件路径和问题列表",
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                    "error": "请提供文件路径和问题列表",
                    "content": None
                }, ensure_ascii=False)}]}],
                "status": {"state": TaskState.FAILED}
            }

        try:
            # 获取文件扩展名
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # 如果是TXT文件，创建一个新的DOCX文件
            if file_ext == '.txt':
                try:
                    # 读取TXT文件内容
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 创建临时DOCX文件
                    from docx import Document
                    doc = Document()
                    doc.add_paragraph(content)
                    temp_docx = os.path.splitext(file_path)[0] + '_temp.docx'
                    doc.save(temp_docx)
                    
                    # 更新文件路径
                    file_path = temp_docx
                    logger.info(f"已将TXT文件转换为DOCX: {temp_docx}")
                except Exception as e:
                    logger.error(f"转换TXT文件失败: {str(e)}")
                    return {
                        "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                            "error": f"转换TXT文件失败: {str(e)}",
                            "content": None
                        }, ensure_ascii=False)}]}],
                        "status": {"state": TaskState.FAILED}
                    }

            # 调用MCP的highlight_contract工具
            result = self._call_mcp_tool("highlight_contract", {
                "original_path": file_path,
                "issues": issues
            })
            
            # 如果是临时文件，清理它
            if file_ext == '.txt' and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info("已清理临时DOCX文件")
                except:
                    logger.warning("清理临时DOCX文件失败")

            if "error" in result:
                return {
                    "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                        "error": result["error"],
                        "content": None
                    }, ensure_ascii=False)}]}],
                    "status": {"state": TaskState.FAILED}
                }

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                    "error": None,
                    "content": result
                }, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
            
        except Exception as e:
            logger.error(f"高亮处理失败: {str(e)}")
            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                    "error": str(e),
                    "content": None
                }, ensure_ascii=False)}]}],
                "status": {"state": TaskState.FAILED}
            }

class IntegrationAgent(BaseAgent):
    """整合分析Agent"""
    def __init__(self):
        card = AgentCard(
            name="Integration Analysis Agent",
            description="整合分析专家",
            url=f"http://localhost:{INTEGRATION_PORT}",
            version="1.0.0",
            skills=[
                AgentSkill(
                    name="Risk Integration",
                    description="整合各专业Agent的分析结果，生成综合报告"
                )
            ]
        )
        super().__init__(card)

    def _calculate_risk_score(self, issues: list) -> float:
        """计算风险分数（0-100，分数越高风险越大）"""
        if not issues:
            return 0.0
            
        # 风险权重
        weights = {
            "高": 1.0,
            "中": 0.6,
            "低": 0.3
        }
        
        # 类型权重
        type_weights = {
            "法律风险": 1.0,
            "商业风险": 0.8,
            "格式问题": 0.5
        }
        
        total_score = 0
        max_possible_score = 0
        
        for issue in issues:
            risk_weight = weights.get(issue.get("风险等级", "低"), 0.3)
            type_weight = type_weights.get(issue.get("类型", "").split()[0], 0.5)
            
            # 计算该问题的风险分数
            issue_score = risk_weight * type_weight * 100
            
            total_score += issue_score
            max_possible_score += 100  # 最高可能分数
        
        # 归一化到0-100范围
        if max_possible_score > 0:
            final_score = (total_score / max_possible_score) * 100
            return round(final_score, 2)
        return 0.0

    def _generate_risk_analysis(self, issues: list) -> dict:
        """生成风险分析报告"""
        # 按风险等级和类型分类
        categorized_issues = {
            "法律风险": {"高": [], "中": [], "低": []},
            "商业风险": {"高": [], "中": [], "低": []},
            "格式问题": {"高": [], "中": [], "低": []}
        }
        
        # 统计信息
        stats = {
            "total": len(issues),
            "by_level": {"高": 0, "中": 0, "低": 0},
            "by_type": {"法律风险": 0, "商业风险": 0, "格式问题": 0},
            "illegal": 0      # 违法条款数
        }
        
        # 分类统计
        for issue in issues:
            risk_type = issue.get("类型", "").split()[0]
            risk_level = issue.get("风险等级", "低")
            
            if risk_type in categorized_issues and risk_level in categorized_issues[risk_type]:
                categorized_issues[risk_type][risk_level].append(issue)
                
            # 更新统计
            stats["by_level"][risk_level] = stats["by_level"].get(risk_level, 0) + 1
            stats["by_type"][risk_type] = stats["by_type"].get(risk_type, 0) + 1
                
            # 检查是否违法
            if "违法" in issue.get("类型", "") or "违规" in issue.get("类型", ""):
                stats["illegal"] += 1
        
        # 计算总体风险分数
        risk_score = self._calculate_risk_score(issues)
        
        # 生成风险等级
        risk_level = "高" if risk_score >= 70 else "中" if risk_score >= 40 else "低"
        
        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "statistics": stats,
            "categorized_issues": categorized_issues,
            "key_concerns": self._identify_key_concerns(issues)
        }

    def _identify_key_concerns(self, issues: list) -> list:
        """识别关键问题"""
        key_concerns = []
        
        # 识别所有高风险问题
        high_risks = [issue for issue in issues if issue.get("风险等级") == "高"]
        
        # 识别违法/违规条款
        illegal_issues = [issue for issue in issues 
                        if "违法" in issue.get("类型", "") or "违规" in issue.get("类型", "")]
        
        # 添加关键问题
        if illegal_issues:
            key_concerns.append({
                "type": "违法/违规问题",
                "issues": illegal_issues
            })
            
        if high_risks:
            key_concerns.append({
                "type": "高风险问题",
                "issues": high_risks
            })
            
        return key_concerns


    def _process_content(self, content):
        """处理输入内容"""
        try:
            issues = content.get("issues", [])
            original_text = content.get("text", "")
            
            if not issues:
                return {
                    "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                        "error": "未找到需要分析的问题",
                        "risk_score": 0,
                        "risk_level": "低",
                        "analysis": None
                    }, ensure_ascii=False)}]}],
                    "status": {"state": TaskState.COMPLETED}
                }

            # 生成整合分析的系统提示
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
            
            # 准备用户输入内容
            user_content = {
                "合同文本": original_text,
                "问题列表": issues
            }
            
            # 调用大模型进行分析
            result = self._call_llm(system_prompt, json.dumps(user_content, ensure_ascii=False))
            
            try:
                analysis_report = json.loads(result['content'])
                if isinstance(analysis_report, list):
                    analysis_report = analysis_report[0]
            except:
                logger.error("解析整合分析结果失败")
                analysis_report = None

            return {
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps(analysis_report, ensure_ascii=False)}]}],
                "status": {"state": TaskState.COMPLETED}
            }
            
        except Exception as e:
            logger.error(f"整合分析失败: {str(e)}")
            return {
                "error": str(e),
                "artifacts": [{"parts": [{"type": "text", "text": json.dumps({
                    "error": f"分析失败: {str(e)}",
                    "risk_score": 0,
                    "risk_level": "未知",
                    "analysis": None
                }, ensure_ascii=False)}]}],
                "status": {"state": TaskState.FAILED}
            }


def _llm_sanity_check():
    try:
        resp = llm_client.chat.completions.create(
            messages=[{'role':'user','content':'请返回成功这个词语，不用解释返回就行'}],
            model='default',
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        print("LLM OK. Raw:", resp.choices[0].message.content)
    except Exception as e:
        print("LLM BAD:", e)

def check_environment():
    """检查运行环境"""
    # 检查MCP服务
    try:
        response = requests.get(f"{MCP_SERVER_URL}/health")
        if response.status_code != 200:
            logger.error("MCP服务未正常运行")
            return False
    except:
        logger.error("无法连接到MCP服务")
        return False
    
    # 检查工作目录权限
    try:
        test_file = "test_permissions.tmp"
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except:
        logger.error("当前目录没有写入权限")
        return False
    _llm_sanity_check()
    return True

def run_all_agents():
    """启动所有Agent"""
    import multiprocessing
    import sys
    import time
    
    # 定义所有Agent及其端口
    agents = {
        "coordinator": (ContractCoordinator, COORDINATOR_PORT),
        "legal": (LegalAgent, LEGAL_PORT),
        "business": (BusinessAgent, BUSINESS_PORT),
        "format": (FormatAgent, FORMAT_PORT),
        "processor": (DocumentProcessorAgent, PROCESSOR_PORT),
        "highlighter": (DocumentHighlighterAgent, HIGHLIGHTER_PORT),
        "integrator": (IntegrationAgent, INTEGRATION_PORT)
    }
    
    processes = []
    try:
        # 启动每个Agent
        for agent_name, (agent_class, port) in agents.items():
            process = multiprocessing.Process(
                target=run_agent,
                args=(agent_class, port),
                name=agent_name
            )
            process.start()
            processes.append(process)
            logger.info(f"启动 {agent_name} Agent，端口: {port}")
            time.sleep(2)  # 给每个Agent一些启动时间
        
        # 等待所有进程
        while True:
            for process in processes:
                if not process.is_alive():
                    logger.error(f"{process.name} Agent已停止运行")
                    # 重启进程
                    agent_name = process.name
                    agent_class, port = agents[agent_name]
                    new_process = multiprocessing.Process(
                        target=run_agent,
                        args=(agent_class, port),
                        name=agent_name
                    )
                    new_process.start()
                    processes.remove(process)
                    processes.append(new_process)
                    logger.info(f"重启 {agent_name} Agent")
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("\n正在关闭所有Agent...")
        for process in processes:
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
        logger.info("所有Agent已关闭")

def run_agent(agent_class, port):
    """运行单个Agent"""
    import uvicorn
    try:
        agent = agent_class()
        uvicorn.run(
            agent.app,
            host="0.0.0.0",
            port=port,
            log_level="info"
        )
    except Exception as e:
        logger.error(f"Agent启动失败: {str(e)}")
        raise

if __name__ == "__main__":
    if not check_environment():
        logger.error("环境检查失败，程序退出")
        sys.exit(1)
    
    import argparse
    parser = argparse.ArgumentParser(description="启动合同审查Agent")
    parser.add_argument("agent_type", 
                       choices=["coordinator", "legal", "business", "format", 
                               "processor", "highlighter", "integrator", "all"],
                       help="要启动的Agent类型")
    args = parser.parse_args()

    if args.agent_type == "all":
        run_all_agents()
    else:
        agent_map = {
            "coordinator": (ContractCoordinator, COORDINATOR_PORT),
            "legal": (LegalAgent, LEGAL_PORT),
            "business": (BusinessAgent, BUSINESS_PORT),
            "format": (FormatAgent, FORMAT_PORT),
            "processor": (DocumentProcessorAgent, PROCESSOR_PORT),
            "highlighter": (DocumentHighlighterAgent, HIGHLIGHTER_PORT),
            "integrator": (IntegrationAgent, INTEGRATION_PORT)
        }

        agent_class, port = agent_map[args.agent_type]
        run_agent(agent_class, port) 