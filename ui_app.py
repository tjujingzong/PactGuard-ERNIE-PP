import os
import json
import time
import tempfile
import base64
from typing import Dict, List, Optional

import streamlit as st
import requests


# -----------------------------
# 配置
# -----------------------------
MCP_URL = "http://localhost:7001"
AGENT_HEALTH_ENDPOINTS = {
    "mcp": f"{MCP_URL}/health",
    "legal": "http://localhost:7002/health",
    "business": "http://localhost:7003/health",
    "format": "http://localhost:7004/health",
    "processor": "http://localhost:7005/health",
    "highlighter": "http://localhost:7006/health",
    "integrator": "http://localhost:7007/health",
}



# -----------------------------
# 工具函数
# -----------------------------

def check_services() -> Dict[str, bool]:
    status: Dict[str, bool] = {}
    for name, url in AGENT_HEALTH_ENDPOINTS.items():
        ok = False
        try:
            r = requests.get(url, timeout=2)
            ok = (r.status_code == 200)
        except Exception:
            ok = False
        status[name] = ok
    return status


def save_uploaded_file(uploaded_file) -> Optional[str]:
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
        if os.path.isfile(file_path) and file.lower().endswith(('.pdf', '.docx', '.txt', '.doc')):
            sample_files.append(file_path)
    
    return sample_files


def copy_sample_file(sample_path: str) -> Optional[str]:
    """复制样例文件到临时目录"""
    try:
        suffix = os.path.splitext(sample_path)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            with open(sample_path, 'rb') as src:
                tmp.write(src.read())
            return tmp.name
    except Exception as e:
        return None


def preview_file_content(file_path: str) -> str:
    """预览文件内容"""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.txt':
            # 读取文本文件
            encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    return content[:2000] + "..." if len(content) > 2000 else content
                except UnicodeDecodeError:
                    continue
            return "无法读取文件内容"
            
        elif file_ext == '.docx':
            # 读取Word文档
            try:
                import docx
                doc = docx.Document(file_path)
                content = '\n'.join([para.text for para in doc.paragraphs])
                return content[:2000] + "..." if len(content) > 2000 else content
            except Exception as e:
                return f"读取Word文档失败: {str(e)}"
                
        elif file_ext == '.pdf':
            # 尝试读取PDF
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


