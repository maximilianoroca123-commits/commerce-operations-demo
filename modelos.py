# Validated request contracts for product, sale, cash and procurement operations.


from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    model_validator,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)


def normalizar_categoria(valor):
    if isinstance(valor, str):
        return valor.strip().lower()

    return valor


Marca = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProductoCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]

    categoria: Annotated[
        Literal["alimento", "tecnologia", "libreria"],
        BeforeValidator(normalizar_categoria),
    ]

    marca: Marca | None = None
    precio: int = Field(gt=0, strict=True)
    stock: int = Field(default=0, ge=0, strict=True)


class ProductoActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo_stock: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def motivo_requiere_stock(self):
        if (
            "motivo_stock" in self.model_fields_set
            and "stock" not in self.model_fields_set
        ):
            raise ValueError("El motivo de stock requiere enviar stock")
        return self

    marca: Marca | None = None
    precio: int = Field(default=1, gt=0, strict=True)
    stock: int = Field(default=0, ge=0, strict=True)


class VinculoOferta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producto_id: int = Field(gt=0, le=2**63 - 1, strict=True)


class RecepcionPedido(BaseModel):
    model_config = ConfigDict(extra="forbid")
    costo_pagado_centavos: int = Field(gt=0, le=2**63 - 1, strict=True)


class EntregaPedido(RecepcionPedido):
    cantidad: int = Field(gt=0, le=2**63 - 1, strict=True)


class CorreccionEntrega(EntregaPedido):
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class VentaCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producto_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    cantidad: int = Field(gt=0, le=2**63 - 1, strict=True)


class CarritoCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    productos: Annotated[list[VentaCrear], Field(min_length=1, max_length=100)]
    direccion_entrega: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)
        ]
        | None
    ) = None
    canal: Literal["presencial", "online"] = "presencial"
    modalidad: Literal["local", "retiro", "envio"] | None = None

    @model_validator(mode="after")
    def validar_entrega(self):
        if self.modalidad is None:
            self.modalidad = "local" if self.canal == "presencial" else "retiro"
        if (self.canal == "presencial") != (self.modalidad == "local"):
            raise ValueError("Presencial usa local; online usa retiro o envio")
        return self


class PagoSimulado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["aprobado", "rechazado"]


class EventoPagoDemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["pendiente", "procesando", "aprobado", "rechazado", "cancelado"]


class ConexionPagoDemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disponible: bool = Field(strict=True)


class EntregaVenta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["preparando", "listo", "enviado", "entregado"]


class ProductoDevuelto(VentaCrear):
    reponer: bool = Field(strict=True)


class MotivoCancelacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


class DevolucionVenta(MotivoCancelacion):
    productos: Annotated[list[ProductoDevuelto], Field(min_length=1, max_length=100)]


class ReintegroVenta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caja_esperada: (
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")] | None
    ) = None
    estado: Literal["confirmado", "fallido"]


ReferenciaCaja = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class AperturaCaja(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fondo_inicial: int = Field(ge=0, le=2**63 - 1, strict=True)


class CierreCaja(BaseModel):
    model_config = ConfigDict(extra="forbid")
    saldo_esperado: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)
    contado: int = Field(ge=0, le=2**63 - 1, strict=True)


class MovimientoEfectivo(MotivoCancelacion):
    tipo: Literal["ingreso", "retiro"]
    importe: int = Field(gt=0, le=2**63 - 1, strict=True)


class VentaEfectivo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_esperado: int | None = Field(default=None, gt=0, le=2**63 - 1, strict=True)
    caja: ReferenciaCaja
    recibido: int = Field(gt=0, le=2**63 - 1, strict=True)
    productos: Annotated[list[VentaCrear], Field(min_length=1, max_length=100)]


class ReglaReposicion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activa: bool = Field(default=True, strict=True)
    modo: Literal["automatico", "aviso"] = "automatico"
    minimo: int = Field(default=5, ge=0, le=1000000, strict=True)
    objetivo: int = Field(default=10, gt=0, le=1000000, strict=True)
    alertar_desde: int = Field(default=7, ge=0, le=1000000, strict=True)
    multiplo: int = Field(default=1, gt=0, le=1000000, strict=True)
    max_unidades: int = Field(default=100, gt=0, le=1000000, strict=True)
    costo_max_centavos: int | None = Field(
        default=None, gt=0, le=2**63 - 1, strict=True
    )
    importe_max_centavos: int = Field(default=1000000, gt=0, le=2**63 - 1, strict=True)
    vigencia_minutos: int = Field(default=60, ge=1, le=10080, strict=True)
    plazo_horas: int = Field(default=24, ge=1, le=8760, strict=True)
    considerar_reservas: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def validar_umbrales(self):
        if not self.minimo <= self.alertar_desde < self.objetivo:
            raise ValueError("Se requiere minimo <= alertar_desde < objetivo")
        return self


from datetime import date, datetime, timedelta, timezone


class AdjuntoComprobante(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]
    contenido_base64: Annotated[
        str, StringConstraints(min_length=1, max_length=7000000)
    ]


class DatosCompraEmergencia(MotivoCancelacion):
    origen: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    empleado: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ]
    fecha_compra: date
    tipo_comprobante: Literal["ticket", "factura", "boleta", "otro"]
    numero_comprobante: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    adjunto: AdjuntoComprobante | None = None

    @model_validator(mode="after")
    def validar_fecha_compra(self):
        if self.fecha_compra > datetime.now(timezone(timedelta(hours=-3))).date():
            raise ValueError("La recepción no puede registrar una compra futura")
        return self


class LineaEmergencia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    producto_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    cantidad: int = Field(gt=0, le=1000000, strict=True)
    costo_unitario_centavos: int = Field(gt=0, le=2**63 - 1, strict=True)


class CompraEmergencia(DatosCompraEmergencia):
    productos: Annotated[list[LineaEmergencia], Field(min_length=1, max_length=100)]


class ReposicionEmergencia(DatosCompraEmergencia):
    cantidad: int = Field(gt=0, le=1000000, strict=True)
    costo_unitario_centavos: int = Field(gt=0, le=2**63 - 1, strict=True)
