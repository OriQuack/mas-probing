"""One durable batch for SC probes; never blindly repeat an uncertain POST."""
from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path

from minpilot.llm.client import LLMClient
from minpilot.llm.specs import get_spec, reserve_usd
from minpilot.runtime.trace import Trace
from perturbation_consistency import instruction_selection as ins, self_consistency as sc
from perturbation_consistency.batch import TERMINAL, requests_http


def save(path, value):
    """Atomic replacement plus fsync, including parent directory metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, ensure_ascii=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_append(path, row):
    with path.open('a') as f:
        f.write(json.dumps(row) + '\n')
        f.flush()
        os.fsync(f.fileno())


def publish_jsonl(path, rows):
    text = ''.join(json.dumps(r) + '\n' for r in rows)
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def read(path):
    return json.loads(path.read_text())


def plan(exp, prompts, runner):
    model = get_spec(sc.WORKER)
    client = LLMClient(model, Trace(None), transport=lambda *a: None)
    salt = runner.base.digest(exp / 'manifest.json')
    requests = []
    for p in prompts:
        body = client.build_body([{'role': 'user', 'content': p['prompt']}], None, None, None)
        for sample in range(max(sc.KS)):
            key = hashlib.sha256(f'{salt}:{p["target_id"]}:{sample}'.encode()).hexdigest()[:24]
            requests.append({'custom_id': 'sc-' + key, 'key': key, 'target_id': p['target_id'],
                'sample': sample, 'answer_node': p['answer_node'], 'worker': sc.WORKER,
                'body': body, 'reserve_usd': reserve_usd(model, body),
                'trace': f'probe_batch/traces/{key}'})
    return requests


def payload(requests):
    model = get_spec(sc.WORKER)
    return {'endpoint': '/v1/chat/completions', 'model': model.model,
            'provider': {'only': [model.provider], 'allow_fallbacks': False},
            'completion_window': '24h', 'requests': [
                {'custom_id': r['custom_id'], 'body': {k: v for k, v in r['body'].items()
                                                     if k not in ('model', 'provider')}} for r in requests]}


def consume(exp, request, result, runner):
    """Replay cached output through normal validation/parser, without a network call."""
    model = get_spec(sc.WORKER)
    trace = Trace(exp / request['trace'])
    response = (result.get('response') or {}).get('body')
    parsed = {'answer': None, 'status': 'error', 'cost_usd': 0.}
    body = dict(response or {})
    usage = dict(body.get('usage') or {})
    if response:
        if usage.get('cost') is None:
            usage['cost'] = .5 * (model.price_prompt * float(usage.get('prompt_tokens') or 0) +
                                  model.price_completion * float(usage.get('completion_tokens') or 0))
            usage['cost_estimated'] = True
        body['usage'] = usage
        if not body.get('provider'):
            body['provider'] = model.provider
            body['provider_from_batch_pin'] = True
        # An in-memory trace avoids duplicating paid-call records during cached parsing.
        client = LLMClient(model, Trace(None), transport=lambda *a: body, retries=0)
        parsed = ins.solve_segment(client, request['body']['messages'][0]['content'], request['answer_node'])
        parsed.update(cost_usd=float(usage.get('cost') or 0.), cost_estimated=bool(usage.get('cost_estimated')))
    else:
        parsed['error'] = str(result.get('error') or 'terminal batch without request result')[:500]
    old = runner.base.read_rows(exp / request['trace'] / 'llm_calls.jsonl')
    if not any(r.get('status') in ('ok', 'error') for r in old):
        choice = (body.get('choices') or [{}])[0]
        trace.llm({'call_id': 1, 'attempt': 0, 'status': 'error' if parsed['status'] in ('error', 'budget') else 'ok',
                   'model_key': sc.WORKER, 'model': model.model, 'custom_id': request['custom_id'],
                   'usage': usage, 'generation_id': body.get('id'), 'provider': body.get('provider'),
                   'served_model': body.get('model'), 'finish_reason': choice.get('finish_reason'),
                   'output': (choice.get('message') or {}).get('content'), 'error': parsed.get('error')})
    return {'target_id': request['target_id'], 'sample': request['sample'], 'worker': sc.WORKER,
            'custom_id': request['custom_id'], **parsed}


def run(args, targets, runner, *, http=None, sleep=time.sleep):
    if args.session_cost_usd is None or args.run_cost_usd is None or min(args.session_cost_usd, args.run_cost_usd) <= 0:
        raise ValueError('paid batch requires positive session and per-call caps')
    exp = args.experiment
    directory = exp / 'probe_batch'
    directory.mkdir(exist_ok=True)
    expected = plan(exp, runner.base.read_rows(exp / 'prompts.jsonl'), runner)
    requests_path = directory / 'requests.json'
    if requests_path.exists():
        if read(requests_path) != expected:
            raise ValueError('durable request mapping changed')
    else:
        if (exp / 'results.jsonl').exists() or (exp / 'probe_jobs.jsonl').exists():
            raise ValueError('cannot mix threaded/sync probes and durable batch')
        save(requests_path, expected)
    mapping_sha = runner.base.digest(requests_path)
    if sum(r['reserve_usd'] for r in expected) > args.session_cost_usd:
        raise ValueError('total conservative request reservations exceed session cap')
    if max(r['reserve_usd'] for r in expected) > args.run_cost_usd:
        raise ValueError('request reservation exceeds per-call cap')
    journal = exp / 'probe_jobs.jsonl'
    existing = {r['key'] for r in runner.base.read_rows(journal)}
    for r in expected:
        if r['key'] in existing:
            continue
        trace = Trace(exp / r['trace'])
        trace.llm({'call_id': 1, 'attempt': 0, 'status': 'started', 'model_key': sc.WORKER,
                   'model': get_spec(sc.WORKER).model, 'messages': trace.message_hashes(r['body']['messages']),
                   'reserve_usd': r['reserve_usd'], 'custom_id': r['custom_id']})
        durable_append(journal, {'key': r['key'], 'trace': r['trace'], 'worker': sc.WORKER,
            'custom_id': r['custom_id'], 'target_id': r['target_id'], 'sample': r['sample'],
            'transport': 'durable_single_batch', 'session_cost_usd': args.session_cost_usd,
            'run_cost_usd': args.run_cost_usd, 'started_at': runner.base.now()})
    body = payload(expected)
    payload_sha = hashlib.sha256(json.dumps(body).encode()).hexdigest()
    state_path = directory / 'submission.json'
    if http is None:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
        http = requests_http(os.environ['OPENROUTER_API_KEY'])
    if state_path.exists():
        state = read(state_path)
        if state['mapping_sha256'] != mapping_sha or state['payload_sha256'] != payload_sha:
            raise ValueError('submitted request mapping/payload changed')
        if not state.get('batch_id') and (directory / 'submission_response.json').exists():
            saved = read(directory / 'submission_response.json')
            if saved['http_status'] in (200, 201, 202) and saved['response'].get('id'):
                state.update(state='submitted', batch_id=saved['response']['id'])
                save(state_path, state)
        if not state.get('batch_id'):
            raise ValueError('submission outcome uncertain/rejected: reconcile saved POST before retry; no automatic resubmission')
    else:
        state = {'state': 'submitting', 'mapping_sha256': mapping_sha, 'payload_sha256': payload_sha,
                 'submitted_at': runner.base.now(), 'n': len(expected),
                 'reserved_upper_bound_usd': sum(r['reserve_usd'] for r in expected),
                 'stage_cost_limit_usd': args.session_cost_usd}
        save(state_path, state)  # Crash after this point must NOT cause another POST.
        status, response = http('POST', '/batches', body)
        save(directory / 'submission_response.json', {'http_status': status, 'response': response})
        if status not in (200, 201, 202) or not response.get('id'):
            save(state_path, {**state, 'state': 'uncertain_or_rejected', 'http_status': status})
            raise RuntimeError(f'batch POST HTTP {status}: saved response; no automatic resubmission')
        state.update(state='submitted', batch_id=response['id'])
        save(state_path, state)
    batch_id = state['batch_id']
    batches_path = exp / 'probe_batches.jsonl'
    if not any(r.get('event') == 'submitted' for r in runner.base.read_rows(batches_path)):
        durable_append(batches_path, {'event': 'submitted', 'batch_id': batch_id, 'n': len(expected),
            'model': get_spec(sc.WORKER).model, 'custom_ids': [r['custom_id'] for r in expected],
            'mapping_sha256': mapping_sha, 'ts': time.time()})
    print(json.dumps({'batch_id': batch_id, 'requests': len(expected), 'mapping_sha256': mapping_sha}), flush=True)
    if getattr(args, 'submit_only', False):
        return
    cache = directory / 'terminal_response.json'
    while not cache.exists():
        status, data = http('GET', '/batches/' + batch_id, None)
        save(directory / 'poll_status.json', {'checked_at': runner.base.now(), 'http_status': status,
            'batch_id': batch_id, 'status': data.get('status'), 'request_counts': data.get('request_counts'),
            'usage': data.get('usage'), 'error': data.get('error')})
        if status == 200 and data.get('status') in TERMINAL:
            save(cache, data)
            break
        if status in (401, 402, 403, 404):
            raise RuntimeError(f'batch poll HTTP {status}; preserve mapping and stop')
        sleep(30)
    data = read(cache)
    raw = data.get('results') or []
    ids = [r['custom_id'] for r in raw]
    allowed = {r['custom_id'] for r in expected}
    if len(ids) != len(set(ids)) or not set(ids) <= allowed:
        raise ValueError('duplicate or unexpected remote custom IDs; preserve raw output')
    responses = {r['custom_id']: r for r in raw}
    results = []
    for r in expected:
        slot = directory / 'slots' / (r['custom_id'] + '.json')
        if not slot.exists():
            save(slot, consume(exp, r, responses.get(r['custom_id'], {}), runner))
        results.append(read(slot))
    sc.votes(targets, results)  # Exact planned slot/worker validation before publishing.
    result_path = exp / 'results.jsonl'
    text = ''.join(json.dumps(r) + '\n' for r in results)
    if result_path.exists():
        if result_path.read_text() != text:
            raise ValueError('published results differ from cached slots')
    else:
        temp = result_path.with_suffix('.tmp')
        with temp.open('w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(result_path)
    if not any(r.get('event') == 'finished' for r in runner.base.read_rows(batches_path)):
        durable_append(batches_path, {'event': 'finished', 'batch_id': batch_id, 'status': data['status'],
            'request_counts': data.get('request_counts'), 'usage': data.get('usage'), 'error': data.get('error'),
            'ts': time.time()})
    save(directory / 'collection.json', {'complete': True, 'batch_id': batch_id, 'slots': len(results),
        'batch_status': data['status'], 'collected_at': runner.base.now(), 'results_sha256': runner.base.digest(result_path)})
