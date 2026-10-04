"""Original, small trace simulator; no kernel policies are changed."""
import csv
import random
from collections import Counter, deque
from pathlib import Path


def trace(seed, length=2400, pages=24):
    rng = random.Random(seed)
    accesses = []
    for i in range(length):
        if i < length // 2:
            # A repeating four-page loop with occasional out-of-loop references.
            page = i % 4 if rng.random() < 0.92 else rng.randrange(pages)
        else:
            # Independent random references mixed with short, moving bursts.
            hot = 4 + (i // 40) % (pages - 6)
            page = rng.randrange(pages) if rng.random() < 0.65 else hot + rng.randrange(3)
        accesses.append(page)
    return accesses


def features(page, i, last, recent):
    return [i - last[page], recent.count(page)]


def simulate(accesses, frames, policy, model=None, training=False):
    if frames < 1 or not accesses or policy not in ('FIFO', 'LRU', 'Optimal', 'Learned'):
        raise ValueError('Positive frames, nonempty trace and a known policy required')
    if policy == 'Learned' and model is None:
        raise ValueError('Learned policy requires a fitted model')
    resident, last, recent = {}, {}, deque(maxlen=32)
    future = {}
    if policy == 'Optimal' or training:
        for i, page in enumerate(accesses):
            future.setdefault(page, deque()).append(i)
    faults, X, y = [], [], []
    for i, page in enumerate(accesses):
        if future:
            future[page].popleft()
        miss = page not in resident
        faults.append(int(miss))
        if miss:
            if len(resident) == frames:
                candidates = list(resident)
                if training:
                    # Labels mean "not reused in the next 12 references".
                    # Future is consulted ONLY on independent training traces.
                    for p in candidates:
                        X.append(features(p, i, last, recent))
                        y.append(int(not future[p] or future[p][0] > i + 12))
                if policy == 'FIFO':
                    victim = min(resident, key=resident.get)
                elif policy == 'LRU':
                    victim = min(resident, key=last.get)
                elif policy == 'Optimal':
                    victim = max(resident, key=lambda p: future[p][0] if future[p] else float('inf'))
                else:
                    scores = model.predict_proba([features(p, i, last, recent) for p in candidates])
                    column = list(model.classes_).index(1)
                    victim = max(zip(candidates, scores), key=lambda pair: (pair[1][column], i - last[pair[0]], -pair[0]))[0]
                del resident[victim]
            resident[page] = i
        last[page] = i
        recent.append(page)
    return faults, X, y


def run(output):
    from sklearn.tree import DecisionTreeClassifier, export_text
    X, y = [], []
    for seed in (101, 102, 103, 104):
        _, inputs, targets = simulate(trace(seed), 6, 'LRU', training=True)
        X.extend(inputs)
        y.extend(targets)
    model = DecisionTreeClassifier(max_depth=4, min_samples_leaf=40, random_state=11)
    model.fit(X, y)
    (output / 'tree.txt').write_text(export_text(model, feature_names=['recency', 'recent_count']), encoding='utf-8')
    rows, windows = [], []
    for seed in (11, 22, 33, 44, 55):
        accesses = trace(seed)
        for frames in (4, 6, 8):
            for policy in ('FIFO', 'LRU', 'Optimal', 'Learned'):
                faults, _, _ = simulate(accesses, frames, policy, model)
                for phase, values in [('before', faults[:1200]), ('after', faults[1200:]), ('overall', faults)]:
                    rows.append(dict(seed=seed, frames=frames, policy=policy, phase=phase, references=len(values), faults=sum(values), hit_ratio=1 - sum(values) / len(values)))
                if seed == 11 and frames == 6:
                    for start in range(0, len(faults), 100):
                        windows.append(dict(policy=policy, start=start, fault_ratio=sum(faults[start:start+100]) / 100))
        if seed == 11:
            write_csv(output / 'evaluation_trace.csv', [dict(index=i, page=p, phase='before' if i < 1200 else 'after') for i, p in enumerate(accesses)])
    write_csv(output / 'simulation.csv', rows)
    write_csv(output / 'windows.csv', windows)
    return dict(training_seeds=[101, 102, 103, 104], evaluation_seeds=[11, 22, 33, 44, 55], training_samples=len(y), training_labels=dict(Counter(y)), horizon=12, window=32, frames=[4, 6, 8], references=2400, shift=1200)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check():
    from functools import lru_cache
    from itertools import product
    reference = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2]
    assert [sum(simulate(reference, 3, p)[0]) for p in ('FIFO', 'LRU', 'Optimal')] == [10, 9, 7]
    anomaly = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    assert [sum(simulate(anomaly, n, 'FIFO')[0]) for n in (3, 4)] == [9, 10]
    # Independent exhaustive search verifies Optimal, rather than repeating its rule.
    for refs in product(range(3), repeat=6):
        @lru_cache(None)
        def best(i, memory):
            if i == len(refs):
                return 0
            p, occupied = refs[i], set(memory)
            if p in occupied:
                return best(i + 1, memory)
            if len(occupied) < 2:
                return 1 + best(i + 1, tuple(sorted(occupied | {p})))
            return 1 + min(best(i + 1, tuple(sorted((occupied - {v}) | {p}))) for v in occupied)
        assert sum(simulate(refs, 2, 'Optimal')[0]) == best(0, ())
        for policy in ('FIFO', 'LRU'):
            assert sum(simulate(refs, 2, policy)[0]) >= best(0, ())
    assert trace(11) == trace(11) and trace(11) != trace(22)
    print('Correctness checks passed: textbook counts, FIFO anomaly, 729 exhaustive traces.')


if __name__ == '__main__':
    check()
