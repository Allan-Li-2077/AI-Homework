from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    args = parser.parse_args()

    events = [line.strip(" -") for line in args.events.splitlines() if line.strip(" -")]
    print("# Timeline")
    print()
    for index, event in enumerate(events, start=1):
        print(f"{index}. {event}")


if __name__ == "__main__":
    main()
