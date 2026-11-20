# Portfolio description

[Español](PROFILE.es.md) · [English](PROFILE.en.md) · [Home](../README.en.md)

## Title

Commerce operations system with an ES/EN interface and simulated replenishment

## Description

A personal demonstration project for small-business operations: inventory, sales, cash register, online orders, delivery, returns, customer service and procurement.

Built with Python, FastAPI, SQLite and JavaScript. The web interface switches between Spanish and English while preserving the same business logic, session and data. It includes role-based access, order ownership, movement history and bilingual receipts.

The replenishment demonstration evaluates inventory, offers and simulated funds, reserves the purchase amount and allows a simulated payment to be approved. The automatic supplier progresses to dispatch; manual goods receipt confirms the units entering inventory.

The repository includes source code, local installation, reproducible walkthroughs and automated tests of business rules, permissions, retries and translation. Payments and automatic suppliers are simulated: there are no real banking transactions or tax invoices.

## Demonstrated capabilities

- Separation of interface, API, business rules and persistence.
- Related operations within SQLite transactions.
- Access control and record ownership.
- Duplicate prevention through references and controlled retries.
- Automation through persisted states and bilingual presentation.
- Documentation of expected outcomes and regression testing.

## Scope of the experience presented

This is a personal example developed iteratively with AI assistance and functional verification. It is not presented as a commercial client engagement, a real banking integration or a deployed production system.
