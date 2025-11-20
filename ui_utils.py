# ui_utils.py

import os
import json
import tempfile
import streamlit as st
from typing import Dict, List, Optional, Any, Tuple
import hashlib


def compute_file_md5(file_path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    计算文件内容的 MD5 值。

    Args:
        file_path: 文件路径
        chunk_size: 读取块大小，默认 1MB

    Returns:
        32 位十六进制 MD5 字符串，若文件不存在或读取失败则返回 None
    """
    if not file_path:
        return None

    try:
        if not os.path.exists(file_path):
            return None

        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()
    except Exception:
        return None


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
    if "loaded_from_history" not in st.session_state:
        st.session_state.loaded_from_history = False
    if "ocr_parse_result" not in st.session_state:
        # 用于右侧对照面板的在线解析结果缓存
        st.session_state.ocr_parse_result = None
    if "ocr_parsed_file_path" not in st.session_state:
        # 记录上次OCR解析的文件路径，用于检查文件是否切换
        st.session_state.ocr_parsed_file_path = None
    if "ocr_parsed_original_file_name" not in st.session_state:
        # 记录上次OCR解析对应的原始文件名，便于比较
        st.session_state.ocr_parsed_original_file_name = None
    if "ocr_parsed_file_hash" not in st.session_state:
        # 记录上次OCR解析对应的文件内容哈希，优先用于判断是否同一文件
        st.session_state.ocr_parsed_file_hash = None
    if "view_mode" not in st.session_state:
        # preview: 预览界面；analysis: 分析结果界面
        st.session_state.view_mode = "preview"
    if "llm_api_base_url" not in st.session_state:
        st.session_state.llm_api_base_url = os.getenv("LLM_API_BASE_URL", "")
    if "llm_api_key" not in st.session_state:
        st.session_state.llm_api_key = os.getenv("LLM_API_KEY", "")
    if "ocr_api_url" not in st.session_state:
        st.session_state.ocr_api_url = os.getenv("OCR_API_URL", "")
    if "ocr_api_token" not in st.session_state:
        st.session_state.ocr_api_token = os.getenv("OCR_API_TOKEN", "")
    if "skip_uploaded_file_once" not in st.session_state:
        st.session_state.skip_uploaded_file_once = False
    if "file_hash" not in st.session_state:
        st.session_state.file_hash = None


def load_latest_result_by_filename(
    file_name: str,
    file_path: Optional[str] = None,
    file_hash: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """根据文件内容哈希加载该文件的最新分析结果。

    参数中的 file_name 保留向后兼容，但匹配完全依赖 file_hash。
    """
    results_dir = "contract_analysis_results"
    if not os.path.exists(results_dir):
        return None

    content_hash = file_hash
    if not content_hash and file_path:
        content_hash = compute_file_md5(file_path)

    if not content_hash:
        return None

    candidates: List[Dict[str, Any]] = []
    for fname in os.listdir(results_dir):
        if not fname.lower().endswith(".json"):
            continue
        fpath = os.path.join(results_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 匹配逻辑
            match = False
            saved_content_hash = data.get("file_content_hash")
            if isinstance(saved_content_hash, str) and saved_content_hash == content_hash:
                match = True

            if match:
                # 以 processing_time 为主，退化到文件名时间戳排序
                ts = data.get("processing_time")
                candidates.append(
                    {
                        "_ts": float(ts) if isinstance(ts, (int, float)) else 0.0,
                        "_path": fpath,
                        "data": data,
                    }
                )
        except Exception:
            continue

    if not candidates:
        return None

    def extract_name_ts(p: str) -> float:
        base = os.path.basename(p)
        # 形如 contract_analysis_YYYYmmdd_HHMMSS.json
        try:
            stem = os.path.splitext(base)[0]
            parts = stem.split("_")
            if len(parts) >= 3:
                dt = parts[-2] + parts[-1]  # YYYYmmdd + HHMMSS
                # 转换为结构化时间
                import datetime

                d = datetime.datetime.strptime(dt, "%Y%m%d%H%M%S")
                return d.timestamp()
        except Exception:
            pass
        return 0.0

    for c in candidates:
        if not c["_ts"]:
            c["_ts"] = extract_name_ts(c["_path"]) or 0.0

    candidates.sort(key=lambda x: x["_ts"], reverse=True)
    return candidates[0]["data"]


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


def get_cache_file_paths(
    file_path: str,
    original_file_name: Optional[str] = None,
    file_hash: Optional[str] = None,
) -> Tuple[str, str]:
    """根据文件路径生成缓存文件路径（json和md）

    优先使用原始文件名（original_file_name），如果没有则使用文件路径中的文件名。
    使用PDF文件名（去掉扩展名）作为基础名称，便于与PDF对应。
    附加文件内容的短哈希，避免不同版本互相覆盖。
    如果文件名包含特殊字符，会进行清理以确保文件系统兼容性。
    """
    import re

    if original_file_name:
        base_name = os.path.splitext(original_file_name)[0]
    else:
        base_name = os.path.splitext(os.path.basename(file_path))[0]

    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]", "_", base_name)
    safe_name = re.sub(r"_+", "_", safe_name)
    safe_name = safe_name.strip("_")

    if not safe_name:
        safe_name = "unnamed_file"

    content_hash = file_hash or compute_file_md5(file_path)
    if content_hash:
        safe_name = f"{safe_name}_{content_hash[:12]}"
    else:
        abs_path = os.path.abspath(file_path)
        path_hash = hashlib.md5(abs_path.encode("utf-8")).hexdigest()[:8]
        safe_name = f"{safe_name}_{path_hash}"

    json_path = os.path.join("jsons", f"{safe_name}.json")
    md_path = os.path.join("mds", f"{safe_name}.md")

    return json_path, md_path


def load_cached_parse_result(
    file_path: str, original_file_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """从缓存加载解析结果"""
    file_hash = compute_file_md5(file_path)
    json_path, md_path = get_cache_file_paths(
        file_path, original_file_name, file_hash=file_hash
    )

    if os.path.exists(json_path) and os.path.exists(md_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_result = json.load(f)
            with open(md_path, "r", encoding="utf-8") as f:
                markdown_text = f.read()

            return {
                "json_result": json_result,
                "markdown_text": markdown_text,
                "raw_text": preview_file_content(file_path),
                "_cached": True,
            }
        except Exception as e:
            print(f"加载缓存失败: {e}")

    return None


def save_parse_result(
    file_path: str,
    json_result: Dict[str, Any],
    markdown_text: str,
    original_file_name: Optional[str] = None,
):
    """保存解析结果到缓存文件"""
    file_hash = compute_file_md5(file_path)
    json_path, md_path = get_cache_file_paths(
        file_path, original_file_name, file_hash=file_hash
    )

    os.makedirs("jsons", exist_ok=True)
    os.makedirs("mds", exist_ok=True)

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_result, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
        print(f"已保存解析结果: {json_path}, {md_path}")
    except Exception as e:
        print(f"保存解析结果失败: {e}")
