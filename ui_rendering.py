# ui_rendering.py

import os
import json
import base64
from typing import Dict, List, Any
import streamlit as st
from ui_utils import preview_file_content, load_cached_parse_result, compute_file_md5
from ui_ocr_utils import (
    call_online_parse_api,
    find_text_positions_in_json,
    A4_WIDTH_PX,
    A4_HEIGHT_PX,
    _classify_font_size,
    _calculate_font_size_from_bbox,
    _get_text_alignment,
    _extract_ocr_text_elements,
)


def render_file_preview(file_path: str, height: int = 780):
    """左侧源文件预览"""
    file_ext = os.path.splitext(file_path)[1].lower()

    if file_ext == ".pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            if doc.page_count == 0:
                st.warning("PDF 无页面可预览")
                return

            page_key = f"pdf_page_{os.path.basename(file_path)}"
            current_page = int(st.session_state.get(page_key, 1))
            if current_page < 1:
                current_page = 1
            if current_page > doc.page_count:
                current_page = doc.page_count

            page_images = []
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode()
                page_images.append({"page_num": page_num + 1, "img_base64": img_base64})

            container_id = f"pdf-container-{os.path.basename(file_path).replace('.', '_').replace(' ', '_')}"
            scroll_key = f"scroll_to_page_{page_key}"
            target_page = st.session_state.get(scroll_key, current_page)

            pages_html_content = ""
            for page_data in page_images:
                page_num = page_data["page_num"]
                img_base64 = page_data["img_base64"]
                pages_html_content += f'<div id="pdf-page-{page_num}" style="margin-bottom: 20px; text-align: center;"><img src="data:image/png;base64,{img_base64}" style="width: 100%; max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: block; margin: 10px auto;" /><div style="margin-top: 10px; color: #666; font-size: 12px;">第 {page_num} 页 / 共 {doc.page_count} 页</div></div>'

            # 构建完整的HTML
            html_content = f"""
            <div id="{container_id}" style="max-height: {height}px; overflow-y: auto; overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 4px; padding: 10px; margin-bottom: 10px; background-color: #fafafa;">
                {pages_html_content}
            </div>
            <script>
                (function() {{
                    const containerId = '{container_id}';
                    const targetPage = {target_page};
                    
                    function scrollToPage(pageNum) {{
                        const container = document.getElementById(containerId);
                        const pageElement = document.getElementById('pdf-page-' + pageNum);
                        if (container && pageElement) {{
                            const scrollTop = pageElement.offsetTop - container.offsetTop - 10;
                            container.scrollTo({{
                                top: scrollTop,
                                behavior: 'smooth'
                            }});
                        }}
                    }}
                    
                    function initScroll() {{
                        const container = document.getElementById(containerId);
                        if (container) {{
                            scrollToPage(targetPage);
                        }} else {{
                            setTimeout(initScroll, 100);
                        }}
                    }}
                    
                    if (document.readyState === 'loading') {{
                        document.addEventListener('DOMContentLoaded', initScroll);
                    }} else {{
                        initScroll();
                    }}
                    
                    window['scrollToPage_' + containerId] = scrollToPage;
                }})();
            </script>
            """

            st.markdown(html_content, unsafe_allow_html=True)

            ctrl_left, ctrl_mid, ctrl_right = st.columns([1, 2, 1])
            with ctrl_left:
                if st.button("上一页", width="stretch", key=f"prev_{page_key}"):
                    new_page = max(1, current_page - 1)
                    if new_page != current_page:
                        st.session_state[page_key] = new_page
                        st.session_state[scroll_key] = new_page
                        st.rerun()
            with ctrl_mid:
                new_val = st.number_input(
                    "页码",
                    min_value=1,
                    max_value=doc.page_count,
                    value=current_page,
                    step=1,
                    key=f"num_{page_key}",
                    label_visibility="collapsed",
                )
                if int(new_val) != current_page:
                    st.session_state[page_key] = int(new_val)
                    st.session_state[scroll_key] = int(new_val)
                    st.rerun()
            with ctrl_right:
                if st.button("下一页", width="stretch", key=f"next_{page_key}"):
                    new_page = min(doc.page_count, current_page + 1)
                    if new_page != current_page:
                        st.session_state[page_key] = new_page
                        st.session_state[scroll_key] = new_page
                        st.rerun()
        except Exception:
            st.warning("图片预览失败，已切换为文本模式。")
            st.text_area(
                "文件内容",
                preview_file_content(file_path),
                height=height,
                disabled=True,
                key="left_text_area",
            )
    else:
        st.text_area(
            "文件内容",
            preview_file_content(file_path),
            height=height,
            disabled=True,
            key="left_text_area",
        )


