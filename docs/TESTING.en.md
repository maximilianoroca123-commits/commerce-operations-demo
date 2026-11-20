# Testing and verification

[Español](TESTING.es.md) · [English](TESTING.en.md) · [Home](../README.en.md)

## Environment and execution

The release was verified with Python 3.12.14 and Node 24.22.3. The Python suite uses unittest and FastAPI's test client. JavaScript tests use Node's test runner; bilingual interface contracts use Happy DOM.

```bash
python -m unittest discover -q
npm ci
npm test
```

Use the virtual environment's interpreter and run from the project root. To run a specific group: `python -m unittest test_portfolio_release -q` or `node --test test_i18n_dom.cjs`.

Release result: **326 Python tests and 41 JavaScript tests passed**.

## Functional coverage

| Area | Verified behavior | References |
| --- | --- | --- |
| Inventory and catalog | Quantities, filters, movements and constraints | `test_regresion.py`, `test_movimientos.py` |
| Access and ownership | Roles, owned data, accounts and passwords | `test_usuarios.py`, `test_ciclo_cuentas.py` |
| Sales and cash | Payment, change, shifts, refunds and counted closing | `test_efectivo.py`, `test_interfaz_ventas_caja.py` |
| Online purchasing | Reservation, payment, order and ownership | `test_caja.py`, `test_interfaz_cliente.py` |
| Delivery and service | Transitions, requests and linked responses | `test_pedidos_venta.py`, `test_interfaz_entregas_atencion.py` |
| Returns and refunds | Physical/financial separation and replay | `test_devoluciones.py`, `test_interfaz_devoluciones.py` |
| Suppliers and delivery notes | Notices, ownership, partial receipts and closing | `test_abastecimiento.py`, `test_interfaz_abastecimiento.py` |
| Automatic replenishment | Funds, offers, reservations, concurrency and dispatch | `test_reposicion_simulada.py` |
| Recovery and evidence | Audit, backups and receipts | `test_auditoria_comercial.py`, `test_respaldos.py`, `test_tickets.py` |
| Bilingual presentation | Language, untranslated data, forms and identical writes | `test_i18n_dom.cjs` |
| Portfolio edition | ES/EN receipts, ownership and idempotent setup | `test_portfolio_release.py` |

HTTP tests create temporary databases per case. Automatic demo tests control the clock to verify deadlines without long waits. Other cases allow the API worker to progress without an open screen.

## Language contracts

The added checks verify that:

- Sign-in, navigation, catalog and controls are presented in both languages.
- The preference persists without storing credentials.
- Language changes preserve cart and input values without new mutation requests.
- Names, brands and notes remain unchanged even when they match a translatable word.
- The complete automatic workflow sends identical fields and quantities in ES/EN.
- Periodic refresh preserves the language and does not erase an unsent contribution.
- Automatic notices are translated; user-authored notes are not.
- Domain errors have English messages while retaining HTTP status codes.
- Downloading a receipt in another language does not bypass ownership or change stock.
- Repeated account setup does not change existing passwords.

JSON names such as `cantidad` and `costo_pagado_centavos` are API contracts; they are not translated when the interface language changes.

## Evidence and limitations

This edition builds on manual workflows from the previous functional version and adds automated bilingual presentation tests. It does not claim that Happy DOM replaces visual review across all browsers.

The suite does not prove the absence of every defect or replace tests of a banking gateway, public deployment or physical logistics. For visual review, follow the same [demonstration walkthrough](DEMO.en.md) in both languages using isolated databases and fictitious data.

Personal development screenshots are not distributed. Fixtures in `tests/fixtures/` are responses from a temporary database with synthetic identities and no passwords. They contain neither the user's database nor real customer data.
