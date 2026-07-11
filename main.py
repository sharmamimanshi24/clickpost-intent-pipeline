"""
main.py
-------
Runs score.py and activator.py in order.

tier.py is run SEPARATELY, on purpose - so its output can be checked before
scoring runs on it. Run it yourself first:

    python tier.py --overwrite

Then run this:

    python main.py
"""

import subprocess
import sys
import os

PIPELINE_STAGES = [
    ("score.py", "Scoring and ranking all brands"),
    ("activator.py", "Generating outreach for top 5 accounts"),
]


def run_stage(script_name, description):
    print(f"\n{'='*70}")
    print(f"  {description}  ({script_name})")
    print(f"{'='*70}\n")

    if not os.path.exists(script_name):
        print(f"ERROR: {script_name} not found in the current folder. Stopping.")
        return False

    result = subprocess.run([sys.executable, script_name])

    if result.returncode != 0:
        print(f"\n{script_name} exited with an error (code {result.returncode}). Stopping pipeline.")
        return False
    return True


def main():
    for script_name, description in PIPELINE_STAGES:
        success = run_stage(script_name, description)
        if not success:
            print("\nPipeline stopped early. Fix the error above and re-run.")
            sys.exit(1)

    print(f"\n{'='*70}")
    print("  Pipeline complete. Outputs:")
    print("    - scored_accounts.csv   (all 25 brands, ranked)")
    print("    - outreach_top5.csv     (LinkedIn + email for top 5)")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()