def render_preview_panel(file_path: str, preview_text: str):
    """两栏预览：左侧源文件，右侧识别结果对照，支持同步滚动"""

    current_hash = st.session_state.get("file_hash")
    if not current_hash:
        current_hash = compute_file_md5(file_path)
        st.session_state.file_hash = current_hash

    if (
        st.session_state.ocr_parsed_file_hash != current_hash
        or st.session_state.ocr_parsed_file_path != file_path
    ):
        original_file_name = st.session_state.get("file_name")
        cached_result = load_cached_parse_result(file_path, original_file_name)
        if cached_result:
            st.session_state.ocr_parse_result = cached_result
            st.session_state.ocr_parsed_file_path = file_path
            st.session_state.ocr_parsed_original_file_name = original_file_name
            st.session_state.ocr_parsed_file_hash = current_hash
        else:
            st.session_state.ocr_parse_result = None
            st.session_state.ocr_parsed_file_path = None
            st.session_state.ocr_parsed_original_file_name = None
            st.session_state.ocr_parsed_file_hash = None

    sync_scroll_js = """
    <script>
    (function() {
        let leftPanel = null;
        let rightPanel = null;
        let isScrolling = false;
        
        function findScrollablePanels() {
            const allElements = document.querySelectorAll('*');
            const scrollableElements = [];
            
            for (let el of allElements) {
                const style = window.getComputedStyle(el);
                const hasScroll = el.scrollHeight > el.clientHeight;
                const isScrollable = style.overflow === 'auto' || 
                                    style.overflow === 'scroll' || 
                                    style.overflowY === 'auto' || 
                                    style.overflowY === 'scroll';
                
                if (hasScroll && isScrollable && el.offsetHeight > 200) {
                    scrollableElements.push(el);
                }
            }
            
            const textareas = Array.from(document.querySelectorAll('textarea'));
            let rightTextarea = null;
            
            for (let ta of textareas) {
                const rect = ta.getBoundingClientRect();
                if (rect.left > window.innerWidth / 2 && 
                    ta.scrollHeight > ta.clientHeight) {
                    rightTextarea = ta;
                    break;
                }
            }
            
            let leftPanel = null;
            
            for (let el of scrollableElements) {
                const rect = el.getBoundingClientRect();
                if (rect.left < window.innerWidth / 2) {
                    if (el.id && el.id.includes('pdf-container')) {
                        leftPanel = el;
                        break;
                    }
                    if (el.querySelector('img') || el.tagName === 'TEXTAREA') {
                        leftPanel = el;
                        break;
                    }
                }
            }
            
            if (!leftPanel && scrollableElements.length > 0) {
                scrollableElements.sort((a, b) => {
                    return a.getBoundingClientRect().left - b.getBoundingClientRect().left;
                });
                leftPanel = scrollableElements[0];
            }
            
            if (leftPanel && rightTextarea && leftPanel !== rightTextarea) {
                return [leftPanel, rightTextarea];
            }
            
            if (leftPanel && !rightTextarea && scrollableElements.length >= 2) {
                for (let el of scrollableElements) {
                    const rect = el.getBoundingClientRect();
                    if (rect.left > window.innerWidth / 2 && el !== leftPanel) {
                        return [leftPanel, el];
                    }
                }
            }
            
            if (scrollableElements.length >= 2) {
                scrollableElements.sort((a, b) => {
                    return a.getBoundingClientRect().left - b.getBoundingClientRect().left;
                });
                return [scrollableElements[0], scrollableElements[1]];
            }
            
            return null;
        }
        
        function syncScroll(source, target) {
            if (isScrolling || !source || !target) return;
            isScrolling = true;
            
            const sourceScrollTop = source.scrollTop;
            const sourceScrollHeight = source.scrollHeight;
            const sourceClientHeight = source.clientHeight;
            const targetScrollHeight = target.scrollHeight;
            const targetClientHeight = target.clientHeight;
            
            if (sourceScrollHeight <= sourceClientHeight || targetScrollHeight <= targetClientHeight) {
                isScrolling = false;
                return;
            }
            
            const scrollRatio = sourceScrollTop / (sourceScrollHeight - sourceClientHeight);
            const targetScrollTop = scrollRatio * (targetScrollHeight - targetClientHeight);
            
            target.scrollTop = targetScrollTop;
            
            setTimeout(() => { isScrolling = false; }, 10);
        }
        
        function initSyncScroll() {
            const panels = findScrollablePanels();
            if (panels && panels.length === 2) {
                leftPanel = panels[0];
                rightPanel = panels[1];
                
                if (leftPanel._syncScrollHandler) {
                    leftPanel.removeEventListener('scroll', leftPanel._syncScrollHandler);
                }
                if (rightPanel._syncScrollHandler) {
                    rightPanel.removeEventListener('scroll', rightPanel._syncScrollHandler);
                }
                
                leftPanel._syncScrollHandler = () => syncScroll(leftPanel, rightPanel);
                rightPanel._syncScrollHandler = () => syncScroll(rightPanel, leftPanel);
                
                leftPanel.addEventListener('scroll', leftPanel._syncScrollHandler, { passive: true });
                rightPanel.addEventListener('scroll', rightPanel._syncScrollHandler, { passive: true });
            }
        }
        
        const observer = new MutationObserver(() => {
            setTimeout(initSyncScroll, 100);
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        
        setTimeout(initSyncScroll, 1000);
        
        window.addEventListener('load', () => {
            setTimeout(initSyncScroll, 500);
        });
    })();
    </script>
    """

    st.components.v1.html(sync_scroll_js, height=0)

    left, right = st.columns([1, 1], gap="large")

    with left:
        left_container = st.container()
        with left_container:
            st.markdown(
                '<span id="left-preview-anchor"></span>', unsafe_allow_html=True
            )
            render_file_preview(file_path)

    with right:
        right_container = st.container()
        with right_container:
            st.markdown('<span id="right-panel-anchor"></span>', unsafe_allow_html=True)
            tabs = st.tabs(["OCR识别对照", "Markdown", "JSON"])

            with tabs[0]:
                if st.session_state.ocr_parse_result and isinstance(
                    st.session_state.ocr_parse_result, dict
                ):
                    json_result = st.session_state.ocr_parse_result.get(
                        "json_result", {}
                    )
                    if json_result:
                        html_content = generate_html_layout(json_result, [])
                        st.components.v1.html(html_content, height=780, scrolling=True)
                    else:
                        st.info("暂无JSON结果，无法进行版面恢复。")
                else:
                    st.info("请先调用OCR解析以查看识别对照结果。")

            with tabs[1]:
                markdown_content = None
                if st.session_state.ocr_parse_result and isinstance(
                    st.session_state.ocr_parse_result, dict
                ):
                    markdown_content = st.session_state.ocr_parse_result.get(
                        "markdown_text"
                    )

                if markdown_content:
                    render_markdown_box(markdown_content, height=780, enable_scroll=True)
                else:
                    st.text_area(
                        "Markdown内容",
                        "",
                        height=780,
                        disabled=False,
                        label_visibility="collapsed",
                        key="markdown_preview_area",
                    )

            with tabs[2]:
                if st.session_state.ocr_parse_result and isinstance(
                    st.session_state.ocr_parse_result, dict
                ):
                    json_result = st.session_state.ocr_parse_result.get(
                        "json_result", {}
                    )
                    if json_result:
                        json_str = json.dumps(json_result, ensure_ascii=False, indent=2)
                        st.text_area(
                            "JSON内容",
                            json_str,
                            height=780,
                            disabled=False,
                            label_visibility="collapsed",
                            key="json_preview_area",
                        )
                    else:
                        st.info("暂无JSON结果。")
                else:
                    st.text_area(
                        "JSON内容",
                        "",
                        height=780,
                        disabled=False,
                        label_visibility="collapsed",
                        key="json_preview_area",
                    )


