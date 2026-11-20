"""Additional HTTP server exposing synthetic supplier catalogs."""

import os

from fastapi import FastAPI

app = FastAPI()


@app.get("/catalogo")
def catalogo():
    return {
        "moneda": "ARS",
        "productos": [
            {
                "id": "0012",
                "nombre": "  Mouse  ",
                "marca": "TecnoSur",
                "categoria": "tecnología",
                "stock": int(os.getenv("DEMO_STOCK_MOUSE", "20")),
                "precio": os.getenv("DEMO_COSTO_MOUSE", "1250.50"),
            },
            {
                "id": "0013",
                "nombre": "Arroz 500 g",
                "marca": "Campo Claro",
                "categoria": "alimentos",
                "stock": 30,
                "precio": "950.00",
            },
            {
                "id": "0014",
                "nombre": "Pan",
                "marca": "Pan del Barrio",
                "categoria": "alimentos",
                "stock": 0,
                "precio": "500.00",
            },
            {
                "id": "0015",
                "nombre": "Cuaderno",
                "marca": "Papel Norte",
                "categoria": "libreria",
                "stock": 5,
            },
        ],
    }


@app.get("/catalogo-b")
def catalogo_b():
    return {
        "moneda": "ARS",
        "productos": [
            {
                "id": "0012",
                "nombre": "Mouse",
                "marca": "TecnoSur",
                "categoria": "tecnologia",
                "stock": int(os.getenv("DEMO_B_STOCK_MOUSE", "10")),
                "precio": os.getenv("DEMO_B_COSTO_MOUSE", "1200.00"),
            }
        ],
    }
