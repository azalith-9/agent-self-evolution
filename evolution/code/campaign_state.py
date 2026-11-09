"""Versioned, exclusively owned campaign progress with durable seed commits."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import stat
import threading
import uuid
from decimal import Decimal
from contextlib import contextmanager
from typing import Iterator
from pathlib import Path
from types import MappingProxyType

from evolution.code import strict_json as js
from evolution.code.verification_contracts import digest, fields, text
from evolution.core.secure_paths import ProtectedRoot, metadata_identity

MAX_RECORD = 1048576
ENVELOPE = {'schema_version', 'sequence', 'campaign_id', 'kind', 'previous_hash', 'payload', 'record_hash'}


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative integer required')
    return value


def _result(value: object) -> None:
    fields(value, {'diagnostic_status', 'reason', 'candidate_snapshot_id', 'observation_digest', 'cost_observation_ids', 'cost_coverage'})
    if value['diagnostic_status'] not in ('passed', 'failed'):
        raise ValueError('completion requires a measured result')
    text(value['reason'])
    if value['candidate_snapshot_id'] is not None:
        digest(value['candidate_snapshot_id'])
    digest(value['observation_digest'])
    if (type(value['cost_observation_ids']) is not list or
            len(set(value['cost_observation_ids'])) != len(value['cost_observation_ids']) or
            any(type(x) is not str or not x for x in value['cost_observation_ids']) or
            value['cost_coverage'] not in ('complete', 'unknown_remainder')):
        raise ValueError('invalid cost references or coverage')


def _torn(data: bytes) -> bool:
    try:
        source = data.decode('utf-8')
        json.loads(source)
        return False
    except UnicodeError:
        return False
    except json.JSONDecodeError as exc:
        # Only an object truncated at EOF or inside its final string qualifies.
        return (source.startswith('{') and not source.rstrip().endswith(('}', ']')) and
                (exc.pos >= len(source.rstrip()) or
                 (exc.msg.startswith('Unterminated string') and source[exc.pos:].count('"') == 1)))


class _LiveOwner:
    def __copy__(self) -> object:
        raise TypeError('live campaign owners cannot be copied')

    def __deepcopy__(self, memo: dict) -> object:
        raise TypeError('live campaign owners cannot be copied')

    def __reduce__(self) -> object:
        raise TypeError('live campaign owners cannot be serialized')


class SeedAttempt(_LiveOwner):
    """An attempt exists durably before the caller may dispatch candidate work."""
    def __init__(self, progress: SeedProgress, attempt_id: str) -> None:
        self._progress, self.attempt_id = progress, attempt_id

    def commit(self, result: dict) -> str:
        start = self._progress._journal._starts[self.attempt_id]
        return self._progress._journal.append('seed_completed', {
            **{k: start['payload'][k] for k in ('organism_id', 'seed_id', 'seed_index', 'attempt_id')},
            'start_record_hash': start['record_hash'], 'result': result})

    @contextmanager
    def capture_costs(self) -> Iterator[None]:
        """Flush callback prices before completion; observation gaps stay unknown."""
        from evolution.core.lm_timing_callback import capture_cost_observations
        original = None
        capture = None
        try:
            with capture_cost_observations() as capture:
                yield
        except BaseException as error:
            original = error
            raise
        finally:
            try:
                for row in (() if capture is None else capture.rows.values()):
                    amount = row['amount_usd']
                    self.observe_cost({
                        'observation_id': js.identity('attempt-cost', {
                            'attempt_id': self.attempt_id, 'delivery': row['observation_id']}),
                        'owner': 'seed_attempt', 'attempt_id': self.attempt_id,
                        'status': 'unknown' if amount is None else 'measured', 'amount_usd': amount,
                        'coverage': 'partial' if amount is None else 'complete',
                        'source': row['source'], 'observation_digest': js.identity('callback-cost', row)})
                if capture is not None and capture.error is not None:
                    raise capture.error
            except BaseException as persistence_error:
                if original is not None:
                    raise original from persistence_error
                raise

    def cost_references(self) -> list[str]:
        return [key for key, row in self._progress._journal._costs.items()
                if row['payload']['attempt_id'] == self.attempt_id]

    def observe_cost(self, observation: dict) -> str:
        if observation.get('attempt_id') != self.attempt_id:
            raise ValueError('campaign_transition_invalid: cost owner mismatch')
        return self._progress._journal.append('cost_observed', observation)


class SeedProgress(_LiveOwner):
    def __init__(self, journal: CampaignJournal, organism_id: str) -> None:
        self._journal, self.organism_id = journal, organism_id

    @property
    def completed(self) -> MappingProxyType:
        return MappingProxyType({index: copy.deepcopy(row['payload']['result'])
            for (oid, index), row in self._journal._seeds.items() if oid == self.organism_id})

    @property
    def outstanding(self) -> list[dict]:
        return [copy.deepcopy(row['payload']) for aid, row in self._journal._starts.items()
                if row['kind'] == 'seed_started' and row['payload']['organism_id'] == self.organism_id
                and aid not in self._journal._terminals]

    def latest_inconclusive(self, index: int) -> str | None:
        rows = [r for r in self._journal._attempts.values()
                if r['payload']['organism_id'] == self.organism_id and
                r['payload']['seed_index'] == index]
        return rows[-1]['payload']['attempt_id'] if rows else None

    def recover_outstanding(self, *, reason: str) -> None:
        for row in self.outstanding:
            self.record_attempt(row['seed_index'], attempt_id=row['attempt_id'], reason=reason)

    def start(self, index: int, *, retry_of: str | None = None) -> SeedAttempt:
        seed = self._journal.seed(self.organism_id, index)
        attempt_id = uuid.uuid4().hex
        self._journal.append('seed_started', {
            'organism_id': self.organism_id, 'seed_id': seed['seed_id'], 'seed_index': index,
            'attempt_id': attempt_id, 'retry_of': retry_of})
        return SeedAttempt(self, attempt_id)

    def commit(self, index: int, *, attempt_id: str, result: dict) -> str:
        self._journal._check_writer()
        start = self._journal._starts.get(attempt_id)
        if (start is None or start['payload'].get('seed_index') != index or
                start['payload']['organism_id'] != self.organism_id):
            raise ValueError('campaign_transition_invalid: start required before execution')
        return SeedAttempt(self, attempt_id).commit(result)

    def record_attempt(self, index: int, *, attempt_id: str, reason: str,
                     observation_digest: str | None = None) -> str:
        seed = self._journal.seed(self.organism_id, index)
        start = self._journal._starts.get(attempt_id)
        if start is None:
            raise ValueError('campaign_transition_invalid: start required before execution')
        return self._journal.append('seed_inconclusive', {
            'organism_id': self.organism_id, 'seed_id': seed['seed_id'], 'seed_index': index,
            'attempt_id': attempt_id, 'start_record_hash': start['record_hash'],
            'status': 'inconclusive', 'reason': reason, 'observation_digest': observation_digest,
            'cost_coverage': 'unknown_remainder'})


class CampaignJournal(_LiveOwner):
    """The journal is authoritative; derived reports never restore completed work."""
    @classmethod
    def open(cls, root: Path, *, identity: dict) -> CampaignJournal:
        self = cls()
        self._root = None
        self._lock_fd = self._fd = -1
        self._uncertain = False
        self._closed = False
        self._records = []
        self._mutex = threading.RLock()
        self._starts, self._terminals, self._costs = {}, {}, {}
        self._sessions = {}
        self._current_session = None
        self._owner_pid = os.getpid()
        self._seeds, self._attempts, self._organisms, self._stages = {}, {}, {}, {}
        self._terminal = None
        self.identity = copy.deepcopy(identity)
        self.campaign_id = js.identity('campaign', identity)
        try:
            self._validate_identity(self.identity)
            root = Path(root).absolute()
            with ProtectedRoot.open(root.parent) as parent:
                try:
                    os.mkdir(root.name, mode=0o700, dir_fd=parent.fd)
                except FileExistsError:
                    pass
            self._root = ProtectedRoot.open(root)
            info = os.fstat(self._root.fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('campaign_storage_untrusted: output directory permissions')
            self._lock_fd = self._private_file('campaign_progress.lock')
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('campaign_writer_busy') from exc
            self._fd = self._private_file('campaign_progress.jsonl')
            self._load()
            if not self._records:
                self.append('campaign_initialized', identity)
            elif not js.equivalent(self._records[0]['payload'], identity):
                raise ValueError('campaign_state_incompatible')
            self._barrier()
            os.fsync(self._root.fd)
            return self
        except BaseException:
            self.close()
            raise

    def _validate_identity(self, value: dict) -> None:
        try:
            fields(value, {'identity_manifest', 'configuration', 'organisms', 'stages'})
            if type(value['configuration']) is not dict or value['configuration'].get('durability') not in ('seed', 'organism'):
                raise ValueError('invalid durability')
            if value['identity_manifest'].get('journal_version') != '2':
                raise ValueError('unsupported journal identity version')
            _integer(value['configuration'].get('max_organisms', len(value['organisms'])))
            budget = value['configuration'].get('budget_policy')
            if budget is not None:
                fields(budget, {'currency', 'scope', 'initial_ceiling_usd', 'change_rule'})
                ceiling = budget['initial_ceiling_usd']
                if (budget['currency'] != 'USD' or budget['scope'] != 'campaign_total' or
                        budget['change_rule'] != 'increase_only' or
                        (ceiling is not None and (type(ceiling) is not Decimal or
                         not ceiling.is_finite() or ceiling < 0))):
                    raise ValueError('invalid budget policy')
            if type(value['organisms']) is not list or type(value['stages']) is not list:
                raise ValueError('invalid population')
            if value['stages'] != sorted(set(value['stages'])) or any(_integer(x) < 1 for x in value['stages']):
                raise ValueError('invalid stages')
            self._members = {}
            for org in value['organisms']:
                fields(org, {'organism_id', 'candidate_identity', 'seeds'})
                oid = digest(org['organism_id'])
                if oid != js.identity('organism', org['candidate_identity']) or oid in self._members:
                    raise ValueError('invalid organism identity')
                if type(org['seeds']) is not list or not org['seeds']:
                    raise ValueError('missing seeds')
                for index, seed in enumerate(org['seeds']):
                    fields(seed, {'seed_id', 'seed_index', 'seed_value'})
                    if _integer(seed['seed_index']) != index or type(seed['seed_value']) is not int:
                        raise ValueError('invalid seed schedule')
                    expected = js.identity('seed', {'organism_id': oid, 'seed_index': index,
                        'seed_value': seed['seed_value'], 'configuration': value['configuration']})
                    if digest(seed['seed_id']) != expected:
                        raise ValueError('invalid seed identity')
                self._members[oid] = org
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('campaign_state_incompatible: ' + str(exc)) from exc

    def _private_file(self, name: str) -> int:
        try:
            fd = self._root.open_regular(name, flags=os.O_RDWR | os.O_CREAT)
            info = os.fstat(fd)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                os.close(fd)
                raise ValueError('unsafe ownership, mode or links')
            return fd
        except ValueError as exc:
            raise ValueError('campaign_storage_untrusted: ' + str(exc)) from exc

    def _barrier(self) -> None:
        try:
            os.fsync(self._fd)
        except OSError as exc:
            self._uncertain = True
            raise ValueError('campaign_persistence_uncertain') from exc

    @classmethod
    def inspect(cls, root: Path) -> list[dict]:
        """Validate a pinned journal without locks, writes, initialization or repair."""
        self = cls()
        self._root = None
        self._lock_fd = self._fd = -1
        self._closed = False
        self._records = []
        self._starts, self._terminals, self._costs = {}, {}, {}
        self._sessions = {}
        self._seeds, self._attempts, self._organisms, self._stages = {}, {}, {}, {}
        self._terminal = None
        try:
            self._root = ProtectedRoot.open(Path(root).absolute())
            self._fd = self._root.open_regular('campaign_progress.jsonl')
            metadata = os.fstat(self._fd)
            if (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600 or
                    metadata.st_nlink != 1):
                raise ValueError('campaign_storage_untrusted')
            with os.fdopen(os.dup(self._fd), 'rb') as stream:
                initial = js.loads(stream.readline(MAX_RECORD + 1))
            self.identity = initial['payload']
            self.campaign_id = js.identity('campaign', self.identity)
            self._validate_identity(self.identity)
            self._load(repair=False)
            if metadata_identity(os.fstat(self._fd)) != metadata_identity(metadata):
                raise ValueError('campaign_state_corrupt: journal changed during inspection')
            return self.records
        except (KeyError, TypeError) as exc:
            raise ValueError('campaign_state_corrupt: invalid initialization') from exc
        finally:
            self.close()

    def _load(self, *, repair: bool = True) -> None:
        offset = 0
        # Duplicate shares offset but not ownership; reads stay bounded by record.
        with os.fdopen(os.dup(self._fd), 'rb') as stream:
            stream.seek(0)
            while True:
                line = stream.readline(MAX_RECORD + 1)
                if not line:
                    break
                if len(line) > MAX_RECORD:
                    raise ValueError('campaign_state_corrupt: oversized record')
                try:
                    row = js.loads(line)
                except ValueError as exc:
                    if not line.endswith(b'\n') and _torn(line) and repair:
                        name = 'campaign_progress.torn.' + hashlib.sha256(line).hexdigest() + '.bin'
                        tail = self._private_file(name)
                        try:
                            existing = os.read(tail, MAX_RECORD + 1)
                            if existing and existing != line:
                                raise ValueError('campaign_state_corrupt: conflicting recovery tail')
                            if not existing:
                                self._write(tail, line)
                            os.fsync(tail)
                            os.fsync(self._root.fd)
                        finally:
                            os.close(tail)
                        os.ftruncate(self._fd, offset)
                        self._barrier()
                        break
                    raise ValueError('campaign_state_corrupt: malformed record') from exc
                try:
                    fields(row, ENVELOPE)
                    material = {key: val for key, val in row.items() if key != 'record_hash'}
                    if (row['schema_version'] != '2' or type(row['sequence']) is not int or
                            row['sequence'] != len(self._records) or
                            row['previous_hash'] != (self._records[-1]['record_hash'] if self._records else '0' * 64) or
                            row['record_hash'] != js.identity('journal-record', material)):
                        raise ValueError('invalid envelope or chain')
                    if row['campaign_id'] != self.campaign_id:
                        if not self._records:
                            raise ValueError('campaign_state_incompatible')
                        raise ValueError('foreign campaign')
                    self._transition(row['kind'], row['payload'])
                    self._accept(row)
                except (ValueError, TypeError, KeyError) as exc:
                    if 'campaign_state_incompatible' in str(exc):
                        raise ValueError('campaign_state_incompatible') from exc
                    raise ValueError('campaign_state_corrupt: ' + str(exc)) from exc
                offset += len(line)
                if not line.endswith(b'\n') and repair:
                    os.lseek(self._fd, 0, os.SEEK_END)
                    self._write(self._fd, b'\n')
                    self._barrier()

    def start_session(self, *, session_id: str, ceiling_usd: Decimal | None = None) -> str:
        """Synchronize the effective campaign ceiling before dependent work."""
        with self._mutex:
            existing = self._sessions.get(session_id)
            if existing is not None:
                if session_id != self._current_session:
                    raise ValueError('campaign_transition_invalid: session belongs to a prior writer')
                if ceiling_usd is None or ceiling_usd == existing['payload']['ceiling_usd']:
                    return self.append('session_started', existing['payload'])
                raise ValueError('campaign_transition_invalid: conflicting session retry')
            prior = next(reversed(self._sessions.values()), None) if self._sessions else None
            initial = self.identity['configuration'].get('budget_policy', {}).get('initial_ceiling_usd')
            previous = prior['payload']['ceiling_usd'] if prior else initial
            effective = previous if ceiling_usd is None else ceiling_usd
            result = self.append('session_started', {
                'session_id': session_id, 'previous_session_record_hash': prior['record_hash'] if prior else None,
                'previous_ceiling_usd': previous, 'ceiling_usd': effective,
                'reason': 'initial' if prior is None else 'resume' if effective == previous else 'ceiling_increase'})
            self._current_session = session_id
            return result

    def seed(self, oid: str, index: int) -> dict:
        try:
            _integer(index)
            return copy.deepcopy(self._members[oid]['seeds'][index])
        except (ValueError, KeyError, IndexError) as exc:
            raise ValueError('campaign_transition_invalid: unknown seed') from exc

    def seed_progress(self, organism_id: str) -> SeedProgress:
        if organism_id not in self._members:
            raise ValueError('campaign_transition_invalid: unknown organism')
        return SeedProgress(self, organism_id)

    @property
    def records(self) -> list[dict]:
        return copy.deepcopy(self._records)

    def _existing(self, kind: str, payload: dict) -> dict | None:
        if kind == 'session_started':
            return self._sessions.get(payload.get('session_id'))
        if kind == 'seed_completed':
            return self._seeds.get((payload.get('organism_id'), payload.get('seed_index')))
        if kind in ('seed_started', 'organism_started'):
            return self._starts.get(payload.get('attempt_id'))
        if kind in ('seed_inconclusive', 'organism_inconclusive'):
            return self._terminals.get(payload.get('attempt_id'))
        if kind == 'cost_observed':
            return self._costs.get(payload.get('observation_id'))
        if kind in ('organism_completed', 'organism_skipped'):
            return self._organisms.get(payload.get('organism_id'))
        if kind == 'stage_decided':
            return self._stages.get(payload.get('stage_index'))
        if kind == 'campaign_completed':
            return self._terminal
        return None

    def _transition(self, kind: str, payload: dict) -> None:
        if not self._records:
            if kind != 'campaign_initialized' or not js.equivalent(payload, self.identity):
                raise ValueError('initialization required')
            return
        if self._terminal:
            raise ValueError('campaign already completed')
        if self._existing(kind, payload) is not None:
            raise ValueError('duplicate terminal record')
        if kind != 'campaign_completed' and any(r['payload']['decision'] == 'stop' for r in self._stages.values()):
            raise ValueError('event after futility stop')
        measured_count = sum(r['kind'] == 'organism_completed' for r in self._organisms.values())
        pending = [i for i, boundary in enumerate(self.identity['stages'])
                   if boundary <= measured_count and i not in self._stages]
        if pending and kind != 'stage_decided':
            raise ValueError('stage decision required before dependent work')
        if kind == 'session_started':
            fields(payload, {'session_id', 'previous_session_record_hash', 'previous_ceiling_usd',
                             'ceiling_usd', 'reason'})
            text(payload['session_id'])
            prior = next(reversed(self._sessions.values()), None) if self._sessions else None
            initial = self.identity['configuration'].get('budget_policy', {}).get('initial_ceiling_usd')
            previous = prior['payload']['ceiling_usd'] if prior else initial
            ceiling = payload['ceiling_usd']
            if ceiling is not None and (type(ceiling) is not Decimal or not ceiling.is_finite() or ceiling < 0):
                raise ValueError('invalid session ceiling')
            if prior is not None and previous is None and ceiling is not None:
                raise ValueError('unlimited session ceiling must remain unlimited')
            if previous is not None and (ceiling is None or ceiling < previous):
                raise ValueError('session ceiling may only increase')
            expected_reason = ('initial' if prior is None else
                               'resume' if ceiling == previous else 'ceiling_increase')
            if prior is None and ceiling != initial:
                raise ValueError('initial session must retain initial ceiling')
            if (payload['previous_session_record_hash'] != (prior['record_hash'] if prior else None) or
                    payload['previous_ceiling_usd'] != previous or payload['reason'] != expected_reason):
                raise ValueError('invalid session linkage')
        elif kind in ('seed_started', 'organism_started'):
            budget = self.identity['configuration'].get('budget_policy')
            if budget is not None:
                if not self._sessions:
                    raise ValueError('durable session required before execution')
                ceiling = next(reversed(self._sessions.values()))['payload']['ceiling_usd']
                if ceiling is not None:
                    unknown = (bool(self._attempts) or
                        any('attempt_id' in r['payload'] for r in self._organisms.values()) or
                        any(r['kind'] == 'organism_inconclusive' for r in self._terminals.values()) or
                        any(r['payload']['result']['cost_coverage'] != 'complete' for r in self._seeds.values()) or
                        any(r['payload']['status'] != 'measured' or r['payload']['coverage'] != 'complete'
                            for r in self._costs.values()))
                    spent = sum((r['payload']['amount_usd'] for r in self._costs.values()
                                 if r['payload']['status'] == 'measured'), Decimal('0'))
                    if unknown or spent >= ceiling:
                        raise ValueError('campaign budget capacity cannot be established')
            legacy = kind == 'organism_started'
            fields(payload, {'organism_id', 'attempt_id', 'retry_of'} |
                   (set() if legacy else {'seed_id', 'seed_index'}))
            oid = payload['organism_id']
            if oid not in self._members or oid in self._organisms:
                raise ValueError('unknown or terminal organism')
            if self.identity['configuration']['durability'] != ('organism' if legacy else 'seed'):
                raise ValueError('attempt durability mismatch')
            text(payload['attempt_id'])
            if payload['attempt_id'] in self._starts:
                raise ValueError('attempt already started')
            limit = self.identity['configuration'].get('max_organisms', len(self._members))
            if measured_count >= limit:
                raise ValueError('configured organism limit reached')
            if any(aid not in self._terminals for aid in self._starts):
                raise ValueError('outstanding execution must be resolved first')
            expected_oid = next((x for x in self._members if x not in self._organisms), None)
            if oid != expected_oid:
                raise ValueError('ordered population violation')
            prior = [r for r in self._starts.values() if r['kind'] == kind and
                     r['payload']['organism_id'] == oid and
                     (legacy or r['payload']['seed_index'] == payload['seed_index'])]
            retry = payload['retry_of']
            if (prior and retry != prior[-1]['payload']['attempt_id']) or (not prior and retry is not None):
                raise ValueError('retry must reference latest inconclusive attempt')
            if not legacy:
                seed = self.seed(oid, payload['seed_index'])
                if (seed['seed_id'] != payload['seed_id'] or
                        payload['seed_index'] != len([k for k in self._seeds if k[0] == oid])):
                    raise ValueError('seed schedule violation')
        elif kind == 'cost_observed':
            fields(payload, {'observation_id', 'owner', 'attempt_id', 'status', 'amount_usd',
                             'coverage', 'source', 'observation_digest'})
            text(payload['observation_id'])
            text(payload['source'])
            digest(payload['observation_digest'])
            start = self._starts[payload['attempt_id']]
            if payload['attempt_id'] in self._terminals or payload['owner'] != (
                    'seed_attempt' if start['kind'] == 'seed_started' else 'organism_attempt'):
                raise ValueError('invalid cost owner')
            amount = payload['amount_usd']
            if (payload['status'] not in ('measured', 'unknown') or
                    payload['coverage'] not in ('complete', 'partial') or
                    (payload['status'] == 'unknown' and amount is not None) or
                    (payload['status'] == 'measured' and
                     (type(amount) is not Decimal or not amount.is_finite() or amount < 0))):
                raise ValueError('invalid cost measurement')
        elif kind in ('seed_completed', 'seed_inconclusive'):

            names = {'organism_id', 'seed_id', 'seed_index', 'attempt_id'}
            fields(payload, names | ({'result', 'start_record_hash'} if kind == 'seed_completed' else
                   {'status', 'reason', 'observation_digest', 'start_record_hash', 'cost_coverage'}))
            oid, index = payload['organism_id'], payload['seed_index']
            seed = self.seed(oid, index)
            if seed['seed_id'] != payload['seed_id'] or oid in self._organisms:
                raise ValueError('seed identity or terminal organism mismatch')
            start = self._starts.get(payload['attempt_id'])
            if (start is None or start['kind'] != 'seed_started' or
                    payload['attempt_id'] in self._terminals or
                    payload['start_record_hash'] != start['record_hash'] or
                    any(payload[k] != start['payload'][k] for k in names)):
                raise ValueError('terminal requires matching live durable start')
            if kind == 'seed_completed':
                _result(payload['result'])
                result = payload['result']
                expected = [oid for oid, row in self._costs.items()
                            if row['payload']['attempt_id'] == payload['attempt_id']]
                if result['cost_observation_ids'] != expected:
                    raise ValueError('cost observation references differ')
                if result['cost_coverage'] == 'complete' and (not expected or any(
                        self._costs[x]['payload']['status'] != 'measured' or
                        self._costs[x]['payload']['coverage'] != 'complete' for x in expected)):
                    raise ValueError('complete costs lack measured evidence')
            else:
                if (payload['status'] != 'inconclusive' or (oid, index) in self._seeds or
                        payload['cost_coverage'] != 'unknown_remainder'):
                    raise ValueError('invalid inconclusive attempt')
                text(payload['reason'])
                if payload['observation_digest'] is not None:
                    digest(payload['observation_digest'])
        elif kind == 'organism_completed':
            legacy = self.identity['configuration']['durability'] == 'organism'
            fields(payload, {'organism_id', 'seeds', 'deploy_reachable'} |
                   ({'attempt_id', 'start_record_hash'} if legacy else {'seed_record_hashes'}))
            oid = payload['organism_id']
            population = self._members[oid]['seeds']
            if legacy:
                start = self._starts.get(payload['attempt_id'])
                if (start is None or start['kind'] != 'organism_started' or
                        start['payload']['organism_id'] != oid or
                        payload['attempt_id'] in self._terminals or
                        payload['start_record_hash'] != start['record_hash']):
                    raise ValueError('organism completion requires durable start')
                seeds = payload['seeds']
            else:
                rows = [self._seeds[(oid, i)] for i in range(len(population))]
                seeds = [r['payload']['result']['diagnostic_status'] == 'passed' for r in rows]
                if payload['seed_record_hashes'] != [r['record_hash'] for r in rows]:
                    raise ValueError('invalid seed references')
            if (len(seeds) != len(population) or any(type(x) is not bool for x in seeds) or
                    not js.equivalent(payload['seeds'], seeds) or type(payload['deploy_reachable']) is not bool or
                    payload['deploy_reachable'] != (sum(seeds) > 0 and 2 * sum(seeds) >= len(seeds))):
                raise ValueError('incomplete or inconsistent organism aggregate')
        elif kind == 'organism_inconclusive':
            fields(payload, {'organism_id', 'attempt_id', 'start_record_hash', 'reason'})
            start = self._starts[payload['attempt_id']]
            if (start['kind'] != 'organism_started' or payload['attempt_id'] in self._terminals or
                    start['record_hash'] != payload['start_record_hash'] or
                    start['payload']['organism_id'] != payload['organism_id']):
                raise ValueError('invalid organism interruption')
            text(payload['reason'])
        elif kind == 'organism_skipped':
            fields(payload, {'organism_id', 'reason'})
            oid = payload['organism_id']
            if oid not in self._members or type(payload['reason']) is not str or not payload['reason']:
                raise ValueError('invalid organism skip')
            if any(k[0] == oid for k in self._seeds) or any(
                    r['payload']['organism_id'] == oid
                    for r in self._starts.values()):
                raise ValueError('cannot discard attempted organism')
        elif kind == 'stage_decided':
            fields(payload, {'stage_index', 'organism_record_hashes', 'aggregate', 'decision'})
            index = _integer(payload['stage_index'])
            if index != len(self._stages) or index >= len(self.identity['stages']):
                raise ValueError('invalid stage order')
            if any(r['payload']['decision'] == 'stop' for r in self._stages.values()):
                raise ValueError('stage follows futility stop')
            expected = self.stage_payload(index)
            if not js.equivalent(payload, expected):
                raise ValueError('invalid stage aggregate or decision')
        elif kind == 'campaign_completed':
            fields(payload, {'stage_record_hashes', 'organism_record_hashes', 'stop_reason', 'unexecuted_organism_ids'})
            if payload['stage_record_hashes'] != [r['record_hash'] for r in self._stages.values()] or payload['organism_record_hashes'] != [r['record_hash'] for r in self._organisms.values()]:
                raise ValueError('invalid completion references')
            stop = any(r['payload']['decision'] == 'stop' for r in self._stages.values())
            limit = measured_count >= self.identity['configuration'].get('max_organisms', len(self._members))
            expected_reason = ('futility_stop' if stop else 'population_complete'
                               if len(self._organisms) == len(self._members) else 'configured_limit_reached')
            if (payload['stop_reason'] != expected_reason or
                    (not stop and not limit and len(self._organisms) != len(self._members)) or
                    any(aid not in self._terminals for aid in self._starts) or
                    payload['unexecuted_organism_ids'] != [x for x in self._members if x not in self._organisms]):
                raise ValueError('invalid completion or outstanding population')

        else:
            raise ValueError('unknown journal transition')

    def stage_payload(self, index: int) -> dict:
        from evolution.code.campaign_report import wilson
        boundary = self.identity['stages'][index]
        rows = list(self._organisms.values())
        measured = [r for r in rows if r['kind'] == 'organism_completed']
        if len(measured) != boundary:
            raise ValueError('stage boundary not measured')
        if any(oid not in self._organisms for oid, index in self._seeds) or any(
                r['payload']['organism_id'] not in self._organisms for r in self._attempts.values()):
            raise ValueError('outstanding measurements prevent stage decision')
        k = sum(r['payload']['deploy_reachable'] for r in measured)
        lower, upper = wilson(k, len(measured))
        requested_seeds = sum(len(self._members[r['payload']['organism_id']]['seeds']) for r in rows)
        measured_seeds = sum(len(r['payload']['seeds']) for r in measured)
        return {'stage_index': index, 'organism_record_hashes': [r['record_hash'] for r in rows],
            'aggregate': {'requested_organisms': len(rows), 'measured_organisms': len(measured),
                'skipped_organisms': len(rows) - len(measured), 'requested_seeds': requested_seeds,
                'measured_seeds': measured_seeds, 'outstanding_seeds': 0, 'inconclusive_seeds': 0,
                'correct_organisms': k, 'wilson_lower': Decimal(str(lower)),
                'wilson_upper': Decimal(str(upper)), 'kill_line': Decimal('0.1')},
            'decision': 'stop' if lower < .1 else 'continue'}

    def _accept(self, row: dict) -> None:
        self._records.append(row)
        kind, p = row['kind'], row['payload']
        if kind == 'session_started':
            self._sessions[p['session_id']] = row
        if kind == 'seed_completed':
            self._seeds[(p['organism_id'], p['seed_index'])] = row
        elif kind == 'seed_inconclusive':
            self._attempts[p['attempt_id']] = row
        if kind in ('seed_started', 'organism_started'):
            self._starts[p['attempt_id']] = row
        if kind in ('seed_completed', 'seed_inconclusive', 'organism_inconclusive') or (
                kind == 'organism_completed' and 'attempt_id' in p):
            self._terminals[p['attempt_id']] = row
        if kind == 'cost_observed':
            self._costs[p['observation_id']] = row
        if kind in ('organism_completed', 'organism_skipped'):
            self._organisms[p['organism_id']] = row
        elif kind == 'stage_decided':
            self._stages[p['stage_index']] = row
        elif kind == 'campaign_completed':
            self._terminal = row

    @staticmethod
    def _write(fd: int, data: bytes) -> None:
        written = os.write(fd, data)
        if written != len(data):
            raise OSError('short journal write')

    def _check_writer(self) -> None:
        if self._owner_pid != os.getpid():
            raise ValueError('campaign_writer_busy: inherited journal')
        if self._uncertain:
            raise ValueError('campaign_persistence_uncertain')
        if self._closed:
            raise ValueError('campaign journal is closed')

    def append(self, kind: str, payload: dict) -> str:
        self._check_writer()
        with self._mutex:
            return self._append(kind, payload)

    def _append(self, kind: str, payload: dict) -> str:
        if self._owner_pid != os.getpid():
            raise ValueError('campaign_writer_busy: inherited journal')
        if self._uncertain:
            raise ValueError('campaign_persistence_uncertain')
        if self._closed:
            raise ValueError('campaign journal is closed')
        try:
            if (kind in ('seed_started', 'organism_started') and
                    self.identity['configuration'].get('budget_policy') is not None and
                    self._current_session is None):
                raise ValueError('current writer must establish a durable session before execution')
            payload = copy.deepcopy(payload)
            js.canonical_bytes(payload)
            previous = self._existing(kind, payload)
            if previous:
                if previous['kind'] == kind and js.equivalent(previous['payload'], payload):
                    return previous['record_hash']
                raise ValueError('conflicting repeated commit')
            self._transition(kind, payload)
            row = {'schema_version': '2', 'sequence': len(self._records), 'campaign_id': self.campaign_id,
                   'kind': kind, 'previous_hash': self._records[-1]['record_hash'] if self._records else '0' * 64,
                   'payload': payload}
            row['record_hash'] = js.identity('journal-record', row)
            encoded = js.dumps(row) + b'\n'
            if len(encoded) > MAX_RECORD:
                raise ValueError('record exceeds storage bound')
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('campaign_transition_invalid: ' + str(exc)) from exc
        try:
            os.lseek(self._fd, 0, os.SEEK_END)
            self._write(self._fd, encoded)
            self._barrier()
        except OSError as exc:
            self._uncertain = True
            raise ValueError('campaign_persistence_uncertain') from exc
        except BaseException:
            self._uncertain = True
            raise
        self._accept(row)
        return row['record_hash']

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        if self._lock_fd >= 0:
            os.close(self._lock_fd)
            self._lock_fd = -1
        if self._root is not None:
            self._root.close()
        self._closed = True

    def __enter__(self) -> CampaignJournal:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
