# 보고서 안내

현재 `v13/r15/e3`의 실제 모델·웹 도구 진단은 [GAIA 주요 trace live 재실행](2026-10-12-gaia-key-traces-live.ko.md)에 있습니다.
5개 탐색 과제를 두 조건에서 각 1회 실행했습니다. 기존 결과와의 대조, 시간 한도, 참조 오류와 비용 불명 호출을 함께 기록했습니다.

먼저 [2026-10-10 종합 재분석](2026-10-10-synthesis.ko.md)을 읽습니다.
이 문서는 기존 보고서의 수치·해석을 정정하고 관측, 해석, 미검증 가설을 구분합니다.
실제 worker probe를 통한 재작성의 평균 이득은 아직 입증되지 않았으며,
현재 실행 prompt v7 / refiner r9의 전체 비교 결과도 없습니다.

| 보고서 | 읽는 목적 |
|---|---|
| [GAIA 주요 trace live 재실행](2026-10-12-gaia-key-traces-live.ko.md) | 현재 shared-state runtime의 10회 실제 실행, 과거 결과 대조와 실패 경로 |
| [최신 종합 재분석](2026-10-10-synthesis.ko.md) | 현재 가장 신뢰할 결론과 한계 |
| [Benchmark 검토와 추천](benchmark-selection.ko.md) | 기존 probe와 worker 선택 실험에 맞는 후보·추천 이유·한계 |
| [Baseline·probe 비교](2026-10-09-baseline-and-probe-comparison.ko.md) | 50문제 baseline과 47문제 조건 비교의 당시 기록 |
| [Refiner 후속 진단](2026-10-10-refiner-diagnostics.ko.md) | 선택 문제의 기존 초안 회귀 점검과 최신 prompt 진단 |
| [사례 심층 분석 종합](2026-10-10-case-analysis.ko.md) | 실패 경로와 사후 분류; 인과 효과와 구분 |
| [문제별 사례](cases/README.md) | 26문제 및 전 조건 정답 22문제 분석 |
| [초기 pilot](2026-10-08-initial-pilot.ko.md) | 이전 설계의 역사적 참고; 현재 성능 결과로 사용하지 않음 |

과거 보고서의 주장은 최신 종합 문서에서 정정된 부분이 있습니다. 같은 실행을 여러 보고서가
다루므로 독립 반복으로 합산하지 않습니다. 과거 stage/phase 이름은 [용어 대응표](../experiments.md)에 있습니다.

원본 실행은 `outputs/experiments/`에 목적별로 보존했습니다. `python scripts/experiments.py list`로 찾습니다.
보존·이동·삭제 상세는 [retention.json](retention.json), 파일 검증은 `python scripts/experiments.py verify`입니다.
