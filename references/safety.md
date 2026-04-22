# Safety

MVP is read-only.

## Hard Deny

Do not call:

- Futu `place_order.py`
- Futu `modify_order.py`
- Futu `cancel_order.py`
- Futu trade unlock APIs
- Longbridge order placement tools
- Any direct order, cancel, modify, or unlock operation

## Language Rules

Use conditional decision-support language:

- Good: "若日收站上 44.20 且量能确认，则突破条件可观察。"
- Good: "若跌破 40.60，则该结构失效。"
- Bad: "现在买入。"
- Bad: "卖出这只股票。"

## Future Trading Support

Trading support requires a separate plan with:

- account selection
- explicit user confirmation
- risk gate
- order preview
- audit log
- real/simulated environment separation