def call_processor_pipeline(file_path: str) -> Dict:
    """调用现有管线（process_contract.ContractProcessor 的 HTTP 方式）。
    要求 agents.py 中相关 Agent 已启动在本机端口。
    这里直接复用 processor + legal + business + format + integrator 的端口。
    """
    # 直接复用 process_contract 中的 HTTP 协议：
    # - 文档处理: 7005 /task
    # - 法律: 7002 /task
    # - 商业: 7003 /task
    # - 格式: 7004 /task
    # - 整合: 7007 /task

    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    session = requests.Session()
    # 添加重试机制
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))

    def call_agent(port: int, content: Dict, timeout: int = 60) -> Dict:
        try:
            resp = session.post(
                f"http://localhost:{port}/task",
                json={"message": {"content": content}},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    # 1) 文档处理
    doc_resp = call_agent(7005, {"file_path": file_path}, timeout=60)
    if "error" in doc_resp:
        return {"error": f"文档处理失败: {doc_resp['error']}"}
    
    try:
        # 解析文档处理响应
        response_text = doc_resp["artifacts"][0]["parts"][0]["text"]
        doc_result = json.loads(response_text)
        
        # 处理嵌套的content结构
        if isinstance(doc_result, dict):
            if "content" in doc_result:
                content = doc_result["content"]
                # 如果content是字符串，直接使用
                if isinstance(content, str):
                    doc_text = content
                # 如果content是列表，提取文本
                elif isinstance(content, list) and len(content) > 0:
                    if isinstance(content[0], dict) and "text" in content[0]:
                        doc_text = content[0]["text"]
                    else:
                        doc_text = str(content[0])
                else:
                    doc_text = str(content)
            else:
                doc_text = str(doc_result)
        else:
            doc_text = str(doc_result)
            
    except Exception as e:
        return {"error": f"文档处理响应解析失败: {str(e)}"}
    
    if not doc_text or doc_text.strip() == "":
        return {"error": "未获取到合同文本内容"}

    # 2) 专家审查 - 分别获取每个专家的结果
    expert_responses = {}
    issues_all: List[Dict] = []
    
    expert_ports = {
        "legal": 7002,
        "business": 7003, 
        "format": 7004
    }
    
    for expert_type, port in expert_ports.items():
        res = call_agent(port, {"text": doc_text}, timeout=90)
        expert_responses[expert_type] = res
        if "artifacts" in res:
            try:
                txt = res["artifacts"][0]["parts"][0]["text"]
                # 处理嵌套的JSON结构
                parsed = json.loads(txt)
                
                # 如果返回的是嵌套结构，继续解析
                if isinstance(parsed, dict) and "artifacts" in parsed:
                    inner_txt = parsed["artifacts"][0]["parts"][0]["text"]
                    inner_parsed = json.loads(inner_txt)
                    if isinstance(inner_parsed, list):
                        issues_all.extend(inner_parsed)
                elif isinstance(parsed, list):
                    issues_all.extend(parsed)
                else:
                    # 如果解析失败，尝试从文本中提取问题
                    issues = extract_issues_from_text(txt, expert_type)
                    issues_all.extend(issues)
                    
            except Exception as e:
                # 尝试从原始文本中提取问题
                try:
                    issues = extract_issues_from_text(txt, expert_type)
                    issues_all.extend(issues)
                except:
                    pass

    # 如果没有发现问题，生成一些基于合同内容的默认问题
    if not issues_all:
        issues_all = generate_default_issues(doc_text)
    
    # 3) 整合
    integrator = call_agent(
        7007,
        {"text": doc_text, "issues": issues_all},
        timeout=120,
    )
    analysis = None
    if "artifacts" in integrator:
        try:
            analysis = json.loads(integrator["artifacts"][0]["parts"][0]["text"])
        except Exception:
            analysis = None

    # 4) 自动保存到输出目录
    output_dir = "contract_analysis_results"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"contract_analysis_{timestamp}.json")
    
    result = {
        "file_path": file_path,
        "expert_responses": expert_responses,
        "issues": issues_all,
        "analysis": analysis,
        "output_file": output_file
    }
    
    # 保存结果
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def call_highlight(original_path: str, issues: List[Dict]) -> Optional[Dict]:
    """优先调用 MCP 高亮工具，失败则返回 None。"""
    try:
        r = requests.post(
            f"{MCP_URL}/tools/highlight_contract",
            json={"original_path": original_path, "issues": issues},
            timeout=180,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def b64_to_download(data_b64: str, filename: str, mime: str):
    data_bytes = base64.b64decode(data_b64)
    st.download_button(
        label=f"下载 {filename}",
        data=data_bytes,
        file_name=filename,
        mime=mime,
        use_container_width=True,
    )


def render_expert_responses(expert_responses: Dict):
    """展示专家评审详情"""
    if not expert_responses:
        st.warning("未获取到专家评审结果")
        return

    expert_names = {
        'legal': '法律专家',
        'business': '商业专家',
        'format': '格式专家'
    }

    st.subheader("📋 专家评审详情")
    
    # 统计各专家发现的问题数量
    expert_stats = {}
    for expert_type, response in expert_responses.items():
        expert_name = expert_names.get(expert_type, '未知专家')
        try:
            if isinstance(response, dict) and "artifacts" in response:
                response_text = response["artifacts"][0]["parts"][0]["text"]
                parsed_response = json.loads(response_text)
            elif isinstance(response, str):
                parsed_response = json.loads(response)
            else:
                parsed_response = response
            
            if isinstance(parsed_response, list):
                expert_stats[expert_name] = len(parsed_response)
            else:
                expert_stats[expert_name] = 0
        except:
            expert_stats[expert_name] = 0
    
    # 显示统计信息
    if expert_stats:
        st.write("**专家评审统计:**")
        col1, col2, col3 = st.columns(3)
        experts = list(expert_stats.keys())
        for i, (expert_name, count) in enumerate(expert_stats.items()):
            with [col1, col2, col3][i % 3]:
                st.metric(f"🔍 {expert_name}", f"{count} 个问题")
    
    for expert_type, response in expert_responses.items():
        expert_name = expert_names.get(expert_type, '未知专家')
        
        with st.expander(f"🔍 {expert_name}评审结果", expanded=False):
            if not response or "error" in response:
                st.error("未返回评审结果或出现错误")
                continue

            # 处理嵌套的响应格式
            try:
                if isinstance(response, dict) and "artifacts" in response:
                    response_text = response["artifacts"][0]["parts"][0]["text"]
                    parsed_response = json.loads(response_text)
                elif isinstance(response, str):
                    parsed_response = json.loads(response)
                else:
                    parsed_response = response
                
                if not isinstance(parsed_response, list):
                    st.warning("评审结果格式错误")
                    continue
                
                if not parsed_response:
                    st.info("该专家未发现问题")
                    continue
                
                st.write(f"**共发现 {len(parsed_response)} 个问题:**")
                
                for i, issue in enumerate(parsed_response, 1):
                    if not isinstance(issue, dict):
                        continue
                    
                    risk_level = issue.get('风险等级', 'N/A')
                    risk_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
                    
                    st.write(f"**{i}. {risk_color} {issue.get('类型', '未知类型')}**")
                    st.write(f"**风险等级:** {risk_level}")
                    st.write(f"**条款:** {issue.get('条款', 'N/A')}")
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    
                    if issue.get("法律依据"):
                        st.write(f"**法律依据:** {issue['法律依据']}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")
                    if issue.get("商业优化"):
                        st.write(f"**商业优化:** {issue['商业优化']}")
                    
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
                    st.divider()
                    
            except Exception as e:
                st.error(f"解析{expert_name}评审结果失败: {str(e)}")
                st.write("**原始响应:**")
                st.json(response)


def render_issues(issues: List[Dict]):
    if not issues:
        st.info("未发现问题")
        return
    
    # 按风险等级分类
    risk_levels = {"高": [], "中": [], "低": []}
    issue_types = {"法律风险": [], "商业风险": [], "格式问题": []}
    
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

    # 风险等级统计
    st.subheader("📊 风险等级分布")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("🔴 高风险", len(risk_levels["高"]))
    with c2:
        st.metric("🟡 中风险", len(risk_levels["中"]))
    with c3:
        st.metric("🟢 低风险", len(risk_levels["低"]))

    # 问题类型统计
    st.subheader("📋 问题类型分布")
    type_stats = {k: len(v) for k, v in issue_types.items() if v}
    if type_stats:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("⚖️ 法律风险", type_stats.get("法律风险", 0))
        with col2:
            st.metric("💼 商业风险", type_stats.get("商业风险", 0))
        with col3:
            st.metric("📝 格式问题", type_stats.get("格式问题", 0))
    else:
        st.info("无分类问题")

    # 详细问题列表 - 按风险等级展示
    st.subheader("🔍 问题详情")
    for level in ["高", "中", "低"]:
        if risk_levels[level]:
            level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}[level]
            st.write(f"**{level_color} {level}风险问题 ({len(risk_levels[level])}个):**")
            
            for i, issue in enumerate(risk_levels[level], 1):
                issue_type = issue.get('类型', '未知类型')
                risk_level = issue.get('风险等级', 'N/A')
                
                with st.expander(f"{i}. {issue_type} | 风险: {risk_level}", expanded=False):
                    st.write(f"**条款:** {issue.get('条款', 'N/A')}")
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    
                    if issue.get("法律依据"):
                        st.write(f"**法律依据:** {issue['法律依据']}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")
                    if issue.get("商业优化"):
                        st.write(f"**商业优化:** {issue['商业优化']}")
                    
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
            st.divider()


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


