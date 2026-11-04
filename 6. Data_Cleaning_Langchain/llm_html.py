import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import pandas as pd

# ============================================================
# 0. 데이터 불러오기
# ============================================================

df = pd.read_csv(r'data.csv', encoding="cp949")
df.shape
df.head(1)
df.info()

# ============================================================
# 1. 환경변수
# ============================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")


# ============================================================
# 2. 출력 데이터 구조 정의
# ============================================================

class ContentInfo(BaseModel):
    content: Optional[str] = Field(
        default=None,
        description="내용"
    )

# ============================================================
# 3. OpenAI 모델
# ============================================================

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
)

# 구조화 출력 적용
structured_llm = llm.with_structured_output(ContentInfo)

# ============================================================
# 4. 프롬프트
# ============================================================

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
당신은 텍스트 데이터 정제 전문가입니다.

입력된 텍스트에는 내용 뿐만 아니라 html 양식도 같이 혼재되어 있습니다.

html 양식을 제거하고 내용만을 추출하여주십시오.

다음 내용을 분석하십시오.

------------------------------
{target_contents}
------------------------------
"""
    )
])

# ============================================================
# 5. Chain
# ============================================================

chain = prompt | structured_llm

# ============================================================
# 6. 반복문
# ============================================================

df.head(1)

for i in range(df.shape[0]) :
    print(f"진행도 : {i}/{df.shape[0]}")
    target_contents = df.loc[i, "내용"]

    result = chain.invoke({
        "target_contents" : target_contents
    })

    df.loc[i,"내용"] = result.content

df.to_excel(r'데이터 정제.xlsx' ,index=False)