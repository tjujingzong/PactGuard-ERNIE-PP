# Please make sure the requests library is installed
# pip install requests
import base64
import json
import os
import requests

API_URL = "https://uft8mbk5g3ndv3m1.aistudio-app.com/layout-parsing"
TOKEN = "6f83207f504098cd644f75618f9ed9507a5dfa7b"

file_path = "E:\Opensource\pp-contract\contracts\劳动合同.pdf"

with open(file_path, "rb") as file:
    file_bytes = file.read()
    file_data = base64.b64encode(file_bytes).decode("ascii")

headers = {"Authorization": f"token {TOKEN}", "Content-Type": "application/json"}

# For PDF documents, set `fileType` to 0; for images, set `fileType` to 1
payload = {
    "file": file_data,
    "fileType": 0,
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
    "useChartRecognition": False,
}

response = requests.post(API_URL, json=payload, headers=headers)
print(response.status_code)
assert response.status_code == 200
result = response.json()["result"]


# save result to json
with open("ppv3_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)


output_dir = "output2"
os.makedirs(output_dir, exist_ok=True)
print(result)
for i, res in enumerate(result["layoutParsingResults"]):
    md_filename = os.path.join(output_dir, f"doc_{i}.md")
    with open(md_filename, "w", encoding="utf-8") as md_file:
        md_file.write(res["markdown"]["text"])
    print(f"Markdown document saved at {md_filename}")
    for img_path, img in res["markdown"]["images"].items():
        full_img_path = os.path.join(output_dir, img_path)
        os.makedirs(os.path.dirname(full_img_path), exist_ok=True)
        img_bytes = requests.get(img).content
        with open(full_img_path, "wb") as img_file:
            img_file.write(img_bytes)
        print(f"Image saved to: {full_img_path}")
    for img_name, img in res["outputImages"].items():
        img_response = requests.get(img)
        if img_response.status_code == 200:
            # Save image to local
            filename = os.path.join(output_dir, f"{img_name}_{i}.jpg")
            with open(filename, "wb") as f:
                f.write(img_response.content)
            print(f"Image saved to: {filename}")
        else:
            print(f"Failed to download image, status code: {img_response.status_code}")
