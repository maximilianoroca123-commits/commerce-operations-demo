// Separate physical return receipt and refund presentation.
"use strict";
function pendingReturnLines(p) {
  return p.productos
    .map((x) => ({
      ...x,
      pendientes:
        x.cantidad -
        p.devoluciones.operaciones.reduce(
          (n, op) =>
            n +
            op.productos
              .filter((i) => i.producto_id === x.producto_id)
              .reduce((s, i) => s + i.cantidad, 0),
          0,
        ),
    }))
    .filter((x) => x.pendientes > 0);
}
function returnPayload(p, values, motivo) {
  const reason = motivo.trim();
  if (!reason) throw new Error(tr("Explicá el motivo de la devolución."));
  const remaining = new Map(
    pendingReturnLines(p).map((x) => [x.producto_id, x]),
  );
  const products = [];
  let amount = 0;
  for (const value of values) {
    const line = remaining.get(value.producto_id);
    if (
      !line ||
      !Number.isSafeInteger(value.cantidad) ||
      value.cantidad < 0 ||
      value.cantidad > line.pendientes
    )
      throw new Error(tr("Revisá las cantidades pendientes de devolución."));
    if (value.cantidad === 0) continue;
    if (typeof value.reponer !== "boolean")
      throw new Error(
        tr("Indicá si cada producto recibido está apto para volver al stock."),
      );
    if (products.some((x) => x.producto_id === value.producto_id))
      throw new Error(tr("No repitas productos en la devolución."));
    products.push({
      producto_id: value.producto_id,
      cantidad: value.cantidad,
      reponer: value.reponer,
    });
    amount += line.precio_unitario * value.cantidad;
  }
  if (!products.length)
    throw new Error(tr("Ingresá al menos una unidad recibida físicamente."));
  return {
    data: {
      motivo: reason,
      productos: products,
    },
    amount,
  };
}
function addReturnActions(box, c) {
  const p = c.pedido,
    card = el(
      "div",
      ui(() => undefined, false),
      "tarjeta cabecera-turno",
    );
  card.append(
    el(
      "h2",
      ui(() => tr("Devoluciones y reintegros"), false),
    ),
  );
  card.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Recibir mercadería registra la devolución física. Confirmar un reintegro registra el dinero devuelto; son pasos separados.",
          ),
        false,
      ),
    ),
  );
  if (c.acciones.includes("devolver"))
    card.append(
      button(
        ui(() => tr("Recibir devolución"), false),
        () => returnForm(p.id),
        "principal",
      ),
    );
  if (c.acciones.includes("atender_solicitud"))
    card.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "Hay una solicitud pendiente del cliente. Abrila desde Atención al cliente para mantener vinculadas la gestión y su respuesta.",
            ),
          false,
        ),
        "aviso",
      ),
    );
  if (!p.devoluciones.operaciones.length)
    card.append(
      el(
        "p",
        ui(
          () => tr("Esta venta todavía no tiene devoluciones registradas."),
          false,
        ),
      ),
    );
  for (const op of p.devoluciones.operaciones) {
    const item = el(
      "article",
      ui(() => undefined, false),
      "evento",
    );
    item.append(
      el(
        "h3",
        ui(() => label(op.tipo) + " · " + money.format(op.importe), false),
      ),
    );
    definition(item, [
      [ui(() => tr("Motivo"), false), ui(() => op.motivo, true)],
      [ui(() => tr("Registrada"), false), ui(() => date(op.creado_en), false)],
      [
        ui(() => tr("Reintegro"), false),
        ui(() => label(op.estado_reintegro), false),
      ],
    ]);
    for (const x of op.productos) {
      const product = p.productos.find((v) => v.producto_id === x.producto_id);
      item.append(
        el(
          "p",
          ui(
            () =>
              tr("{0}: {1} unidad(es). {2}", [
                product?.nombre || tr("Producto ID ") + x.producto_id,
                x.cantidad,
                x.reponer
                  ? tr("Apto: volvió al stock.")
                  : tr("No apto: no aumentó el stock."),
              ]),
            true,
          ),
        ),
      );
    }
    item.append(
      el(
        "p",
        ui(() => tr("Referencia: ") + op.referencia, true),
        "referencia",
      ),
    );
    if (
      op.estado_reintegro !== "confirmado" &&
      c.acciones.includes("reintegrar") &&
      !c.acciones.includes("atender_solicitud")
    )
      item.append(
        button(
          ui(
            () => tr("Gestionar reintegro de ") + money.format(op.importe),
            false,
          ),
          () => refundForm(p.id, op.referencia),
          "principal",
        ),
      );
    else if (op.estado_reintegro === "confirmado")
      item.append(
        el(
          "p",
          ui(
            () =>
              tr(
                "Reintegro confirmado. No se vuelve a registrar la salida de dinero.",
              ),
            false,
          ),
        ),
      );
    card.append(item);
  }
  box.append(card);
}
async function returnForm(id, solicitud = null) {
  const c = await api(
      solicitud ? requestBase(solicitud) : `/operaciones/ventas/${id}`,
    ),
    p = c.pedido;
  const back = () =>
    solicitud ? showRequest(solicitud.id, solicitud.reference) : showSale(id);
  const screen = solicitud ? "atencion-web" : "ventas-web";
  if (!c.acciones.includes(solicitud ? "recibir" : "devolver")) {
    await back();
    throw new Error(
      tr(
        "Esta venta ya no permite registrar una nueva devolución desde este recorrido.",
      ),
    );
  }
  view(screen);
  const box = $(screen);
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Recibir devolución · Venta {0}", [id]), false),
    "titulo-devolucion",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Ingresá sólo unidades que ya recibiste físicamente. Cantidad 0 omite ese producto. El importe usa el precio de la venta original.",
          ),
        false,
      ),
    ),
    el(
      "p",
      ui(
        () =>
          tr("Este paso no devuelve dinero. El reintegro se gestiona después."),
        false,
      ),
      "aviso",
    ),
  );
  const form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    ),
    fields = [];
  for (const product of pendingReturnLines(p)) {
    const part = el(
      "div",
      ui(() => undefined, false),
      "evento",
    );
    part.append(
      el(
        "h2",
        ui(() => product.nombre, true),
      ),
      el(
        "p",
        ui(
          () =>
            tr(
              "Compradas: {0} · Pendientes de devolución: {1} · Precio original: {2}",
              [
                product.cantidad,
                product.pendientes,
                money.format(product.precio_unitario),
              ],
            ),
          false,
        ),
      ),
    );
    const qty = field(
      part,
      ui(() => tr("Cantidad recibida"), false),
      "dev-cantidad-" + product.producto_id,
      0,
      {
        type: "number",
        min: 0,
        max: product.pendientes,
        step: 1,
        required: true,
      },
    );
    const l = el(
      "label",
      ui(() => tr("¿Está apto para volver al stock?"), false),
    );
    l.htmlFor = "dev-apto-" + product.producto_id;
    const apt = el("select");
    apt.id = l.htmlFor;
    for (const [value, text] of [
      ["", tr("Elegir si se recibe alguna unidad")],
      ["si", tr("Sí, vuelve al stock")],
      ["no", tr("No, no aumenta el stock")],
    ]) {
      const option = el(
        "option",
        ui(() => text, false),
      );
      option.value = value;
      apt.append(option);
    }
    part.append(l, apt);
    form.append(part);
    fields.push({
      product,
      qty,
      apt,
    });
  }
  const reason = field(
    form,
    ui(() => tr("Motivo de la devolución"), false),
    "dev-motivo",
    solicitud ? c.solicitud.motivo : "",
    {
      required: true,
      maxLength: 500,
    },
  );
  const actions = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    ),
    submit = el(
      "button",
      ui(() => tr("Revisar devolución"), false),
      "principal",
    );
  submit.type = "submit";
  actions.append(
    button(
      ui(() => tr("Cancelar"), false),
      back,
    ),
    submit,
  );
  form.append(actions);
  box.append(form);
  on(form, "submit", async () => {
    const values = fields.map(({ product, qty, apt }) => ({
      producto_id: product.producto_id,
      cantidad: integer(qty, 0),
      reponer: apt.value === "" ? null : apt.value === "si",
    }));
    const payload = returnPayload(p, values, reason.value);
    const rows = payload.data.productos.map((x) => [
      p.productos.find((v) => v.producto_id === x.producto_id).nombre,
      tr("{0} unidad(es) · {1}", [
        x.cantidad,
        x.reponer ? tr("Vuelve al stock") : tr("No vuelve al stock"),
      ]),
    ]);
    const op = operation(
      `/pedidos-venta/${id}/devoluciones/${solicitud ? c.referencia_operacion : ref("devolucion-web")}`,
      payload.data,
    );
    reviewOperation(
      [
        ...rows,
        [ui(() => tr("Motivo"), false), ui(() => payload.data.motivo, true)],
        [
          ui(() => tr("Importe a reintegrar después"), false),
          ui(() => money.format(payload.amount), false),
        ],
        [
          ui(() => tr("Dinero devuelto en este paso"), false),
          ui(() => money.format(0), false),
        ],
      ],
      op,
      tr("Revisar recepción de devolución"),
      tr("Confirmar devolución recibida"),
      async () => {
        await back();
        announce(
          ui(
            () =>
              tr(
                "Devolución recibida. El reintegro todavía está pendiente; elegí Gestionar reintegro para continuar.",
              ),
            false,
          ),
        );
      },
    );
  });
  focusTitle("titulo-devolucion");
}
async function refundForm(id, reference, solicitud = null) {
  const c = await api(
      solicitud ? requestBase(solicitud) : `/operaciones/ventas/${id}`,
    ),
    p = c.pedido,
    op = p.devoluciones.operaciones.find((x) => x.referencia === reference);
  const back = () =>
    solicitud ? showRequest(solicitud.id, solicitud.reference) : showSale(id);
  const screen = solicitud ? "atencion-web" : "ventas-web";
  if (
    !op ||
    op.estado_reintegro === "confirmado" ||
    !c.acciones.includes("reintegrar")
  ) {
    await back();
    throw new Error(
      tr("El reintegro ya está confirmado o no está disponible."),
    );
  }
  const cash =
    p.medio_pago === "efectivo"
      ? (await api("/operaciones/caja-actual")).caja
      : null;
  view(screen);
  const box = $(screen);
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Reintegro simulado · Venta {0}", [id]), false),
    "titulo-reintegro",
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  definition(card, [
    [ui(() => tr("Importe"), false), ui(() => money.format(op.importe), false)],
    [
      ui(() => tr("Estado actual"), false),
      ui(() => label(op.estado_reintegro), false),
    ],
    [ui(() => tr("Motivo de la devolución"), false), ui(() => op.motivo, true)],
  ]);
  card.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "La devolución física ya está registrada. Este paso no vuelve a ingresar productos al stock.",
          ),
        false,
      ),
      "aviso",
    ),
  );
  if (p.medio_pago === "efectivo") {
    if (cash) {
      definition(card, [
        [
          ui(() => tr("Turno que registrará la salida"), false),
          ui(() => cash.referencia, true),
        ],
        [
          ui(() => tr("Saldo disponible en caja"), false),
          ui(() => money.format(cash.saldo_esperado), false),
        ],
      ]);
      if (cash.saldo_esperado < op.importe)
        card.append(
          el(
            "p",
            ui(
              () =>
                tr(
                  "El saldo no alcanza para confirmar este reintegro. Revisá la caja; no se registrará una salida que la deje en negativo.",
                ),
              false,
            ),
            "aviso",
          ),
        );
    } else
      card.append(
        el(
          "p",
          ui(
            () =>
              tr(
                "No hay caja abierta. Para confirmar un reintegro en efectivo, abrí un turno con el efectivo realmente contado.",
              ),
            false,
          ),
          "aviso",
        ),
        button(
          ui(() => tr("Ir a caja"), false),
          loadCash,
        ),
      );
  }
  card.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Es una simulación de la operación: no se contacta ninguna billetera ni se realiza una transferencia bancaria.",
          ),
        false,
      ),
      "secundario",
    ),
  );
  const form = el("form"),
    l = el(
      "label",
      ui(() => tr("Resultado a registrar"), false),
    );
  l.htmlFor = "reintegro-resultado";
  const result = el("select");
  result.id = l.htmlFor;
  result.required = true;
  for (const [value, text] of [
    ["", tr("Elegir resultado")],
    ["confirmado", tr("Confirmado")],
    ["fallido", tr("Fallido (no devuelve dinero)")],
  ]) {
    const option = el(
      "option",
      ui(() => text, false),
    );
    option.value = value;
    result.append(option);
  }
  form.append(l, result);
  const actions = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    ),
    submit = el(
      "button",
      ui(() => tr("Revisar reintegro"), false),
      "principal",
    );
  submit.type = "submit";
  actions.append(
    button(
      ui(() => tr("Cancelar"), false),
      back,
    ),
    submit,
  );
  form.append(actions);
  card.append(form);
  box.append(card);
  on(form, "submit", async () => {
    if (!["confirmado", "fallido"].includes(result.value))
      throw new Error(tr("Elegí el resultado a registrar."));
    const data = {
      estado: result.value,
    };
    const rows = [
      [tr("Venta"), id],
      [tr("Importe del reintegro"), money.format(op.importe)],
      [tr("Resultado"), label(result.value)],
      [tr("Cambio en stock"), tr("Ninguno; la recepción ya está registrada")],
    ];
    if (p.medio_pago === "efectivo" && result.value === "confirmado") {
      if (!cash)
        throw new Error(
          tr("Abrí una caja antes de confirmar el reintegro en efectivo."),
        );
      if (cash.saldo_esperado < op.importe)
        throw new Error(
          tr("La caja no tiene saldo suficiente. Cancelá y revisá el turno."),
        );
      data.caja_esperada = cash.referencia;
      rows.push(
        [tr("Turno"), cash.referencia],
        [tr("Salida de efectivo"), money.format(op.importe)],
        [
          tr("Saldo estimado posterior"),
          money.format(cash.saldo_esperado - op.importe),
        ],
      );
    } else rows.push([tr("Salida de efectivo de caja"), money.format(0)]);
    rows.push([tr("Referencia de la devolución"), reference]);
    const request = operation(
      `/pedidos-venta/${id}/devoluciones/${encodeURIComponent(reference)}/reintegro`,
      data,
    );
    reviewOperation(
      rows,
      request,
      tr("Revisar reintegro simulado"),
      tr("Confirmar registro del reintegro"),
      async () => {
        await back();
        announce(
          ui(
            () =>
              result.value === "confirmado"
                ? tr(
                    "Reintegro confirmado. Podés consultar el comprobante y los movimientos de caja.",
                  )
                : tr(
                    "Resultado fallido registrado. El importe sigue pendiente; no se devolvió dinero.",
                  ),
            true,
          ),
        );
      },
    );
  });
  focusTitle("titulo-reintegro");
}
