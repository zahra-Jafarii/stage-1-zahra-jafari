"""Compare output hashes of two manifest files."""
import json
import sys


def load_hashes(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["output_hashes"]


def main(first_path: str, second_path: str) -> int:
    first, second = load_hashes(first_path), load_hashes(second_path)
    all_same = True
    for name in sorted(set(first) | set(second)):
        same = first.get(name) == second.get(name)
        all_same = all_same and same
        print(f"{name}: {'OK' if same else 'DIFFERENT'}")
    return 0 if all_same else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))