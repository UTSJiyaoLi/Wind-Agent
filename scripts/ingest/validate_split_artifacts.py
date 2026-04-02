import argparse
import json
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Validate split artifacts: source jsonl vs light jsonl vs full metadata index.')
    p.add_argument('--source-jsonl', required=True)
    p.add_argument('--light-jsonl', required=True)
    p.add_argument('--full-metadata-jsonl', required=True)
    p.add_argument('--full-metadata-idx', required=True)
    p.add_argument('--sample-size', type=int, default=20)
    return p.parse_args()


def count_lines(path: Path) -> int:
    c = 0
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                c += 1
    return c


def load_ids_from_light(path: Path) -> list[str]:
    ids = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            row_id = str(row.get('id', '')).strip()
            if not row_id:
                md = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
                row_id = str(md.get('id', '')).strip()
            if row_id:
                ids.append(row_id)
    return ids


def main() -> None:
    args = parse_args()
    source = Path(args.source_jsonl)
    light = Path(args.light_jsonl)
    full_jsonl = Path(args.full_metadata_jsonl)
    idx_path = Path(args.full_metadata_idx)

    source_lines = count_lines(source)
    light_lines = count_lines(light)
    full_lines = count_lines(full_jsonl)

    with idx_path.open('r', encoding='utf-8') as f:
        idx = json.load(f)
    if not isinstance(idx, dict):
        raise ValueError('Index file must be a JSON object mapping id -> offset')

    ids = load_ids_from_light(light)
    unique_ids = set(ids)

    missing_in_idx = [x for x in unique_ids if x not in idx]

    sampled = random.sample(list(unique_ids), k=min(args.sample_size, len(unique_ids))) if unique_ids else []
    sample_seek_ok = 0
    with full_jsonl.open('rb') as fp:
        for row_id in sampled:
            offset = int(idx[row_id])
            fp.seek(offset)
            line = fp.readline()
            if not line:
                continue
            obj = json.loads(line.decode('utf-8'))
            if str(obj.get('id', '')) == row_id:
                sample_seek_ok += 1

    payload = {
        'source_lines': source_lines,
        'light_lines': light_lines,
        'full_metadata_lines': full_lines,
        'index_ids': len(idx),
        'light_unique_ids': len(unique_ids),
        'duplicate_id_count_in_light': len(ids) - len(unique_ids),
        'missing_ids_in_index': len(missing_in_idx),
        'sample_seek_checked': len(sampled),
        'sample_seek_ok': sample_seek_ok,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
