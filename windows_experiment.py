"""Bounded experiments on our own child processes only; Windows required."""
import argparse
import ctypes
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import psutil


def worker(kind, limit, cores):
    process = psutil.Process()
    process.cpu_affinity(cores)
    if kind == 'memory':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetProcessWorkingSetSizeEx.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_ulong]
        kernel.SetProcessWorkingSetSizeEx.restype = ctypes.c_int
        if not kernel.SetProcessWorkingSetSizeEx(kernel.GetCurrentProcess(), 1 << 20, limit << 20, 0x06):
            raise ctypes.WinError(ctypes.get_last_error())
        # Allocation is identical across limits; only the residency cap changes.
        data = bytearray(48 << 20)
        offsets = list(range(0, len(data), 4096))
        random.Random(17).shuffle(offsets)
    else:
        data = b'x' * (64 << 10)
    baseline = process.memory_info().num_page_faults
    start, cpu = time.perf_counter(), time.process_time()
    checksum = 0
    peak = 0
    for _ in range(8):
        if kind == 'memory':
            for offset in offsets:
                data[offset] = (data[offset] + 1) % 256
                checksum += data[offset]
        else:
            for _ in range(1500):
                checksum ^= hashlib.sha256(data).digest()[0]
        peak = max(peak, process.memory_info().rss)
    info = process.memory_info()
    print(json.dumps(dict(seconds=time.perf_counter() - start, cpu_seconds=time.process_time() - cpu,
                         fault_delta=info.num_page_faults - baseline, sampled_rss_mib=peak / (1 << 20), checksum=checksum)))


def run(output):
    if os.name != 'nt':
        raise RuntimeError('This experiment requires Windows; simulation runs on other platforms.')
    from simulation import write_csv
    allowed = psutil.Process().cpu_affinity()
    if len(allowed) < 2:
        raise RuntimeError('Two allowed logical CPUs are required for the CPU comparison')
    rows = []
    for repeat in range(3):
        conditions = [('memory', 24, 1), ('memory', 96, 1), ('cpu', 0, 1), ('cpu', 0, 2)]
        random.Random(700 + repeat).shuffle(conditions)
        for kind, limit, cpu_count in conditions:
            # CPU experiment: always two workers with fixed total work, varying allowed CPUs.
            count = 2 if kind == 'cpu' else 1
            start = time.perf_counter()
            children = [subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', kind,
                        '--limit', str(limit), '--cores', ','.join(map(str, allowed[:cpu_count]))],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(count)]
            records = []
            try:
                for child in children:
                    stdout, stderr = child.communicate(timeout=90)
                    if child.returncode:
                        raise RuntimeError(stderr)
                    records.append(json.loads(stdout))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
            row = dict(kind=kind, repeat=repeat+1, working_set_limit_mib=limit, allowed_cpus=cpu_count,
                       workers=count, wall_seconds=time.perf_counter()-start,
                       work_seconds=max(r['seconds'] for r in records),
                       cpu_seconds=sum(r['cpu_seconds'] for r in records),
                       windows_fault_delta=sum(r['fault_delta'] for r in records),
                       sampled_rss_mib=max(r['sampled_rss_mib'] for r in records),
                       checksum=sum(r['checksum'] for r in records))
            rows.append(row)
            print(f"{kind}: cap={limit} MiB, CPUs={cpu_count}, {row['wall_seconds']:.3f}s, faults={row['windows_fault_delta']}")
    write_csv(output / 'windows_resources.csv', rows)
    return dict(platform=sys.platform, cpu_model=os.environ.get('PROCESSOR_IDENTIFIER', 'unknown'),
                logical_cpus=psutil.cpu_count(), allowed_cpus=allowed, total_ram_mib=psutil.virtual_memory().total/(1 << 20),
                repeats=3, memory_allocation_mib=48, memory_passes=8, page_stride=4096,
                cpu_work='two workers; each performs 12000 SHA-256 operations on 64 KiB',
                measurement='child fault delta excludes allocation; wall time includes child startup; RSS sampled after each pass')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', choices=['memory', 'cpu'], required=True)
    parser.add_argument('--limit', type=int, default=96)
    parser.add_argument('--cores', required=True)
    args = parser.parse_args()
    if args.limit < 1 and args.worker == 'memory':
        parser.error('memory limit must be positive')
    worker(args.worker, args.limit, [int(c) for c in args.cores.split(',')])
