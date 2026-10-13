# Evaluator 단독 state 갱신: 실제 pilot 진단

2026-10-12 KST. 실행 v16, probe/refiner r19, evaluator e6, tools v7.

## 목적과 고정 조건

Evaluator가 유효한 state를 바로 갱신하고 orchestrator는 다음 작업·executor·context를 선택하는 구조를 실제 모델과 웹 도구로 확인한다. 승인·거부 필드와 별도 refiner 재검토 호출을 제거했다. 네 필드 state, 전체 목록 교체 저장, 역할 소개와 prompt 절 구성은 유지했다. 오프라인 테스트 147개가 통과했다.

사용자 요청에 따라 기존 저비용 탐색 과제에서 Secret Santa → OpenCV → Freud 순서로 `multi_worker_probe` fresh를 각 1회 실행한다. Pool은 gen_luna·gen_haiku이며 둘 다 probe하고 하나를 실행자로 선택한다. Run당 $0.30·15분, 합계 $0.90 상한이다. 기본 위임·호출 한도와 task당 Serper 100-credit 제한은 유지한다. V7 공용 cache를 사용하므로 fresh는 새 대화·state·workspace를 뜻하며 빈 웹 cache를 뜻하지 않는다.

실행 전에 planned.csv·manifest.json·코드 snapshot을 저장했고 실행 중 production 코드를 바꾸지 않았다. `baseline_v1` 소속을 확인했으며 `eval_v1`은 열람·튜닝·실행하지 않는다. 정답 채점은 실행 후 별도 수행한다. 선택한 익숙한 과제 3개·단일 조건·반복 1회이므로 평균 성능이나 변경의 인과 효과를 추정하지 않는다.

## 결과

| 과제 | 채점 | 위임 / 실행자 | 수정 | 비용 | Serper credit | 소요 |
|---|---|---|---|---:|---:|---:|
| Secret Santa | 오답: Fred/Micah 조건부 답 보류 (정답 Fred) | 1 / haiku | rewritten | $0.01830114 | 0 | 2분 24.4초 |
| OpenCV | 정답 `Li Peng` | 1 / luna | not_needed | $0.05250946 | 21 | 2분 58.4초 |
| Freud | 정답 `Kleinpaul` | 3 / luna → luna → haiku | not_needed → not_needed → rewritten | $0.10966822 | 40 | 8분 18.5초 |

세 실행 모두 정상 종료했고 예정 실행 누락·인프라 실패·예산 종료는 없다. 정답은 2/3이다. 총 알려진 비용 **$0.18047882**(LLM 약 $0.11948, 유료 검색 $0.061)이며 비용 불명 LLM·검색 요청은 0건이다. LLM 83회, 도구 81회, 유료 검색 61 credit이다. Probe·조회·평가·수정·재시도 호출도 포함했다. 각 run의 검색 credit은 100 미만이며, 이번 live에서는 한도 도달·차단 경로를 거치지 않았다.

시작은 2026-10-12 13:46 KST, 마지막 실행 완료는 약 14:00 KST다. 저장된 실험 timestamp는 UTC 원문을 유지한다.

## Trace에서 확인한 동작

- State 갱신 10건 모두 evaluator 출력 직후 저장됐다. 이후 orchestrator 입력과 context 선택 snapshot이 당시 state와 일치했다. 승인 필드·승인 이벤트·별도 refiner 재검토 호출은 없었다.
- Context 선택 13건에서 선택 행의 내용·상태와 연결 근거 ID를 대조했다. 직접 선택한 기록과 해당 행의 근거가 실제 context에 포함됐으며, 참조 오류·JSON 수정 요청은 0건이었다.
- Haiku와 Luna 모두 실행자로 선택됐다. 수정 경로는 Secret Santa와 Freud 세 번째 위임, 수정 생략 경로는 OpenCV와 Freud 첫 두 위임에서 확인했다.
- Evaluator의 원 도구 기록 조회가 세 사례 모두 발생했다. Freud는 세 위임에 걸쳐 state를 유지하고 이전 보고도 조회했다. 첫 두 실행의 접근 차단·검색 실패와 새로운 단서를 다음 선택에 전달했다.
- 수정 불가·평가 실패·잘못된 참조·checkpoint 복원·검색 한도 도달은 이번 live에 발생하지 않았다. 해당 예외 경로의 근거는 오프라인 계약 검사이며 실제 모델 결과로 확대하지 않는다.

