# 프롬프트 읽기와 수정

역할별 Python 파일을 열면 실제 지시 문구를 multiline 문자열로 읽을 수 있습니다.
입력 준비와 본문이 같은 함수 안에 있으며, 별도 템플릿 파일이나 범용 로더는 없습니다.

| 읽을 내용 | 파일 / 함수 |
|---|---|
| 위임·최종 답변 | [orchestrator.py](orchestrator.py): `orchestrator_system` — 단일·복수 역할 각각 완성된 본문 |
| 작업 수행·보고 | [worker.py](worker.py): `worker_system`, `worker_request` |
| 이해·선택·위험·계획 질문 | [refiner.py](refiner.py): `probe_instruction` |
| worker 응답 예측 | [refiner.py](refiner.py): `simulate_request` |
| 쟁점 판단·확인 요청 | [refiner.py](refiner.py): `analyze_request` |
| 사전 확인·최종 지시 작성 | [refiner.py](refiner.py): `verify_instruction`, `rewrite_request` |
| 원 문제·실행 날짜 | [task.py](task.py): `original_task_text` |
| 페이지 판독 | [reader.py](reader.py): `PROMPT`, `PART_PROMPT` |

`{original_task}`, `{instruction}`, 응답·도구 목록 등은 실행 데이터입니다.
공통 검토 머리말, 도구 정책, 선택적 context는 작은 상수·함수로 공유합니다.
분석 함수의 선택적 응답 대조 문단은 본문의 검토 순서에 놓았습니다.
`direct_check`는 그 문단을 생략하며, 조건에 따라 추가되는 문구도 같은 함수에서 확인할 수 있습니다.
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
이번 단순화는 기존 v7/r9의 출력 문구를 유지합니다.
