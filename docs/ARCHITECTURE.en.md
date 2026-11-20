# Architecture and behavior

[Español](ARCHITECTURE.es.md) · [English](ARCHITECTURE.en.md) · [Home](../README.en.md)

## Overall design

The system is a modular FastAPI application with a local SQLite database and two clients: web and console. The web client uses same-origin JavaScript, HTML and CSS. Modules separate HTTP entry points, identity, business rules, storage and history without presenting every file as an independent microservice.

| Responsibility | Main files |
| --- | --- |
| Routes and server lifecycle | `servidor.py`, `rutas_*.py` |
| Input contracts and limits | `modelos.py`, models in `usuarios.py` and routers |
| Identity, roles and ownership | `autenticacion.py`, `usuarios.py` |
| Catalog and inventory | `repositorio_sqlite.py`, `movimientos_inventario.py`, `inventario_reservas.py` |
| Payments and sale tracking | `caja.py`, `caja_efectivo.py`, `pedidos_venta.py` |
| Returns and customer service | `devoluciones.py`, `gestiones_cliente.py` |
| Supplier offers and goods receipt | `catalogos.py`, `reposicion.py`, `pedidos_proveedor.py` |
| General rule and simulated fund | `reposicion_simulada.py` |
| Audit and recovery | `auditoria_comercial.py`, `respaldos.py` |
| Interface and translation | `interfaz/*.js`, `interfaz/i18n.js` |

Services execute SQL where they need to coordinate a complete transaction. No ORM is used. The original CRUD entry point, `main.py`, retains its `productos.db` database; the web application uses `productos_api.db`. `menu_api.py` is a client of the latter API.

## Contracts and permissions

FastAPI and Pydantic check accepted types, quantities and fields. Dependencies verify identity and role. Services additionally validate inventory, funds, status and ownership at execution time.

Authenticating an account does not permit access to every order: customers can access only their purchases, and suppliers their purchase orders. Available buttons guide users, but the server retains actual authorization control.

Passwords are stored using scrypt with an individual salt. Validation responses avoid echoing sensitive request data. Web credentials remain in memory and are cleared on sign-out.

## Transactions and retries

Related changes are committed in one transaction. `BEGIN IMMEDIATE` obtains the write turn before checking and changing balances or quantities that may be contested.

Delivery notes, sales, contributions and other operations use references and replay checks. Repeating a reference with the same data retrieves the result where supported; reusing it with different content causes a conflict.

If a response is lost, the web client retains the reference and request body of the uncertain operation. It retries those same values rather than creating another operation. This is not an exactly-once guarantee for any future external service.

## Inventory and money

| Concept | Meaning |
| --- | --- |
| Physical stock | Units recorded at the business |
| Goods reservation | Units committed to open purchases |
| Available stock | Physical stock minus reserved units |
| On order | Goods ordered from a supplier but not yet received |
| Sales cash register | Expected and counted cash by shift |
| Emergency fund | Earlier record of emergency purchases and expenditure |
| Simulated fund | Fictitious funds reserved and paid in the automatic demo |

Creating an online purchase reserves goods; approving payment deducts the corresponding stock once. Delivery does not deduct it again. Receiving resalable returned goods and refunding money are separate operations.

Creating, paying or dispatching a supplier purchase order does not add units to local inventory. Only confirmed goods receipt does so. The sales cash register and simulated fund do not affect each other.

Local selling prices and cash operations use whole ARS; procurement costs and the simulated fund use integer cents. For example, `costo_pagado_centavos=50050` means ARS 500.50 per unit. Field names retain that distinction.

## Demonstration automation

The general rule orders 3 units when the selected product reaches physical stock 0, subject to a maximum unit cost of ARS 1000, an eligible offer and sufficient funds. The full amount is reserved before payment is allowed.

The administrator approves fictitious payment with a button. The simulated supplier advances through preparing → ready → dispatched. States and timestamps are stored in SQLite. Goods receipt remains manual and may be partial.

The API task runs approximately every second; each preparation/dispatch step takes about five seconds. The panel polls results every two seconds. Closing the page does not stop processing if the API remains running; stopping the API suspends it, with continuity from persisted state after restart.

Pausing prevents new orders without undoing reservations or payments. Cancelling before payment releases the reservation and pauses generation. Supplier refunds and post-payment cost changes are not implemented in this demo.

## Internationalization

`messages.json` contains the ES/EN catalog; `i18n.js` manages language and presentation. `messages.js` is the generated browser copy. After editing the catalog, run `python tools/build_i18n.py`; the package already includes this asset and does not require regeneration to run. Text elements are bound to presentation functions so they update without reloading or repeating mutation requests. Fields, session, cart and references are preserved.

Translations do not change status codes, JSON fields, persisted categories or identifiers. User-entered notes and names are treated as data. Simulator-authored messages are localized. Receipt download sends `idioma=es` or `idioma=en`, with the same ownership checks.

Only the language preference is stored in local storage. HTML forms localize common validation messages. The currency remains ARS even when separators and display formatting change.

## History and recovery

Inventory movements explain quantity changes. Audit records identify the actor and operation. Both are recorded with the corresponding change. A backup preserves the complete state, not just the catalog.

Copies are checked using SQLite integrity, relationships and a SHA-256 digest. Restoration requires stopping the server and retains a snapshot of the previous state. Events predating audit tracking are not retrospectively reconstructed.

## Deliberately separate extensions

The individual-rule engine, emergency purchases and advanced administration remain in existing modules/API/console tools. This presentation does not add real payments or automate physical transport. A future external integration would need to address notification authenticity, failures, reconciliation and testing without replacing these rules with interface assumptions.
