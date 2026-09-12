name: Budget Monitor

on:
  workflow_dispatch:

  schedule:
    - cron: "10 0 * * *"

permissions:
  contents: write

jobs:
  budget-monitor:

    runs-on: ubuntu-latest

    steps:

      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install packages
        run: |
          pip install requests

      - name: Run budget monitor
        env:
          LOFIN_API_KEY: ${{ secrets.LOFIN_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python budget_monitor.py

      - name: Save budget history
        run: |
          if [ -f seen_budget_ids.json ]; then

            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

            git add seen_budget_ids.json

            if ! git diff --cached --quiet; then

              git commit -m "Update budget monitor history"
              git push

            else

              echo "No budget history changes"

            fi

          else

            echo "seen_budget_ids.json does not exist"

          fi
