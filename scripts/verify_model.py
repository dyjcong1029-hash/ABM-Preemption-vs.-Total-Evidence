"""Read-only source and mathematical acceptance of the pinned NetLogo models.

This is deliberately NOT a NetLogo implementation or a replacement simulation.
A fail-closed interpreter executes a small, explicitly supported language subset
from the actual source: arithmetic/update procedures, one message handler, and
the go control flow with event stubs. Native execution is verified separately.
The JSON distinguishes these guarantees from full compiler/runtime guarantees.
Uses only the Python standard library; never writes models or upstream data.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LEX = re.compile(r'\s+|;[^\n]*|"(?:\\.|[^"\\])*"|[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[a-zA-Z_][\w?%-]*|->|<=|>=|!=|[\[\]()<>+*/^=,-]')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def tokens(source):
    """Tokenize strings/comments separately; reject unrecognized characters."""
    result, cursor = [], 0
    for match in LEX.finditer(source):
        require(not source[cursor:match.start()].strip(),
                f"Unsupported source at {source[cursor:match.start()]!r}")
        value = match.group()
        if not value.isspace() and not value.startswith(';'):
            result.append(value)
        cursor = match.end()
    require(not source[cursor:].strip(), "Unrecognized trailing source")
    return result


@dataclass
class Procedure:
    name: str
    args: list[str]
    body: list[str]


def procedures(source):
    ts, result, i = tokens(source), {}, 0
    while i < len(ts):
        if ts[i] not in ('to', 'to-report'):
            i += 1
            continue
        name, i = ts[i + 1], i + 2
        args = []
        if ts[i] == '[':
            j = ts.index(']', i)
            args, i = ts[i + 1:j], j + 1
        j = ts.index('end', i)
        require(name not in result, f"Duplicate procedure {name}")
        result[name] = Procedure(name, args, ts[i:j])
        i = j + 1
    require(result, "No procedures found")
    return result


ARITY = {'ln': 1, 'exp': 1, 'abs': 1, 'floor': 1, 'round': 1, 'not': 1,
         'min': 1, 'max': 1, 'length': 1, 'empty?': 1, 'member?': 2,
         'lput': 2, 'item': 2, 'sort': 1, 'range': 1, 'expert': 1,
         'is-layperson?': 1, 'random-float': 1}
PREC = {'or': 1, 'and': 2, '=': 3, '!=': 3, '<': 3, '>': 3,
        '<=': 3, '>=': 3, '+': 4, '-': 4, '*': 5, '/': 5, '^': 6}


class Parser:
    """A restricted parser; unsupported NetLogo constructs are errors."""
    def __init__(self, ts, procs):
        self.ts, self.i, self.procs = ts, 0, procs

    def take(self, expected=None):
        require(self.i < len(self.ts), 'Unexpected end of restricted program')
        value = self.ts[self.i]
        self.i += 1
        require(expected is None or value == expected, f"Expected {expected}, got {value}")
        return value

    def peek(self):
        return self.ts[self.i] if self.i < len(self.ts) else None

    def expr(self, minimum=0):
        token = self.take()
        if token == '(':
            if self.peek() == 'list':
                self.take()
                items = []
                while self.peek() != ')':
                    items.append(self.expr())
                left = ('list', items)
            else:
                left = self.expr()
            self.take(')')
        elif token == '[':
            items = []
            while self.peek() != ']':
                items.append(self.expr())
            self.take(']')
            left = ('list', items)
        elif token.startswith('"'):
            left = ('literal', json.loads(token))
        elif re.fullmatch(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?', token):
            left = ('literal', float(token))
        elif token in ('true', 'false'):
            left = ('literal', token == 'true')
        elif token in ARITY or (token in self.procs and token != 'go'):
            arity = ARITY[token] if token in ARITY else len(self.procs[token].args)
            left = ('call', token, [self.expr(7) for _ in range(arity)])
        else:
            left = ('var', token)
        while self.peek() in PREC and PREC[self.peek()] >= minimum:
            operator = self.take()
            right = self.expr(PREC[operator] + 1)
            left = ('binary', operator, left, right)
        return left

    def block(self):
        self.take('[')
        result = self.commands(']')
        self.take(']')
        return result

    def commands(self, until=None):
        result = []
        while self.peek() is not None and self.peek() != until:
            command = self.take()
            if command in ('let', 'set'):
                result.append((command, self.take(), self.expr()))
            elif command in ('report', 'error'):
                result.append((command, self.expr()))
            elif command in ('stop', 'tick'):
                result.append((command,))
            elif command in ('if', 'ifelse'):
                condition, yes = self.expr(), self.block()
                no = self.block() if command == 'ifelse' else []
                result.append(('if', condition, yes, no))
            elif command in ('ask', 'repeat'):
                result.append((command, self.expr(), self.block()))
            elif command == 'foreach':
                collection = self.expr()
                self.take('[')
                variable = self.take()
                self.take('->')
                body = self.commands(']')
                self.take(']')
                result.append(('foreach', collection, variable, body))
            elif command in self.procs:
                result.append(('invoke', command,
                               [self.expr(7) for _ in self.procs[command].args]))
            else:
                raise ValueError(f"Unsupported restricted command {command!r}")
        return result


class Report(Exception):
    def __init__(self, value):
        self.value = value


class Subset:
    def __init__(self, procs, state=None, stubs=None):
        self.procs, self.state = procs, state if state is not None else {}
        self.stubs, self.compiled = stubs or {}, {}

    def evaluate(self, expression, local):
        kind = expression[0]
        if kind == 'literal':
            return expression[1]
        if kind == 'var':
            name = expression[1]
            require(name in local or name in self.state, f"Unknown restricted variable {name}")
            return local[name] if name in local else self.state[name]
        if kind == 'list':
            return [self.evaluate(item, local) for item in expression[1]]
        if kind == 'binary':
            op = expression[1]
            a, b = (self.evaluate(x, local) for x in expression[2:])
            return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b,
                    '/': lambda: a/b, '^': lambda: a**b, '=': lambda: a == b,
                    '!=': lambda: a != b, '<': lambda: a < b, '>': lambda: a > b,
                    '<=': lambda: a <= b, '>=': lambda: a >= b,
                    'and': lambda: bool(a and b), 'or': lambda: bool(a or b)}[op]()
        name, arguments = expression[1], [self.evaluate(x, local) for x in expression[2]]
        funcs = {'ln': math.log, 'exp': math.exp, 'abs': abs, 'floor': math.floor,
                 'round': round, 'not': lambda x: not x, 'min': min, 'max': max,
                 'length': len, 'empty?': lambda x: not x, 'member?': lambda x, xs: x in xs,
                 'lput': lambda x, xs: [*xs, x], 'item': lambda n, xs: xs[int(n)],
                 'sort': sorted, 'range': lambda n: list(range(int(n))),
                 'expert': lambda n: ('expert', n), 'is-layperson?': lambda _: True}
        if name == 'random-float':
            raise ValueError('Random sampling is forbidden in this deterministic checker')
        return funcs[name](*arguments) if name in funcs else self.call(name, arguments)

    def execute(self, commands, local):
        for statement in commands:
            kind = statement[0]
            if kind in ('let', 'set'):
                name, value = statement[1], self.evaluate(statement[2], local)
                (local if kind == 'let' or name in local else self.state)[name] = value
            elif kind == 'report':
                raise Report(self.evaluate(statement[1], local))
            elif kind == 'error':
                raise ValueError(self.evaluate(statement[1], local))
            elif kind == 'stop':
                raise Report(None)
            elif kind == 'tick':
                self.state['ticks'] += 1
            elif kind == 'if':
                self.execute(statement[2] if self.evaluate(statement[1], local) else statement[3], local)
            elif kind == 'ask':
                self.evaluate(statement[1], local)
                self.execute(statement[2], local)
            elif kind == 'repeat':
                for _ in range(int(self.evaluate(statement[1], local))):
                    self.execute(statement[2], local)
            elif kind == 'foreach':
                for value in self.evaluate(statement[1], local):
                    self.execute(statement[3], {**local, statement[2]: value})
            elif kind == 'invoke':
                self.call(statement[1], [self.evaluate(x, local) for x in statement[2]])
            else:
                raise ValueError(f"Unsupported restricted statement {kind}")

    def call(self, name, arguments=()):
        if name in self.stubs:
            return self.stubs[name](*arguments)
        if name not in self.compiled:
            self.compiled[name] = Parser(self.procs[name].body, self.procs).commands()
        require(len(arguments) == len(self.procs[name].args), f"Wrong arity: {name}")
        try:
            self.execute(self.compiled[name], dict(zip(self.procs[name].args, arguments)))
        except Report as result:
            return result.value


def bracket_body(ts, start):
    require(ts[start] == '[', 'Block start expected')
    depth = 1
    for j in range(start + 1, len(ts)):
        depth += (ts[j] == '[') - (ts[j] == ']')
        if depth == 0:
            return ts[start + 1:j], j + 1
    raise ValueError('Unbalanced source block')


def after_sequence(ts, sequence):
    hits = [i for i in range(len(ts) - len(sequence) + 1) if ts[i:i+len(sequence)] == sequence]
    require(len(hits) == 1, f"Expected one source sequence {sequence}, got {len(hits)}")
    return hits[0] + len(sequence)


def close(actual, expected, label, tolerance=2e-12):
    require(math.isfinite(actual) and abs(actual - expected) <= tolerance,
            f"{label}: {actual!r} != {expected!r}")


def git_blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def source_identity(root):
    manifest = json.loads((root / 'source_manifest.json').read_text(encoding='utf-8'))
    checked = []
    # README is an editable explanation; figures and legacy models are outside
    # the core executable/data scope. Do not label documentation edits defects.
    for item in manifest['files']:
        if not item['path'].startswith(('models/', 'data/')):
            continue
        path = root / item['path']
        require(path.is_file(), f"Missing upstream scientific file {item['path']}")
        require(git_blob(path) == item['git_blob_sha'], f"Upstream scientific file changed: {item['path']}")
        checked.append(item['path'])
    return {'repository': manifest['repository'], 'commit': manifest['ref'],
            'scientific_files_checked': len(checked), 'excluded_editable_explanation': 'README.md'}


def grids(xml):
    result = {}
    for experiment in xml.findall('.//experiments/experiment'):
        values = {}
        for node in experiment.iter():
            if node.tag == 'enumeratedValueSet':
                values[node.attrib['variable']] = [json.loads(x.attrib['value']) for x in node]
            elif node.tag == 'steppedValueSet':
                first, step, last = (int(node.attrib[x]) for x in ('first', 'step', 'last'))
                require(step > 0 and last >= first and (last-first) % step == 0, 'Bad stepped grid')
                values[node.attrib['variable']] = list(range(first, last+1, step))
        count = int(experiment.attrib['repetitions']) * math.prod(map(len, values.values()))
        require(len(set(experiment.findtext('setup', '').split())) > 0, 'Missing setup command')
        require(experiment.findtext('go') in ('go', 'go-expert-calibration'), 'Unexpected go command')
        result[experiment.attrib['name']] = {'runs': count, 'variables': values,
                                             'go': experiment.findtext('go')}
    require(result, 'No BehaviorSpace experiments parsed')
    return result


def probability_checks(procs):
    sub = Subset(procs)
    sub.call('setup-fixed-constants')
    constants = sub.state
    require([constants[x] for x in ('laypeople-fixed', 'total-ticks-fixed',
            'expert-active-ticks-fixed', 'expert-pulls-per-tick-fixed')] == [10, 500, 25, 5],
            'Scientific design constants changed')
    close(constants['p-a'], .5, 'p_A')
    close(constants['p-b-good'], .55, 'p_B good')
    close(constants['p-b-bad'], .45, 'p_B bad')
    close(constants['llr-unit'], math.log(11/9), 'B outcome log likelihood')
    update = 'update-decision-belief-from-result' if 'update-decision-belief-from-result' in procs else 'update-belief-from-result'
    cases = 0
    # Execute the parsed source and compare with a separate exact-rational
    # likelihood calculation, including A's zero likelihood contribution.
    for success in range(21):
        for failure in range(21):
            sub.state.update({'belief-llr': 0., 'evidence-b-successes': 0, 'evidence-b-failures': 0})
            for _ in range(success):
                sub.call(update, [True, 1])
            for _ in range(failure):
                sub.call(update, [True, 0])
            before = dict(sub.state)
            sub.call(update, [False, 0])
            sub.call(update, [False, 1])
            require(sub.state == before, 'A outcome changed decision evidence')
            likelihood_good = Fraction(11, 20)**success * Fraction(9, 20)**failure
            likelihood_bad = Fraction(9, 20)**success * Fraction(11, 20)**failure
            expected = float(likelihood_good / (likelihood_good + likelihood_bad))
            close(sub.call('posterior-q', [sub.state['belief-llr']]), expected, 'Exact Bayes posterior')
            cases += 1
    # Evaluate each actual arm-choice expression, rather than an independent
    # reimplementation of Thompson sampling.
    for procedure, sink in (('layperson-pull', 'chose-b?'), ('expert-pull', 'last-chose-b?')):
        body = procs[procedure].body
        pos = after_sequence(body, ['set', sink])
        parser = Parser(body[pos:], procs)
        selection = parser.expr()
        require(selection == ('binary', '<', ('var', 'thompson-draw'), ('var', 'q')),
                f"{procedure}: unexpected action formula / hidden input")
        pos = after_sequence(body, ['let', 'thompson-draw'])
        require(Parser(body[pos:], procs).expr() == ('call', 'random-float', [('literal', 1.)]),
                'Action coin must be independent random-float 1')
        require(not any(body[i:i+2] in (['set', 'q'], ['set', 'thompson-draw'])
                        for i in range(len(body)-1)), 'Action coin or q overwritten before selection')
        for q in (0., .1, .5, .9, 1.):
            for coin in (0., .05, .5, .95):
                require(sub.evaluate(selection, {'q': q, 'thompson-draw': coin}) == (coin < q), 'Thompson boundary')
    return {'parsed_source_Bayes_cases': cases, 'exact_oracle': 'Fraction likelihoods',
            'A_uninformative': True, 'Thompson_expression_and_boundaries': True,
            'predictive_B_success': '.45 + .10*q (derived; not the action probability)'}


def policy_checks(procs):
    if 'apply-evidence-intervention' not in procs:
        return {'applicable': False}
    source = procs['apply-evidence-intervention'].body
    branches = {}
    for policy in ('E-Preemption', 'E-Total Evidence'):
        pos = after_sequence(source, ['if', 'evidence-policy', '=', json.dumps(policy)])
        body, _ = bracket_body(source, pos)
        branches[policy] = Parser(body, procs).commands()
    cases = 0
    unit = math.log(11/9)
    for local_net in range(-12, 13):
        for expert_net in range(-5, 6):
            for policy, commands in branches.items():
                successes, failures = max(local_net, 0), max(-local_net, 0)
                state = {'llr-unit': unit, 'evidence-b-successes': successes, 'evidence-b-failures': failures,
                         'processed-successes': max(expert_net, 0),
                         'processed-failures': max(-expert_net, 0),
                         'processed-packet-llr': expert_net*unit,
                         'pre-intervention-llr': local_net*unit,
                         'pre-intervention-local-item-count': 75,
                         'expert-packet-size-at-intervention': 125}
                sub = Subset(procs, state)
                sub.execute(commands, {})
                net = expert_net + (local_net if policy == 'E-Total Evidence' else 0)
                expected_odds = Fraction(11, 9)**net
                close(sub.call('posterior-q', [state['decision-base-llr']]),
                      float(expected_odds/(1+expected_odds)), 'Evidence policy exact posterior')
                require(state['decision-base-item-count'] == (200 if policy == 'E-Total Evidence' else 125),
                        'Policy active evidence count')
                # Execute the actual post-intervention update procedure. This
                # checks that P is a one-time replacement, not frozen copying.
                state.update({'belief-llr': state['decision-base-llr'], 'archive-b-successes': 0,
                              'archive-b-failures': 0, 'deference-applied?': True, 'self': 1,
                              'post-intervention-local-llr': 0., 'post-intervention-local-item-count': 0})
                sub.call('observe-new-evidence', [True, 1])
                close(state['belief-llr'], (net+1)*unit, 'Continuing post-intervention learning')
                close(state['belief-llr'], state['decision-base-llr']+state['post-intervention-local-llr'],
                      'Decision decomposition')
                require(state['post-intervention-local-item-count'] == 1, 'Post-intervention count')
                cases += 1
    return {'parsed_source_policy_and_continuation_cases': cases,
            'exact_oracle': 'rational likelihood odds; no random sampling',
            'not_claimed': 'Raw expert packet construction/overlap rejection; see native fixtures'}


def control_flow_checks(procs):
    sub = Subset(procs)
    sub.call('setup-fixed-constants')
    sub.state.update({'ticks': 0, 'laypeople': list(range(1, 11))})
    events = []
    names = ['expert-pull', 'layperson-pull', 'queue-first-hand-messages',
             'deliver-peer-messages', 'record-expertise-snapshot', 'update-display']
    intervention = next((n for n in ('apply-evidence-intervention', 'apply-credence-intervention') if n in procs), None)
    if intervention:
        names.append(intervention)
    sub.stubs = {name: (lambda *args, name=name: events.append((name, sub.state['ticks']))) for name in names}
    for _ in range(500):
        sub.call('go')
    require(sum(n == 'expert-pull' for n, _ in events) == 125, 'Expert scheduling count')
    require(sum(n == 'layperson-pull' for n, _ in events) == 5000, 'Student scheduling count')
    for t in range(500):
        require(sum(n == 'layperson-pull' and k == t for n, k in events) == 10, 'Student cadence')
        if t:
            delivery = events.index(('deliver-peer-messages', t))
            action = events.index(('layperson-pull', t))
            require(events.index(('queue-first-hand-messages', t-1)) < delivery < action, 'Message timing')
    require(('deliver-peer-messages', 500) not in events, 'Unexpected final-round delivery')
    if intervention:
        require(sum(n == intervention for n, _ in events) == 1, 'Intervention count')
        require(events.index(('deliver-peer-messages', 25)) < events.index((intervention, 25)) <
                events.index(('layperson-pull', 25)), 'Round-25/26 intervention boundary')
    old_events = len(events)
    sub.call('go')
    require(len(events) == old_events, 'go did not stop at horizon')
    return {'method': 'parsed go control flow; named agent/environment/event calls stubbed',
            'expert_pulls': 125, 'student_pulls': 5000, 'last_delivered_round': 499,
            'intervention_after_round25_delivery_before_round26_action': bool(intervention),
            'not_claimed': 'NetLogo agent scheduling/compiler correctness; see native fixtures'}


def communication_checks(procs):
    ts = procs['deliver-peer-messages'].body
    start = after_sequence(ts, ['foreach', 'delivered', '[', 'message', '->'])
    # Return the enclosing lambda's body, excluding its closing bracket.
    handler, _ = bracket_body(['['] + ts[start:], 0)
    compiled = Parser(handler, procs).commands()
    state = {'belief-llr': 0., 'llr-unit': math.log(11/9), 'evidence-b-successes': 0,
             'evidence-b-failures': 0, 'archive-b-successes': 0, 'archive-b-failures': 0,
             'seen-evidence-ids': [], 'peer-messages-received': 0, 'duplicate-message-count': 0,
             'deference-applied?': False, 'self': 1}
    sub = Subset(procs, state)
    message = [[2, 0, 0], True, 1]
    sub.execute(compiled, {'message': message})
    close(state['belief-llr'], math.log(11/9), 'First peer message')
    sub.execute(compiled, {'message': message})
    close(state['belief-llr'], math.log(11/9), 'Duplicate peer message counted twice')
    require(state['peer-messages-received'] == 1 and state['duplicate-message-count'] == 1,
            'Duplicate accounting')
    queue = procs['queue-first-hand-messages'].body
    pos = after_sequence(queue, ['let', 'message'])
    payload = Parser(queue[pos:], procs).expr()
    require(payload == ('list', [('list', [('var', 'who'), ('var', 'ticks'), ('literal', 0.)]),
                                ('var', 'chose-b?'), ('var', 'current-reward')]),
            'Peer payload can contain relayed/private evidence')
    require(queue.count('next-inbox') == 2 and queue.count('message') == 2,
            'Unexpected additional queue read/write path')
    return {'parsed_message_handler_duplicate_replay': True,
            'payload_exactly_own_current_arm_outcome_and_source_id': True,
            'no_forwarded_payload_in_this_queue_procedure': True,
            'not_claimed': 'Runtime agent identity and queue counts; see native fixtures'}


def expression_dependencies(expression, procs, visiting=None):
    """Conservative reporter-call closure for hidden-value reads."""
    visiting = visiting or set()
    if expression[0] == 'var':
        return {expression[1]}
    if expression[0] == 'literal':
        return set()
    if expression[0] == 'binary':
        return set().union(*(expression_dependencies(x, procs, visiting) for x in expression[2:]))
    if expression[0] == 'list':
        return set().union(*(expression_dependencies(x, procs, visiting) for x in expression[1]))
    name, args = expression[1:]
    deps = set().union(*(expression_dependencies(x, procs, visiting) for x in args))
    if name in procs and name not in visiting:
        # This intentionally over-approximates all tokens in the reporter. It
        # cannot prove the entire model is information-flow secure.
        deps |= set(procs[name].body)
        for token in procs[name].body:
            if token in procs and token != name:
                deps |= expression_dependencies(('call', token, []), procs, visiting | {name})
    return deps


def isolation_checks(procs):
    forbidden = {'hidden-world', 'p-b', 'p-a', 'action-correct?', 'posterior-truth-mass',
                 'recommendation-correct-score', 'correct-pulls', 'cumulative-expected-regret',
                 'private-expert-q-at-intervention', 'private-expert-llr-at-intervention'}
    checked = []
    for name in ('posterior-q', 'update-belief-from-result', 'update-decision-belief-from-result',
                 'observe-new-evidence', 'archive-evidence-result', 'deliver-peer-messages',
                 'queue-first-hand-messages'):
        if name not in procs:
            continue
        closure = expression_dependencies(('call', name, []), procs)
        require(not closure.intersection(forbidden), f"Hidden scoring input in evidence path {name}: {closure & forbidden}")
        checked.append(name)
    # Pull procedures legitimately call the environment and score with truth;
    # validate the actual decision inputs, not an incorrect blanket ban.
    for name in ('layperson-pull', 'expert-pull'):
        body = procs[name].body
        pos = after_sequence(body, ['let', 'q'])
        expr = Parser(body[pos:], procs).expr()
        require(expr == ('call', 'posterior-q', [('var', 'belief-llr')]), 'Action belief input changed')
        require(not expression_dependencies(expr, procs).intersection(forbidden), 'Truth path to action belief')
    result = {'protected_evidence_procedure_call_closures': checked,
              'decision_q_depends_only_on_belief_llr': True,
              'allowed_truth_uses': 'environment rewards and scoring/display instrumentation',
              'limit': 'Conservative source-level check of named paths; not whole-program noninterference or full social Bayesian inference'}
    if 'apply-credence-intervention' in procs:
        ts = procs['apply-credence-intervention'].body
        pos = after_sequence(ts, ['ask', 'a-layperson', '['])
        body, _ = bracket_body(['['] + ts[pos:], 0)
        require(not set(body).intersection(forbidden | {'experts', 'expert', 'evidence-archive'}),
                'Opaque recipient directly reads hidden expert/true state')
        # Compile the actual recipient body to reject unsupported hidden paths.
        commands = Parser(body, procs).commands()
        received = []
        for policy in ('C-Preemption', 'C-Total Evidence'):
            for hidden in (-4., 4.):
                state = {'belief-llr': -.4, 'seen-evidence-ids': [[1, 0, 0]],
                         'broadcast-message-bin': 6, 'broadcast-message-llr': .729360182394239,
                         'credence-items-received': 0, 'maximum-message-bin-copy-error': 0,
                         'maximum-message-llr-copy-error': 0, 'maximum-immediate-policy-formula-error': 0,
                         'shared-prior-llr': 0, 'credence-policy': policy,
                         'private-expert-q-at-intervention': hidden, 'hidden-world': str(hidden)}
                sub = Subset(procs, state)
                sub.execute(commands, {})
                expected = .729360182394239 + (-.4 if policy == 'C-Total Evidence' else 0)
                close(state['belief-llr'], expected, 'Coarse recipient update')
                received.append(state['belief-llr'])
        require(received[0] == received[1] and received[2] == received[3], 'Opaque recipient hidden state dependence')
        result['opaque_recipient_body_parsed_and_executed'] = True
        result['opaque_same_message_local_evidence_invariant_to_hidden_expert_state'] = True
    return result


def frozen_table_check(root, procs, grid):
    sub = Subset(procs)
    sub.call('setup-fixed-constants')
    table = sub.state['report-llr-table']
    with (root / 'data/experiment_2/frozen_credence_message_table.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == len(table) == 10, 'Message table is not ten bins')
    require(sum(int(row['estimate_count_good']) for row in rows) == int(rows[0]['estimate_n_good']), 'Good calibration sample accounting')
    require(sum(int(row['estimate_count_bad']) for row in rows) == int(rows[0]['estimate_n_bad']), 'Bad calibration sample accounting')
    for i, row in enumerate(rows):
        require(int(row['message_bin']) == i, 'Bin order')
        n_good, n_bad = int(row['estimate_n_good']), int(row['estimate_n_bad'])
        good = (int(row['estimate_count_good']) + .5) / (n_good + 10*.5)
        bad = (int(row['estimate_count_bad']) + .5) / (n_bad + 10*.5)
        close(float(row['p_message_given_good']), good, 'Jeffreys good probability')
        close(float(row['p_message_given_bad']), bad, 'Jeffreys bad probability')
        close(float(row['message_lambda']), math.log(good/bad), 'Message LLR recomputation')
        close(table[i], math.log(good/bad), 'Frozen table versus model source')
        close(sub.call('posterior-q', [table[i]]), float(row['implied_p_good_given_message']), 'Implied message posterior')
        for q in (i/10 + .0001, (i+1)/10 - .0001):
            require(sub.call('credence-bin', [q]) == i, 'Parsed bin boundaries')
    require(sub.call('credence-bin', [0]) == 0 and sub.call('credence-bin', [1]) == 9, 'Bin endpoints')
    calibration = [set(v['variables']['run-seed']) for k, v in grid.items() if 'calibration-' in k]
    for i, left in enumerate(calibration):
        for right in calibration[i+1:]:
            require(left.isdisjoint(right), 'Calibration/heldout seed ranges overlap')
    main_seeds = set(next(v['variables']['run-seed'] for k, v in grid.items() if 'opaque-main-final' in k))
    require(all(main_seeds.isdisjoint(c) for c in calibration), 'Formal seeds overlap calibration')
    return {'bins': 10, 'source_equals_CSV': True, 'Jeffreys_smoothing_and_LLR_recomputed': True,
            'estimate_and_heldout_seed_grids_disjoint': True,
            'limit': 'Does not regenerate calibration trajectories; heldout data checked separately'}


def verify(root):
    identity = source_identity(root)
    models = []
    expected_main = [1000, 3000, 3000]
    for index in range(3):
        folder = root / 'models' / f'experiment_{index}'
        source_path, = folder.glob('*.nls')
        model_path, = folder.glob('*.nlogox')
        source = source_path.read_text(encoding='utf-8-sig')
        xml = ET.parse(model_path).getroot()
        require((xml.findtext('code') or '').strip() == source.strip(), f"Embedded code differs: {model_path}")
        procs, grid = procedures(source), grids(xml)
        main = [v for k, v in grid.items() if 'main-final' in k]
        require(len(main) == 1 and main[0]['runs'] == expected_main[index], 'Main experiment grid size')
        require(set(main[0]['variables']['world-mode']) == {'B-good', 'B-bad'}, 'Main worlds')
        require(main[0]['variables']['peer-sharing?'] == [True], 'Main peer-sharing setting')
        seeds = main[0]['variables']['run-seed']
        require(len(seeds) == len(set(seeds)) == 500, 'Main paired seeds')
        if index:
            key = 'evidence-policy' if index == 1 else 'credence-policy'
            policies = ['No Deference', 'E-Preemption', 'E-Total Evidence'] if index == 1 else ['No Deference', 'C-Preemption', 'C-Total Evidence']
            require(main[0]['variables'][key] == policies, 'Main strategy grid contains unexpected/exact validation policy')
        result = {'experiment': index, 'embedded_source_equal': True,
                  'grid_run_counts': {k: v['runs'] for k, v in grid.items()},
                  'mathematics': probability_checks(procs), 'control_flow_projection': control_flow_checks(procs),
                  'evidence_policy_subset': policy_checks(procs),
                  'communication_subset': communication_checks(procs), 'information_paths': isolation_checks(procs)}
        if index == 2:
            result['frozen_message_table'] = frozen_table_check(root, procs, grid)
        models.append(result)
    return {'passed': True, 'scope': 'static source + restricted parsed-source deterministic execution + exact mathematics',
            'upstream_identity': identity, 'models': models,
            'requires_separate_native_acceptance': ['NetLogo compilation', 'actual agent contexts and ring topology',
                'runtime message scheduling', 'all six main method/world paths and evidence intervention invariants'],
            'interpretation_boundary': 'Local evidence updating; no proof of full Bayesian social inference from neighbors arm choices.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'verification' / 'model')
    args = parser.parse_args(argv)
    try:
        result = verify(args.root.resolve())
    except Exception as error:
        result = {'passed': False, 'error_type': type(error).__name__, 'error': str(error),
                  'scope': 'model acceptance; failure is not by itself proof of a source-model defect'}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / 'model_verification.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'report': str(path),
                      **({'error': result['error']} if 'error' in result else {})}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
