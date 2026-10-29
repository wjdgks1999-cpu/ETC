import pandas as pd
from sdv.metadata import SingleTableMetadata
from sdv.single_table import GaussianCopulaSynthesizer
from sdv.single_table import CTGANSynthesizer
from dotenv import load_dotenv
import os

load_dotenv('.env')

#%% 1. 데이터 로드 및 메타데이터 추론
FILE_PATH = os.getenv('origin_path')
data = pd.read_excel(FILE_PATH)
data.head(5)

# 2. 메타데이터 객체 생성 및 자동 추론
metadata = SingleTableMetadata()
metadata.detect_from_dataframe(data)
print(metadata)

#%% 2. PII(개인정보) 열 메타데이터 업데이트 
# 자동으로 추론된 메타데이터에서 이름과 주소 열이 단순한 카테고리가 아니라 '개인정보'임을 명시해야 합니다.
# sdtype을 지정하고 pii=True로 설정하면 통계적 모델링에서 제외되며 안전하게 가짜 데이터로 대체됩니다.
# sdtype으로 id, name, email, address, phone_number, ssn, company, city, country, postcode 등이 사용될 수 있음

# - 고객ID는 무작위 고유 ID 형식으로 설정
metadata.update_column(
    column_name='고객ID',
    sdtype='id',
    regex_format='C[0-9]{3}'
)

# - 고객명은 Faker의 'name' 기능과 연결
metadata.update_column(
    column_name='고객명',
    sdtype='name',
    pii=True
)

# - 주소는 Faker의 'address' 기능과 연결
metadata.update_column(
    column_name='주소',
    sdtype='address',
    pii=True
)

#%% 3. 모델 학습 및 합성 데이터 생성(한국어 로케일 적용)
# 모델을 생성할 때 locales=['ko_KR'] 파라미터를 넘겨주면, 
# 앞서 pii=True로 설정한 열들이 자동으로 한국어 형식(한국 이름, 한국 주소 등)에 맞춰 생성됩니다.

# 1. 모델 초기화 (가우시안 분포 모델)
synthesizer_gaussian = GaussianCopulaSynthesizer(
    metadata,
    locales=['ko_KR']
)

# 원본 데이터 통계적 특성 학습
synthesizer_gaussian.fit(data)

# 합성 데이터 10개 생성
synthetic_data_gaussian = synthesizer_gaussian.sample(num_rows=10000)
print(synthetic_data_gaussian)

# 2. CTGAN 모델 학습
synthesizer_GAN = CTGANSynthesizer(
    metadata,
    locales=['ko_KR'],
    epochs=2000,      
    verbose=True      
)

# CTGAN 모델 학습 (딥러닝 기반이라 데이터량/에포크에 따라 시간이 걸림)
print("CTGAN 학습을 시작합니다...")
synthesizer_GAN.fit(data)

# 합성 데이터 생성
synthetic_data_GAN = synthesizer_GAN.sample(num_rows=10000)

print("\n--- 생성된 합성 데이터 ---")
print(synthetic_data_GAN)

#%% 4. 품질 평가
from sdv.evaluation.single_table import evaluate_quality

# (1). 가우시안 코풀라 모델 품질 평가
print("\n[가우시안 코풀라 모델 품질 평가]")
quality_report_gaussian = evaluate_quality(
    real_data=data,
    synthetic_data=synthetic_data_gaussian,
    metadata=metadata
)
score_gaussian = quality_report_gaussian.get_score()

# (2). CTGAN 모델 품질 평가
print("\n[CTGAN 모델 품질 평가]")
quality_report_GAN = evaluate_quality(
    real_data=data,
    synthetic_data=synthetic_data_GAN,
    metadata=metadata
)
score_GAN = quality_report_GAN.get_score()

# (3). 성능 비교 및 최고 성능 데이터 선택
print("="*50)
print(f"가우시안 코풀라 모델 종합 점수: {score_gaussian:.4f}")
print(f"CTGAN 모델 종합 점수: {score_GAN:.4f}")

if score_gaussian >= score_GAN:
    print("🏆 가우시안 코풀라 모델의 성능이 더 우수합니다. (가우시안 데이터 선택)")
    best_synthetic_data = synthetic_data_gaussian
    best_report = quality_report_gaussian
else:
    print("🏆 CTGAN 모델의 성능이 더 우수합니다. (CTGAN 데이터 선택)")
    best_synthetic_data = synthetic_data_GAN
    best_report = quality_report_GAN
print("="*50)

# (4). 최고 성능 모델의 세부 지표 확인
shape_details = best_report.get_details(property_name='Column Shapes')
print("\n--- 최고 성능 모델의 개별 열 분포 유사도 ---")
print(shape_details)

trend_details = best_report.get_details(property_name='Column Pair Trends')
print("\n--- 최고 성능 모델의 열 간 상관관계 유사도 ---")
print(trend_details)


#%% 기타
best_synthetic_data.to_excel(r'synthetic_data.xlsx', index=False)
print("\n✅ 최고 성능의 합성데이터가 'synthetic_data.xlsx'로 저장되었습니다.")
