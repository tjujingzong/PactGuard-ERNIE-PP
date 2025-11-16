# mcp_service.py

from python_a2a.mcp import FastMCP, text_response, create_fastapi_app
import uvicorn
from docx import Document
from pdfminer.high_level import extract_text
import fitz
import os
import re
from tempfile import NamedTemporaryFile
from paddleocr import PaddleOCR
import logging
from typing import List, Dict
import platform
import base64

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("DocProcessor")

contract_mcp = FastMCP(
    name="Contract Processing Tools", description="合同审查专用工具集", version="1.0.0"
)

try:
    ocr = PaddleOCR(
        use_angle_cls=True,  # 使用方向分类器
        lang="ch",  # 中文模型
        enable_mkldnn=True,  # 启用MKL-DNN加速
    )
    logger.info("PaddleOCR初始化成功")
except Exception as e:
    logger.error(f"PaddleOCR初始化失败: {e}")
    ocr = None


def _detect_file_type(file_path: str) -> str:
    """检测文件类型"""
    return os.path.splitext(file_path)[1].lower()[1:]


def _preprocess_text(text: str) -> str:
    """文本预处理"""
    text = re.sub(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("　", " ")
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


@contract_mcp.tool(name="parse_contract", description="解析合同文件获取文本内容")
def parse_contract(file_path: str):
    """解析合同文件（支持PDF/DOCX/TXT/DOC）"""
    file_type = _detect_file_type(file_path)
    logger.info(f"开始处理文件: {file_path}，类型: {file_type}")

    try:
        if file_type == "pdf":
            text = _parse_pdf(file_path)
        elif file_type == "docx":
            text = _parse_docx(file_path)
        elif file_type == "doc":
            text = _parse_doc(file_path)
        elif file_type == "txt":
            text = _parse_txt(file_path)
        else:
            return {"error": f"不支持的文件格式: {file_type}"}

        if isinstance(text, dict) and "error" in text:
            return text

        return {"content": text}
    except Exception as e:
        logger.error(f"解析失败：{str(e)}")
        return {"error": f"解析失败：{str(e)}"}


def _parse_pdf(file_path: str):
    """处理PDF文件，支持OCR"""
    try:
        logger.info("尝试直接提取PDF文本...")
        text = extract_text(file_path)

        if not text or text.isspace():
            logger.info("直接提取文本失败，尝试使用OCR处理...")

            if ocr is None:
                logger.error("OCR服务不可用")
                return text_response("OCR服务不可用，无法处理扫描版PDF文件")

            doc = fitz.open(file_path)
            text_parts = []

            for page_num in range(doc.page_count):
                page = doc[page_num]
                pix = page.get_pixmap()
                img_path = f"temp_page_{page_num}.png"
                pix.save(img_path)

                try:
                    result = ocr.ocr(img_path, cls=True)
                    if result and result[0]:
                        page_text = "\n".join([line[1][0] for line in result[0]])
                        text_parts.append(page_text)
                except Exception as e:
                    logger.error(f"OCR处理第{page_num+1}页时失败: {e}")
                finally:
                    if os.path.exists(img_path):
                        os.remove(img_path)

            doc.close()
            text = "\n\n".join(text_parts)

            if not text or text.isspace():
                logger.warning(f"OCR处理后文本仍为空: {file_path}")
                return text_response(
                    "OCR处理后文本仍为空，请检查PDF文件是否包含可识别的文本"
                )

            logger.info(f"OCR处理成功，提取文本长度: {len(text)} 字符")
        else:
            logger.info(f"成功直接提取PDF文本，长度: {len(text)} 字符")

        processed_text = _preprocess_text(text)
        logger.info(f"文本预处理后长度: {len(processed_text)} 字符")

        return text_response(processed_text)

    except Exception as e:
        logger.error(f"处理PDF文件时发生错误: {file_path}")
        logger.error(f"错误信息: {str(e)}")
        return text_response(f"处理PDF失败：{str(e)}")


def _parse_docx(file_path: str):
    """处理Word文档"""
    try:
        logger.info(f"处理Word文档: {file_path}")
        doc = Document(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        processed_text = _preprocess_text(text)
        logger.info(f"Word文档处理完成，文本长度: {len(processed_text)} 字符")

        return text_response(processed_text)
    except Exception as e:
        logger.error(f"处理Word文档失败: {file_path}")
        logger.error(f"错误信息: {str(e)}")
        return text_response(f"处理Word文档失败：{str(e)}")


def _parse_doc(file_path: str):
    """处理旧版Word文档（.doc）"""
    try:
        logger.info(f"处理旧版Word文档: {file_path}")

        if platform.system() != "Windows":
            return text_response("处理.doc文件需要Windows系统环境")

        import win32com.client

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(file_path)
        text = doc.Content.Text
        doc.Close()
        word.Quit()

        processed_text = _preprocess_text(text)
        logger.info(f"旧版Word文档处理完成，文本长度: {len(processed_text)} 字符")

        return text_response(processed_text)
    except Exception as e:
        logger.error(f"处理旧版Word文档失败: {file_path}")
        logger.error(f"错误信息: {str(e)}")
        return text_response(f"处理旧版Word文档失败：{str(e)}")


def _parse_txt(file_path: str):
    """处理文本文件"""
    try:
        logger.info(f"处理文本文件: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            encodings = ["gbk", "gb2312", "latin-1"]
            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        text = f.read()
                    logger.info(f"使用 {encoding} 编码成功处理文件")
                    break
                except UnicodeDecodeError:
                    continue
            else:
                logger.error(f"无法解码文件 {file_path}")
                return text_response(f"无法解码文件: {file_path}")

        processed_text = _preprocess_text(text)
        logger.info(f"文本文件处理完成，文本长度: {len(processed_text)} 字符")

        return text_response(processed_text)
    except Exception as e:
        logger.error(f"处理文本文件失败: {file_path}")
        logger.error(f"错误信息: {str(e)}")
        return text_response(f"处理文本文件失败：{str(e)}")


@contract_mcp.tool(name="highlight_contract", description="生成带高亮的合同文件")
def highlight_contract(original_path: str, issues: List[Dict]):
    """生成高亮PDF/Word文件"""
    file_type = _detect_file_type(original_path)
    logger.info(f"开始生成高亮文件: {original_path}，类型: {file_type}")

    try:
        if file_type == "pdf":
            result = _highlight_pdf(original_path, issues)
        elif file_type == "docx":
            result = _highlight_docx(original_path, issues)
        else:
            return {"error": f"不支持的文件格式: {file_type}，仅支持PDF和DOCX"}

        if isinstance(result, dict) and "error" in result:
            return result

        return result
    except Exception as e:
        logger.error(f"高亮生成失败：{str(e)}")
        return {"error": f"高亮生成失败：{str(e)}"}


def _highlight_pdf(original_path: str, issues: List[Dict]):
    """生成高亮PDF文件"""
    try:
        doc = fitz.open(original_path)
        output_path = NamedTemporaryFile(delete=False, suffix=".pdf").name

        for issue in issues:
            if not issue or not isinstance(issue, dict):
                continue

            text_to_highlight = issue.get("条款", "")
            if not text_to_highlight:
                continue

            for page_num in range(len(doc)):
                page = doc[page_num]
                text_instances = page.search_for(text_to_highlight)

                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst)
                    risk_level = issue.get("风险等级", "低")
                    if risk_level == "高":
                        highlight.set_colors(stroke=[1, 0, 0])
                    elif risk_level == "中":
                        highlight.set_colors(stroke=[1, 0.5, 0])
                    else:
                        highlight.set_colors(stroke=[1, 1, 0])
                    highlight.update()

        doc.save(output_path)
        doc.close()

        logger.info(f"PDF高亮完成，生成文件: {output_path}")

        with open(output_path, "rb") as f:
            file_content = f.read()
        file_base64 = base64.b64encode(file_content).decode("utf-8")

        return {
            "status": "success",
            "file_type": "pdf",
            "file_name": "highlighted_contract.pdf",
            "content": file_base64,
        }
    except Exception as e:
        logger.error(f"PDF高亮失败：{str(e)}")
        return text_response(f"PDF高亮失败：{str(e)}")


def _highlight_docx(original_path: str, issues: List[Dict]):
    """生成高亮Word文件"""
    try:
        doc = Document(original_path)
        output_path = NamedTemporaryFile(delete=False, suffix=".docx").name

        for issue in issues:
            if not issue or not isinstance(issue, dict):
                continue

            text_to_highlight = issue.get("条款", "")
            if not text_to_highlight:
                continue

            for para in doc.paragraphs:
                if text_to_highlight in para.text:
                    for run in para.runs:
                        if text_to_highlight in run.text:
                            risk_level = issue.get("风险等级", "低")
                            if risk_level == "高":
                                run.font.highlight_color = 6
                            elif risk_level == "中":
                                run.font.highlight_color = 4
                            else:
                                run.font.highlight_color = 7

        doc.save(output_path)

        logger.info(f"Word高亮完成，生成文件: {output_path}")

        with open(output_path, "rb") as f:
            file_content = f.read()
        file_base64 = base64.b64encode(file_content).decode("utf-8")

        return {
            "status": "success",
            "file_type": "docx",
            "file_name": "highlighted_contract.docx",
            "content": file_base64,
        }
    except Exception as e:
        logger.error(f"Word高亮失败：{str(e)}")
        return text_response(f"Word高亮失败：{str(e)}")


if __name__ == "__main__":
    app = create_fastapi_app(contract_mcp)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7001,
        log_level="info",
    )
