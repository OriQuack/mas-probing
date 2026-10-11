# 프롬프트 읽기와 수정

역할별 Python 파일을 열면 실제 지시 문구를 multiline 문자열로 읽을 수 있습니다.
입력 준비와 본문이 같은 함수 안에 있으며, 별도 템플릿 파일이나 범용 로더는 없습니다.

| 읽을 내용 | 파일 / 함수 |
|---|---|
| 위임·최종 답변 | [orchestrator.py](orchestrator.py): `orchestrator_system` — 단일·복수 역할 각각 완성된 본문 |
| 작업 수행·보고 | [worker.py](worker.py): `worker_system`, `worker_request` |
| 수행 전 이해·가정·위험·계획 | [probe.py](probe.py): `probe_system`, `probe_instruction`, `parse_probe` |
| worker 응답 예측 | [refiner.py](refiner.py): `simulate_request` |
| 쟁점 판단·확인 요청 | [refiner.py](refiner.py): `analyze_request` |
| 사전 확인·최종 지시 작성 | [refiner.py](refiner.py): `verify_instruction`, `rewrite_request` |
| 원 문제·실행 날짜 | [task.py](task.py): `original_task_text` |
| 페이지 판독 | [reader.py](reader.py): `PROMPT`, `PART_PROMPT` |

`{original_task}`, `{instruction}`, 응답·도구 목록 등은 실행 데이터입니다.
공통 검토 머리말, 도구 정책, 선택적 context는 작은 상수·함수로 공유합니다.
분석 함수의 선택적 응답 대조 문단은 본문의 검토 순서에 놓았습니다.
실제 응답과 예측 응답의 설명, 복수 응답 비교 등 조건별 문구도 같은 함수에서 확인할 수 있습니다.
본문을 읽기 위해 다른 템플릿을 찾아 조립하지 않아도 되도록 유지합니다.

JSON 출력 계약은 [schemas.py](schemas.py), 도구 설명은 [tools.py](tools.py)에 있습니다.
공통 문구를 고칠 때는 공유 상수·함수를 수정하고, 단일·복수 역할 orchestrator의 공통 규칙을
고칠 때는 두 본문을 함께 수정합니다. 문구를 바꾸면 `__init__.py`의 해당 버전을 올립니다.
실행 prompt 버전과 refiner prompt 버전은 독립적이며, 구조만 바꿔 출력이 같으면 올리지 않습니다.

실제 데이터가 채워진 예시가 필요할 때만 미리보기를 사용합니다. 모델이나 웹을 호출하지 않습니다.

```bash
python scripts/show_prompts.py --component probe
python scripts/show_prompts.py --component analysis --context "Earlier report" --probe-tools
python scripts/show_prompts.py --component all --pool multi
```

실행 당시 전체 입력은 해당 run의 `messages.jsonl`과 `llm_calls.jsonl`에 있습니다.
현재 버전은 실행 v10 / refiner r12입니다. v8에서 orchestrator를 재작성했고,
v9에서는 worker 실행 지침을 정리했습니다. r10은 probe 전용 system prompt를 도입하고
`choices`를 `assumptions`로 변경했습니다. r10에서는 Analysis의 항목 명칭 외 검토·rewrite 정책을 유지했습니다.
r11에서는 refiner의 분석·rewrite를 의미별 섹션으로 재작성하고, subtask 범위 보존·해석 해결·증거 부족 처리를 명확히 했습니다. Pipeline과 응답 스키마는 유지합니다.

실행 v10 / refiner r12에서는 위임 경계와 context 근거 확인 기준을 구체화하고, probe 중복과 refiner 추상 표현을 줄였습니다. 결과에 영향 없는 구체적 우려는 `not_relevant`로 기록합니다. 역할·pipeline·응답 스키마는 유지하며 행동 효과는 아직 평가하지 않았습니다.

실행·사전 검증은 `worker_system`, probe·후속 질문은 `probe_system`을 사용합니다.
등록된 역할·도구·환경은 같으며 행동 지침만 다릅니다. 실제 probe와 예측 probe는 같은 본문을 씁니다.
연결 실행 variant는 이전 probe 대화를 유지하되 system prompt를 실행용으로 바꿉니다.
Probe의 질문·도구 정책·응답 파서는 `probe.py`, orchestrator 측 검토·수정은 `refiner.py`에 있습니다.
