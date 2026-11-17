"""대상별 수집기를 실행하고 저장·오류 처리·브라우저 정리를 연결한다."""

from . import datasets, usecases
from .browser import browser_session, save_debug
from .common import CrawlConfig, CrawlResult
from .export import check_output, save


def run(config: CrawlConfig) -> CrawlResult:
    """수집기를 실행해 결과를 반환하며, 수집 중 예외가 나도 최종 저장과 브라우저 정리를 시도한다."""
    check_output(config)
    result = CrawlResult()
    collector = usecases.collect if config.target == "usecase" else datasets.collect
    with browser_session(config) as driver:
        try:
            collector(driver, config, result, lambda: save(config, result))
        except KeyboardInterrupt as error:
            result.stopped = "interrupted"
            result.add_error(result.current_page, "수집 중단", error)
        except Exception as error:
            result.stopped = "error"
            result.add_error(result.current_page, "수집/저장", error)
            save_debug(driver, config.output.parent / (config.output.stem + ".debug"), str(error))
        finally:
            save(config, result)
    return result