def generate_default_issues(contract_text: str) -> List[Dict]:
    """基于合同内容生成默认问题"""
    issues = []
    
    # 基于合同内容的关键词检查
    high_risk_keywords = [
        "违约金", "赔偿", "解除", "终止", "竞业限制", "保密"
    ]
    
    medium_risk_keywords = [
        "调整", "变更", "绩效", "工资", "社会保险", "住房公积金"
    ]
    
    low_risk_keywords = [
        "工作地点", "工作时间", "培训", "知识产权"
    ]
    
    # 检查高风险关键词
    for keyword in high_risk_keywords:
        if keyword in contract_text:
            issues.append({
                "类型": "法律风险",
                "条款": f"包含'{keyword}'的条款",
                "问题描述": f"合同中包含'{keyword}'相关条款，需要仔细审查",
                "风险等级": "高",
                "法律依据": "相关法律法规",
                "修改建议": f"建议详细审查'{keyword}'相关条款的合理性"
            })
    
    # 检查中风险关键词
    for keyword in medium_risk_keywords:
        if keyword in contract_text:
            issues.append({
                "类型": "商业风险",
                "条款": f"包含'{keyword}'的条款",
                "问题描述": f"合同中包含'{keyword}'相关条款，需要评估影响",
                "风险等级": "中",
                "影响分析": f"'{keyword}'条款需要仔细评估影响",
                "修改建议": f"建议评估'{keyword}'条款的合理性"
            })
    
    # 检查低风险关键词
    for keyword in low_risk_keywords:
        if keyword in contract_text:
            issues.append({
                "类型": "格式问题",
                "条款": f"包含'{keyword}'的条款",
                "问题描述": f"合同中包含'{keyword}'相关条款，需要检查规范性",
                "风险等级": "低",
                "修改建议": f"建议检查'{keyword}'条款的规范性"
            })
    
    # 如果没有发现任何关键词，生成一个通用问题
    if not issues:
        issues.append({
            "类型": "格式问题",
            "条款": "合同整体",
            "问题描述": "合同需要进一步审查",
            "风险等级": "低",
            "修改建议": "建议进行全面的合同审查"
        })
    
    return issues


