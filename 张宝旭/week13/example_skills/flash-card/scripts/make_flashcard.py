from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    args = parser.parse_args()

    topic = " ".join(args.topic.split())
    print(f"# Flash Card: {topic}")
    print()
    print(f"Question: What is the core idea of {topic}?")
    print(f"Answer: Explain {topic} in one clear sentence, then connect it to one concrete example.")
    print(f"Memory cue: {topic} -> definition -> example -> why it matters.")


if __name__ == "__main__":
    main()
