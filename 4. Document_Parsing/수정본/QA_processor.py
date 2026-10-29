import json
from google import genai
from google.genai import types
from config import settings

# 1. 새 SDK 방식의 클라이언트 초기화
client = genai.Client(api_key=settings.GEMINI_API_KEY)

async def generate_qa_from_chunk(text: str, count: int = 3) -> list:
    """
    텍스트 구간에서 지정된 개수(count)만큼의 Q&A를 생성합니다.
    """
    prompt = f"""
    당신은 전문 교육 컨텐츠 제작자입니다. 
    다음 문서 내용을 바탕으로, 독자가 전체 맥락을 이해하는 데 꼭 필요한 핵심 질문과 답변을 딱 {count}개만 생성해주세요.
    
    [지침]
    1. 답변은 친절하고 명확하게 2줄 이내로 작성하세요.
    2. 문서 내에 평가 산식이나 수식이 텍스트로 깨져서 포함되어 있을 수 있습니다. 수식을 답변에 포함할 때는 흩어진 텍스트를 논리적으로 조합하여 'A 나누기 B 곱하기 C'와 같이 풀어쓰거나 명확한 문장으로 다듬어서 설명해 주세요.
    3. 출력 형식은 반드시 아래 JSON 배열 형식을 지키세요.
    
    [
        {{"question": "질문", "answer": "답변"}}
    ]

    문서 내용:
    {text}
    """
    
    try:
        # 2. 새 SDK의 비동기 호출 방식 (client.aio.models...)
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
        # 3. 안전 필터링 등으로 인해 텍스트가 비어있는지 사전 체크
        if not response.text:
            print(f"⚠️ 안전 필터링 등 사유로 응답이 생성되지 않았습니다. (prompt 일부: {text[:50]}...)")
            return []
            
        return json.loads(response.text)
        
    except Exception as e:
        print(f"❌ Gemini API 호출 또는 JSON 파싱 오류 발생: {e}")
        return []