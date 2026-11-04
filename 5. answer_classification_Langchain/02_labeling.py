import pandas as pd
df = pd.read_excel(r'Q16.xlsx')
df.shape
df.info()
df.dropna(inplace=True)
df.shape
df.head(1)
df['category'] = pd.isna
df.reset_index(inplace=True, drop=True)

from dotenv import load_dotenv
load_dotenv('.env')

df.columns = ['No.', 'answer', 'category']

#%% 세팅
from pydantic import BaseModel, Field
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

#1. 결과 폼
class category(BaseModel) :
    category : str = Field(description="답변의 주제")

class categories(BaseModel) :
    categories : list[category] = Field(description="답변의 주제 리스트")

#2. 프롬프트 불러오기
with open("prompt.md", "r", encoding="utf-8") as f:
    classify_template = f.read()
classify_prompt = PromptTemplate.from_template(classify_template)
classify_prompt.input_variables

#3. 질문 설정
question = "한국여성인권진흥원의 공공데이터 개방과 활용과 관련하여 자유롭게 의견이나 건의사항을 작성해 주세요."

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
    result_categories = (classify_prompt | llm.with_structured_output(categories)).invoke(
        input_data)
    result_categories_list = result_categories.model_dump()['categories']
    
    #정리
    categories_final = []
    for individual in result_categories_list :
        categories_final.append(individual['category'])

    df.loc[i,'category'] = str(categories_final).replace("['","").replace("']","")


df.info()
df.to_excel('Q16_분류결과.xlsx', index=False)

#%% 이어서돌리기
import pandas as pd
df = pd.read_excel(r'분류결과.xlsx')
df.shape
df.info()
df.dropna(inplace=True)
df.shape
df.head(1)
df.reset_index(inplace=True, drop=True)
df.loc[249,]

from dotenv import load_dotenv
load_dotenv('.env')

from pydantic import BaseModel, Field
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

#1. 결과 폼
class category(BaseModel) :
    category : str = Field(description="답변의 주제")

class categories(BaseModel) :
    categories : list[category] = Field(description="답변의 주제 리스트")

#2. 프롬프트 불러오기
with open("prompt.md", "r", encoding="utf-8") as f:
    classify_template = f.read()
classify_prompt = PromptTemplate.from_template(classify_template)
classify_prompt.input_variables

#3. 질문 설정
question = "한국데이터산업진흥원의 공공데이터 개방·활용과 관련하여 자유롭게 의견이나 건의사항을 작성해 주세요."

for i in range(249, df.shape[0]) :
    print(f"진행률: {i+1}/{df.shape[0]}")
    target_row = df.loc[i,]
    target_answer = target_row['answer']

    input_data = {
        "question" : question,
        "answer" : target_answer
    }
    llm = ChatOpenAI(model="gpt-4o-mini")
    result_categories = (classify_prompt | llm.with_structured_output(categories)).invoke(
        input_data)
    result_categories_list = result_categories.model_dump()['categories']
    
    #정리
    categories_final = []
    for individual in result_categories_list :
        categories_final.append(individual['category'])

    df.loc[i,'category'] = str(categories_final).replace("['","").replace("']","")


df.info()

df.to_excel('분류결과.xlsx', index=False)





