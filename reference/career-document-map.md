# 커리어 문서 지도

기준일: 2026.11.16. `docs/career/`의 문서 위치와 작성 상태를 관리합니다. 웹사이트 문안은 [이력 개요](overview.md)에서 시작하고, 공개 기준은 [README](README.md)와 각 상세 기록에서 확인합니다. 공감데이터는 [전용 안내](records/gonggam-data/README.md)에서 평가제도 → 담당업무 → 특이 사례 순서로 읽습니다.

## 폴더 구조

```text
docs/career/
├─ README.md                 목적·작성 단위·근거 및 공개 기준
├─ career-document-map.md         문서 위치·전체 작성 목록·진행 상태 (이 문서)
├─ overview.md               전체 이력 요약 (완료)
├─ records/                  기존 개별 이력 21개 + 공감데이터 안내·평가·사례 4개
│  └─ gonggam-data/
│     ├─ README.md           전체 안내·트리
│     ├─ employment.md       회사 경력
│     ├─ institutions-by-year.md  연도·기관·업무 근거
│     ├─ evaluation/         평가 개요·2026년 지표와 업무 연결
│     ├─ work/               기존 담당업무 8개
│     └─ cases/              GOAD 직접 분석 특이 사례
└─ reference/                원본 증빙·Excel·평가편람·추가자료
   ├─ 1. 학교 졸업 및 성적/
   ├─ 2. 과거 이력서/
   ├─ 3. 프로젝트 관련 문서/
   │  └─ 공감데이터 이력 추가자료/
   │     ├─ 1. 데이터 분석 및 정책활용 수행사례_한국언론진흥재단/
   │     └─ 2. 공공데이터 활용사례집_과학기술정보통신부/
   └─ 4. 기타/
```

Markdown 파일은 28개(루트 3개, 기존 개별 기록 21개, 새 안내·평가·사례 문서 4개)입니다. 이력 개요를 포함해 기존 승인된 이력 항목은 22개입니다. 특이 사례의 분리는 새 독립 프로젝트 실적을 추가한 것이 아니며, 신규 평가 설명에 기존 이력의 승인 상태를 자동 적용하지 않습니다.

## 전체 진행 상태

| 작성 상태 | 수 | 의미 |
| --- | --- | --- |
| 완료 | 22 | 사용자 문안 확인 및 승인 완료 |
| 합계 | 22 | 완료 전 항목 없음 |

**13~19번 AN·SH·SY·PR·SU·DQ·CB는 사용자 확인 범위로 이력 작성 완료**입니다 (2026.11.04). CB는 보완 답변·Excel 재대조 반영 후 사용자의 문안 동의·다음 작업 문의를 반영했습니다. 국토부 CB 업무는 기관 최종 확인 대기로 진행 중이며 이력 작성 완료와 구분합니다. 기존 공개 제한·미확인·미재현 사항은 유지합니다. FindSeoul은 사용자 문안 확인으로 완료했습니다. 기술 역량·이력 개요와 회사 경력·공통 기관 이력표·민간활용은 최종 문안 승인으로 완료했습니다.

### 기존 완료 기록 9개

기록 내용과 공개 범위는 사용자 확인을 마쳤습니다 (학력·ACT·논문: 2026.10.29, 나머지: 2026.11.02). 각 문서에 남긴 기억·측정·미확인 사항은 그대로 유효하며, 완료 표시는 모든 수치를 독립적으로 재현했다는 뜻이 아닙니다.

| 번호 | 이력·시작 시점 | 문서 | 상태·확인 범위 |
| --- | --- | --- | --- |
| 01 | 중앙대학교 심리학과 학부 · 2013.03.02 | [education-chung-ang-undergraduate.md](records/education-chung-ang-undergraduate.md) | 완료 · 학력·학업 경험 공개 가능 |
| 02 | 중앙대학교 대학원 심리학과 석사 · 2019.09.02 | [education-chung-ang-graduate.md](records/education-chung-ang-graduate.md) | 완료 · 학력·연구 경험 공개 가능 |
| 03 | ACT 적응적 인지검사 개발 · 2021.10.01 | [project-act-adaptive-cognitive-test.md](records/project-act-adaptive-cognitive-test.md) | 완료 · 명칭·역할·수치·공개 링크 허용. 일부 평가 조건은 회상 |
| 04 | AMT 활용 적응적 심리검사 논문 · 2021.12 | [publication-amt-computerized-adaptive-testing.md](records/publication-amt-computerized-adaptive-testing.md) | 완료 · 서지·연구 내용·기여 공개 가능 |
| 05 | 코리아리서치인터내셔널 경력 · 2022.06.07 | [employment-korea-research-international.md](records/employment-korea-research-international.md) | 완료 · 회사·협력사·업무·코드·사업비 공개 가능. 6천만원 수주 건의 세부 범위는 미확인 |
| 06 | 국내 의류산업 분석·앱 개발 · 2022.06.07 | [project-domestic-clothing-industry-analysis.md](records/project-domestic-clothing-industry-analysis.md) | 완료 · 데이터·수행·수치 공개 가능, 고객사 익명. 종료 후 유지보수 반영 |
| 07 | 국민건강보험 소셜 데이터 대시보드 · 2022.10 | [project-nhis-social-data-dashboard.md](records/project-nhis-social-data-dashboard.md) | 완료 · 명칭·주제·데이터·수행 공개 가능. 토픽·키워드 일부 참여는 회상 |
| 08 | AI 정성 데이터 분석 플랫폼 · 2023.04.01 | [project-ai-qualitative-data-labeling-platform.md](records/project-ai-qualitative-data-labeling-platform.md) | 완료 · 인력 3명 운영·Python 자동화·성과 반영. 시간 절감의 세부 측정 자료는 미확인 |
| 09 | 제주도 관광지 추천 웹서비스 · 2023.09 | [project-jeju-travel-recommendation.md](records/project-jeju-travel-recommendation.md) | 완료 · 웹 MVP 외부 사용·배포 해결·후속 중단 반영. 현재 운영·성능 재현은 미확인 |

