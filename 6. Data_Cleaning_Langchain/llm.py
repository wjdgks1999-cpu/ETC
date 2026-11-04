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

df = pd.read_excel(r'데이터 정제.xlsx', dtype="object")
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
    Preprocess_Content: Optional[str] = Field(
        default=None,
        description="개인정보를 삭제한 공고문 정보"
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
당신은 정부·공공기관의 사업 공고문에서 개인정보를 삭제하는 데이터 정제 전문가입니다.

입력된 텍스트는 공고문 내용에는 사업 담당자의 개인정보가 존재할 수 있습니다.

공고문에서 개인정보를 삭제하고, 개인정보를 삭제한 공고문을 결과로 내주세요.

삭제할때 개인정보가 있는 문구 전체를 삭제해야합니다.(사업담당자: 주임 홍길동(전화번호) 전체를 삭제)

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

    df.loc[i,"내용"] = result.Preprocess_Content

df.to_excel(r'데이터 정제2.xlsx' ,index=False)