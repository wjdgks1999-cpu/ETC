# 공공데이터 개방 제외 사유 검토

이 코드는 기관이 보유·운영하는 DB의 테이블별 공공데이터 개방 제외 사유를 작성·검수하는 업무에 사용한 코드를 바탕으로 한다. 

실제 업무에서는 로컬 환경에서 구동한 대규모 언어 모델(LLM)을 연결했으며, 현재 저장소에서는 모델 호출에 OpenAI API를 사용한다.

## 사용 목적과 업무 활용

행정안전부 주관 **공공데이터 제공운영 및 데이터기반행정 평가**의 ‘**메타관리시스템 기반 공공데이터 개방계획 수립 및 이행**’ 지표에 따라 기관 DB 테이블의 개방 및 제외 사유 작성 등 개방 대상 관리 과정을 자동화했다.

이 코드는 테이블명과 컬럼 정보를 바탕으로 제외 코드와 사유를 작성·검수하고 Excel 자료로 정리하는 데 사용한다. 테이블·컬럼 자료의 이름 비교는 사유 작성에 앞서 두 자료의 연결과 누락을 확인하기 위한 준비 단계이다.


| 업무 단계        | 코드의 역할                                                                                                                         |
|----------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| 검토 자료 준비 | 테이블 목록과 컬럼 자료의 테이블명 일치·누락 비교                                                                  |
| 제외 사유 작성 | 테이블·컬럼 정보를 주된 근거로 제외 코드·사유 작성. 정보시스템명·논리DB명은 보조 맥락으로 활용 |
| 검수와 정리     | 작성 결과를 검수·교정하고, 최종 결과·추가 검토 사항·처리 내역을 Excel로 정리                             |


컬럼이 2개 이하인 테이블은 업무 규칙에 따라 **제외코드 9**, \*\*‘3열 5행 미만 테이블’\*\*로 고정 처리한다.

그 외 테이블은 작성·검수·교정 과정을 거치며, 제외 근거가 정리되지 않은 결과는 판단 보류 또는 추가 검토 대상으로 남긴다.

## 코드 구조

```mermaid
flowchart TB  
    entry["review.py<br/>실행 진입점"] --> cli  
    subgraph package ["metadata_review/"]  
        cli["cli.py<br/>비교·검토 명령"] --> comparison["comparison.py<br/>사전 이름 대조"]  
        cli --> workflow["workflow.py<br/>검토 작업 실행"]  
        settings["config.py · schemas.py<br/>설정·입출력 형식"] -.-> workflow  
        inputs["inputs.py<br/>메타데이터 연결"] --> workflow  
        workflow --> pipeline["pipeline.py · rules.py<br/>고정 규칙·작성·검수·교정"]  
        prompts["prompts.py · prompt/<br/>판단 기준·단계별 지침"] --> pipeline  
        pipeline --> export["export.py<br/>결과 정리"]  
    end  
    comparison --> check["이름 비교 결과"]  
    export --> output["테이블별 검토 Excel"]
```

## 간단한 실행

테이블·컬럼 정보 Excel을 준비한 뒤 이 폴더에서 실행한다.

```powershell
python -m pip install -r requirements.txt  
python review.py compare --tables tables.xlsx --columns columns.xlsx  
python review.py run --tables tables.xlsx --columns columns.xlsx
```

컬럼이 3개 이상인 테이블을 검토하려면 `.env.example`을 참고해 `.env`에 `OPENAI_API_KEY`와 `OPENAI_MODEL`을 설정한다. 모델명은 `--model` 옵션으로도 지정할 수 있다. 테이블명 비교와 컬럼이 2개 이하인 테이블의 검토는 API 호출 없이 실행된다. 시트·출력 경로 등 추가 옵션은 각 명령의 `--help`에서 확인한다.

 