## 사례별 판단과 남은 문제

### Secret Santa: worker의 조건부 후보를 evaluator가 답 보류로 확정

Haiku는 gift 매칭을 Python으로 계산해 선물을 받지 못한 사람이 Rebecca임을 확인했다. 표의 두 번째 열을 recipient로 읽으면 Fred라고 추천했지만, 열 제목 `Giftee | Recipient` 때문에 반대로 읽으면 Micah라는 조건을 함께 적었다. Evaluator는 원 파일·계산 도구 기록을 읽고도 열 방향을 미확인으로 남겼으며 “no single giver should be selected”라고 판단했다. Orchestrator는 그 state를 따라 최종 답을 보류했다.

채점 정답은 Fred다. 이번 실패는 참조나 state 전달 문제가 아니라 **문제의 의도된 표 읽기와 허용할 해석 수준에 대한 worker·evaluator 판단**에 남았다. 특히 evaluator가 어떤 추가 조건을 필수로 요구하는지 검토할 사례다. 승인 단계 제거만으로 해결되지 않았으며, 정답을 prompt에 넣거나 이 표에만 적용되는 규칙을 추가하지 않았다.

### OpenCV: 버전 기여자와 기능 작성자를 구분한 채 정답

Luna는 OpenCV 4.0.0 변경 기록의 Mask-RCNN 항목, 같은 버전의 기여자 명단, 동명의 중국 총리 정보를 연결해 Li Peng을 답했다. 특정 기능의 PR 작성자를 확인하지 못했다는 한계를 별도로 보고했고 evaluator는 그 한계를 정답 보류 조건으로 확대하지 않았다. 최종 답은 Li Peng이었다. 이번 1회가 일반적인 개선 효과를 입증하지는 않는다.

### Freud: 두 번의 접근 실패 뒤 probe가 해결, 마지막 실행은 전달만 수행

첫 두 실행은 책·장·부분 snippet은 확인했지만 본문 접근이 막혀 답을 찾지 못했다. 세 번째 위임의 Haiku probe가 2024년 Wayback의 OAPEN 본문에서 Rudolf Kleinpaul의 책을 읽은 뒤 Freud가 “endopsychic myths”를 발견했다는 대목을 찾았다. Evaluator는 이 원문과 장 위치의 indexed excerpt를 함께 근거로 Kleinpaul을 supported로 갱신했다. Printed page를 확인하지 못한 점은 surname 답의 필수 조건으로 삼지 않았다.

이때 **probe 평가만으로 답이 지지됐는데도 실행자 선택 단계는 finish를 허용하지 않아 추가 worker 실행을 거쳤다.** Orchestrator는 그 실행을 새 검색 없이 이미 지지된 답만 보고하도록 바꾸고 Haiku를 선택했으며 refiner가 지시를 작성했다. 따라서 정답에는 도달했지만 마지막 refiner·실행·평가가 필요했는지는 후속 설계 검토 대상으로 남는다. 이번에는 호출 계약을 바꾸거나 실험 중 코드를 수정하지 않았다.

## 해석의 범위

이전 v13/r15/e3 진단과 비교하면 선택한 세 과제의 정오 패턴은 동일하다. 그렇다고 버전이 동등하다고 결론 내릴 수 없다. 이번에는 단일 조건·각 1회이며 도구 v7의 별도 cache, 웹 접근 결과와 예산도 달랐다. 역할 분담과 기록 전달 계약은 실제 trace에서 확인했지만 정확도·비용의 인과적 개선은 입증하지 않았다.


## 원본과 재현

실험 디렉터리: `outputs/experiments/2026-10-12_evaluator-owned-state-live/`. `planned.csv`, `manifest.json`, `code_snapshot.tar.gz`, `batch.jsonl`, `runs/`, `logs/`에 계획·코드·원본을 보존한다. `analysis/`에 읽기용 trace·채점·계약 검사를 기록한다.
