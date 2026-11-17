"""제외 코드·사유의 일관성과 금지 표현을 검증한다."""
import json
import unittest
from pydantic import ValidationError
from helpers import make_result as result
from metadata_review import rules

class ValidationTests(unittest.TestCase):
    """정상 문장 보존과 잘못된 판단 결과의 거부를 확인한다."""
    def test_information_word_endings_are_not_speculation(self):
        """정보라는 낱말의 종결 표현을 추측 표현으로 오인하지 않는지 확인한다."""
        for ending in ["정보이므로", "정보이며", "정보이고"]:
            candidate = result(reason=f"업무 설정과 상태를 관리하는 {ending} 개방에서 제외")
            with self.subTest(ending=ending):
                rules.validate_final(candidate, candidate.table_name)

    def test_standalone_speculation_word_is_still_rejected(self):
        """독립적으로 사용된 추측 표현을 제외 사유에서 거부하는지 확인한다."""
        candidate = result(reason="내부 운영정보로 보이므로 개방에서 제외")
        with self.assertRaisesRegex(ValueError, "추측"):
            rules.validate_final(candidate, candidate.table_name)

    def test_uncertainty_cannot_be_used_as_exclusion_reason(self):
        """확인 필요성을 제외 근거로 삼는 문구가 허용되지 않는지 확인한다."""
        reasons = [
            "API 값의 실제 인증정보 포함 여부를 확인할 필요가 있어 개방 제외",
            "책임자 정보는 공개 적정성 확인 전 개방 제외",
            "공개 가능 여부 검토가 필요하여 제외",
            "개인 식별정보가 포함될 수 있어 개방에서 제외",
            "개인 활동과 연결될 가능성이 있어 제외",
            "내부 관리성 데이터에 해당할 수 있어 제외",
        ]
        for reason in reasons:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError,"추측"):
                rules.validate_final(result(reason=reason), "API KEY 관리")

    def test_actual_review_column_names_are_not_uncertainty(self):
        """검토와 관련된 실제 컬럼명을 불확실성 표현으로 오인하지 않는지 확인한다."""
        candidate = result(reason="검토일자, 확인여부 등 심사 이력을 관리하는 데이터이므로 개방에서 제외")
        rules.validate_final(candidate, candidate.table_name)

    def test_selected_code_requires_reason_even_with_review_flag(self):
        """추가 검토 표시가 있어도 선택한 코드의 사유가 필요한지 확인한다."""
        candidate = result().model_copy(update={"exclusion_reason":"", "review_required":True})
        with self.assertRaisesRegex(ValueError,"반드시"):
            rules.validate_final(candidate, candidate.table_name)

    def test_open_recommendation_is_rejected_but_deferral_is_allowed(self):
        """개방 권고는 거부하고 근거가 없는 판단 보류는 허용하는지 확인한다."""
        candidate = result().model_copy(update={
            "exclusion_code":None, "exclusion_reason":"", "review_required":True,
            "review_comment":"이 테이블은 개방해야 합니다",
        })
        with self.assertRaisesRegex(ValueError,"개방을 권고"):
            rules.validate_final(candidate, candidate.table_name)
        candidate.review_comment = "전체 관리 목적과 개인정보 구성을 검토했으나 근거가 부족하여 판단 보류하며 개방 결정이 아닙니다"
        rules.validate_final(candidate, candidate.table_name)

    def test_schema_only_input_cannot_prove_prior_publication(self):
        """스키마만으로 개방 완료 코드 10을 선정하지 못하도록 검사하는지 확인한다."""
        published = result().model_copy(update={"exclusion_code":"10"})
        with self.assertRaisesRegex(ValueError, "개방 완료"):
            rules.validate_final(published, published.table_name)

    def test_invalid_reason_or_null_decision_is_rejected(self):
        """사유 형식과 코드 없는 결과의 필드 일관성을 확인한다."""
        for reason in ["사유 제외.", " 항목을 관리하므로 제외", "항목을 관리하는 데이터"]:
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                rules.validate_final(result(reason=reason), "API KEY 관리")
        invalid = result().model_copy(update={"exclusion_code":None})
        with self.assertRaises(ValueError):
            rules.validate_final(invalid, invalid.table_name)
        valid = result().model_copy(update={"exclusion_code":None, "exclusion_reason":"", "review_required":True})
        rules.validate_final(valid, valid.table_name)

    def test_format_cleanup_preserves_source_names_and_other_fields(self):
        """사유의 형식을 정리하면서 실제 컬럼명과 다른 필드가 보존되는지 확인한다."""
        columns = json.dumps([
            {"컬럼명(한글)": "생성·수정자", "컬럼명(영문)": "author.name"},
            {"컬럼명(한글)": "사용 여부", "컬럼명(영문)": "use_yn"},
        ], ensure_ascii=False)
        candidate = result(reason="  생성·수정자·사용 여부, author.name으로\r\n 설정을 관리하므로 제외.  ")
        normalized = rules.normalize_result(candidate, columns)
        self.assertEqual(normalized.exclusion_reason,
                         "생성·수정자, 사용 여부, author.name으로 설정을 관리하므로 제외")
        self.assertEqual(normalized.model_dump(exclude={"exclusion_reason"}),
                         candidate.model_dump(exclude={"exclusion_reason"}))
        self.assertTrue(candidate.exclusion_reason.startswith("  "))  # 초안은 원문을 보존한다.
        self.assertEqual(rules.normalize_result(normalized, columns), normalized)
        rules.validate_final(normalized, normalized.table_name)

    def test_schema_rejects_unknown_code_and_string_boolean(self):
        """정의되지 않은 코드와 문자열 형태의 불리언을 거부하는지 확인한다."""
        for changes in [{"exclusion_code":"11"}, {"review_required":"false"}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                rules.ExclusionResult.model_validate({**result().model_dump(), **changes})
