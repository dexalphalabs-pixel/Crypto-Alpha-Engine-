# Crypto Alpha Engine v0.7.6

## Data Source Reliability

- Dodano Bybit fallback dla CEX scanner.
- CEX fallback chain: Binance → OKX → Bybit.
- Market Context fallback chain: Binance → CoinGecko → Bybit.
- Dodano tryb działania w Telegram summary: FULL / DEX_ONLY / DEX_ONLY_DEGRADED / CEX_ONLY / DEGRADED.
- Performance z opóźnieniem powyżej 6h oznaczany jest jako STALE w Telegramie.
- Fast-fail uwzględnia CEX/BybitFallback i MarketContext/BybitFallback.
- Primary-source failures są warnings, jeśli fallback dostarczył dane.
- Zaktualizowano User-Agent do 0.7.6.