### 공감데이터 작성 대상 10개

기관·연도별 사업을 독립 프로젝트로 나누지 않고 회사 1개·공통 근거 1개·업무 8개로 정리합니다. 기존 10개 기록은 `records/gonggam-data/`의 회사 개요·기관 이력표·`work/`로 이동했습니다. 기존 승인 상태는 아래 각 기록을 따릅니다.

| 추가 문서 | 역할·상태 |
| --- | --- |
| [공감데이터 안내](records/gonggam-data/README.md) | 실제 폴더 트리와 읽는 순서 |
| [평가제도 개요](records/gonggam-data/evaluation/overview.md) | 공식 자료 조사, 두 평가의 차이·운영 맥락·연도별 확인 범위 |
| [2026년 지표와 담당업무](records/gonggam-data/evaluation/indicators-2026.md) | 제공된 2026.7 편람의 전체 구조·배점·업무 연결 |
| [GOAD 직접 분석 사례](records/gonggam-data/cases/kpf-goad-2025.md) | 기존 승인 AN 상세를 분리. 일반 업무와의 차이·기여·근거·공개 제한 유지 |

| 번호 | 문서·업무 | 현재 또는 예정 파일 | 상태 |
| --- | --- | --- | --- |
| 10 | 회사 경력 개요 | [gonggam-data/employment.md](records/gonggam-data/employment.md) | 완료 · 사용자 최종 문안 승인 (2026.11.06) |
| 11 | 연도별 수행 기관·담당 업무 이력표 | [gonggam-data/institutions-by-year.md](records/gonggam-data/institutions-by-year.md) | 완료 · 사용자 최종 문안 승인 (2026.11.06) |
| 12 | PU · 공공데이터 민간활용 성과 | [gonggam-data/work/private-data-utilization.md](records/gonggam-data/work/private-data-utilization.md) | 완료 · 사용자 최종 문안 승인 (2026.11.06) |
| 13 | AN · 데이터 분석 및 정책활용 실적 | [gonggam-data/work/analysis-policy-use.md](records/gonggam-data/work/analysis-policy-use.md) | 완료 · 원본 대조·보완 답변 반영 후 사용자 확인 (2026.11.04). 추가 질문 없음 |
| 14 | SH · 공유데이터 실적 | [gonggam-data/work/shared-data.md](records/gonggam-data/work/shared-data.md) | 완료 · 원본 대조·보완 답변·대표 코드 2개 열람 반영 후 사용자 확인 (2026.11.04). 추가 질문 없음 |
| 15 | SY · 가명정보 제공 및 합성데이터 개방 실적 | [gonggam-data/work/pseudonymous-synthetic-data.md](records/gonggam-data/work/pseudonymous-synthetic-data.md) | 완료 · S0·S7·G1·공개 Python 4개·보완 답변 반영 후 사용자 확인 (2026.11.04). 추가 질문 없음 |
| 16 | PR · 제안서 작성 | [gonggam-data/work/proposals.md](records/gonggam-data/work/proposals.md) | 완료 · 확인된 범위의 문안 승인·다음 업무 요청 (2026.11.04). 미답변 세부 방법·협업·일정·발표 분담은 미확인으로 유지 |
| 17 | SU · 대국민 공공데이터 활용 수요조사 | [gonggam-data/work/public-data-demand-survey.md](records/gonggam-data/work/public-data-demand-survey.md) | 완료 · S0·S2·공개 코드·보완 답변 반영 후 사용자 확인 (2026.11.04). 추가 질문 없음 |
| 18 | DQ · 데이터 값 관리 | [gonggam-data/work/data-quality-management.md](records/gonggam-data/work/data-quality-management.md) | 완료 · S0·S4·보완 답변 3개 반영 후 사용자 확인·완료 정리 요청 (2026.11.04). 상사 검토·실제 오류 수정 미수행·시기 미특정·공개 제한 유지. 추가 질문 없음 |
| 19 | CB · 기관 공공데이터 활용사례집 제작 | [gonggam-data/work/data-use-casebook.md](records/gonggam-data/work/data-use-casebook.md) | 완료 · 보완 답변·S0·S2 재대조 반영 후 사용자 문안 확인 (2026.11.04). 추가 질문 없음. 국토부는 기관 최종 확인 대기로 진행 중이며 이력 완료와 구분 |

