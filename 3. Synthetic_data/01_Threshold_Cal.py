import pandas as pd
import numpy as np
import warnings
from dotenv import load_dotenv
import os

load_dotenv('.env')

# 불필요한 경고 메시지(0 나누기 방지용 미세값 부여 등으로 인한 경고) 숨김
warnings.filterwarnings('ignore')

# 안전성 및 유용성 계산 함수를 불러옵니다.
from evaluation_func import (
    calculate_single_out_risk, 
    calculate_1d_similarity_updated, 
    evaluate_2d_relationship_similarity
)

def simulate_and_calculate_thresholds(origin_file_path, iterations=100, safety_percentile=95):
    """
    원본 데이터를 50:50으로 분할하여 평가 지표를 반복 측정하고 임계값을 산출합니다.
    """
    print(f"🚀 원본 데이터 로드 및 {iterations}회 시뮬레이션 임계값 산출을 시작합니다...")
    origin_df = pd.read_excel(origin_file_path)
    total_records = len(origin_df)
    
    # 결과를 저장할 리스트
    single_out_risks = []
    sim_1d_scores = []
    sim_2d_errors = []
    
    for i in range(iterations):
        # 1. 원본 데이터 50:50 무작위 셔플 및 분할
        shuffled_df = origin_df.sample(frac=1, random_state=i).reset_index(drop=True)
        mid_point = total_records // 2
        
        # A데이터(임시 원본), B데이터(임시 합성) 생성
        mock_origin = shuffled_df.iloc[:mid_point]
        mock_synth = shuffled_df.iloc[mid_point:]
        
        # 2. 지표 1: 구별 위험도 측정 및 보정
        p_hat, _, _ = calculate_single_out_risk(mock_origin, mock_synth)
        # 가이드라인 보정 공식 적용: p* = 1 - (1 - p_hat)^2
        p_star = 1 - (1 - p_hat)**2
        single_out_risks.append(p_star)
        
        # 3. 지표 2: 1차원 분포 유사도 측정 (전체 평균)
        report_1d = calculate_1d_similarity_updated(mock_origin, mock_synth)
        mean_1d_sim = report_1d['유사도 지표 (0~1)'].mean()
        sim_1d_scores.append(mean_1d_sim)
        
        # 4. 지표 3: 2차원 관계 유사성 측정 (차이값 행렬의 표준편차 sigma_D)
        sigma_d, _, _, _ = evaluate_2d_relationship_similarity(mock_origin, mock_synth)
        sim_2d_errors.append(sigma_d)
        
        # 진행률 출력 (10회마다)
        if (i + 1) % 10 == 0:
            print(f"  -> 시뮬레이션 진행 중... ({i + 1}/{iterations}) 완료")

    # 5. 임계값(Threshold) 산정
    print("\n✅ 시뮬레이션 완료! 임계값을 산출합니다.\n")
    
    # 구별 위험도는 '위험도'이므로 최대 허용치를 위해 상위 분위수(예: 95%) 사용 (낮을수록 좋음)
    threshold_single_out = np.percentile(single_out_risks, safety_percentile)
    
    # 1차원 유사도는 '점수'이므로 최소 허용치를 위해 하위 분위수(예: 100-95 = 5%) 사용 (높을수록 좋음)
    threshold_1d = np.percentile(sim_1d_scores, 100 - safety_percentile)
    
    # 2차원 유사성(sigma_D)은 '오차'이므로 최대 허용치를 위해 상위 분위수 사용 (낮을수록 좋음)
    threshold_2d = np.percentile(sim_2d_errors, safety_percentile)
    
    print("="*50)
    print(f"🎯 [합성데이터 검증 임계값 (Threshold) 산출 결과]")
    print(f"  * 시뮬레이션 횟수: {iterations}회 | 적용 분위수: {safety_percentile}%")
    print("="*50)
    print(f" 1️⃣ 구별 위험도 임계값 : {threshold_single_out:.4f} 이하이어야 합격 (보정식 적용)")
    print(f" 2️⃣ 1차원 유사도 임계값 : {threshold_1d:.4f} 이상이어야 합격 (전체 변수 평균 기준)")
    print(f" 3️⃣ 2차원 오차 임계값   : {threshold_2d:.4f} 이하이어야 합격 (차이 행렬 표준편차)")
    print("="*50)
    
    return threshold_single_out, threshold_1d, threshold_2d

# --- 파일 실행 ---
FILE_PATH = os.getenv('origin_path')

# 기본 100회 반복, 90% 분위수를 기준으로 임계값을 산출합니다.
t_single, t_1d, t_2d = simulate_and_calculate_thresholds(FILE_PATH, iterations=100, safety_percentile=90)

# 임계값 정보를 데이터프레임으로 변환하여 엑셀로 저장
threshold_df = pd.DataFrame({
    '평가 지표': ['구별 위험도 (Single-out risk)', '1차원 유사도 (1D Similarity)', '2차원 오차 (2D Error)'],
    '임계값': [t_single, t_1d, t_2d],
    '합격 기준': ['이하', '이상', '이하']
})

output_path = 'threshold_results.xlsx'
threshold_df.to_excel(output_path, index=False)
print(f"\n💾 임계값 정보가 '{output_path}' 파일로 저장되었습니다.")