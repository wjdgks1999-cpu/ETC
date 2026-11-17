"""가상 데이터와 손계산 값으로 평가식·입력 경계를 검증한다."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from config import WorkflowError
from data_io import resolve_types
from evaluation import judge, matrix_sheet
from metrics import anova_ratio, corrected_split_risk, cramers_v, measure


class MetricsTests(unittest.TestCase):
    """수식 변경과 기존에 유효했던 계산의 회귀를 확인한다."""

    def evaluate(self, origin, synthetic, types=None, risk_columns=None):
        """가상 표를 만들고 기본 또는 지정 유형으로 평가한다."""
        origin, synthetic = pd.DataFrame(origin), pd.DataFrame(synthetic)
        return measure(origin, synthetic, types or resolve_types(origin, {}), risk_columns)

    def test_identical_numeric_data(self):
        """동일한 수치 분포와 관계의 기준값을 보존한다."""
        data = {"x": [1, 2, 3, 4], "y": [4, 1, 2, 3]}
        result = self.evaluate(data, data)
        self.assertEqual(result.scores, {"single_out": 1, "similarity_1d": 1, "error_2d": 0})
        self.assertEqual(result.matched_count, 4)

    def test_duplicate_original_does_not_multiply_matches(self):
        """원본 중복으로 일치 건수가 부풀려지지 않는다."""
        result = self.evaluate({"x": [1, 1, 2]}, {"x": [1, 1, 3]})
        self.assertAlmostEqual(result.scores["single_out"], 2 / 3)
        self.assertEqual(result.matched_count, 2)

    def test_risk_column_subset(self):
        """준식별자 비교 컬럼을 명시하는 기존 기능을 보존한다."""
        result = self.evaluate({"x": [1, 2], "y": [3, 4]}, {"x": [1, 2], "y": [8, 9]}, risk_columns=["x"])
        self.assertEqual(result.scores["single_out"], 1)

    def test_missing_values_can_match_without_record_output(self):
        """일치 지표의 결측 비교 동작을 확인하고 레코드를 결과에 싣지 않는다."""
        result = self.evaluate({"x": [np.nan, 1]}, {"x": [np.nan, 2]})
        self.assertEqual(result.matched_count, 1)
        self.assertFalse(hasattr(result, "matched_data"))

    def test_new_category_uses_tvd(self):
        """원본에 없는 범주가 있어도 비율 차이 0.1을 계산한다."""
        result = self.evaluate({"c": ["a"] * 10}, {"c": ["a"] * 9 + ["b"]})
        self.assertEqual(result.scores["similarity_1d"], 0.9)

    def test_categorical_probability_scale_is_size_independent(self):
        """같은 범주 비율은 표본 크기가 달라도 같은 점수를 낸다."""
        origin = {"c": ["a"] * 5 + ["b"] * 5}
        first = self.evaluate(origin, {"c": ["a"] * 8 + ["b"] * 2})
        second = self.evaluate(origin, {"c": ["a"] * 80 + ["b"] * 20})
        self.assertEqual(first.scores["similarity_1d"], 0.7)
        self.assertEqual(first.scores["similarity_1d"], second.scores["similarity_1d"])

    def test_single_category_is_perfect_distribution(self):
        """동일한 단일 범주가 NaN 대신 유사도 1을 반환한다."""
        result = self.evaluate({"c": ["a"] * 4}, {"c": ["a"] * 8})
        self.assertEqual(result.scores["similarity_1d"], 1)

    def test_numeric_rounding_is_preserved(self):
        """일차원 점수의 소수 넷째 자리 반올림을 보존한다."""
        result = self.evaluate({"x": [0, 1, 2]}, {"x": [0, 1, 3]})
        self.assertEqual(result.scores["similarity_1d"], 0.6667)

    def test_numeric_categorical_override(self):
        """숫자 코드의 범주형 지정이 분포·관계 계산에 적용된다."""
        result = self.evaluate({"code": [1, 1, 2, 2]}, {"code": [1, 1, 3, 3]}, {"code": "categorical"})
        self.assertEqual(result.columns.iloc[0]["지표"], "1-TVD")
        self.assertEqual(result.scores["similarity_1d"], 0.5)

    def test_two_column_correlation_reversal(self):
        """반대 관계의 전체 차이 행렬 표준편차는 손계산 값 1이다."""
        result = self.evaluate({"x": [1, 2, 3, 4], "y": [1, 2, 3, 4]},
                               {"x": [1, 2, 3, 4], "y": [4, 3, 2, 1]})
        self.assertEqual(result.scores["error_2d"], 1)
        self.assertEqual(result.pairs.iloc[0]["차이 절댓값"], 2)

    def test_anova_uses_variance_ratio(self):
        """SSB=4, SST=8인 예의 관계값은 제곱근 없이 0.5다."""
        self.assertEqual(anova_ratio(pd.Series(["a", "a", "b", "b"]), pd.Series([0., 2., 2., 4.])), 0.5)

    def test_cramers_continuity_correction_preserved(self):
        """2×2 교차표의 기존 연속성 보정 결과를 유지한다."""
        series = pd.Series(["a"] * 5 + ["b"] * 5)
        self.assertAlmostEqual(cramers_v(series, series), 0.8)

    def test_sparse_cramers_matches_dense_formula(self):
        """빈 조합을 생략해 계산해도 기존 교차표 수식과 일치한다."""
        left = pd.Series(["a", "a", "b", "b", "c", "c", "c", "d"])
        right = pd.Series(["x", "y", "x", "z", "x", "z", "z", "y"])
        table = pd.crosstab(left, right)
        expected = np.sqrt(chi2_contingency(table)[0] / (len(left) * (min(table.shape) - 1)))
        self.assertAlmostEqual(cramers_v(left, right), expected)

    def test_high_cardinality_does_not_allocate_dense_table(self):
        """고유값 10,000개의 관계를 1억 셀 교차표 없이 계산한다."""
        values = pd.Series([f"item_{index}" for index in range(10000)])
        with patch("metrics.pd.crosstab", side_effect=AssertionError("dense table")):
            self.assertAlmostEqual(cramers_v(values, values), 1)

    def test_split_risk_correction_and_final_raw_risk(self):
        """분할에는 보정하고 실제 평가 위험도 0.1은 그대로 비교한다."""
        self.assertAlmostEqual(corrected_split_risk(0.1), 0.19)
        result = self.evaluate({"x": list(range(10)), "y": list(range(10))},
                               {"x": [0] + list(range(11, 20)), "y": [0] + list(range(11, 20))})
        summary, _ = judge(result, {"single_out": .15, "similarity_1d": 0, "error_2d": 2})
        self.assertEqual(summary.iloc[0]["측정값"], 0.1)
        self.assertEqual(summary.iloc[0]["판정"], "통과")

    def test_all_missing_blocks_average_and_pass(self):
        """결측뿐인 컬럼이 평균에서 조용히 빠지지 않는다."""
        result = self.evaluate({"x": [np.nan] * 4, "y": [1, 2, 3, 4]},
                               {"x": [np.nan] * 4, "y": [1, 2, 3, 4]})
        self.assertIsNone(result.scores["similarity_1d"])
        _, overall = judge(result, {"single_out": 1, "similarity_1d": 0, "error_2d": 2})
        self.assertEqual(overall, "평가 불가")

    def test_constant_numeric_pair_is_unavailable(self):
        """정의되지 않은 상수 Pearson 관계를 0으로 위장하지 않는다."""
        result = self.evaluate({"x": [1] * 4, "y": [1, 2, 3, 4]},
                               {"x": [1] * 4, "y": [1, 2, 3, 4]})
        self.assertIsNone(result.scores["error_2d"])

    def test_single_column_has_no_relationship_score(self):
        """컬럼 하나는 이차원 관계 평가 불가다."""
        self.assertIsNone(self.evaluate({"x": [1, 2]}, {"x": [1, 2]}).scores["error_2d"])

    def test_empty_and_mismatched_columns_are_rejected(self):
        """빈 합성데이터와 누락 컬럼이 유효한 평가로 처리되지 않는다."""
        for synthetic in ({"x": []}, {"y": [1, 2]}):
            with self.subTest(synthetic=synthetic), self.assertRaises(WorkflowError):
                self.evaluate({"x": [1, 2]}, synthetic)

    def test_invalid_numeric_types_are_rejected(self):
        """문자 혼입과 무한대를 계산 전에 거부한다."""
        for values in (["a", "b"], [1, np.inf]):
            with self.subTest(values=values), self.assertRaises(WorkflowError):
                self.evaluate({"x": [1, 2]}, {"x": values})

    def test_reordered_columns_and_duplicate_indices(self):
        """컬럼 순서·행 인덱스에 따라 같은 데이터의 결과가 달라지지 않는다."""
        data = pd.DataFrame({"x": [1, 2, 3, 4], "y": [4, 3, 1, 2]}, index=[0, 0, 1, 1])
        result = measure(data, data[["y", "x"]], resolve_types(data, {}))
        self.assertEqual(result.scores["error_2d"], 0)
        self.assertEqual(result.matched_count, 4)

    def test_matrix_row_label_does_not_conflict(self):
        """행 이름과 같은 업무 컬럼이 있어도 관계 행렬을 내보낼 수 있다."""
        matrix = pd.DataFrame([[1, 0], [0, 1]], columns=["행 컬럼", "_행 컬럼"], index=["행 컬럼", "_행 컬럼"])
        exported = matrix_sheet(matrix)
        self.assertEqual(exported.shape, (2, 3))
        self.assertTrue(exported.columns.is_unique)


if __name__ == "__main__":
    unittest.main()