def format_json_result_as_text(json_result: Dict[str, Any]) -> str:
    """从JSON中提取文字、位置、排版等信息并格式化为可读文本"""
    if not json_result:
        return "暂无JSON结果"

    lines = []

    if "file_name" in json_result:
        lines.append(f"📄 文件名: {json_result.get('file_name', 'N/A')}")
        lines.append(f"🆔 文件ID: {json_result.get('file_id', 'N/A')}")
        lines.append("")

    # 处理页面信息
    pages = json_result.get("pages", [])
    if pages:
        lines.append(f"📑 共 {len(pages)} 页")
        lines.append("=" * 80)
        lines.append("")

        for page_idx, page in enumerate(pages):
            page_num = page.get("page_num", page_idx)
            page_id = page.get("page_id", f"page-{page_idx}")

            lines.append(f"📄 第 {page_num + 1} 页 (page_id: {page_id})")
            lines.append("-" * 80)

            meta = page.get("meta", {})
            if meta:
                page_width = meta.get("page_width", 0)
                page_height = meta.get("page_height", 0)
                lines.append(
                    f"📏 页面尺寸: {page_width} × {page_height} 像素 | 页面类型: {meta.get('page_type', 'N/A')}"
                )
                lines.append("")

            # 优先显示页面完整文本内容
            page_text = page.get("text", "").strip()
            if page_text:
                lines.append("【识别文本内容】")
                lines.append("-" * 80)
                lines.append(page_text)
                lines.append("")
                lines.append("-" * 80)
                lines.append("")

            layouts = page.get("layouts", [])
            if layouts:
                lines.append(f"【布局结构信息】共 {len(layouts)} 个布局元素")
                lines.append("")

                layout_dict = {layout.get("layout_id"): layout for layout in layouts}
                root_layouts = [
                    layout for layout in layouts if layout.get("parent") == "root"
                ]

                def format_layout_with_text(layout, indent_level=0):
                    """格式化单个布局元素，突出显示文本和位置信息"""
                    indent = "  " * indent_level
                    layout_id = layout.get("layout_id", "N/A")
                    layout_type = layout.get("type", "N/A")
                    sub_type = layout.get("sub_type", "")
                    text = layout.get("text", "").strip()
                    position = layout.get("position", [])

                    direction_hint = ""
                    if position and len(position) >= 4:
                        x, y, w, h = position[0], position[1], position[2], position[3]
                        if w > 0 and h > 0:
                            aspect_ratio = w / h
                            if aspect_ratio > 2.0:
                                direction_hint = " [水平]"
                            elif aspect_ratio < 0.5:
                                direction_hint = " [垂直]"
                        pos_str = f"[位置: ({x}, {y}) 尺寸: {w}×{h}{direction_hint}]"
                    else:
                        pos_str = "[位置: N/A]"

                    type_label = f"{layout_type}"
                    if sub_type:
                        type_label += f"/{sub_type}"

                    result = []
                    if text:
                        text_to_display = text
                        if position and len(position) >= 4:
                            x, y, w, h = (
                                position[0],
                                position[1],
                                position[2],
                                position[3],
                            )
                            if w > 0 and h > 0:
                                aspect_ratio = w / h
                                text_lines = text.split("\n")
                                is_single_char_per_line = all(
                                    len(line.strip()) == 1
                                    for line in text_lines
                                    if line.strip()
                                )

                                if aspect_ratio > 1.2 and is_single_char_per_line:
                                    text_to_display = "".join(
                                        line.strip()
                                        for line in text_lines
                                        if line.strip()
                                    )
                                    result.append(f"{indent}【{type_label}】{pos_str}")
                                    result.append(
                                        f"{indent}  文本（水平）: {text_to_display}"
                                    )
                                elif aspect_ratio < 0.8:
                                    result.append(f"{indent}【{type_label}】{pos_str}")
                                    result.append(f"{indent}  文本（垂直排列）:")
                                    for line in text_lines:
                                        if line.strip():
                                            result.append(f"{indent}    {line}")
                                else:
                                    if len(text_lines) == 1:
                                        result.append(
                                            f"{indent}【{type_label}】{pos_str}"
                                        )
                                        result.append(
                                            f"{indent}  文本: {text_to_display}"
                                        )
                                    else:
                                        result.append(
                                            f"{indent}【{type_label}】{pos_str}"
                                        )
                                        result.append(f"{indent}  文本:")
                                        for line in text_lines:
                                            if line.strip():
                                                result.append(f"{indent}    {line}")
                            else:
                                text_lines = text_to_display.split("\n")
                                if len(text_lines) == 1:
                                    result.append(f"{indent}【{type_label}】{pos_str}")
                                    result.append(f"{indent}  文本: {text_to_display}")
                                else:
                                    result.append(f"{indent}【{type_label}】{pos_str}")
                                    result.append(f"{indent}  文本:")
                                    for line in text_lines:
                                        if line.strip():
                                            result.append(f"{indent}    {line}")
                        else:
                            text_lines = text_to_display.split("\n")
                            if len(text_lines) == 1:
                                result.append(f"{indent}【{type_label}】{pos_str}")
                                result.append(f"{indent}  文本: {text_to_display}")
                            else:
                                result.append(f"{indent}【{type_label}】{pos_str}")
                                result.append(f"{indent}  文本:")
                                for line in text_lines:
                                    if line.strip():
                                        result.append(f"{indent}    {line}")
                    else:
                        result.append(f"{indent}【{type_label}】{layout_id} {pos_str}")

                    return result

                def process_layout_tree_ordered(layout, indent_level=0, processed=None):
                    """递归处理布局树结构，按顺序展示文本内容"""
                    if processed is None:
                        processed = set()

                    layout_id = layout.get("layout_id")
                    if layout_id in processed:
                        return []

                    processed.add(layout_id)
                    result = format_layout_with_text(layout, indent_level)

                    children_ids = layout.get("children", [])
                    if children_ids:
                        for child_id in children_ids:
                            if child_id in layout_dict:
                                child_layout = layout_dict[child_id]
                                child_result = process_layout_tree_ordered(
                                    child_layout, indent_level + 1, processed
                                )
                                result.extend(child_result)

                    return result

                processed_ids = set()
                for root_layout in root_layouts:
                    layout_lines = process_layout_tree_ordered(
                        root_layout, indent_level=0, processed=processed_ids
                    )
                    lines.extend(layout_lines)
                    lines.append("")

                orphan_layouts = [
                    layout
                    for layout in layouts
                    if layout.get("layout_id") not in processed_ids
                ]
                if orphan_layouts:
                    lines.append("【其他布局元素】")
                    for orphan in orphan_layouts:
                        layout_lines = format_layout_with_text(orphan, indent_level=0)
                        lines.extend(layout_lines)
                        lines.append("")

            tables = page.get("tables", [])
            if tables:
                lines.append(f"【表格信息】共 {len(tables)} 个表格")
                for i, table in enumerate(tables):
                    lines.append(f"  表格 {i+1}: ID={table.get('table_id', 'N/A')}")
                    if "position" in table:
                        pos = table["position"]
                        if len(pos) >= 4:
                            lines.append(
                                f"    位置: ({pos[0]}, {pos[1]}) 尺寸: {pos[2]}×{pos[3]}"
                            )
                lines.append("")

            images = page.get("images", [])
            if images:
                lines.append(f"【图片信息】共 {len(images)} 个图片")
                for i, image in enumerate(images):
                    lines.append(f"  图片 {i+1}: ID={image.get('image_id', 'N/A')}")
                    if "position" in image:
                        pos = image["position"]
                        if len(pos) >= 4:
                            lines.append(
                                f"    位置: ({pos[0]}, {pos[1]}) 尺寸: {pos[2]}×{pos[3]}"
                            )
                lines.append("")

            lines.append("")
            lines.append("=" * 80)
            lines.append("")

    return "\n".join(lines)