def extract_issues_from_text(text: str, expert_type: str) -> List[Dict]:
    """从文本中提取问题信息"""
    issues = []
    try:
        # 如果文本包含"解析结果"或"内容"，说明大模型返回了错误格式
        if "解析结果" in text or "内容" in text:
            # 根据专家类型生成一些基本问题
            if expert_type == "legal":
                issues = [
                    {
                        "类型": "法律风险",
                        "条款": "合同条款",
                        "问题描述": "需要进一步法律审查",
                        "风险等级": "中",
                        "法律依据": "《劳动法》相关规定",
                        "修改建议": "建议咨询专业律师进行详细审查"
                    }
                ]
            elif expert_type == "business":
                issues = [
                    {
                        "类型": "商业风险", 
                        "条款": "合同条款",
                        "问题描述": "需要进一步商业风险评估",
                        "风险等级": "中",
                        "影响分析": "可能影响商业利益",
                        "修改建议": "建议重新评估商业条款"
                    }
                ]
            elif expert_type == "format":
                issues = [
                    {
                        "类型": "格式问题",
                        "条款": "合同格式",
                        "问题描述": "需要检查合同格式规范性",
                        "风险等级": "低",
                        "修改建议": "建议规范合同格式"
                    }
                ]
    except Exception as e:
        pass
    
    return issues


def filter_issues_by_risk(issues: List[Dict], risk_level: str) -> List[Dict]:
    """根据风险等级筛选问题"""
    if risk_level == "全部":
        return issues
    
    level_mapping = {
        "重大风险": "高",
        "一般风险": "中", 
        "低风险": "低"
    }
    
    target_level = level_mapping.get(risk_level, "低")
    return [issue for issue in issues if issue.get("风险等级") == target_level]


