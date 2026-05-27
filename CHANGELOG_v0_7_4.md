# Crypto Alpha Engine v0.7.4

## Zmiany

- Poprawione schedule: cron przeniesiony z `0 * * * *` na `17 * * * *`, aby zmniejszyć opóźnienia GitHub Actions na pełnej godzinie.
- Test Telegrama działa tylko przy ręcznym uruchomieniu (`workflow_dispatch`), nie przy każdym runie z harmonogramu.
- Telegram summary zawiera teraz krótką sekcję „Warte uwagi / alerty” oraz „Do obserwacji”.
- Każdy kandydat w Telegram summary pokazuje: score, risk, data quality, security, zmianę 24h, wolumen, tagi, 2 powody i 2 ryzyka.
- Wersja etykiet zaktualizowana do v0.7.4.