def generate_html_layout(json_result: Dict[str, Any], issues: List[Dict]) -> str:
    """基于JSON生成HTML版面恢复，并标注风险点"""
    if not json_result:
        return "<div>暂无文档内容</div>"

    issue_positions = {}
    for idx, issue in enumerate(issues):
        clause_text = issue.get("条款", "")
        if clause_text:
            positions = find_text_positions_in_json(clause_text, json_result)
            if positions:
                issue_positions[idx] = {"issue": issue, "positions": positions}

    html_parts = []
    html_parts.append(
        """
    <style>
        .document-container {
            font-family: 'SimSun', '宋体', serif;
            position: relative;
            max-width: 100%;
            margin: 0 auto;
            padding: 10px;
            background: #fff;
            min-height: 100vh;
            box-sizing: border-box;
            overflow-x: hidden;
            overflow-y: auto;
        }
        .page-wrapper {
            position: relative;
            margin: 0 auto 40px;
            max-width: 100%;
            width: __A4_WIDTH__px;
            height: __A4_HEIGHT__px;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            background-color: #fff;
            box-shadow: 0 6px 18px rgba(0,0,0,0.08);
            overflow: hidden;
            box-sizing: border-box;
        }
        @media (max-width: 850px) {
            .page-wrapper {
                width: 100% !important;
                height: auto !important;
                aspect-ratio: __A4_WIDTH__ / __A4_HEIGHT__;
            }
            .document-container {
                padding: 5px;
            }
        }
        .text-element {
            position: absolute;
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.0;
            overflow: visible;
        }
        .text-block {
            position: relative;
            margin: 2px 0;
            padding: 1px 4px;
            text-align: left;
            line-height: 1.2;
            /* font-size 由内联样式控制，根据block_label动态设置 */
        }
        .risk-highlight {
            cursor: pointer;
            position: static;
            display: inline;
            line-height: inherit;
            font-size: inherit;
            font-weight: inherit;
            font-family: inherit;
            text-align: inherit;
            margin: 0;
            padding: 0;
            vertical-align: baseline;
            white-space: normal;
            word-wrap: break-word;
        }
        .risk-highlight.risk-high {
            color: #d32f2f;
        }
        .risk-highlight.risk-medium {
            color: #f57c00;
        }
        .risk-highlight.risk-low {
            color: #388e3c;
        }
        .risk-tooltip {
            position: fixed;
            background: #333;
            color: #fff;
            padding: 12px;
            border-radius: 6px;
            font-size: 14px;
            z-index: 10000;
            max-width: 380px;
            display: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            pointer-events: none;
            word-wrap: break-word;
            line-height: 1.6;
        }
        .risk-tooltip.show {
            display: block;
        }
        .risk-tooltip h4 {
            margin: 0 0 8px 0;
            font-size: 16px;
            color: #ef9a9a;
            border-bottom: 1px solid #555;
            padding-bottom: 8px;
        }
        .risk-tooltip p {
            margin: 8px 0;
            font-size: 14px;
            line-height: 1.6;
        }
    </style>
    <div class="document-container">
    """.replace(
            "__A4_WIDTH__", str(A4_WIDTH_PX)
        ).replace(
            "__A4_HEIGHT__", str(A4_HEIGHT_PX)
        )
    )

    layout_results = json_result.get("layoutParsingResults", [])

    use_precise_layout = False
    for layout_result in layout_results:
        text_elements = _extract_ocr_text_elements(layout_result)
        if text_elements:
            use_precise_layout = True
            break

    if use_precise_layout:
        for layout_idx, layout_result in enumerate(layout_results):
            text_lines = _extract_ocr_text_elements(layout_result)

            if not text_lines:
                continue

            # 获取block信息用于匹配block_label
            pruned_result = layout_result.get("prunedResult", {})
            parsing_list = pruned_result.get("parsing_res_list", [])
            blocks_by_text = {}
            blocks_by_bbox = []  # 存储带bbox的block，用于位置匹配
            for block in parsing_list:
                block_content = block.get("block_content", "").strip()
                if block_content:
                    # 使用清理后的文本作为key
                    block_content_clean = " ".join(block_content.split())
                    if block_content_clean:
                        blocks_by_text[block_content_clean] = block
                # 同时存储带bbox的block用于位置匹配
                block_bbox = block.get("block_bbox", [])
                if block_bbox and len(block_bbox) >= 4:
                    blocks_by_bbox.append({
                        "block": block,
                        "bbox": block_bbox  # [x, y, width, height] 或 [x1, y1, x2, y2]
                    })

            max_x = max(
                [line["x"] + line["width"] for line in text_lines], default=A4_WIDTH_PX
            )
            max_y = max(
                [line["y"] + line["height"] for line in text_lines],
                default=A4_HEIGHT_PX,
            )

            for line in text_lines:
                if line["elements"]:
                    line["alignment"] = _get_text_alignment(
                        line["elements"][0]["poly"], max_x
                    )
                if line["alignment"] not in ["left", "center", "right"]:
                    line["alignment"] = "left"

            doc_width = max_x if max_x > 0 else A4_WIDTH_PX
            doc_height = max_y if max_y > 0 else A4_HEIGHT_PX
            width_scale = A4_WIDTH_PX / doc_width
            height_scale = A4_HEIGHT_PX / doc_height
            scale = min(width_scale, height_scale)
            if scale <= 0:
                scale = 1.0
            min_font_size = 12.0

            html_parts.append(
                f'<div class="page-wrapper" style="width: {A4_WIDTH_PX}px; height: {A4_HEIGHT_PX}px;">'
            )

            # 确保文本行按 y 坐标排序（从上到下），如果 y 坐标相同则按 x 坐标排序（从左到右）
            text_lines.sort(key=lambda l: (l["y"], l["x"]))

            for line_idx, line in enumerate(text_lines):
                line_y = line["y"] * scale
                line_x = line["x"] * scale
                line_width = line["width"] * scale
                
                # 尝试匹配block_label
                line_text = "".join([elem["text"] for elem in line["elements"]])
                line_text_clean = " ".join(line_text.split())
                matched_block = None
                
                # 首先尝试文本匹配
                if line_text_clean:
                    # 尝试完全匹配
                    if line_text_clean in blocks_by_text:
                        matched_block = blocks_by_text[line_text_clean]
                    else:
                        # 尝试部分匹配
                        for block_text, block in blocks_by_text.items():
                            if line_text_clean in block_text or block_text in line_text_clean:
                                matched_block = block
                                break
                
                # 如果文本匹配失败，尝试基于位置（bbox）匹配
                # 这对于多行doc_title特别有用
                if not matched_block:
                    line_center_x = line_x + line_width / 2
                    line_center_y = line_y + (line.get("height", 0) * scale) / 2
                    
                    for bbox_item in blocks_by_bbox:
                        bbox = bbox_item["bbox"]
                        block = bbox_item["block"]
                        block_label = block.get("block_label", "")
                        
                        # 判断bbox格式：根据JSON，通常是 [x1, y1, x2, y2] 格式
                        if len(bbox) >= 4:
                            # 检查是否是 [x, y, width, height] 格式（width和height应该小于x和y的值）
                            # 或者直接假设是 [x1, y1, x2, y2] 格式（更常见）
                            if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                                # [x1, y1, x2, y2] 格式
                                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                            else:
                                # [x, y, width, height] 格式
                                x1, y1 = bbox[0], bbox[1]
                                x2, y2 = x1 + bbox[2], y1 + bbox[3]
                            
                            # 缩放bbox以匹配缩放后的坐标
                            bbox_x1 = x1 * scale
                            bbox_y1 = y1 * scale
                            bbox_x2 = x2 * scale
                            bbox_y2 = y2 * scale
                            
                            # 检查行的中心点是否在block的bbox内，或者行与block有重叠
                            line_x_scaled = line_x
                            line_y_scaled = line_y
                            line_w_scaled = line_width
                            line_h_scaled = line.get("height", 0) * scale
                            
                            # 检查是否有重叠（允许一些容差）
                            tolerance = 20 * scale
                            if (line_center_x >= bbox_x1 - tolerance and 
                                line_center_x <= bbox_x2 + tolerance and
                                line_center_y >= bbox_y1 - tolerance and 
                                line_center_y <= bbox_y2 + tolerance):
                                matched_block = block
                                break
                            # 或者检查行是否与block有重叠
                            elif not (line_x_scaled + line_w_scaled < bbox_x1 - tolerance or
                                     line_x_scaled > bbox_x2 + tolerance or
                                     line_y_scaled + line_h_scaled < bbox_y1 - tolerance or
                                     line_y_scaled > bbox_y2 + tolerance):
                                matched_block = block
                                break
                
                # 根据block_label调整字体大小
                base_font_size = max(min_font_size, line["font_size"] * scale * 1.2)
                if matched_block:
                    block_label = matched_block.get("block_label", "text")
                    if block_label == "doc_title":
                        # 对于doc_title，使用较大的字体
                        base_font_size = max(28.0, base_font_size * 1.5)
                    elif block_label == "paragraph_title":
                        base_font_size = 18
                    # text和其他类型保持原样
                
                line_font_size = base_font_size
                line_alignment = line["alignment"]

                line_content_parts = []
                elem_global_idx = 0
                prev_elem_end_x = None

                for elem in line["elements"]:
                    text = elem["text"]
                    elem_x = elem["x"] * scale
                    elem_width = elem["width"] * scale
                    elem_end_x = elem_x + elem_width

                    relative_x = elem_x - line_x

                    spacing = ""
                    if prev_elem_end_x is not None and elem_x > prev_elem_end_x:
                        gap = elem_x - prev_elem_end_x
                        if gap > line_font_size * 0.3:
                            spacing = f'<span style="display: inline-block; width: {gap}px;"></span>'
                        else:
                            spacing = " "

                    text_clean = " ".join(text.split())
                    matching_issue = None
                    matching_issue_idx = None

                    if len(text_clean) > 3:
                        for issue_idx, issue_data in issue_positions.items():
                            clause_text = issue_data["issue"].get("条款", "")
                            if clause_text:
                                clause_clean = " ".join(clause_text.split())
                                if text_clean in clause_clean:
                                    matching_issue = issue_data["issue"]
                                    matching_issue_idx = issue_idx
                                    break

                    escaped_text = _escape_html(text)
                    if matching_issue:
                        risk_level = matching_issue.get("风险等级", "低")
                        risk_class = {
                            "高": "risk-highlight risk-high",
                            "中": "risk-highlight risk-medium",
                            "低": "risk-highlight risk-low",
                        }.get(risk_level, "risk-highlight risk-low")

                        issue_type = matching_issue.get("类型", "")
                        issue_desc = matching_issue.get("问题描述", "")
                        issue_suggestion = matching_issue.get("修改建议", "")

                        tooltip_id = f"tooltip_{layout_idx}_{line_idx}_{elem_global_idx}_{matching_issue_idx}"

                        line_content_parts.append(
                            f'{spacing}<span class="{risk_class}" data-issue-idx="{matching_issue_idx}" onmouseenter="showTooltip(event, \'{tooltip_id}\')" onmouseleave="hideTooltip(\'{tooltip_id}\')">{escaped_text}<div id="{tooltip_id}" class="risk-tooltip"><h4>{_escape_html(issue_type)}</h4><p><strong>风险等级：</strong>{risk_level}</p><p><strong>问题描述：</strong>{_escape_html(issue_desc)}</p><p><strong>修改建议：</strong>{_escape_html(issue_suggestion)}</p></div></span>'
                        )
                    else:
                        line_content_parts.append(
                            f'{spacing}<span style="display: inline;">{escaped_text}</span>'
                        )

                    prev_elem_end_x = elem_end_x
                    elem_global_idx += 1

                line_content = "".join(line_content_parts)

                text_align = "left"
                if line_alignment == "center":
                    text_align = "center"
                elif line_alignment == "right":
                    text_align = "right"

                font_category, _ = _classify_font_size(line_font_size)
                if font_category == "大":
                    tag = "h2"
                elif font_category == "中":
                    tag = "h3"
                else:
                    tag = "div"

                # 调整样式，减小行间距，增大字体
                style = f"left: {line_x}px; top: {line_y}px; font-size: {line_font_size}px; text-align: {text_align}; width: {line_width}px; position: absolute; line-height: 1.0; margin: 0; padding: 0;"

                if tag in ["h2", "h3"]:
                    html_parts.append(
                        f'<{tag} class="text-element" style="{style}">{line_content}</{tag}>'
                    )
                else:
                    html_parts.append(
                        f'<div class="text-element" style="{style}">{line_content}</div>'
                    )

            html_parts.append("</div>")
    else:
        for layout_idx, layout_result in enumerate(layout_results):
            pruned_result = layout_result.get("prunedResult", {})
            parsing_list = pruned_result.get("parsing_res_list", [])

            sorted_blocks = sorted(
                [b for b in parsing_list if b.get("block_order") is not None],
                key=lambda x: x.get("block_order", 0),
            )

            for block in sorted_blocks:
                block_content = block.get("block_content", "")
                block_label = block.get("block_label", "text")
                block_bbox = block.get("block_bbox", [])

                if not block_content:
                    continue

                # 根据block_label设置不同的基础字体大小
                if block_label == "doc_title":
                    base_font_size = 28.0  # 文档标题使用较大字体
                elif block_label == "paragraph_title":
                    base_font_size = 16.0  # 段落标题使用中等字体
                else:
                    # 对于普通文本，根据bbox计算字体大小，如果没有bbox则使用默认值
                    if block_bbox:
                        calculated_size = _calculate_font_size_from_bbox(block_bbox)
                        base_font_size = max(14.0, calculated_size)
                    else:
                        base_font_size = 14.0

                block_content_clean = " ".join(block_content.split())

                matching_issue = None
                matching_issue_idx = None

                if len(block_content_clean) > 3:
                    for issue_idx, issue_data in issue_positions.items():
                        clause_text = issue_data["issue"].get("条款", "")
                        if clause_text:
                            clause_clean = " ".join(clause_text.split())
                            if block_content_clean in clause_clean:
                                matching_issue = issue_data["issue"]
                                matching_issue_idx = issue_idx
                                break

                escaped_content = _escape_html(block_content)

                if matching_issue:
                    risk_level = matching_issue.get("风险等级", "低")
                    risk_class = {
                        "高": "risk-highlight risk-high",
                        "中": "risk-highlight risk-medium",
                        "低": "risk-highlight risk-low",
                    }.get(risk_level, "risk-highlight risk-low")

                    issue_type = matching_issue.get("类型", "")
                    issue_desc = matching_issue.get("问题描述", "")
                    issue_suggestion = matching_issue.get("修改建议", "")

                    tooltip_id = f"tooltip_{layout_idx}_{block.get('block_id')}_{matching_issue_idx}"

                    html_content = f'<span class="{risk_class}" data-issue-idx="{matching_issue_idx}" onmouseenter="showTooltip(event, \'{tooltip_id}\')" onmouseleave="hideTooltip(\'{tooltip_id}\')">{escaped_content}<div id="{tooltip_id}" class="risk-tooltip"><h4>{_escape_html(issue_type)}</h4><p><strong>风险等级：</strong>{risk_level}</p><p><strong>问题描述：</strong>{_escape_html(issue_desc)}</p><p><strong>修改建议：</strong>{_escape_html(issue_suggestion)}</p></div></span>'
                else:
                    html_content = escaped_content

                if block_label == "doc_title":
                    html_parts.append(
                        f'<h1 style="text-align: center; margin: 15px 0; font-size: {base_font_size}px; line-height: 1.2;">{html_content}</h1>'
                    )
                elif block_label == "paragraph_title":
                    html_parts.append(
                        f'<h2 style="margin: 10px 0 5px 0; font-size: {base_font_size}px; line-height: 1.2;">{html_content}</h2>'
                    )
                else:
                    html_parts.append(
                        f'<div class="text-block" style="font-size: {base_font_size}px; line-height: 1.2;">{html_content}</div>'
                    )

    html_parts.append(
        """
    <script>
        // 确保函数在全局作用域中定义
        window.showTooltip = function(event, tooltipId) {
            const tooltip = document.getElementById(tooltipId);
            if (tooltip) {
                tooltip.classList.add('show');
                const rect = event.target.getBoundingClientRect();
                const tooltipRect = tooltip.getBoundingClientRect();
                
                // 默认显示在右侧，并垂直居中
                let left = rect.right + 15; // 15px 偏移量
                let top = rect.top + rect.height / 2 - tooltipRect.height / 2;

                // 如果右侧空间不足，则显示在左侧
                if (left + tooltipRect.width > window.innerWidth - 15) {
                    left = rect.left - tooltipRect.width - 15;
                }

                // 左侧边界检查
                if (left < 15) {
                    left = 15;
                }

                // 上下边界检查
                if (top < 15) {
                    top = 15;
                }
                if (top + tooltipRect.height > window.innerHeight - 15) {
                    top = window.innerHeight - tooltipRect.height - 15;
                }
                
                tooltip.style.left = left + 'px';
                tooltip.style.top = top + 'px';
            }
        };
        
        window.hideTooltip = function(tooltipId) {
            const tooltip = document.getElementById(tooltipId);
            if (tooltip) {
                tooltip.classList.remove('show');
            }
        };
        
    </script>
    </div>
    """
    )

    return "".join(html_parts)


