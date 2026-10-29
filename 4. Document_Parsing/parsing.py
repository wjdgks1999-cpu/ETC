import os
import asyncio
from typing import List
from langchain_upstage import UpstageDocumentParseLoader
from langchain_core.documents import Document
from config import settings

# API 키 설정
os.environ["UPSTAGE_API_KEY"] = settings.UPSTAGE_API_KEY

def get_parsing_loader(
    filepath: str
) -> UpstageDocumentParseLoader:    
    return UpstageDocumentParseLoader(
        file_path=filepath,
        output_format="markdown", # 결과물은 md 파일(수정필요)
        ocr="force",
        split="page" # 페이지 단위로 파일을 만듬(수정필요)
    )

async def parse_hwp_async(file_path: str) -> List[Document]:
    """
    HWP 파일을 비동기적으로 파싱하여 Document 리스트를 반환합니다.
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
    # --- 활용 예시 ---
    target_file = 'target_doc.hwpx' # 파일 디렉토리(수정필요)
    output_dir = 'parsing_result' # 파싱 결과를 저장하는 곳
    
    # 저장할 디렉토리가 없으면 생성
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 비동기 함수 호출
    docs = await parse_hwp_async(target_file)

    # enumerate를 사용하면 인덱스(i)와 내용(doc)을 동시에 다룰 수 있어 편리합니다.
    for i, doc in enumerate(docs, start=1):
        save_path = os.path.join(output_dir, f'parsing_page_{i}.md')
        
        with open(save_path, "w", encoding="utf-8") as f:
            # 각 순서에 맞는 페이지 내용(doc.page_content)을 기록합니다.
            f.write(doc.page_content)
            
    print(f"✅ 총 {len(docs)}개의 페이지가 '{output_dir}' 폴더에 저장되었습니다.")

# 스크립트 실행
if __name__ == "__main__":
    asyncio.run(main())