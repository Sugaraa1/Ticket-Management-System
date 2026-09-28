#!/usr/bin/env bash
# Тест ажиллуулах богино скрипт. Түр SQLite DB ашиглана (.env-ийн Postgres-т хүрэхгүй).
#
#   ./test.sh                  — бүх тест
#   ./test.sh --rules          — зөвхөн дүрмийн тестүүд (docs/rules.md)
#   ./test.sh --cov            — бүх тест + coverage (htmlcov/index.html)
#   ./test.sh --e2e [--show]   — browser E2E тест (--show: дэлгэцэн дээр харуулна)
#   ./test.sh --browser        — автомат тестийн worker-ийг жинхэнэ Chromium-аар шалгах тест
#   ./test.sh apps.tickets     — зөвхөн заасан хэсэг
cd "$(dirname "$0")"
export DATABASE_URL="sqlite:///:memory:"
PY=.venv/bin/python

case "$1" in
  --rules)
    exec $PY manage.py test apps.accounts.test_rules_auth apps.tickets.tests.test_rules_tickets \
      apps.tickets.tests.test_attachment_rules ;;
  --cov)
    .venv/bin/coverage run --source=apps --omit="*/migrations/*,*/tests*,*/test_*" manage.py test --exclude-tag browser
    code=$?
    .venv/bin/coverage report --skip-covered | tail -15
    .venv/bin/coverage html -q && echo "Дэлгэрэнгүй: htmlcov/index.html"
    exit $code ;;
  --browser)
    exec $PY manage.py test apps.autotest --tag browser ;;
  --e2e)
    shift
    exec ./e2e/run.sh "$@" ;;
  "")
    exec $PY manage.py test --parallel auto --exclude-tag browser ;;
  *)
    exec $PY manage.py test "$@" ;;
esac