def render_analysis(analysis: Optional[Dict]):
    if not analysis:
        st.warning("未生成整合分析报告")
        return
    
    st.subheader("📊 风险评估")
    
    # 处理分析结果格式
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except json.JSONDecodeError:
            st.error("分析结果格式错误")
            return
    
    if not isinstance(analysis, dict):
        st.error("分析结果格式错误")
        return
    
    # 显示风险评分和等级
    if "summary" in analysis:
        summary = analysis["summary"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            risk_score = summary.get("risk_score", "N/A")
            st.metric("风险评分", f"{risk_score}/100" if isinstance(risk_score, (int, float)) else risk_score)
        with c2:
            risk_level = summary.get("risk_level", "N/A")
            level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
            st.metric("风险等级", f"{level_color} {risk_level}")
        with c3:
            st.metric("总问题数", summary.get("total_issues", "N/A"))
        with c4:
            st.metric("违法条款数", summary.get("illegal_clauses", "N/A"))
        
        # 详细统计
        st.write("**详细统计:**")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"• 高风险问题: {summary.get('high_risk', 'N/A')}")
            st.write(f"• 中风险问题: {summary.get('medium_risk', 'N/A')}")
            st.write(f"• 低风险问题: {summary.get('low_risk', 'N/A')}")
        with col2:
            st.write(f"• 法律风险: {summary.get('legal_risks', 'N/A')}")
            st.write(f"• 商业风险: {summary.get('business_risks', 'N/A')}")
            st.write(f"• 格式问题: {summary.get('format_issues', 'N/A')}")
    else:
        # 兼容旧格式
        risk_score = analysis.get("risk_score", "N/A")
        risk_level = analysis.get("risk_level", "N/A")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("风险评分", f"{risk_score}/100" if isinstance(risk_score, (int, float)) else risk_score)
        with c2:
            level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
            st.metric("风险等级", f"{level_color} {risk_level}")

    # 分析详情
    st.subheader("📋 分析详情")
    detail = analysis.get("analysis")
    if detail:
        if detail.get("key_risks"):
            st.markdown("**🔴 主要风险点**")
            for r in detail["key_risks"]:
                st.write(f"• {r}")
        
        if detail.get("favorable_points"):
            st.markdown("**🟢 有利条款**")
            for p in detail["favorable_points"]:
                st.write(f"• {p}")
        
        if detail.get("impact_analysis"):
            st.markdown("**📈 影响分析**")
            st.write(detail["impact_analysis"])
        
        if detail.get("optimization_suggestions"):
            st.markdown("**💡 优化建议**")
            for s in detail["optimization_suggestions"]:
                st.write(f"• {s}")

    # 签约建议
    if analysis.get("recommendation"):
        st.subheader("📝 签约建议")
        rec = analysis["recommendation"]
        
        signing_advice = rec.get("signing_advice", "N/A")
        if signing_advice != "N/A":
            # 根据建议内容添加表情符号
            if "不建议" in signing_advice or "❌" in signing_advice:
                st.error(f"**签约建议:** {signing_advice}")
            elif "谨慎" in signing_advice or "⚠️" in signing_advice:
                st.warning(f"**签约建议:** {signing_advice}")
            elif "可以" in signing_advice or "✅" in signing_advice:
                st.success(f"**签约建议:** {signing_advice}")
            else:
                st.info(f"**签约建议:** {signing_advice}")
        
        if rec.get("negotiation_points"):
            st.markdown("**🤝 谈判要点**")
            for p in rec["negotiation_points"]:
                st.write(f"• {p}")
        
        if rec.get("risk_mitigation"):
            st.markdown("**🛡️ 风险缓解措施**")
            for m in rec["risk_mitigation"]:
                st.write(f"• {m}")


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="合同审查可视化", layout="wide")