def _escape_html(text: str) -> str:
    """转义HTML特殊字符并处理换行"""
    if not text:
        return ""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
    escaped = escaped.replace("\n", "<br>")
    return escaped


def filter_issues_by_risk(issues: List[Dict], risk_level: str) -> List[Dict]:
    """根据风险等级筛选问题"""
    if risk_level == "全部":
        return issues

    level_mapping = {"重大风险": "高", "一般风险": "中", "低风险": "低"}

    target_level = level_mapping.get(risk_level, "低")
    return [issue for issue in issues if issue.get("风险等级") == target_level]


def render_risk_analysis(risk_analysis: Dict[str, Any]):
    """渲染风险分析结果"""
    st.markdown("### 🔍 风险分析结果")

    statistics = risk_analysis.get("statistics", {})
    all_issues = risk_analysis.get("all_issues", [])

    # 风险统计
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("问题数", statistics.get("total_issues", 0))
    with col2:
        st.metric("高风险", statistics.get("by_level", {}).get("高", 0))
    with col3:
        st.metric("中风险", statistics.get("by_level", {}).get("中", 0))
    with col4:
        st.metric("低风险", statistics.get("by_level", {}).get("低", 0))

    # 风险评分
    risk_score = statistics.get("risk_score", 0)
    risk_level = statistics.get("risk_level", "低")

    st.markdown("### 📊 风险评分")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("风险评分", f"{risk_score}/100")
    with col2:
        level_color = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(risk_level, "⚪")
        st.metric("风险等级", f"{level_color} {risk_level}")

    # 问题详情
    if all_issues:
        st.markdown("### 📋 问题详情")

        # 按风险等级分类
        high_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "高"
        ]
        medium_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "中"
        ]
        low_risk_issues = [
            issue for issue in all_issues if issue.get("风险等级") == "低"
        ]

        # 显示高风险问题
        if high_risk_issues:
            st.markdown("#### 🔴 高风险问题")
            for i, issue in enumerate(high_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=True,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
                    if issue.get("法律依据"):
                        st.write(f"**法律依据:** {issue['法律依据']}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")

        # 显示中风险问题
        if medium_risk_issues:
            st.markdown("#### 🟡 中风险问题")
            for i, issue in enumerate(medium_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=False,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
                    if issue.get("影响分析"):
                        st.write(f"**影响分析:** {issue['影响分析']}")

        # 显示低风险问题
        if low_risk_issues:
            st.markdown("#### 🟢 低风险问题")
            for i, issue in enumerate(low_risk_issues, 1):
                with st.expander(
                    f"{i}. {issue.get('类型', '未知类型')} - {issue.get('条款', 'N/A')[:50]}...",
                    expanded=False,
                ):
                    st.write(f"**问题描述:** {issue.get('问题描述', 'N/A')}")
                    st.write(f"**修改建议:** {issue.get('修改建议', 'N/A')}")
    else:
        st.info("未发现问题")


def render_suggestions(suggestions: Dict[str, Any]):
    """渲染建议和推荐"""
    st.markdown("### 💡 综合建议")

    summary = suggestions.get("summary", {})
    analysis = suggestions.get("analysis", {})
    recommendation = suggestions.get("recommendation", {})

    # 摘要信息
    st.markdown("#### 📊 分析摘要")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("风险评分", f"{summary.get('risk_score', 0)}/100")
    with col2:
        st.metric("问题数", summary.get("total_issues", 0))
    with col3:
        st.metric("违法条款", summary.get("illegal_clauses", 0))

    # 主要风险点
    if analysis.get("key_risks"):
        st.markdown("#### 🔴 主要风险点")
        for risk in analysis["key_risks"]:
            st.write(f"• {risk}")

    # 影响分析
    if analysis.get("impact_analysis"):
        st.markdown("#### 📈 影响分析")
        st.write(analysis["impact_analysis"])

    # 优化建议
    if analysis.get("optimization_suggestions"):
        st.markdown("#### 🛠️ 优化建议")
        for suggestion in analysis["optimization_suggestions"]:
            st.write(f"• {suggestion}")

    # 签约建议
    if recommendation.get("signing_advice"):
        st.markdown("#### 📝 签约建议")
        signing_advice = recommendation["signing_advice"]
        if "不建议" in signing_advice or "❌" in signing_advice:
            st.error(f"**{signing_advice}**")
        elif "谨慎" in signing_advice or "⚠️" in signing_advice:
            st.warning(f"**{signing_advice}**")
        elif "可以" in signing_advice or "✅" in signing_advice:
            st.success(f"**{signing_advice}**")
        else:
            st.info(f"**{signing_advice}**")

    # 谈判要点
    if recommendation.get("negotiation_points"):
        st.markdown("#### 🤝 谈判要点")
        for point in recommendation["negotiation_points"]:
            st.write(f"• {point}")

    # 风险缓解措施
    if recommendation.get("risk_mitigation"):
        st.markdown("#### 🛡️ 风险缓解措施")
        for measure in recommendation["risk_mitigation"]:
            st.write(f"• {measure}")


def render_markdown_box(markdown_text: str, height: int = 780, enable_scroll: bool = True):
    """将Markdown内容渲染在框中，支持复制"""
    if not markdown_text:
        st.info("暂无内容")
        return

    try:
        import markdown as md_lib

        html_body = md_lib.markdown(
            markdown_text,
            extensions=["extra", "codehilite", "tables", "fenced_code"],
        )
    except Exception:
        import html as html_escape

        escaped = html_escape.escape(markdown_text)
        html_body = escaped.replace("\n", "<br>")

    if enable_scroll:
        overflow_style = "overflow-y: auto; overflow-x: auto;"
        height_style = f"height: {height}px;"
    else:
        overflow_style = "overflow: visible;"
        height_style = "min-height: 100%;"

    html_template = f"""
    <style>
    body {{
        margin: 0;
        padding: 0;
    }}
    .md-preview-box {{
        {height_style}
        {overflow_style}
        padding: 16px;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        background-color: #fff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .md-preview-box *,
    .md-preview-box {{
        user-select: text !important;
        -webkit-user-select: text !important;
        -moz-user-select: text !important;
        -ms-user-select: text !important;
        cursor: text !important;
    }}
    .md-preview-box pre {{
        background: #f6f8fa;
        padding: 12px;
        border-radius: 6px;
        overflow-x: auto;
    }}
    .md-preview-box code {{
        background: #f6f8fa;
        padding: 2px 4px;
        border-radius: 4px;
        font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
    }}
    .md-preview-box table {{
        border-collapse: collapse;
        width: 100%;
        margin: 1em 0;
    }}
    .md-preview-box table th,
    .md-preview-box table td {{
        border: 1px solid #dee2e6;
        padding: 8px 12px;
        text-align: left;
    }}
    .md-preview-box table th {{
        background-color: #f2f4f7;
        font-weight: 600;
    }}
    </style>
    <div class="md-preview-box">{html_body}</div>
    """

    if enable_scroll:
        iframe_height = height
        scrolling_enabled = False
    else:
        iframe_height = 1500
        scrolling_enabled = False
    
    st.components.v1.html(
        html_template,
        height=iframe_height,
        scrolling=scrolling_enabled,
    )
