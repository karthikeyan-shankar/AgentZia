"""Krefter - a tiny routine tracker. Tell it what you have; it reminds you next time.

Run:  python krefter.py      (no API key, no internet, no cost)

Just type something to save it, e.g.  "assignment 3 for DBMS due friday"
Commands:  list | done <id> | delete <id> | all | help | exit
"""
import json
import os
from datetime import datetime

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krefter_data.json")
HELP = "Type anything to save it.  Commands: list | done <id> | delete <id> | all | help | exit"


def load():
    if os.path.exists(FILE):
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(items):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def show(items, include_done=False):
    shown = [i for i in items if include_done or not i["done"]]
    if not shown:
        print("  Nothing pending. You're clear!")
        return
    for i in shown:
        mark = "x" if i["done"] else " "
        print(f"  [{mark}] #{i['id']}  {i['text']}   (added {i['date']})")


def main():
    items = load()
    print("Krefter here. You have:")
    show(items)
    print(HELP)

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        cmd = cmd.lower()

        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            print(HELP)
        elif cmd == "list":
            show(items)
        elif cmd == "all":
            show(items, include_done=True)
        elif cmd in ("done", "delete") and arg.strip().isdigit():
            n = int(arg)
            target = next((i for i in items if i["id"] == n), None)
            if not target:
                print("  No such id.")
                continue
            if cmd == "done":
                target["done"] = True
                print(f"  Marked #{n} done.")
            else:
                items.remove(target)
                print(f"  Deleted #{n}.")
            save(items)
        else:
            next_id = max((i["id"] for i in items), default=0) + 1
            items.append({
                "id": next_id,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "text": line,
                "done": False,
            })
            save(items)
            print(f"  Saved as #{next_id}.")

    print("Bye!")


if __name__ == "__main__":
    main()