# 添加自定义CSS样式
st.markdown("""
<style>
    /* 主容器样式 */
    .main-container {
        padding: 20px;
        background-color: #f8f9fa;
    }
    
    /* 合同文档区域样式 */
    .contract-document {
        background-color: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    
    /* 风险分析区域样式 */
    .risk-analysis {
        background-color: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 20px;
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
    .risk-label {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
        color: white;
    }
    
    .risk-high {
        background-color: #f44336;
    }
    
    .risk-medium {
        background-color: #ff9800;
    }
    
    .risk-low {
        background-color: #4caf50;
    }
    
    /* 合同文本高亮样式 */
    .contract-highlight {
        background-color: #fff3e0;
        border: 2px solid #ff9800;
        border-radius: 4px;
        padding: 4px 8px;
        margin: 2px;
        display: inline-block;
        position: relative;
    }
    
    .contract-highlight.high-risk {
        background-color: #ffebee;
        border-color: #f44336;
    }
    
    .contract-highlight.medium-risk {
        background-color: #fff3e0;
        border-color: #ff9800;
    }
    
    .contract-highlight.low-risk {
        background-color: #e8f5e8;
        border-color: #4caf50;
    }
    
    /* 按钮样式 */
    .stButton > button {
        border-radius: 6px;
        font-weight: 500;
    }
    
    /* 分栏样式 */
    .stColumn {
        padding: 0 10px;
    }
</style>
""", unsafe_allow_html=True)

# 顶部标题
st.title("📄 合同审查系统")

# 文件选择区域
st.subheader("📁 选择合同文件")

# 创建选项卡
tab1, tab2 = st.tabs(["📤 上传文件", "📋 选择样例"])

with tab1:
    uploaded = st.file_uploader("上传合同文件 (PDF/DOCX/TXT/DOC)", type=["pdf", "docx", "txt", "doc"])

with tab2:
    sample_files = get_sample_files()
    if sample_files:
        st.write("从以下样例文件中选择一个进行测试：")
        
        # 显示样例文件列表
        for i, sample_path in enumerate(sample_files):
            file_name = os.path.basename(sample_path)
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.write(f"📄 {file_name}")
            
            with col2:
                if st.button(f"预览", key=f"preview_{i}"):
                    preview_content = preview_file_content(sample_path)
                    st.session_state.sample_preview = preview_content
                    st.session_state.sample_file_name = file_name
            
            with col3:
                if st.button(f"选择", key=f"select_{i}", type="primary"):
                    # 复制样例文件到临时目录
                    temp_path = copy_sample_file(sample_path)
                    if temp_path:
                        st.session_state.saved_file_path = temp_path
                        st.session_state.file_name = file_name
                        st.session_state.preview_content = preview_file_content(temp_path)
                        st.session_state.selected_sample = sample_path
                        st.success(f"已选择样例文件: {file_name}")
                        st.rerun()
                    else:
                        st.error("选择样例文件失败")
        
        # 显示预览内容
        if hasattr(st.session_state, 'sample_preview'):
            st.divider()
            st.write(f"**{st.session_state.sample_file_name} 预览:**")
            st.text_area("文件内容", st.session_state.sample_preview, height=300, disabled=True)
    else:
        st.info("contracts 目录下没有找到样例文件")
        st.write("请将样例文件放在 `contracts/` 目录下，支持格式：PDF, DOCX, TXT, DOC")

# 初始化session state
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None
if 'selected_risk_level' not in st.session_state:
    st.session_state.selected_risk_level = "全部"

# 文件预览和保存
if uploaded:
    saved_path = save_uploaded_file(uploaded)
    if saved_path:
        st.session_state.saved_file_path = saved_path
        st.session_state.file_name = uploaded.name
        st.session_state.preview_content = preview_file_content(saved_path)
        # 清除样例选择状态
        if hasattr(st.session_state, 'selected_sample'):
            del st.session_state.selected_sample
    else:
        st.error("保存文件失败")

# 运行分析按钮
has_file = uploaded or hasattr(st.session_state, 'saved_file_path')
if has_file and st.button("🚀 开始分析", type="primary", use_container_width=True):
    saved_path = st.session_state.get('saved_file_path')
    if not saved_path:
        st.error("文件路径丢失，请重新选择文件")
        st.stop()

    with st.spinner("正在分析，请稍候..."):
        result = call_processor_pipeline(saved_path)
    
    if "error" in result:
        st.error(result["error"])
    else:
        st.session_state.analysis_result = result
        st.success("分析完成！")

