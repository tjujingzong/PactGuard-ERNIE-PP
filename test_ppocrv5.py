# Please make sure the requests library is installed
# pip install requests
import os
import base64
import requests
import json

API_URL = "https://t101v7sbh6gbz1e4.aistudio-app.com/ocr"
TOKEN = "6f83207f504098cd644f75618f9ed9507a5dfa7b"

file_path = "E:\Opensource\pp-contract\contracts\劳动合同.pdf"
input_filename = os.path.splitext(os.path.basename(file_path))[0]

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
}

response = requests.post(API_URL, json=payload, headers=headers)

assert response.status_code == 200
result = response.json()["result"]
print(result)
#
# save result to json
with open("ocr_result.json", "w") as f:
    json.dump(result, f)
# os.makedirs("output", exist_ok=True)

# for i, res in enumerate(result["ocrResults"]):
#     print(res["prunedResult"])
#     image_url = res["ocrImage"]
#     img_response = requests.get(image_url)
#     if img_response.status_code == 200:
#         # Save image to local
#         filename = f"output2/{input_filename}_{i}.jpg"
#         with open(filename, "wb") as f:
#             f.write(img_response.content)
#         print(f"Image saved to: {filename}")
#     else:
#         print(f"Failed to download image, status code: {img_response.status_code}")
