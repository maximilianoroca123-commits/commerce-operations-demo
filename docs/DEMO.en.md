# Demonstration walkthrough

[Español](DEMO.es.md) · [English](DEMO.en.md) · [Home](../README.en.md)

Use fictitious data and a demonstration database only. IDs are generated during operations; record the actual values shown by the application. No fixed order number is assumed. Account setup is described in the README.

## 1. Minimal automatic workflow

1. Sign in as `demo_admin`. Select English in the header.
2. Open Simulated replenishment → Prepare demo example → review → confirm.
3. Wait: with an opening fund of zero, no purchase order should be created.
4. Add **2000** in simulated funds and confirm. Wait for automatic order generation.
5. Check three units at **500.50**: reserved **1501.50**, paid **0**, available **498.50**.
6. Select Simulate approved payment and confirm. Paid becomes **1501.50**; reserved becomes **0**.
7. Observe preparing → ready → dispatched without manually submitting notices. Physical stock remains **0**.
8. Open the purchase order → Receive goods. Delivery note `demo-auto-1`, quantity **3**, unit cost **500.50**. Review and confirm.
9. Check stock **3**, received order and available funds **498.50**.
10. Return to the panel and Pause purchase order generation.

Prepare demo example is idempotent: an existing example is preserved; stock is not reset and funds are not added. To repeat from scratch, use another isolated database rather than editing tables manually.

## 2. Online purchasing and customer service

1. As administrator, create fictitious product `Demo item`, Technology category, brand `Demo`, price **1000** and stock **5**.
2. As `demo_customer`, add one unit to the cart, select Store pickup and create the order.
3. Before payment: physical **5**, reserved **1**, available **4**. Approve simulated payment before the reservation expires.
4. Physical stock becomes **4**. As `demo_staff`, advance delivery through preparing, ready and delivered.
5. As customer, request a return. The request alone changes neither stock nor money.
6. As employee, open Customer service, receive one resalable unit and confirm the simulated refund.
7. Complete the request with a fictitious explanation. The customer should see it on their request.
8. Result: stock **5**, refunded **1000**, outstanding **0**, request completed. The online purchase does not add cash to the register.

Creating an order and paying are separate steps. Delivery does not charge or deduct stock again. Returns use the stored sale price.

## 3. Cash register and in-person sale

1. As employee, open a cash shift with a counted opening float of **1000**. If a shift already exists, review it first.
2. Sell one unit of `Demo item` for **1000**; cash received **2000**, change **1000**.
3. Check stock **5 → 4** and expected balance **1000 → 2000**. Download the receipt.
4. Record a resalable return of one unit: stock **4 → 5**, with the refund still outstanding.
5. Confirm the **1000** refund from the open cash shift: expected balance returns to **1000**.
6. Count and close with **1000**; expected difference **0**.

Returned goods receipt and the money outflow are separate operations. A previously closed shift is not modified to record a later refund.

## 4. Supplier and partial goods receipt

1. As administrator, create `Demo procurement`, price **1000**, stock **0**, with no individual rule.
2. As `demo_supplier`, open My catalog. Add code `demo-offer-1`, name `Demo procurement`, brand `Demo`, Technology, cost **500.50**, availability **3**. Keep any other offers that should remain active.
3. As administrator, link that offer to the local product and evaluate replenishment. Record the new purchase order ID.
4. As supplier, submit confirmed and dispatched notices. Local stock remains **0**.
5. As employee, receive delivery note `demo-delivery-1`, one unit at **500.50**: partially received, **2** outstanding, stock **1**.
6. Receive delivery note `demo-delivery-2`, two units at the same cost: received, **0** outstanding, stock **3**.
7. As supplier, view the closed order: no new notices are allowed.

Published catalogs are complete replacements: omitting a row makes that offer inactive. This normal purchase order does not use the automatic workflow's simulated fund.

## 5. Bilingual verification

Switch ES/EN with an unsent cart or form. Its values and session should remain, with no new mutation requests. Labels, displayed states, dates and amounts change; user-authored names and notes remain unchanged.

Finish or cancel an open confirmation dialog before changing language. Downloaded receipts use the selected language. Repeating the same workflow in a new database in Spanish produces the same quantity, money and history effects.

## 6. Additional operations

| Operation | Access and precondition |
| --- | --- |
| Cancel customer purchase | Request before dispatch; administration processes cancellation and refund |
| Cancel supplier purchase order | Administration, no receipts; an unpaid simulated order releases funds and pauses generation |
| Correct delivery note or close incomplete | Administration, normal partially received order; do not use an already paid demo order |
| Account administration | Console/API; purchases do not change roles |
| Individual rules and alerts | API/console; separate from the general demo rule |
| Emergency purchases and receipts | API/console; separate fund and records |
| Backup and restoration | Create/verify through API/console; restore locally with the API stopped |

Alternative branches require suitable test records. The same fully received order cannot subsequently demonstrate cancellation, correction and incomplete closing.
