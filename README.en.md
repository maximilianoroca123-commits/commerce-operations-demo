# Commerce operations: functional demonstration

[Español](README.es.md) · [English](README.en.md)

A portfolio application for a small business: catalog and inventory, sales, cash register, online orders, delivery, returns, customer service and procurement. It includes an automatic replenishment demonstration with reserved funds, manual simulated payment approval and automatic dispatch by a simulated supplier.

The web interface provides the same functions in Spanish and English through the header selector. One backend and one database retain the business rules, quantities, balances and history. These are not two independently maintained applications.

**All payments, QR workflows and automatic supplier processes are demonstrations. No banks are connected and no real transfers are made. Receipts are not tax invoices.**

## Features

- Paginated catalog, search, filters, product details and inventory movements.
- Product creation and editing for administrators.
- In-person sales: cart, cash shift opening, cash received, change, movements and counted closing.
- Online purchasing: temporary reservation, simulated payment, customer-owned orders and delivery tracking.
- Separate physical returns and refunds, with a final response visible to the customer.
- Supplier catalog, offer linking, purchase orders, notices and partial or complete goods receipt.
- Replenishment demo: general rule, simulated fund, reserved amount, approved payment and automatic dispatch; manual goods receipt.
- Account authentication, role permissions and order ownership restrictions.
- Audit history, regression tests and verified backups.
- Sales receipts in ES/EN HTML, preserving transaction data.

## Technology and organization

Python, FastAPI, Pydantic, SQLite and JavaScript without a frontend framework. HTML and CSS are served by the same application as the API. The web interface requires neither a build step nor Node to run. Node is used for JavaScript and DOM tests.

API identifiers, table names and many functions retain their original Spanish names for compatibility. This edition uses formal technical documentation and concise implementation comments; the language selector translates presentation, not the data schema.

## Local installation

Use a new folder. The package includes no private databases, personal passwords, backups or personal screenshots. Preparation adds the schema and initial products when the database is empty; it is not a command for resetting existing data.

Environment verified for this release: **Python 3.12.14 and Node 24.22.3** for tests. The original application was also used on Windows with a Python 3.14 environment. Python dependencies are pinned in the requirements files.

### Windows / PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-pruebas.txt
.\.venv\Scripts\python.exe demo_setup.py --language en
.\.venv\Scripts\python.exe -m uvicorn servidor:app --host 127.0.0.1 --port 8000
```

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-pruebas.txt
.venv/bin/python demo_setup.py --language en
.venv/bin/python -m uvicorn servidor:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/interfaz/**. Keep the API running. Choose **Español** or **English** in the header; the language preference is stored locally. Credentials are not saved in local storage.

Setup prompts for a password, without echoing it, for new demonstration accounts. Use 10–128 ASCII characters. The four new accounts share this password solely to simplify this local demonstration. Running setup again does not modify existing accounts or passwords.

| Demo account | Role |
| --- | --- |
| `demo_admin` | Administrator |
| `demo_staff` | Employee |
| `demo_customer` | Customer |
| `demo_supplier` | Supplier associated with Demo |

When using a copy of an existing database, its accounts and passwords are preserved. Account setup is not required to use the language selector.

## Demonstration and tests

The shortest walkthrough is in [docs/DEMO.en.md](docs/DEMO.en.md). The administrator can prepare the automatic example in the web interface, add simulated funds, approve payment and observe dispatch before confirming goods receipt.

```bash
python -m unittest discover -q
npm ci
npm test
```

Use the virtual environment's interpreter for the first command. `npm ci` installs development dependencies only; it is not required to run the application. Console QR tools are optional; their dependencies are in `requirements-qr.txt`.

Test cases, verification levels and testing limitations are described in [docs/TESTING.en.md](docs/TESTING.en.md).

## Languages, data and compatibility

Changing language does not duplicate orders or reset the session, cart or form values. Language changes are temporarily blocked during confirmations and ongoing operations to keep the reviewed summary consistent. Dates and amounts follow the selected locale; the currency remains ARS.

Product names, brands, references, email addresses, notes and user-authored responses keep their original text. Notices generated by the simulated supplier are localized. Language changes labels and messages, not business data.

Historical console tools retain their original Spanish interface. The portfolio web interface and account setup support ES/EN; additional operations are documented in both languages and can also be called through the API. This release does not claim that every console menu is translated or that every administrative tool has a web screen.

## Scope and limitations

This is a personal demonstration prototype, developed iteratively with AI assistance and test-based validation. It does not represent a commercial commission or a production installation.

It includes no real banking gateway, payment webhook, automated physical logistics, tax invoicing or production-hardened public deployment. Goods receipt remains a business decision. The automatic supplier runs inside the local simulator, not on an external platform.

HTTP Basic access is intended for local testing; Base64 is not encryption. Public deployment requires reviewing transport, authentication, configuration and operations. Backup restoration requires stopping the server.

The earlier individual-rule engine remains available through the API/console. The final demonstration uses a fixed general rule to avoid unnecessary complexity. Full account administration, emergency purchases and some backup tools remain primarily in the console/API.
