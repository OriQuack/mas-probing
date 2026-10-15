# 보고서 안내

최신 GAIA 결과는 [GAIA (non-web) Probing](2026-10-15-gaia-nonweb-v23-34tasks.ko.md)(136 run)입니다. 직전 표적 재실행은 [evaluator 제거 v22의 v21 오답 11문제 재실행](2026-10-15-gaia-nonweb-v22-failed-tasks.ko.md)(22 run)입니다. 36문제 비교는 [worker 대화 유지·plan probe·refiner 제거](2026-10-15-gaia-nonweb-conversation-probe.ko.md)(v21/r23/e7, 72 run)이고, 오답 분류는 [GAIA non-web 실패 유형](2026-10-15-gaia-nonweb-failure-modes.ko.md)에 있습니다.

이전 `v16/r19/e6`·tools v7의 저비용 실제 진단은 [Evaluator 단독 state 갱신 live 진단](2026-10-12-evaluator-owned-state-live.ko.md)에 있습니다.
탐색 과제 3개에서 2개 정답, 총 $0.18047882였습니다. State·context 전달 계약은 통과했으며 답 보류와 probe 해결 뒤 추가 실행 문제를 따로 기록했습니다.

이전 `v13/r15/e3`의 실제 모델·웹 도구 진단은 [GAIA 주요 trace live 재실행](2026-10-12-gaia-key-traces-live.ko.md)에 있습니다.
5개 탐색 과제를 두 조건에서 각 1회 실행했습니다. 기존 결과와의 대조, 시간 한도, 참조 오류와 비용 불명 호출을 함께 기록했습니다.

먼저 [2026-10-10 종합 재분석](2026-10-10-synthesis.ko.md)을 읽습니다.
이 문서는 기존 보고서의 수치·해석을 정정하고 관측, 해석, 미검증 가설을 구분합니다.
실제 worker probe를 통한 재작성의 평균 이득은 아직 입증되지 않았으며,
당시 실행 prompt v7 / refiner r9의 전체 비교 결과도 없었습니다.

| 보고서 | 읽는 목적 |
|---|---|
| [GAIA non-web: worker 대화 유지·plan probe·refiner 제거](2026-10-15-gaia-nonweb-conversation-probe.ko.md) | v21/r23/e7(C41) 72 run: 공식 23 vs 22, 보정 26 vs 25, adaptive 비용 1.7배. 단서 붙은 정답 11→3, evaluator의 조건부 답 요구는 두 조건에 남음 |
| [GAIA (non-web) Probing](2026-10-15-gaia-nonweb-v23-34tasks.ko.md) | 34문제 × 2조건 × 2반복: 정답률 direct 83.8% vs adaptive 73.5%(−10.3%p, CI −20.6~−1.5). probe 뒤 orchestrator가 해석을 미리 좁혀 두 worker의 독립 해석이 사라지는 것이 손실 원인. worker 선택에 probe 응답이 쓰이지 않음 |
| [GAIA non-web v22: evaluator 제거, v21 오답 11문제 재실행](2026-10-15-gaia-nonweb-v22-failed-tasks.ko.md) | C42(v22/r24) 표적 재실행 22 run: 같은 11문제에서 adaptive 0→4(공식)·5(보정), direct 1→2, adaptive 비용 −40%. 오답으로 고른 표본이라 개선 폭은 미정. 새 실패: 그럴듯한 틀린 해석·수 확정(ec09fa32, cca530fc), finish 옮겨 쓰기 오류 |
| [GAIA non-web 실패 유형](2026-10-15-gaia-nonweb-failure-modes.ko.md) | 위 72 run의 오답 21개(direct 10, adaptive 11) trace 분류: 외부 지식, 정답 후보 미확정(adaptive 3), 해석 오류 확정, "답 없음" 결론, 이미지 범위. 대부분 evaluator 판단이 최종 답을 정함 |
| [GAIA non-web: direct vs adaptive](2026-10-13-gaia-nonweb-direct-vs-adaptive.ko.md) | v19/r22/e6 두 번째 실행 72 run: 두 조건의 흐름, 보정 채점 결과(27 vs 27, 비용 2.6배), 단서·refiner·probe 동작 관측 |
| [Evaluator 단독 state 갱신 live 진단](2026-10-12-evaluator-owned-state-live.ko.md) | v16/r19/e6·tools v7, 저비용 탐색 3개에서 실제 갱신·선택·전달 경로 확인 |
| [현재 프롬프트 검토](2026-10-12-prompt-review.ko.md) | v14 검토와 후속 수정, v16/r19/e6의 evaluator 단독 갱신까지 기록 |
| [GAIA 주요 trace live 재실행](2026-10-12-gaia-key-traces-live.ko.md) | v13/r15/e3 shared-state runtime의 10회 실제 실행, 과거 결과 대조와 실패 경로 |
| [최신 종합 재분석](2026-10-10-synthesis.ko.md) | 현재 가장 신뢰할 결론과 한계 |
| [Benchmark 검토와 추천](benchmark-selection.ko.md) | 기존 probe와 worker 선택 실험에 맞는 후보·추천 이유·한계 |
| [LongCoT perturbation 일관성 worker 선택](2026-10-12-longcot-perturbation-consistency.ko.md) | 별도 패키지 실험: 첫 노드 일관성으로 고른 worker vs 무작위·고정 worker (linear easy 23, hard 26) |
| [LongCoT 첫 subtask 일관성 worker 선택](2026-10-13-longcot-segment-routing.ko.md) | 별도 패키지 실험: 첫 subtask의 변형별 일관성이 첫 subtask·trajectory 전체 정답을 예측하는지, 그걸로 고른 worker vs 무작위·haiku 고정 (linear 41) |
| [Baseline·probe 비교](2026-10-09-baseline-and-probe-comparison.ko.md) | 50문제 baseline과 47문제 조건 비교의 당시 기록 |
| [Refiner 후속 진단](2026-10-10-refiner-diagnostics.ko.md) | 선택 문제의 기존 초안 회귀 점검과 최신 prompt 진단 |
| [사례 심층 분석 종합](2026-10-10-case-analysis.ko.md) | 실패 경로와 사후 분류; 인과 효과와 구분 |
| [문제별 사례](cases/README.md) | 26문제 및 전 조건 정답 22문제 분석 |
| [초기 pilot](2026-10-08-initial-pilot.ko.md) | 이전 설계의 역사적 참고; 현재 성능 결과로 사용하지 않음 |

과거 보고서의 주장은 최신 종합 문서에서 정정된 부분이 있습니다. 같은 실행을 여러 보고서가
다루므로 독립 반복으로 합산하지 않습니다. 과거 stage/phase 이름은 [용어 대응표](../experiments.md)에 있습니다.

원본 실행은 `outputs/experiments/`에 목적별로 보존했습니다. `python scripts/experiments.py list`로 찾습니다.
보존·이동·삭제 상세는 [retention.json](retention.json), 파일 검증은 `python scripts/experiments.py verify`입니다.
