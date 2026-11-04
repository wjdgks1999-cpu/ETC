import pandas as pd

df = pd.read_excel(r'Q17.xlsx')
df.shape
df.info()
df.dropna(inplace=True)
df.shape
df.head(1)

df.columns = ['No.', 'answer']

df['category'] = pd.NA
df.reset_index(inplace=True,drop=True)

from dotenv import load_dotenv
load_dotenv('.env')

#%% 세팅
from pydantic import BaseModel, Field
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

#1. 결과 폼
class category(BaseModel) :
    category : str = Field(description="답변의 주제")

#2. 프롬프트 불러오기
with open("prompt_ai.md", "r", encoding="utf-8") as f:
    classify_template = f.read()
classify_prompt = PromptTemplate.from_template(classify_template)
classify_prompt.input_variables

#3. 질문 설정
question = "인공지능(AI)은 음성비서, 챗봇 상담, 길 안내(내비게이션), 질병 진단 지원 등 다양한 서비스에 활용되고 있습니다.   이러한 AI 서비스 개발에 도움이 되도록 한국여성인권진흥원이 우선 개방했으면 하는 항목은 무엇입니까?"

#%% 반복문
for i in range(df.shape[0]) :
    print(f"진행률: {i+1}/{df.shape[0]}")
    target_row = df.loc[i,]
    target_answer = target_row['answer']

    input_data = {
        "question" : question,
        "answer" : target_answer
    }
    llm = ChatOpenAI(model="gpt-4o-mini")
    result_categories = (classify_prompt | llm.with_structured_output(category)).invoke(
            input_data
        )
    result_categories = result_categories.model_dump()['category']

    df.loc[i,'category'] = result_categories

df.info()
df.to_excel('Q17_AI문항_분류결과.xlsx', index=False)

