# ui_ocr_utils.py

import os
import base64
from typing import Dict, List, Optional, Any
import streamlit as st
import requests
from ui_utils import (
    load_cached_parse_result,
    save_parse_result,
    preview_file_content,
)

A4_WIDTH_PX = 794
A4_HEIGHT_PX = 1123


def call_online_parse_api(file_path: str) -> Optional[Dict[str, Any]]:
    """调用布局解析在线API，并返回markdown和原始JSON"""
    original_file_name = st.session_state.get("file_name")
    api_url = (
        st.session_state.get("ocr_api_url")
        or os.getenv("OCR_API_URL", "").strip()
    )
    api_token = (
        st.session_state.get("ocr_api_token")
        or os.getenv("OCR_API_TOKEN", "").strip()
    )

    if not api_url:
        st.warning("请先在左侧的“接口配置”中填写OCR接口地址")
        return None
    if not api_token:
        st.warning("请先在左侧的“接口配置”中填写OCR访问令牌")
        return None

    cached_result = load_cached_parse_result(file_path, original_file_name)
    if cached_result:
        print(f"从缓存加载解析结果: {file_path}")
        return cached_result

    try:
        with open(file_path, "rb") as file:
            file_bytes = file.read()
            file_data = base64.b64encode(file_bytes).decode("ascii")

        headers = {
            "Content-Type": "application/json",
        }
        if api_token:
            headers["Authorization"] = f"token {api_token}"
        payload = {
            "file": file_data,
            "fileType": 0,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": False,
            "useChartRecognition": False,
        }

        resp = requests.post(api_url, json=payload, headers=headers, timeout=120)
        if resp.status_code != 200:
            st.error(f"在线解析失败，状态码: {resp.status_code}")
            return None
        api_json = resp.json()
        result = api_json.get("result", {})

        layout_results = result.get("layoutParsingResults", []) or []
        merged_markdown_parts: List[str] = []

        for i, res in enumerate(layout_results):
            md_text = ((res.get("markdown") or {}).get("text")) or ""
            if md_text:
                merged_markdown_parts.append(md_text)

        markdown_text = (
            "\n\n---\n\n".join(merged_markdown_parts) if merged_markdown_parts else ""
        )
        json_result = result

        if json_result and markdown_text:
            save_parse_result(file_path, json_result, markdown_text, original_file_name)

        result_payload = {
            "json_result": json_result,
            "markdown_text": markdown_text,
            "raw_text": preview_file_content(file_path),
        }

        return result_payload
    except Exception as e:
        st.error(f"调用在线解析API失败: {e}")
        return None


