import os
import asyncio
import json
import pandas as pd
import datetime
import re
from typing import List
from langchain_core.documents import Document
from langchain_upstage import UpstageDocumentParseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings
from QA_processor import generate_qa_from_chunk

# API 키 설정
os.environ["UPSTAGE_API_KEY"] = settings.UPSTAGE_API_KEY

def get_parsing_loader(
    filepath: str
) -> UpstageDocumentParseLoader:    
    return UpstageDocumentParseLoader(
        file_path=filepath,
        output_format="markdown", # 결과물은 md 파일(수정필요)
        ocr="auto",
        split="none" # 페이지 단위로 파일을 만듬(수정필요)
    )

async def parse_document_async(file_path: str) -> List[Document]:
    """
    타겟 파일을 비동기적으로 파싱하여 Document 리스트를 반환합니다.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    
    try:
        # 로더 생성
        loader = get_parsing_loader(filepath=file_path)
        
        # 비동기 방식으로 로드 (aload 사용)
        pages = await loader.aload()
        
        print(f"✅ 비동기 파싱 성공: {file_path} (요청된 {len(pages)}개 요소 추출 완료)")
        return pages
        
    except Exception as e:
        print(f"❌ 파싱 중 오류 발생: {e}")
        return []

async def main():
    target_file = 'target_doc.pdf' # 확장자 다를 시 수정 필요
    output_dir = 'parsing_result'
    if not os.path.exists(output_dir): os.makedirs(output_dir)

    # 1. 문서 파싱
    docs = await parse_document_async(target_file)
    if not docs: return

    # 2. 모든 페이지를 하나의 텍스트로 합치기
    full_text = "\n".join([doc.page_content for doc in docs])

    # 💾  파싱된 전체 텍스트 저장
    parsed_md_path = os.path.join(output_dir, '1_parsed_full_text.md')
    with open(parsed_md_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"💾 [중간 저장] 전체 파싱 텍스트 저장 완료: {parsed_md_path}")

    # 3. LangChain 분할기 설정 (핵심 변경 사항)
    # chunk_size: 덩어리 하나의 최대 글자 수 (약 3000~4000자 권장)
    # chunk_overlap: 앞뒤로 겹치게 가져갈 글자 수 (문맥 단절 방지)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=10000,
        chunk_overlap=1000, 
        separators=["\n\n", "\n", ". ", " ", ""] # 문단 먼저, 안되면 문장, 안되면 띄어쓰기 기준
    )
    
    # 텍스트를 청크(덩어리) 리스트로 쪼개기
    chunks = text_splitter.split_text(full_text)
    num_chunks = len(chunks)
    
    print(f"🔍 전체 문서를 {num_chunks}개의 청크로 분할 완료 (문맥 보존 Overlap 적용).")

    # 💾  분할된 청크 데이터 저장
    # LLM에 들어가기 직전의 데이터 상태를 확인하고 프롬프트를 튜닝하는 용도
    chunk_data = [{"chunk_id": i+1, "content": chunk} for i, chunk in enumerate(chunks)]
    chunks_json_path = os.path.join(output_dir, '2_chunked_data.json')
    with open(chunks_json_path, 'w', encoding='utf-8') as f:
        json.dump(chunk_data, f, ensure_ascii=False, indent=2)
    print(f"💾 [중간 저장] 분할된 청크 데이터 저장 완료: {chunks_json_path}\n")

    # 4. 목표 Q&A 개수(30쌍)에 맞춰 청크당 할당량 계산
    q_per_chunk = max(1, 40 // num_chunks) if num_chunks > 0 else 40
    
    all_qa_list = []

    for i, chunk_text in enumerate(chunks, 1):
        print(f"⏳ [{i}/{num_chunks}] 번째 덩어리 분석 중... (목표 추출: {q_per_chunk}개)")

        # 청크별로 Gemini 호출
        chunk_qa = await generate_qa_from_chunk(chunk_text, count=q_per_chunk)
        all_qa_list.extend(chunk_qa)
        
        # 전체 30쌍 언저리가 되면 중단 (여유분 포함 35쌍에서 컷)
        if len(all_qa_list) >= 35: 
            break

        # API 부하 방지를 위해 짧은 휴식
        await asyncio.sleep(5)

    # 5. 엑셀 저장
    if all_qa_list:
        df = pd.DataFrame(all_qa_list)
        df.rename(columns={'question': '질문', 'answer': '답변'}, inplace=True)
        save_path = os.path.join(output_dir, 'universal_chunking_QA.xlsx')
        
        try:
            # 기본 이름으로 저장 시도
            df.to_excel(save_path, index=False)
            print(f"\n✅ 완료! 총 {len(all_qa_list)}쌍의 Q&A가 저장되었습니다: {save_path}")
            
        except PermissionError:
            # 만약 엑셀 파일이 열려 있어서 저장이 안 된다면? 시간 붙여서 새 이름으로 저장!
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = os.path.join(output_dir, f'universal_chunking_QA_{now}.xlsx')
            df.to_excel(fallback_path, index=False)
            print(f"\n⚠️ 기존 파일이 열려 있어 새 이름으로 안전하게 저장했습니다: {fallback_path}")

if __name__ == "__main__":
    asyncio.run(main())