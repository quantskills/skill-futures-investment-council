# Feature Contract

## trend.ma_alignment

- Input: `close`
- Output: `state`, `ma_20`, `ma_60`, `ma_120`
- States: `bullish`, `bearish`, `mixed`, `unknown`

## trend.macd

- Input: `close`
- Output: `macd`, `signal`, `histogram`, `state`
- States: `bullish`, `bearish`, `bullish_cross`, `bearish_cross`, `neutral`, `unknown`

## trend.adx

- Input: `high`, `low`, `close`
- Output: `adx`, `trend_strength`
- States: `strong_trend`, `weak_trend`, `range`, `unknown`

## trend.breakout

- Input: `high`, `low`, `close`
- Output: `breakout_20`, `breakout_55`, `breakdown_20`, `breakdown_55`
- Rule: only prior bars may be used.

## momentum.rsi

- Input: `close`
- Output: `rsi`, `state`
- States: `overbought`, `bullish_momentum`, `neutral`, `bearish_momentum`, `oversold`, `unknown`

## volatility.atr_percent

- Formula: `ATR / close`
- Output: ratio
- Missing: `null`

## futures.open_interest_change

- Input: `open_interest`
- Output: multi-window percentage change
- Missing: `available=false`

## futures.price_oi_signal

- Input: `close`, `open_interest`
- Output: `price_up_oi_up`, `price_up_oi_down`, `price_down_oi_up`, `price_down_oi_down`, `flat`, `unknown`

## futures.basis

- Input: `spot_price`, `close`
- Convention: `spot_minus_futures`

## futures.curve_structure

- Input: `curve_snapshot` preferred, or long-form `contract_month` + `settlement`
- Source: Pandadata multi-contract daily bars when available
- Output: `state`, `front`, `back`, `spread`, `front_symbol`, `back_symbol`, `contract_count`
- States: `contango`, `backwardation`, `flat`, `unknown`

## fundamental.spot_price

- Input: `spot_price`
- Output: latest spot price snapshot

## fundamental.inventory_state

- Input: `inventory`
- Output: `inventory`, `change`, `state`

## risk.drawdown

- Input: `close`
- Output: current and lookback drawdown
