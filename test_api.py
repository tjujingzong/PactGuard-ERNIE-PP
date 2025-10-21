# 请安装 OpenAI SDK : pip install openai
# apiKey 获取地址： https://console.bce.baidu.com/iam/#/iam/apikey/list
# 支持的模型列表： https://cloud.baidu.com/doc/WENXINWORKSHOP/s/Fm2vrveyu

from openai import OpenAI
client = OpenAI(
    base_url='https://qianfan.baidubce.com/v2',
    api_key='bce-v3/ALTAK-IS6uG1qXcgDDP9RrmjYD9/ede55d516092e0ca5e9041eab19455df12c7db7f'
)
response = client.chat.completions.create(
    model="ernie-4.5-turbo-128k",
    extra_body={ 
        "stream":False
    },
    messages=[
        {
            "role": "user",
            "content": "你好，我是小度，很高兴认识你"
        }
    ]
)
print(response)
