import pandas as pd
import numpy as np
from scipy.stats import ks_2samp, chisquare, chi2_contingency

#%% 1. 구별 위험도
def calculate_single_out_risk(origin_data, synthetic_data, qi_columns=None):
    """
    최신 가이드라인에 기반한 합성데이터 구별 위험도(Single-out risk) 계산 함수
    
    :param origin_data: 원본 데이터프레임
    :param synthetic_data: 합성 데이터프레임
    :param qi_columns: 비교할 준식별자(Quasi-Identifiers) 컬럼 리스트. 
                    지정하지 않으면 모든 공통 컬럼을 기준으로 비교합니다.
    :return: 구별 위험도 지수 (0~1), 위험도 퍼센트, 일치하는 데이터프레임
    """
    
    # 1. 비교할 컬럼 설정 (qi_columns가 없으면 두 데이터셋의 공통 컬럼 전체 사용)
    if qi_columns is None:
        common_cols = list(set(origin_data.columns) & set(synthetic_data.columns))
    else:
        common_cols = qi_columns
        
    if not common_cols:
        raise ValueError("원본 데이터와 합성데이터 간에 비교할 공통 컬럼이 없습니다.")
        
    # 2. 원본 데이터 중복 제거 
    # (원본의 고유한 프로필과 합성데이터가 일치하는지 확인하기 위함)
    unique_origin_df = origin_data[common_cols].drop_duplicates()
    
    # 3. Pandas 병합(Merge)을 통해 일치 여부 확인
    # 합성데이터를 기준으로 left merge를 수행하고 indicator로 일치 여부를 판별합니다.
    matched = pd.merge(synthetic_data[common_cols], 
                    unique_origin_df, 
                    how='left', 
                    indicator=True)
    
    # 4. '_merge' 값이 'both'인 경우 원본과 완벽하게 일치하는(구별되는) 레코드
    exact_matches = matched[matched['_merge'] == 'both'].drop(columns=['_merge'])
    
    # 5. 구별 위험도 산출
    total_synthetic_records = len(synthetic_data)
    num_exact_matches = len(exact_matches)
    
    # 지수 계산 (일치하는 레코드 수 / 전체 합성데이터 레코드 수)
    single_out_risk_index = num_exact_matches / total_synthetic_records if total_synthetic_records > 0 else 0
    risk_percentage = single_out_risk_index * 100
    
    return single_out_risk_index, risk_percentage, exact_matches
#%% 2. 1차원 분포 유사성
# 연속형 변수(나이, 키 등) : 두 데이터의 누적 분포가 얼마나 차이 나는지 측정하는 KS 통계량 사용
# 범주형 변수(성별, 지역 등) : 카이제곱 적합도 검정 사용
def calculate_1d_similarity_updated(origin_df, synthetic_df):
    """
    연속형 변수는 KS 통계량, 범주형 변수는 카이제곱 통계량(p-value)을 사용하여
    1차원 분포 유사도를 계산합니다.
    """
    results = []
    
    # 두 데이터프레임의 공통 컬럼만 추출
    common_cols = list(set(origin_df.columns) & set(synthetic_df.columns))
    
    for col in common_cols:
        orig_data = origin_df[col].dropna()
        synth_data = synthetic_df[col].dropna()
        
        if len(orig_data) == 0 or len(synth_data) == 0:
            continue
            
        # 1. 연속형(수치형) 변수인 경우: KS 통계량 활용
        if pd.api.types.is_numeric_dtype(orig_data):
            ks_stat, p_val = ks_2samp(orig_data, synth_data)
            # KS 통계량은 0에 가까울수록 분포가 동일하므로 1 - 통계량을 유사도로 사용
            similarity = 1 - ks_stat
            var_type = '연속형 (KS Test)'
            
        # 2. 범주형(문자열/카테고리) 변수인 경우: 카이제곱 통계량 활용
        else:
            orig_counts = orig_data.value_counts()
            synth_counts = synth_data.value_counts()
            
            # 모든 카테고리 추출
            all_categories = list(set(orig_counts.index) | set(synth_counts.index))
            
            total_synth = len(synth_data)
            total_orig = len(orig_data)
            
            f_obs = [] # 관측 빈도 (합성데이터)
            f_exp = [] # 기대 빈도 (원본데이터)
            
            for cat in all_categories:
                # 합성데이터의 실제 관측 빈도
                obs = synth_counts.get(cat, 0)
                
                # 원본데이터의 비율을 바탕으로 계산한 합성데이터에서의 기대 빈도
                exp_prop = orig_counts.get(cat, 0) / total_orig
                exp = exp_prop * total_synth
                
                # [주의] 카이제곱 수식 특성상 기대빈도(분모)가 0이 되면 에러 발생.
                # 원본엔 없는데 합성데이터에 새로 생성된 범주가 있을 경우를 위한 안전장치
                if exp == 0:
                    exp = 1e-5 
                    
                f_obs.append(obs)
                f_exp.append(exp)
                
            # 카이제곱 검정 수행
            chi2_stat, p_value = chisquare(f_obs=f_obs, f_exp=f_exp)
            
            # 카이제곱 검정의 p-value를 0~1 사이의 유사도로 활용
            # (p-value가 0.05 이상이면 귀무가설 채택 -> 두 분포가 통계적으로 같음)
            similarity = p_value 
            var_type = '범주형 (Chi-Square)'
            
        results.append({
            '컬럼명': col,
            '변수 타입': var_type,
            '유사도 지표 (0~1)': round(similarity, 4)
        })
        
    report_df = pd.DataFrame(results).sort_values(by='유사도 지표 (0~1)', ascending=False)
    return report_df
