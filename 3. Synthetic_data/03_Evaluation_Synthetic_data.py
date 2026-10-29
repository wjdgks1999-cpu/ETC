import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os

load_dotenv('.env')

# 안전성 및 유용성 계산 함수를 불러옵니다.
from evaluation_func import (
    calculate_single_out_risk, 
    calculate_1d_similarity_updated, 
    evaluate_2d_relationship_similarity
)

#%% 데이터 불러오기
ORIGIN_FILE_PATH = os.getenv('origin_path')
SYNTHETIC_FILE_PATH = os.getenv('synthetic_path')
THRESHOLD_PATH = os.getenv('threshold_path')

origin_df = pd.read_excel(ORIGIN_FILE_PATH)
origin_df.shape
synthetic_df = pd.read_excel(SYNTHETIC_FILE_PATH)
synthetic_df.shape

threshold_info = pd.read_excel(THRESHOLD_PATH)

#%% 1. 구별위험도
# 함수 실행 (전체 컬럼 기준)
risk_index, risk_percent, matched_data = calculate_single_out_risk(origin_df, synthetic_df)

print(f"📊 [합성데이터 구별 위험도 평가 결과]")
print(f"총 합성데이터 레코드 수: {len(synthetic_df):,}개")
print(f"원본과 완벽히 일치하는 레코드 수: {len(matched_data):,}개")
print(f"⚠️ 구별 위험도 (Single out risk Index): {risk_index:.4f} ({risk_percent:.2f}%)")

# 만약 구별 위험도가 0이 아니라면, 어떤 데이터가 똑같이 생성되었는지 확인
if risk_index > 0:
    print("\n[원본과 똑같이 생성된 데이터 예시 (상위 5개)]")
    print(matched_data.head())

#%% 2. 일차원 분포 유사성
# 함수 실행
similarity_report = calculate_1d_similarity_updated(origin_df, synthetic_df)

# --- 결과 출력 ---
print("📊 [1차원 분포 유사도 평가 결과 (가이드라인 반영)]")
print(similarity_report.to_string(index=False))

print("\n📈 [변수 타입별 평균 유사도]")
type_mean_similarity = similarity_report.groupby('변수 타입')['유사도 지표 (0~1)'].mean()
for var_type, mean_val in type_mean_similarity.items():
    print(f" - {var_type}: {mean_val:.4f}")

overall_mean = similarity_report['유사도 지표 (0~1)'].mean()
print(f"\n💡 전체 변수 평균 유사도: {overall_mean:.4f}")

#%% 3. 2차원 관계 유사성
# --- 실행 및 결과 출력 ---
# origin_df와 synthetic_df가 준비되어 있다고 가정합니다.
sigma_d, diff_matrix, r_ori, r_syn = evaluate_2d_relationship_similarity(origin_df, synthetic_df)

print("📊 [2차원 관계 유사성 평가 결과]")
print(f"⚠️ 차이값 행렬 D의 표준편차 (\u03c3_D): {sigma_d:.5f}")
print("   * 값이 0에 가까울수록 원본 데이터의 상관관계 패턴을 완벽히 보존한 것입니다.\n")

print("🔍 [상관관계 차이가 가장 큰 변수 쌍 Top 3]")
# 절댓값 기준으로 차이가 가장 큰 쌍 찾기
diff_series = diff_matrix.where(np.triu(np.ones(diff_matrix.shape), k=1).astype(bool)).stack().abs()
top_diff = diff_series.sort_values(ascending=False).head(3)

for pair, diff_val in top_diff.items():
    print(f" - [{pair[0]}] ↔ [{pair[1]}] : 차이 절댓값 {diff_val:.4f}")

#%% 4. 종합 평가 보고서 (임계값 비교)
print("\n" + "="*50)
print("🏆 [합성데이터 종합 평가 보고서]")
print("="*50)

# 임계값 추출 (threshold_info 활용)
t_single = threshold_info.loc[threshold_info['평가 지표'].str.contains('구별 위험도'), '임계값'].values[0]
t_1d = threshold_info.loc[threshold_info['평가 지표'].str.contains('1차원 유사도'), '임계값'].values[0]
t_2d = threshold_info.loc[threshold_info['평가 지표'].str.contains('2차원 오차'), '임계값'].values[0]

# 구별 위험도는 임계값 산출 시 적용된 가이드라인 보정식(p* = 1 - (1 - p_hat)^2) 적용
risk_index_adj = 1 - (1 - risk_index)**2

# 합격 여부 판정
pass_single = risk_index_adj <= t_single
pass_1d = overall_mean >= t_1d
pass_2d = sigma_d <= t_2d

print(f"1️⃣ 구별 위험도 (보정치) : {risk_index_adj:.4f} (기준: {t_single:.4f} 이하) ➡️ {'✅ 합격' if pass_single else '❌ 불합격'}")
print(f"2️⃣ 1차원 분포 유사도   : {overall_mean:.4f} (기준: {t_1d:.4f} 이상) ➡️ {'✅ 합격' if pass_1d else '❌ 불합격'}")
print(f"3️⃣ 2차원 관계 오차     : {sigma_d:.4f} (기준: {t_2d:.4f} 이하) ➡️ {'✅ 합격' if pass_2d else '❌ 불합격'}")
print("="*50)

if pass_single and pass_1d and pass_2d:
    print("🎉 [최종 결과] 생성된 합성데이터가 모든 프라이버시 및 유용성 기준을 통과했습니다!")
else:
    print("⚠️ [최종 결과] 일부 지표가 기준을 미달했습니다. 모델 파라미터나 학습 에포크(Epoch)를 조정해보세요.")