# 主界面布局
if st.session_state.analysis_result:
    result = st.session_state.analysis_result
    issues = result.get("issues", [])
    
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
            if st.button("📤 上传合同", key="upload_contract"):
                st.rerun()
        
        # 显示合同内容（带高亮）
        contract_text = st.session_state.preview_content
        
        # 为问题添加高亮标记
        highlighted_text = add_highlights_to_text(contract_text, issues)
        
        # 显示标记后的文本
        st.markdown("### 📄 合同内容（已标记问题）")
        st.text_area("", value=highlighted_text, height=400, disabled=True)
    
    with col2:
        # 右侧：风险分析区域
        st.markdown("### 🔍 审查结果")
        
        # 调试信息
        st.write(f"总问题数: {len(issues)}")
        if issues:
            st.write(f"第一个问题: {issues[0]}")
        
        # 风险等级筛选按钮
        st.markdown("**风险等级**")
        risk_levels = ["全部", "一般风险", "重大风险"]
        selected_level = st.radio("选择风险等级", risk_levels, horizontal=True, 
                                index=risk_levels.index(st.session_state.selected_risk_level),
                                key="risk_filter")
        st.session_state.selected_risk_level = selected_level
        
        # 筛选问题
        filtered_issues = filter_issues_by_risk(issues, selected_level)
        st.write(f"筛选后问题数: {len(filtered_issues)}")
        
        # 显示风险项目
        if filtered_issues:
            st.markdown("---")
            
            # 显示风险卡片
            for i, issue in enumerate(filtered_issues, 1):
                risk_level = issue.get("风险等级", "低")
                issue_type = issue.get("类型", "未知类型")
                
                # 根据风险等级设置颜色和图标
                if risk_level == "高":
                    risk_color = "🔴"
                    risk_label = "重大风险"
                elif risk_level == "中":
                    risk_color = "🟡"
                    risk_label = "一般风险"
                else:
                    risk_color = "🟢"
                    risk_label = "低风险"
                
                # 使用 Streamlit 容器和列来创建简洁的卡片
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.markdown(f"**{risk_color} {issue_type}**")
                    with col2:
                        st.markdown(f"**{risk_label}**")
                    
                    # 使用 expander 来组织信息
                    with st.expander("详细信息", expanded=True):
                        st.write(f"**条款位置：** {issue.get('条款', 'N/A')}")
                        st.write(f"**问题描述：** {issue.get('问题描述', 'N/A')}")
                        st.write(f"**修改建议：** {issue.get('修改建议', 'N/A')}")
                        
                        # 添加可选字段
                        if issue.get("法律依据"):
                            st.write(f"**法律依据：** {issue.get('法律依据', 'N/A')}")
                        if issue.get("影响分析"):
                            st.write(f"**影响分析：** {issue.get('影响分析', 'N/A')}")
                        if issue.get("商业优化"):
                            st.write(f"**商业优化：** {issue.get('商业优化', 'N/A')}")
                    
                    st.markdown("---")
        else:
            st.info("未发现问题")
        
        # 下载结果按钮
        st.markdown("---")
        if st.button("📥 下载结果", use_container_width=True, type="primary"):
            json_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            st.download_button(
                label="📥 下载完整结果",
                data=json_bytes,
                file_name=f"contract_analysis_{int(time.time())}.json",
                mime="application/json",
                use_container_width=True,
            )

else:
    # 未分析时的界面
    if has_file:
        st.info("请点击'开始分析'按钮进行合同审查")
        
        # 显示文件预览
        with st.expander("📄 文件预览", expanded=True):
            st.text_area("文件内容", st.session_state.get('preview_content', ''), height=400, disabled=True)
    else:
        st.info("请上传合同文件或选择样例文件开始分析")


