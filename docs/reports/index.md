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
| [LongCoT instruction 합의 선택](2026-10-15-longcot-instruction-selection.ko.md) ([요약본](2026-10-15-longcot-instruction-selection-summary.ko.md): 전체 성공률·같은 문제 안 AUROC·잡음 기준선) | 별도 패키지 실험(v3, 후보 r2, linear 41): 합의 선택이 뒤 요청 node에서 naive보다 −12.3%p(CI −21.7–−3.4). 분해: instruction 효과 −9.7%p, 선택 효과 −2.6%p(0과 구분 안 됨). 합의 차이와 뒤 node 차이 상관 r=0.10. 실패 유형: clarify 조건 누락, local_check 의존값 보정 거부(undefined), analogical 틀린 유사 공식, 오답 합의 |
| [MoNaCo instruction 합의 선택 2문제 점검](2026-10-14-monaco-instruction-selection-e2e.ko.md) | 별도 패키지 실험: oracle 문서 + 질문만으로 후보 작성→probe→선택→실행→judge 경로 점검(2문제, 성능 비교 아님). 429·답 형식·근거 요구 instruction의 문제 기록 |
| [MoNaCo 답 묶기(luna) 공개 답 쌍 검증](2026-10-14-monaco-answer-clustering-validation.ko.md) | seed 20문제 밖 100문제에서 공개 실행들의 답(문제당 평균 22.5개)을 luna로 묶어 GPT-4.1 점수 라벨과 비교. 라벨 잡음이 커서 오류 예시 34개를 수동 분류: luna가 분명히 틀린 경우 3개, 라벨 잡음 21개 |
| [MoNaCo instruction 합의 선택 중간 난이도 2문제 점검](2026-10-14-monaco-instruction-selection-e2e-hard.ko.md) | v3(judge·묶기 luna-low) 경로 점검(성능 비교 아님). 429 없음. 여러 줄 `ANSWER:` 파싱 결함, 목록 답의 완전 일치 합의가 2/9로 무너져 무작위 선택, gold 결함 2건 |
| [MoNaCo instruction 합의 선택 20문제 본 실행](2026-10-14-monaco-instruction-selection.ko.md) | v4 oracle 설정 20문제 $3.51, v5 judge(luna-high, 최종 답 줄만) 재채점 $0.07. 합의 선택은 naive·random과 차이 없음(−0.009, −0.007). probe 답 채점(분석 전용): probe 점수로 고르면 +0.084(CI 0.007–0.184)라 후보 차이는 있으나 합의가 가리키지 못함(합의 vs probe 점수 28 대 33). 빈 답 합의(443), judge의 본문 항목 계수, 행 안 목록 형식 실패 기록 |
| [MoNaCo instruction 합의 선택 추가 30문제와 50문제 합산](2026-10-14-monaco-instruction-selection-extra30.ko.md) | v6 새 30문제 $4.48. clarify 이득(+0.065)과 probe 점수 선택 이득(+0.084)은 재현되지 않음(−0.027, +0.008). 50문제 합산: 합의 선택 naive 대비 −0.009, random 대비 +0.002; local_check만 naive보다 낮음(−0.047, CI −0.101–−0.008); 사후 최고 +0.058은 잡음 기준선 +0.045와 비슷 |
| [MoNaCo instruction 합의 선택 v7 층화 50문제](2026-10-15-monaco-instruction-selection-v7.ko.md) ([발표용 요약](2026-10-15-monaco-instruction-selection-summary.ko.md): 같은 문제 안 AUROC, 답 합치기) | v7(`Answers:` 줄, split 확인, 층화 대상, decompose·clarify·structured) $9.54. 합의 선택 naive 대비 +0.002, 목록에서는 −0.021로 무작위 선택과 같음(합의율 vs 점수 48 대 56). 사후 최고 +0.054는 잡음 기준선 +0.047과 구분 안 됨. 손실의 약 69%는 목록 수집·수 세기, 18%는 문서 밖 gold로 후보 간 차이 거의 없음 |
| [Baseline·probe 비교](2026-10-09-baseline-and-probe-comparison.ko.md) | 50문제 baseline과 47문제 조건 비교의 당시 기록 |
| [Refiner 후속 진단](2026-10-10-refiner-diagnostics.ko.md) | 선택 문제의 기존 초안 회귀 점검과 최신 prompt 진단 |
| [사례 심층 분석 종합](2026-10-10-case-analysis.ko.md) | 실패 경로와 사후 분류; 인과 효과와 구분 |
| [문제별 사례](cases/README.md) | 26문제 및 전 조건 정답 22문제 분석 |
| [초기 pilot](2026-10-08-initial-pilot.ko.md) | 이전 설계의 역사적 참고; 현재 성능 결과로 사용하지 않음 |

과거 보고서의 주장은 최신 종합 문서에서 정정된 부분이 있습니다. 같은 실행을 여러 보고서가
다루므로 독립 반복으로 합산하지 않습니다. 과거 stage/phase 이름은 [용어 대응표](../experiments.md)에 있습니다.

원본 실행은 `outputs/experiments/`에 목적별로 보존했습니다. `python scripts/experiments.py list`로 찾습니다.
보존·이동·삭제 상세는 [retention.json](retention.json), 파일 검증은 `python scripts/experiments.py verify`입니다.
