import argparse
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import simulation


def main():
    parser = argparse.ArgumentParser(description='Page policies and Windows resource measurements')
    parser.add_argument('--check', action='store_true', help='run simulator correctness checks only')
    parser.add_argument('--simulation-only', action='store_true')
    args = parser.parse_args()
    simulation.check()
    if args.check:
        return
    output = Path(__file__).resolve().parent / 'results'
    if args.simulation_only:
        output = output / 'simulation_only'
    output.mkdir(parents=True, exist_ok=True)
    metadata = dict(created_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                    libraries={p: importlib.metadata.version(p) for p in ['scikit-learn', 'psutil', 'reportlab', 'Pillow']})
    metadata['simulation'] = simulation.run(output)
    if not args.simulation_only:
        import windows_experiment
        metadata['windows'] = windows_experiment.run(output)
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    import make_reports
    make_reports.build(output, include_windows=not args.simulation_only)
    print(f'Results and reports saved to {output}')


if __name__ == '__main__':
    main()
