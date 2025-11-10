import base64
import urllib
import requests
import os
import time


def main():

    url = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task"

    
    # 目标文件路径
    target_path = 'E:\\Opensource\\pp-contract\\contracts\\劳动合同.pdf'

    # 以 x-www-form-urlencoded 方式构建参数
    params = {
        "file_data": get_file_content_as_base64(target_path),
        "file_name": os.path.basename(target_path),
        "recognize_formula": "False",
        "analysis_chart": "False",
        "angle_adjust": "False",
        "parse_image_layout": "False",
        "language_type": "CHN_ENG",
        "switch_digital_width": "auto",
    }

    payload = urllib.parse.urlencode(params)
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Authorization": "Bearer bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f",
    }

    response = requests.request(
        "POST", url, headers=headers, data=payload.encode("utf-8")
    )

    response.encoding = "utf-8"
    print(response.text)

    # 在创建任务成功后，解析返回获取 task_id 并立即查询任务状态
    try:
        resp_json = response.json()
        task_id = (
            resp_json.get("result", {}).get("task_id")
            if isinstance(resp_json, dict)
            else None
        )
        if task_id:
            query_url = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task/query"
            query_payload = f"task_id={task_id}"
            query_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Authorization": headers.get("Authorization", ""),
            }
            # 轮询查询，直到 status 为 success 或达到最大重试次数
            max_retries = 30
            interval_seconds = 2
            for i in range(max_retries):
                query_resp = requests.request(
                    "POST", query_url, headers=query_headers, data=query_payload.encode("utf-8")
                )
                query_resp.encoding = "utf-8"
                try:
                    result_json = query_resp.json()
                except Exception:
                    print(query_resp.text)
                    break

                status = result_json.get("result", {}).get("status")
                print(result_json)

                if status == "success":
                    break
                if status in ("failed", "error"):
                    break
                time.sleep(interval_seconds)
        else:
            print("未获取到 task_id，无法查询任务状态。")
    except Exception as e:
        print(f"解析task_id或查询任务状态时发生错误: {e}")


def get_file_content_as_base64(path, urlencoded=False):
    """
    获取文件base64编码
    :param path: 文件路径
    :param urlencoded: 是否对结果进行urlencoded
    :return: base64编码信息
    """
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf8")
        if urlencoded:
            content = urllib.parse.quote_plus(content)
    return content


if __name__ == "__main__":
    main()