def find_text_positions_in_json(
    clause_text: str, json_result: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """通过文本匹配在JSON中查找条款的位置信息"""
    if not clause_text or not json_result:
        return []

    clause_text_clean = " ".join(clause_text.split())

    if len(clause_text_clean) >= 6:
        search_text = clause_text_clean[-6:]
    else:
        search_text = clause_text_clean

    matches = []
    layout_results = json_result.get("layoutParsingResults", [])

    for layout_idx, layout_result in enumerate(layout_results):
        pruned_result = layout_result.get("prunedResult", {})

        parsing_list = pruned_result.get("parsing_res_list", [])
        for block in parsing_list:
            block_content = block.get("block_content", "")
            if not block_content:
                continue

            block_content_clean = " ".join(block_content.split())

            if search_text in block_content_clean:
                match_start = block_content_clean.find(search_text)
                match_end = match_start + len(search_text)
                matches.append(
                    {
                        "block_id": block.get("block_id"),
                        "block_content": block_content,
                        "block_bbox": block.get("block_bbox", []),
                        "match_text": search_text,
                        "match_start": match_start,
                        "match_end": match_end,
                        "layout_idx": layout_idx,
                        "source": "parsing_res_list",
                    }
                )

        overall_ocr = pruned_result.get("overall_ocr_res", {})
        rec_texts = overall_ocr.get("rec_texts", [])
        rec_boxes = overall_ocr.get("rec_boxes", [])
        rec_polys = overall_ocr.get("rec_polys", [])

        for idx, rec_text in enumerate(rec_texts):
            if not rec_text:
                continue

            rec_text_clean = " ".join(rec_text.split())

            if search_text in rec_text_clean:
                box = rec_boxes[idx] if idx < len(rec_boxes) else []
                poly = rec_polys[idx] if idx < len(rec_polys) else []
                match_start = rec_text_clean.find(search_text)
                match_end = match_start + len(search_text)
                matches.append(
                    {
                        "block_id": f"ocr_{idx}",
                        "block_content": rec_text,
                        "block_bbox": box if box else [],
                        "rec_poly": poly,
                        "match_text": search_text,
                        "match_start": match_start,
                        "match_end": match_end,
                        "layout_idx": layout_idx,
                        "source": "overall_ocr_res",
                    }
                )

    return matches


def _classify_font_size(font_size: float) -> tuple[str, float]:
    """将字体大小分类为大、中、小三类，并返回标准大小"""
    if font_size < 16:
        return ("小", 14.0)
    elif font_size <= 24:
        return ("中", 18.0)
    else:
        return ("大", 24.0)


def _calculate_font_size_from_bbox(bbox: List[float]) -> float:
    """根据边界框计算字体大小（像素），并分类"""
    if len(bbox) < 4:
        return 14.0

    if len(bbox) == 4:
        if bbox[2] > 0 and bbox[3] > 0:
            height = bbox[3]
            font_size = height * 0.8
            _, standard_size = _classify_font_size(font_size)
            return standard_size

    return 14.0


def _calculate_font_size_from_poly(poly: List[List[float]]) -> float:
    """根据多边形坐标计算字体大小，并分类"""
    if not poly or len(poly) < 4:
        return 14.0

    y_coords = [point[1] for point in poly if len(point) >= 2]
    if len(y_coords) >= 2:
        height = max(y_coords) - min(y_coords)
        font_size = height * 0.8
        _, standard_size = _classify_font_size(font_size)
        return standard_size

    return 14.0


def _get_text_alignment(poly: List[List[float]], page_width: float = 1200) -> str:
    """根据文本起始位置判断对齐方式，强制分类为左、中、右三类"""
    if not poly or len(poly) < 4:
        return "left"

    x_coords = [point[0] for point in poly if len(point) >= 1]
    if not x_coords:
        return "left"

    min_x = min(x_coords)
    max_x = max(x_coords)

    if page_width <= 0:
        page_width = max_x * 2

    left_threshold = page_width * 0.35
    right_threshold = page_width * 0.65

    if min_x < left_threshold:
        return "left"
    elif min_x > right_threshold:
        return "right"
    else:
        return "center"


def _extract_ocr_text_elements(layout_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从layout_result中提取所有OCR文本元素及其位置信息，并按行组织"""
    text_elements = []

    pruned_result = layout_result.get("prunedResult", {})
    overall_ocr = pruned_result.get("overall_ocr_res", {})

    if not overall_ocr:
        return text_elements

    rec_texts = overall_ocr.get("rec_texts", [])
    rec_polys = overall_ocr.get("rec_polys", [])
    rec_scores = overall_ocr.get("rec_scores", [])

    for idx, text in enumerate(rec_texts):
        if not text or not text.strip():
            continue

        poly = rec_polys[idx] if idx < len(rec_polys) else []
        score = rec_scores[idx] if idx < len(rec_scores) else 0.0

        if poly and len(poly) >= 4:
            # 计算位置和大小
            x_coords = [p[0] for p in poly if len(p) >= 1]
            y_coords = [p[1] for p in poly if len(p) >= 2]

            if x_coords and y_coords:
                min_x = min(x_coords)
                min_y = min(y_coords)
                max_x = max(x_coords)
                max_y = max(y_coords)

                width = max_x - min_x
                height = max_y - min_y

                if width < 5 or height < 5:
                    continue

                font_size = _calculate_font_size_from_poly(poly)
                alignment = _get_text_alignment(poly)

                text_elements.append(
                    {
                        "text": text,
                        "x": min_x,
                        "y": min_y,
                        "width": width,
                        "height": height,
                        "font_size": font_size,
                        "alignment": alignment,
                        "poly": poly,
                        "score": score,
                    }
                )

    if text_elements:
        text_elements.sort(key=lambda e: (e["y"], e["x"]))

        lines = []
        current_line = []
        line_y = None
        line_height = None

        for elem in text_elements:
            elem_y = elem["y"]
            elem_height = elem["height"]

            if (
                line_y is None
                or abs(elem_y - line_y) > (line_height or elem_height) * 1.5
            ):
                if current_line:
                    # 先按 y 坐标排序（从上到下），再按 x 坐标排序（从左到右）
                    current_line.sort(key=lambda e: (e["y"], e["x"]))
                    avg_font_size = sum(e["font_size"] for e in current_line) / len(
                        current_line
                    )
                    _, line_font_size = _classify_font_size(avg_font_size)

                    line_min_x = min(e["x"] for e in current_line)
                    line_max_x = max(e["x"] + e["width"] for e in current_line)
                    line_width = line_max_x - line_min_x
                    line_alignment = current_line[0]["alignment"]

                    lines.append(
                        {
                            "elements": current_line,
                            "y": line_y,
                            "x": line_min_x,
                            "width": line_width,
                            "height": line_height,
                            "font_size": line_font_size,
                            "alignment": line_alignment,
                        }
                    )
                current_line = [elem]
                line_y = elem_y
                line_height = elem_height
            else:
                current_line.append(elem)
                line_height = max(line_height or elem_height, elem_height)

        if current_line:
            # 先按 y 坐标排序（从上到下），再按 x 坐标排序（从左到右）
            current_line.sort(key=lambda e: (e["y"], e["x"]))
            avg_font_size = sum(e["font_size"] for e in current_line) / len(
                current_line
            )
            _, line_font_size = _classify_font_size(avg_font_size)

            line_min_x = min(e["x"] for e in current_line)
            line_max_x = max(e["x"] + e["width"] for e in current_line)
            line_width = line_max_x - line_min_x
            line_alignment = current_line[0]["alignment"]

            lines.append(
                {
                    "elements": current_line,
                    "y": line_y,
                    "x": line_min_x,
                    "width": line_width,
                    "height": line_height,
                    "font_size": line_font_size,
                    "alignment": line_alignment,
                }
            )

        return lines

    return []
