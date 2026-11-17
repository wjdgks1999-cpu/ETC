# 공감데이터 이력 안내

공감데이터 경력은 **평가제도를 이해한 뒤, 담당업무와 실제 수행 근거를 읽고, 특이 사례를 별도로 확인**하는 구조로 정리한다. 기관별 사업 전체를 각각 독립 프로젝트로 바꾸지 않는다.

2026.11.16 구조 개편. 기존 기록의 승인 상태는 각 문서에 유지했다. 새 평가 설명은 공식 자료와 제공 편람을 조사한 문서이며 개인의 수행 실적을 증명하는 자료가 아니다.

## 읽는 순서

1. [평가제도 개요](evaluation/overview.md): 어떤 평가이며 왜 기관이 대응하는가.
2. [2026년 지표 구조와 담당업무 연결](evaluation/indicators-2026.md): 전체 평가 중 어느 부분을 담당했는가.
3. [회사 경력](employment.md): 재직·책임 범위·연도별 역할 변화.
4. [기관 이력표](institutions-by-year.md): 연도 × 기관 × 업무별 실제 수행 범위와 사례 ID.
5. 아래 담당업무: 반복 수행한 과정·기관 소통·일정·산출물·결과.
6. [특이 사례: 한국언론진흥재단 GOAD 직접 분석](cases/kpf-goad-2025.md): 일반적인 기존 과제 발굴과 달리 직접 분석한 경험.

## 문서 트리

```text
gonggam-data/
├─ README.md
├─ employment.md
├─ institutions-by-year.md
├─ evaluation/
│  ├─ overview.md
│  └─ indicators-2026.md
├─ work/
│  ├─ private-data-utilization.md       PU 민간활용
│  ├─ analysis-policy-use.md           AN 분석·정책활용
│  ├─ shared-data.md                   SH 공유데이터
│  ├─ pseudonymous-synthetic-data.md   SY 합성데이터
│  ├─ proposals.md                     PR 제안서
│  ├─ public-data-demand-survey.md     SU 수요조사
│  ├─ data-quality-management.md       DQ 데이터 값 관리
│  └─ data-use-casebook.md             CB 활용사례집
└─ cases/
   └─ kpf-goad-2025.md
```

## 담당업무와 하위 사례

| 업무 | 평가제도와의 관계 | 상세 기록·하위 사례 |
| --- | --- | --- |
| PU · 공공데이터 민간활용 성과 | 공공데이터 제공 / 개방·활용 | [업무 기록](work/private-data-utilization.md) |
| AN · 데이터 분석·정책활용 실적 및 성과 | 데이터기반행정 / 분석·활용 | [일반 업무](work/analysis-policy-use.md) → [GOAD 직접 분석](cases/kpf-goad-2025.md) |
| SH · 공유데이터 실적 | 데이터기반행정 / 공유 | [업무 기록](work/shared-data.md) |
| SY · 합성데이터 생성·평가 및 개방 지원 | 공공데이터 제공 / 합성데이터 개방 가점 | [업무 기록](work/pseudonymous-synthetic-data.md) |
| PR · 제안서 작성 | 평가 대응 컨설팅 사업의 제안 업무 | [업무 기록](work/proposals.md) |
| SU · 대국민 공공데이터 활용 수요조사 | 공공데이터 활용 지원 활동의 하나 | [업무 기록](work/public-data-demand-survey.md) |
| DQ · 데이터 값 관리 | 공공데이터 제공 / 품질 | [업무 기록](work/data-quality-management.md) |
| CB · 공공데이터 활용사례집 제작 | 별도 지표 번호가 없는 연계 과업 | [업무 기록](work/data-use-casebook.md) |

위 코드는 이력 관리용 업무 코드다. 8개 모두 독립 평가지표라는 의미가 아니다. 2026년 번호와 이전 수행연도의 구분은 [지표 연결표](evaluation/indicators-2026.md#담당업무-8개와의-연결)를 따른다.

## 기록을 해석하는 기준

- 평가제도의 전체 범위, 회사의 컨설팅 범위, 본인이 실제 맡은 범위를 구분한다. 회사의 모든 지표를 본인이 담당했다고 해석하지 않는다.
- 일반 AN 업무는 기관의 기존 분석과 정책활용을 찾아 공식 실적으로 연결하는 일이다. 직접 분석한 것으로 확인된 GOAD 사례는 별도 문서로 읽는다.
- 기존 기관·연도·업무 조합, 하위 교육청 실적, 발굴 과제 수와 직접 분석 건수를 중복 합산하지 않는다.
- 공공데이터 제공은 민간 제공·활용과, 공유데이터는 기관 간 공유와 연결된다. 개방과 공유를 같은 실적으로 취급하지 않는다.
- 새 특이 사례는 사용자 확인 후 추가한다. 이번에는 GOAD만 분리했으며 다른 사례는 각 업무 및 기관 이력표에 유지한다.
- 원본 Excel·평가편람·보고서는 기존 `docs/career/reference/`에 보존한다. 원문 보고서의 공개 제한과 [공통 공개 기준](../../README.md#웹사이트-공개-기준)을 따른다.
- 과거 문서에 남아 있는 이전 경로는 [이동 대응표](../../../superpowers/reports/2026-11-16-gonggam-records.md#이동-대응표)에서 찾는다.
