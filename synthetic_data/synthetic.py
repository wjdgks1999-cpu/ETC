"""임계값 산정·합성데이터 생성·평가의 명령 진입점이다."""

import argparse
import sys

from config import WorkflowError, load_settings
from data_io import check_output, check_types, read_table, resolve_types
from evaluation import judge, save_evaluation
from metrics import measure
from thresholds import calculate_thresholds, evaluation_context, load_thresholds, save_thresholds


def show_threshold_progress(current, total):
    """반복 분할 진행 건수만 출력한다."""
    print(f"임계값 산정: {current}/{total}", flush=True)


def build_parser():
    """작업별 명령과 공통 설정·덮어쓰기 옵션을 정의한다."""
    parser = argparse.ArgumentParser(description="합성데이터 생성 및 세 지표 평가")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (("threshold", "반복 분할 임계값 산정"),
                               ("generate", "두 모델 생성·품질 비교"),
                               ("evaluate", "세 지표 계산·임계값 비교")):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--config", required=True, help="UTF-8 JSON 설정 경로")
        child.add_argument("--overwrite", action="store_true", help="기존 출력 파일 교체 허용")
    return parser


def run(args):
    """입력과 출력을 확인한 뒤 지정한 한 작업만 실행한다."""
    settings = load_settings(args.config)
    outputs = {"threshold": settings.threshold_path, "generate": settings.synthetic_path,
               "evaluate": settings.evaluation_path}
    check_output(outputs[args.command], args.overwrite)
    origin = read_table(settings.origin_path)
    types = resolve_types(origin, settings.column_types)
    check_types(origin, types)
    context = evaluation_context(origin, types, settings)
    if args.command == "threshold":
        values, samples, context = calculate_thresholds(origin, types, settings, show_threshold_progress)
        save_thresholds(settings.threshold_path, values, samples, context, args.overwrite)
    elif args.command == "generate":
        from generation import generate, save_generation

        result = generate(origin, settings, print)
        save_generation(settings.synthetic_path, result, settings, context, args.overwrite)
        print(f"선택 모델: {result.selected_model} | 생성 행 수: {len(result.data)}")
        if result.warning_count:
            print(f"라이브러리 경고 {result.warning_count}건 발생. 원문 대신 건수를 실행 정보에 기록했습니다.")
    else:
        thresholds = load_thresholds(settings.threshold_path, context)
        synthetic = read_table(settings.synthetic_path)
        result = measure(origin, synthetic, types, settings.risk_columns)
        summary, overall = judge(result, thresholds)
        save_evaluation(settings.evaluation_path, result, summary, overall, context,
                        len(synthetic), args.overwrite)
        print(summary.to_string(index=False))
        print(f"평가한 세 지표의 종합 결과: {overall}. 연결·추론 위험도는 평가하지 않았습니다.")
        print("평가 결과 저장 완료.")
        return {"통과": 0, "미달": 1, "평가 불가": 2}[overall]
    print("결과 저장 완료.")
    return 0


def main(argv=None):
    """명령 오류를 원본 데이터 없는 메시지와 종료 코드로 전달한다."""
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except WorkflowError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as error:
        print(f"오류: 작업을 완료할 수 없습니다({type(error).__name__}). "
              "입출력 파일·권한·설정과 패키지 버전을 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