#%% 3. 2차원 관계 유사성
def calculate_cramers_v(cat_series1, cat_series2):
    """범주형-범주형 변수 간의 크래머 V 상관계수 계산"""
    # 교차표(Confusion Matrix) 생성
    confusion_matrix = pd.crosstab(cat_series1, cat_series2)
    
    # 카이제곱 통계량 계산
    chi2 = chi2_contingency(confusion_matrix)[0]
    n = confusion_matrix.sum().sum()
    
    # 행과 열의 차원 수 계산
    r, k = confusion_matrix.shape
    min_dim = min(k-1, r-1)
    
    # 범주가 1개뿐이어서 차원이 0이 되는 경우 에러 방지
    if min_dim == 0:
        return 0.0
        
    # 가이드라인 수식 적용: V = sqrt(chi2 / (n * (k-1)))
    v = np.sqrt(chi2 / (n * min_dim))
    return v

def calculate_anova_correlation(cat_series, num_series):
    """범주형-수치형 변수 간의 상관관계 (Correlation Ratio, eta) 계산"""
    y_mean = num_series.mean()
    
    # 총 변동 (SST: Sum of Square Total)
    sst = ((num_series - y_mean) ** 2).sum()
    if sst == 0:
        return 0.0
        
    # 그룹 간 변동 (SSB: Sum of Square Between)
    ssb = 0
    for cat in cat_series.unique():
        cat_group = num_series[cat_series == cat]
        ssb += len(cat_group) * ((cat_group.mean() - y_mean) ** 2)
        
    # 가이드라인 수식 적용: SSB / SST (분산 설명력)
    # 피어슨 및 크래머 V와 스케일(0~1)을 맞추기 위해 제곱근을 씌워 에타(eta) 값으로 반환
    return np.sqrt(ssb / sst)

def build_mixed_correlation_matrix(df, num_cols, cat_cols):
    """수치형/범주형이 혼합된 데이터프레임의 전체 상관계수 행렬 구축"""
    cols = list(df.columns)
    n = len(cols)
    
    # 빈 상관계수 행렬 초기화 (자기 자신과의 상관계수는 1.0)
    corr_matrix = pd.DataFrame(np.ones((n, n)), index=cols, columns=cols)
    
    for i in range(n):
        for j in range(i+1, n):
            col1, col2 = cols[i], cols[j]
            
            # 결측치 제외 후 두 변수 동시 추출
            valid_idx = df[[col1, col2]].dropna().index
            s1, s2 = df.loc[valid_idx, col1], df.loc[valid_idx, col2]
            
            if len(s1) == 0:
                val = 0.0
            elif col1 in num_cols and col2 in num_cols:
                # 1. 수치형 vs 수치형: 피어슨 상관계수
                val = s1.corr(s2, method='pearson')
            elif col1 in cat_cols and col2 in cat_cols:
                # 2. 범주형 vs 범주형: 크래머 V
                val = calculate_cramers_v(s1, s2)
            else:
                # 3. 수치형 vs 범주형: ANOVA 상관비 (SSB/SST)
                if col1 in cat_cols:
                    val = calculate_anova_correlation(s1, s2)
                else:
                    val = calculate_anova_correlation(s2, s1)
            
            # 대칭 행렬이므로 양쪽에 모두 값 채우기
            corr_matrix.loc[col1, col2] = val
            corr_matrix.loc[col2, col1] = val
            
    return corr_matrix

def evaluate_2d_relationship_similarity(origin_df, synthetic_df):
    """
    최종 2차원 관계 유사성 평가 (차이값 행렬 D의 표준편차 계산)
    """
    # 1. 공통 컬럼 추출 및 변수 타입 분류
    common_cols = list(set(origin_df.columns) & set(synthetic_df.columns))
    num_cols = origin_df[common_cols].select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = list(set(common_cols) - set(num_cols))
    
    # 2. 상관계수 행렬 계산 (R_ori, R_syn)
    r_ori = build_mixed_correlation_matrix(origin_df[common_cols], num_cols, cat_cols)
    r_syn = build_mixed_correlation_matrix(synthetic_df[common_cols], num_cols, cat_cols)
    
    # 3. 차이값 행렬 D 계산
    d_matrix = r_ori - r_syn
    
    # 4. 차이값 행렬의 표준편차(sigma_D) 산출
    # [통계적 정확도 팁] 자기 자신과의 상관계수 차이(대각선 값, 항상 0)와 
    # 대칭되는 중복 값을 제외하기 위해 상단 삼각행렬(Upper Triangle)의 값만 추출하여 계산합니다.
    upper_triangle_indices = np.triu_indices_from(d_matrix, k=1)
    d_values = d_matrix.values[upper_triangle_indices]
    
    # 표준편차 계산 공식 적용: sigma_D = sqrt( (1/n) * sum(d_i - d_mean)^2 )
    sigma_d = np.std(d_values) 
    
    return sigma_d, d_matrix, r_ori, r_syn