PR·SU·DQ·CB도 회사 경력·기관 이력표의 요약에 더해 개별 본문을 작성했고 현재 모두 사용자 확인 범위로 완료입니다. 각 기록의 미확인 한계와 CB의 국토부 기관 최종 확인 대기는 해당 기록대로 유지합니다.

### Excel 전체 업무 대조

기준: [Gonggam_career.xlsx](<reference/3. 프로젝트 관련 문서/Gonggam_career.xlsx>)의 `참여사업 목록!D1:K1`. 아래는 연도 × 대표기관 × 담당 업무의 조합 수이며, 계약·프로젝트·고유 서비스·고객기관 수가 아닙니다.

| 코드 | Excel 업무 | 원본 열·상세 자료 | 업무 조합 수 | 작성 항목 |
| --- | --- | --- | --- | --- |
| PR | 제안서 작업 | D열 / 제안서 작업 시트 | 11 | 16번 |
| SU | 대국민 공공데이터 활용 수요조사 | E열 / 동명 시트 | 11 | 17번 |
| PU | 공공데이터 민간 활용 성과 | F열 / 동명 시트 | 11 | 12번 |
| DQ | 데이터 값 관리 | G열 / 동명 시트 | 2 | 18번 |
| SY | 가명정보 제공 및 합성데이터 개방 실적 | H열 / 동명 시트 | 1 | 15번 |
| AN | 데이터 분석·정책활용 실적 및 성과 | I열 / 동명 시트 | 22 | 13번 |
| SH | 메타관리시스템 기반 데이터 공유 실적 | J열 / 동명 시트 | 9 | 14번 |
| CB | 기관 공공데이터 활용사례집 제작 | K열 / 상세 시트 없음, 추가 PDF·사용자 설명 | 2 | 19번 |
| 합계 | 8개 업무 | 원본 30행 → 기관·연도 29개 묶음 | 69 | 업무 문서 8개 |

기관명 정규화·원본 행·사례 ID·시트 범위·기관별 실적·경력증명서 대조는 [공통 기관 이력표](records/gonggam-data/institutions-by-year.md)에서 관리합니다. 경력증명서의 선택 등록 16개 사업과 기존 안의 번호·시작일은 해당 문서의 부록에 보존했습니다.

### FindSeoul·기술 역량·이력 개요

| 번호 | 대상 | 위치·양식 | 상태·확인할 범위 |
| --- | --- | --- | --- |
| 20 | FindSeoul | [프로젝트 기록](records/project-findseoul-travel-recommendation.md) | 완료 · 사용자 문안 확인 (2026.11.06). GitHub 링크·대회 미선정 공개 가능 |
| 21 | 기술 역량 | [기술 역량](records/skills.md) | 완료 · 사용자 최종 문안 승인 (2026.11.06) |
| 22 | 전체 이력 개요 | [overview.md](overview.md) | 완료 · 사용자 최종 문안 승인 (2026.11.06) |

## 원본 자료 위치

원본은 내부 확인용입니다. 이 표를 공개 웹사이트·챗봇의 파일 제공 목록으로 사용하지 않습니다.

| 위치 | 주요 자료·용도 |
| --- | --- |
| [reference/1. 학교 졸업 및 성적/](<reference/1. 학교 졸업 및 성적/>) | 학부·대학원 성적증명서, 석사학위수여증명서, 출판 논문 원문 |
| [reference/2. 과거 이력서/](<reference/2. 과거 이력서/>) | 2024년 이력서, 과거 포트폴리오 |
| [reference/3. 프로젝트 관련 문서/](<reference/3. 프로젝트 관련 문서/>) | 소프트웨어기술자 경력증명서, ACT 개발참여증빙·관련 뉴스, 공감데이터 Excel |
| [공감데이터 이력 추가자료/](<reference/3. 프로젝트 관련 문서/공감데이터 이력 추가자료/>) | 2026년 평가편람 발췌 HWPX, 언론진흥재단 보고서 3종, 과기정통부 활용사례집 PDF. 보고서 원문 비공개·취합 서술 가능 |
| [reference/4. 기타/](<reference/4. 기타/>) | FindSeoul 기획서·참가 자료·로고, LLM 교육 이수증 |

원본의 구체적인 페이지·시트·행은 각 기록의 근거 항목을 우선합니다. ETC 공개 코드와 기존 프로젝트 저장소의 연결·검증 범위도 각 기록 및 인수인계 문서를 따릅니다.
