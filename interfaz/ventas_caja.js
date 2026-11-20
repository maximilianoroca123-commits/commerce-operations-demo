// Cash sales and shared immutable confirmation/retry snapshots.
"use strict";
const ops = {
  draft: null,
  salesPage: 1,
  cashPage: 1,
  incierta: null,
};
Object.assign(names, {
  presencial: "Presencial",
  online: "Online",
  efectivo: "Efectivo",
  qr_demo: "QR simulado",
  aprobado: "Aprobado",
  pendiente: "Pendiente",
  entregado: "Entregado",
  preparando: "En preparación",
  listo: "Listo",
  despachado: "Despachado",
  devuelta: "Devuelta por completo",
  parcial: "Devolución parcial",
  devuelta_parcial: "Devolución parcial",
  cancelada: "Cancelada",
  sin_devoluciones: "Sin devoluciones",
  confirmado: "Confirmado",
  fallido: "Fallido",
  venta: "Venta",
  reintegro: "Reintegro",
  ingreso: "Ingreso",
  retiro: "Retiro",
  local: "Retiro en local",
  envio: "Envío",
  vigente: "Sin devoluciones",
});
function resetVentasCaja() {
  ops.draft = null;
  ops.salesPage = 1;
  ops.cashPage = 1;
  ops.incierta = null;
  $("cancelar-confirmacion").hidden = false;
}
function staffOnly() {
  if (!["administrador", "empleado"].includes(state.user?.rol_efectivo))
    throw new Error(tr("Este recorrido corresponde al personal del negocio."));
}
function ref(prefix) {
  return prefix + "-" + crypto.randomUUID().replaceAll("-", "");
}
function heading(box, title, id) {
  const h = el(
    "h1",
    ui(() => title, false),
  );
  h.id = id;
  box.append(h);
  return h;
}
function totals(lines) {
  let total = 0;
  for (const line of lines) {
    const sub = line.precio * line.cantidad;
    if (!Number.isSafeInteger(sub) || !Number.isSafeInteger(total + sub))
      throw new Error(tr("El importe supera el rango admitido."));
    total += sub;
  }
  return total;
}
function operation(path, data, method = "PUT") {
  return {
    path,
    data: data === undefined ? undefined : JSON.parse(JSON.stringify(data)),
    method,
  };
}
async function executeOperation(op) {
  try {
    const result = await api(op.path, op.method || "PUT", op.data);
    ops.incierta = null;
    return result;
  } catch (error) {
    if (error.uncertain) {
      ops.incierta = op;
      $("cancelar-confirmacion").hidden = true;
      setText(
        $("aceptar-confirmacion"),
        ui(() => tr("Reintentar la misma operación"), false),
      );
    } else {
      ops.incierta = null;
      $("cancelar-confirmacion").hidden = false;
      setText(
        $("aceptar-confirmacion"),
        ui(() => tr("Volver a confirmar"), false),
      );
    }
    throw error;
  }
}
function reviewOperation(rows, op, title, accept, success) {
  $("cancelar-confirmacion").hidden = false;
  confirm(
    [
      ...rows,
      [
        ui(() => tr("Referencia de operación"), false),
        ui(() => op.path.split("/").at(-1), false),
      ],
    ],
    async () => {
      const result = await executeOperation(op);
      $("confirmacion").close();
      pending = null;
      $("resumen-confirmacion").replaceChildren();
      try {
        await success(result);
      } catch (error) {
        announce(
          ui(
            () =>
              tr(
                "La operación se guardó, pero no se pudo actualizar la pantalla. ",
              ) +
              (state.user?.rol_efectivo === "cliente"
                ? tr("Consultá Mis pedidos o Mis solicitudes")
                : tr("Consultá la operación desde su sección")) +
              tr(" antes de repetirla. ") +
              error.message,
            false,
          ),
          true,
        );
      }
    },
    title,
    accept,
  );
}
$("confirmacion").addEventListener("cancel", (event) => {
  if (ops.incierta) event.preventDefault();
});
on($("nav-ventas"), "click", async () => {
  announce(ui(() => "", false));
  await loadSales(ops.salesPage);
});
on($("nav-caja"), "click", async () => {
  announce(ui(() => "", false));
  await loadCash();
});
async function loadCash() {
  staffOnly();
  const c = await api("/operaciones/caja-actual");
  view("caja-web");
  const box = $("caja-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Caja de efectivo"), false),
    "titulo-caja",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Consultá el turno actual y sus movimientos. Abrir o cerrar requiere revisar y confirmar.",
          ),
        false,
      ),
    ),
  );
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  actions.append(
    button(
      ui(() => tr("Actualizar caja"), false),
      loadCash,
    ),
    button(
      ui(() => tr("Turnos anteriores"), false),
      () => loadCashHistory(1),
    ),
  );
  box.append(actions);
  if (!c.caja) {
    const card = el(
      "div",
      ui(() => undefined, false),
      "tarjeta cabecera-turno",
    );
    card.append(
      el(
        "h2",
        ui(() => tr("No hay caja abierta"), false),
      ),
      el(
        "p",
        ui(
          () =>
            tr(
              "Abrí un turno indicando el fondo inicial contado para poder cobrar ventas en efectivo.",
            ),
          false,
        ),
      ),
      button(
        ui(() => tr("Abrir turno"), false),
        openCashForm,
        "principal",
      ),
    );
    box.append(card);
  } else {
    const cash = c.caja;
    const card = cashSummary(cash);
    card.classList.add("cabecera-turno");
    const buttons = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    );
    if (c.acciones.includes("cobrar"))
      buttons.append(
        button(
          ui(
            () =>
              ops.draft
                ? tr("Continuar venta en preparación")
                : tr("Cobrar venta"),
            false,
          ),
          startSale,
          "principal",
        ),
      );
    if (c.acciones.includes("consultar"))
      buttons.append(
        button(
          ui(() => tr("Ver movimientos"), false),
          () => showCash(cash.referencia),
        ),
      );
    if (c.acciones.includes("cerrar"))
      buttons.append(
        button(
          ui(() => tr("Contar y cerrar turno"), false),
          () => closeCashForm(cash),
        ),
      );
    card.append(buttons);
    box.append(card);
  }
  focusTitle("titulo-caja");
}
function cashSummary(cash) {
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  card.append(
    el(
      "h2",
      ui(
        () => (cash.cerrado_en ? tr("Turno cerrado") : tr("Turno abierto")),
        false,
      ),
    ),
  );
  definition(card, [
    [
      ui(() => tr("Fondo inicial"), false),
      ui(() => money.format(cash.fondo_inicial), false),
    ],
    [
      ui(() => tr("Saldo esperado"), false),
      ui(() => money.format(cash.saldo_esperado), false),
    ],
    [ui(() => tr("Abierto"), false), ui(() => date(cash.abierto_en), false)],
  ]);
  if (cash.cerrado_en)
    definition(card, [
      [ui(() => tr("Cerrado"), false), ui(() => date(cash.cerrado_en), false)],
      [
        ui(() => tr("Efectivo contado"), false),
        ui(() => money.format(cash.contado), false),
      ],
      [
        ui(() => tr("Diferencia"), false),
        ui(() => money.format(cash.diferencia), false),
      ],
    ]);
  card.append(
    el(
      "p",
      ui(() => tr("Referencia: ") + cash.referencia, true),
      "referencia",
    ),
  );
  return card;
}
async function showCash(reference) {
  const cash = await api("/cajas/" + encodeURIComponent(reference));
  view("caja-web");
  const box = $("caja-web");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a caja"), false),
      loadCash,
    ),
  );
  heading(
    box,
    ui(() => tr("Detalle del turno"), false),
    "titulo-turno",
  );
  box.append(cashSummary(cash));
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  card.append(
    el(
      "h2",
      ui(() => tr("Movimientos del turno"), false),
    ),
  );
  if (!cash.movimientos.length)
    card.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "El turno todavía no tiene movimientos. El fondo inicial se muestra por separado.",
            ),
          false,
        ),
      ),
    );
  else
    table(
      card,
      [
        ui(() => tr("Fecha y hora local"), false),
        ui(() => tr("Tipo"), false),
        ui(() => tr("Importe"), false),
        ui(() => tr("Motivo"), false),
      ],
      cash.movimientos.map((x) => [
        ui(() => date(x.registrado_en), false),
        ui(() => label(x.tipo), false),
        ui(() => money.format(x.importe), false),
        ui(() => x.motivo, true),
      ]),
    );
  card.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Saldo esperado = fondo inicial más ingresos y ventas, menos retiros y reintegros. Diferencia = contado menos esperado.",
          ),
        false,
      ),
      "secundario",
    ),
  );
  box.append(card);
  focusTitle("titulo-turno");
}
async function loadCashHistory(page) {
  const r = await api(`/cajas?pagina=${page}&limite=10`);
  ops.cashPage = page;
  view("caja-web");
  const box = $("caja-web");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a caja"), false),
      loadCash,
    ),
  );
  heading(
    box,
    ui(() => tr("Turnos anteriores"), false),
    "titulo-turnos",
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  if (!r.cajas.length)
    card.append(
      el(
        "p",
        ui(() => tr("No hay turnos registrados."), false),
      ),
    );
  else
    table(
      card,
      [
        ui(() => tr("Apertura"), false),
        ui(() => tr("Estado"), false),
        ui(() => tr("Fondo inicial"), false),
        ui(() => tr("Acción"), false),
      ],
      r.cajas.map((x) => [
        ui(() => date(x.abierto_en), false),
        ui(() => (x.cerrado_en ? tr("Cerrado") : tr("Abierto")), false),
        ui(() => money.format(x.fondo_inicial), false),
        button(
          ui(() => tr("Consultar turno"), false),
          () => showCash(x.referencia),
        ),
      ]),
    );
  box.append(card);
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadCashHistory);
  box.append(nav);
  focusTitle("titulo-turnos");
}
function openCashForm() {
  view("caja-web");
  const box = $("caja-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Abrir turno de caja"), false),
    "titulo-apertura",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Contá el efectivo disponible al iniciar el turno. Se registrará como fondo inicial.",
          ),
        false,
      ),
    ),
  );
  const form = el(
    "form",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  const amount = field(
    form,
    ui(() => tr("Fondo inicial contado en pesos"), false),
    "apertura-fondo",
    "",
    {
      type: "number",
      min: 0,
      step: 1,
      required: true,
    },
  );
  const buttons = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  const submit = el(
    "button",
    ui(() => tr("Revisar apertura"), false),
    "principal",
  );
  submit.type = "submit";
  buttons.append(
    button(
      ui(() => tr("Cancelar"), false),
      loadCash,
    ),
    submit,
  );
  form.append(buttons);
  box.append(form);
  on(form, "submit", async () => {
    const value = integer(amount, 0),
      op = operation(`/cajas/${ref("caja-web")}/apertura`, {
        fondo_inicial: value,
      });
    reviewOperation(
      [
        [
          ui(() => tr("Fondo inicial"), false),
          ui(() => money.format(value), false),
        ],
      ],
      op,
      tr("Revisar apertura de caja"),
      tr("Confirmar apertura"),
      async () => {
        await loadCash();
        announce(
          ui(() => tr("Turno abierto. Ya podés cobrar una venta."), false),
        );
      },
    );
  });
  focusTitle("titulo-apertura");
}
async function closeCashForm(cash) {
  if (ops.draft?.lines.length)
    throw new Error(
      tr(
        "Tenés una venta en preparación. Cobrá o descartá ese carrito desde Ventas antes de cerrar el turno.",
      ),
    );
  const current = await api("/cajas/" + encodeURIComponent(cash.referencia));
  if (current.cerrado_en) {
    await loadCash();
    throw new Error(tr("Este turno ya está cerrado."));
  }
  view("caja-web");
  const box = $("caja-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Contar y cerrar turno"), false),
    "titulo-cierre",
  );
  box.append(cashSummary(current));
  const form = el(
    "form",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  const amount = field(
    form,
    ui(() => tr("Efectivo contado en pesos"), false),
    "cierre-contado",
    "",
    {
      type: "number",
      min: 0,
      step: 1,
      required: true,
    },
  );
  const preview = el(
    "p",
    ui(
      () => tr("Ingresá el efectivo contado para calcular la diferencia."),
      false,
    ),
  );
  form.append(preview);
  amount.addEventListener("input", () => {
    const value = Number(amount.value);
    setText(
      preview,
      ui(
        () =>
          amount.value && Number.isSafeInteger(value) && value >= 0
            ? tr("Diferencia estimada: ") +
              money.format(value - current.saldo_esperado)
            : tr("Ingresá un importe entero, igual o mayor a cero."),
        true,
      ),
    );
  });
  const buttons = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    ),
    submit = el(
      "button",
      ui(() => tr("Revisar cierre"), false),
      "principal",
    );
  submit.type = "submit";
  buttons.append(
    button(
      ui(() => tr("Cancelar"), false),
      loadCash,
    ),
    submit,
  );
  form.append(buttons);
  box.append(form);
  on(form, "submit", async () => {
    const counted = integer(amount, 0),
      op = operation(
        "/cajas/" + encodeURIComponent(current.referencia) + "/cierre",
        {
          contado: counted,
          saldo_esperado: current.saldo_esperado,
        },
      );
    reviewOperation(
      [
        [ui(() => tr("Turno"), false), ui(() => current.referencia, true)],
        [
          ui(() => tr("Esperado"), false),
          ui(() => money.format(current.saldo_esperado), false),
        ],
        [
          ui(() => tr("Contado"), false),
          ui(() => money.format(counted), false),
        ],
        [
          ui(() => tr("Diferencia"), false),
          ui(() => money.format(counted - current.saldo_esperado), false),
        ],
      ],
      op,
      tr("Revisar cierre de caja"),
      tr("Confirmar cierre"),
      async () => {
        ops.draft = null;
        await showCash(current.referencia);
        announce(ui(() => tr("Turno cerrado."), false));
      },
    );
  });
  focusTitle("titulo-cierre");
}
async function loadSales(page = 1) {
  staffOnly();
  const r = await api(`/ventas?pagina=${page}&limite=10`);
  ops.salesPage = page;
  view("ventas-web");
  const box = $("ventas-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Ventas cobradas"), false),
    "titulo-ventas",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Abrí una venta para consultar su detalle y guardar su comprobante.",
          ),
        false,
      ),
    ),
  );
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  actions.append(
    button(
      ui(
        () =>
          ops.draft
            ? tr("Continuar venta en preparación")
            : tr("Nueva venta en efectivo"),
        false,
      ),
      startSale,
      "principal",
    ),
    button(
      ui(() => tr("Actualizar ventas"), false),
      () => loadSales(page),
    ),
  );
  box.append(actions);
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  if (!r.pedidos.length)
    card.append(
      el(
        "p",
        ui(() => tr("No hay ventas cobradas en esta página."), false),
      ),
    );
  else
    table(
      card,
      [
        ui(() => tr("Venta"), false),
        ui(() => tr("Fecha"), false),
        ui(() => tr("Canal"), false),
        ui(() => tr("Total"), false),
        ui(() => tr("Entrega"), false),
        ui(() => tr("Acción"), false),
      ],
      r.pedidos.map((x) => [
        ui(() => x.id, false),
        ui(() => date(x.creado_en), false),
        ui(() => label(x.canal), false),
        ui(() => money.format(x.total), false),
        ui(() => label(x.estado_entrega), false),
        button(
          ui(() => tr("Abrir venta {0}", [x.id]), false),
          () => showSale(x.id),
        ),
      ]),
    );
  box.append(card);
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadSales);
  box.append(nav);
  focusTitle("titulo-ventas");
}
async function showSale(id) {
  const c = await api(`/operaciones/ventas/${id}`),
    p = c.pedido;
  view("ventas-web");
  const box = $("ventas-web");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a ventas"), false),
      () => loadSales(ops.salesPage),
    ),
  );
  heading(
    box,
    ui(() => tr("Venta {0}", [p.id]), false),
    "titulo-venta",
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  definition(card, [
    [ui(() => tr("Total"), false), ui(() => money.format(p.total), false)],
    [
      ui(() => tr("Medio de pago"), false),
      ui(() => label(p.medio_pago), false),
    ],
    [ui(() => tr("Pago"), false), ui(() => label(p.estado_pago), false)],
    [ui(() => tr("Entrega"), false), ui(() => label(p.estado_entrega), false)],
    [
      ui(() => tr("Fecha y hora local"), false),
      ui(() => date(p.creado_en), false),
    ],
    [
      ui(() => tr("Registrada por"), false),
      ui(() => p.registrado_por || tr("Sin dato individual"), false),
    ],
    [
      ui(() => tr("Cliente"), false),
      ui(
        () =>
          p.cliente_id
            ? tr("Cliente ID ") + p.cliente_id
            : tr("Consumidor sin identificar"),
        false,
      ),
    ],
  ]);
  if (p.efectivo)
    definition(card, [
      [
        ui(() => tr("Efectivo recibido"), false),
        ui(() => money.format(p.efectivo.recibido), false),
      ],
      [
        ui(() => tr("Vuelto"), false),
        ui(() => money.format(p.efectivo.vuelto), false),
      ],
    ]);
  card.append(
    el(
      "p",
      ui(() => tr("Referencia: ") + p.referencia, true),
      "referencia",
    ),
  );
  box.append(card);
  const products = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  table(
    products,
    [
      ui(() => tr("Producto"), false),
      ui(() => tr("Cantidad"), false),
      ui(() => tr("Precio unitario"), false),
      ui(() => tr("Subtotal"), false),
    ],
    p.productos.map((x) => [
      ui(() => x.nombre, true),
      ui(() => x.cantidad, false),
      ui(() => money.format(x.precio_unitario), false),
      ui(() => money.format(x.precio_unitario * x.cantidad), false),
    ]),
  );
  box.append(products);
  const returns = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  returns.append(
    el(
      "h2",
      ui(() => tr("Estado comercial"), false),
    ),
  );
  definition(returns, [
    [
      ui(() => tr("Estado"), false),
      ui(() => label(p.devoluciones.estado_comercial), false),
    ],
    [
      ui(() => tr("Devoluciones"), false),
      ui(() => money.format(p.devoluciones.importe_devoluciones), false),
    ],
    [
      ui(() => tr("Reintegrado"), false),
      ui(() => money.format(p.devoluciones.importe_reintegrado), false),
    ],
    [
      ui(() => tr("Pendiente de reintegrar"), false),
      ui(() => money.format(p.devoluciones.importe_por_reintegrar), false),
    ],
  ]);
  box.append(returns);
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  if (c.acciones.includes("comprobante"))
    actions.append(
      button(
        ui(() => tr("Guardar comprobante"), false),
        () => downloadTicket(id),
        "principal",
      ),
    );
  actions.append(
    button(
      ui(() => tr("Responsables de la venta"), false),
      () => saleHistory(id, 1),
    ),
  );
  box.append(actions);
  addReturnActions(box, c);
  addServiceActions(box, c);
  const extra = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  extra.id = "historial-venta";
  extra.hidden = true;
  box.append(extra);
  focusTitle("titulo-venta");
}
async function downloadTicket(id) {
  const html = await api(
    `/pedidos-venta/${id}/ticket?idioma=${getLanguage()}`,
    "GET",
    undefined,
    "text",
  );
  const url = URL.createObjectURL(
      new Blob([html], {
        type: "text/html;charset=utf-8",
      }),
    ),
    link = el("a");
  link.href = url;
  link.download = `${getLanguage() === "en" ? "sale" : "venta"}-${id}.html`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  announce(
    ui(
      () =>
        tr(
          "Comprobante preparado para descargar. Abrí el archivo HTML para imprimirlo o guardarlo como PDF con Ctrl+P.",
        ),
      false,
    ),
  );
}
async function saleHistory(id, page) {
  const r = await api(
      `/auditoria/comercial/venta/${id}?pagina=${page}&limite=10`,
    ),
    box = $("historial-venta");
  box.hidden = false;
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Responsables de la venta"), false),
    ),
  );
  if (!r.movimientos.length)
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "No hay eventos registrados desde la incorporación del historial.",
            ),
          false,
        ),
      ),
    );
  for (const m of r.movimientos) {
    const article = el(
      "article",
      ui(() => undefined, false),
      "evento",
    );
    article.append(
      el(
        "h3",
        ui(() => label(m.accion) + " · " + m.actor, true),
      ),
      el(
        "p",
        ui(() => date(m.registrado_en), false),
        "secundario",
      ),
    );
    renderDetails(article, m.detalle);
    box.append(article);
  }
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, (p) => saleHistory(id, p));
  box.append(nav);
}
async function startSale() {
  staffOnly();
  const c = await api("/operaciones/caja-actual");
  if (!c.caja) {
    await loadCash();
    announce(
      ui(
        () =>
          tr("Primero abrí un turno de caja para cobrar ventas en efectivo."),
        false,
      ),
    );
    return;
  }
  if (ops.draft && ops.draft.cash !== c.caja.referencia) {
    ops.draft = null;
    announce(
      ui(
        () =>
          tr("El turno cambió. Prepará un nuevo carrito para la caja actual."),
        false,
      ),
    );
  }
  if (!ops.draft)
    ops.draft = {
      cash: c.caja.referencia,
      lines: [],
      received: "",
      search: "",
      page: 1,
    };
  view("cobro-web");
  const box = $("cobro-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Venta en efectivo"), false),
    "titulo-cobro",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Buscá productos, agregalos al carrito e ingresá el efectivo recibido. El cobro se registra al confirmar el resumen.",
          ),
        false,
      ),
    ),
    el(
      "p",
      ui(() => tr("Turno: ") + ops.draft.cash, false),
      "referencia",
    ),
  );
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  actions.append(
    button(
      ui(() => tr("Volver a ventas"), false),
      () => loadSales(ops.salesPage),
    ),
    button(
      ui(() => tr("Descartar carrito"), false),
      discardCart,
    ),
  );
  box.append(actions);
  const columns = el(
      "div",
      ui(() => undefined, false),
      "cobro-dos-columnas cabecera-turno",
    ),
    searchCard = el(
      "div",
      ui(() => undefined, false),
      "tarjeta",
    );
  searchCard.append(
    el(
      "h2",
      ui(() => tr("Agregar productos"), false),
    ),
  );
  const search = el("form");
  const input = field(
    search,
    ui(() => tr("Nombre o marca"), false),
    "cobro-buscar",
    ops.draft.search,
    {
      type: "search",
      maxLength: 150,
    },
  );
  const submit = el(
    "button",
    ui(() => tr("Buscar productos"), false),
  );
  submit.type = "submit";
  search.append(submit);
  searchCard.append(search);
  const results = el("div");
  results.id = "cobro-resultados";
  searchCard.append(results);
  const cart = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  cart.id = "carrito";
  columns.append(searchCard, cart);
  box.append(columns);
  on(search, "submit", async () => {
    ops.draft.search = input.value.trim();
    await saleProducts(1);
  });
  renderCart();
  await saleProducts(ops.draft.page);
  focusTitle("titulo-cobro");
}
async function saleProducts(page) {
  const params = new URLSearchParams({
    pagina: page,
    limite: 10,
  });
  if (ops.draft.search) params.set("texto", ops.draft.search);
  const r = await api("/productos?" + params);
  ops.draft.page = page;
  const box = $("cobro-resultados");
  box.replaceChildren();
  if (!r.productos.length)
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "No se encontraron productos. Probá otro nombre o buscá con el campo vacío.",
            ),
          false,
        ),
      ),
    );
  for (const p of r.productos) {
    const row = el(
        "div",
        ui(() => undefined, false),
        "seleccion-producto",
      ),
      name = el("div");
    name.append(
      el(
        "strong",
        ui(() => p.nombre, true),
      ),
      el(
        "small",
        ui(
          () =>
            tr("{0} · {1} · Stock físico: {2}", [
              p.marca || tr("Sin marca"),
              money.format(p.precio),
              p.stock,
            ]),
          true,
        ),
      ),
    );
    const add = button(
      ui(() => tr("Agregar"), false),
      () => addProduct(p.id),
    );
    add.disabled = p.stock <= 0;
    row.append(name, add);
    box.append(row);
  }
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, saleProducts);
  box.append(nav);
}
async function addProduct(id) {
  const c = await api(`/operaciones/productos/${id}`),
    p = c.producto,
    existing = ops.draft.lines.find((x) => x.id === id),
    quantity = (existing?.cantidad || 0) + 1;
  if (quantity > c.disponible)
    throw new Error(
      tr("No hay suficientes unidades disponibles de ") +
        p.nombre +
        tr(". Las reservas no se pueden vender."),
    );
  if (existing) {
    existing.cantidad = quantity;
    existing.precio = p.precio;
    existing.disponible = c.disponible;
  } else {
    if (ops.draft.lines.length >= 100)
      throw new Error(tr("El carrito admite hasta 100 productos distintos."));
    ops.draft.lines.push({
      id: p.id,
      nombre: p.nombre,
      precio: p.precio,
      cantidad: 1,
      disponible: c.disponible,
    });
  }
  renderCart();
  announce(ui(() => p.nombre + tr(" agregado al carrito."), true));
}
function renderCart() {
  const box = $("carrito");
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Carrito"), false),
    ),
  );
  const lines = ops.draft.lines;
  for (const line of lines) {
    const row = el(
      "div",
      ui(() => undefined, false),
      "seleccion-producto",
    );
    const name = el("div");
    name.append(
      el(
        "strong",
        ui(() => line.nombre, true),
      ),
      el(
        "small",
        ui(
          () =>
            tr("{0} por unidad · disponibles al consultar: {1}", [
              money.format(line.precio),
              line.disponible,
            ]),
          false,
        ),
      ),
    );
    const control = el(
        "div",
        ui(() => undefined, false),
        "linea-carrito",
      ),
      quantity = el("input");
    quantity.type = "number";
    quantity.min = 1;
    quantity.max = line.disponible;
    quantity.step = 1;
    quantity.value = line.cantidad;
    quantity.className = "cantidad-carrito";
    localizeAttribute(
      quantity,
      "aria-label",
      ui(() => tr("Cantidad de ") + line.nombre, true),
    );
    quantity.addEventListener("change", () => {
      const value = Number(quantity.value);
      if (
        !Number.isSafeInteger(value) ||
        value < 1 ||
        value > line.disponible
      ) {
        quantity.value = line.cantidad;
        announce(
          ui(
            () =>
              tr(
                "La cantidad debe ser entera, positiva y no superar las unidades disponibles consultadas.",
              ),
            false,
          ),
          true,
        );
        return;
      }
      line.cantidad = value;
      setText(
        $("carrito-total"),
        ui(() => tr("Total: ") + money.format(totals(ops.draft.lines)), false),
      );
      $("cobro-recibido").dispatchEvent(new Event("input"));
    });
    control.append(
      quantity,
      button(
        ui(() => tr("Quitar"), false),
        () => {
          ops.draft.lines = lines.filter((x) => x.id !== line.id);
          renderCart();
        },
      ),
    );
    row.append(name, control);
    box.append(row);
  }
  if (!lines.length)
    box.append(
      el(
        "p",
        ui(
          () => tr("El carrito está vacío. Agregá un producto desde la lista."),
          false,
        ),
      ),
    );
  const total = totals(lines),
    totalText = el(
      "p",
      ui(() => tr("Total: ") + money.format(total), false),
      "carrito-total",
    );
  totalText.id = "carrito-total";
  box.append(totalText);
  const form = el("form");
  const received = field(
    form,
    ui(() => tr("Efectivo recibido en pesos"), false),
    "cobro-recibido",
    ops.draft.received,
    {
      type: "number",
      min: 1,
      step: 1,
      required: true,
    },
  );
  const change = el("p");
  const update = () => {
    ops.draft.received = received.value;
    const n = Number(received.value),
      total = totals(ops.draft.lines);
    setText(
      change,
      ui(
        () =>
          !received.value
            ? tr("Ingresá el efectivo recibido.")
            : !Number.isSafeInteger(n) || n < total
              ? tr("El efectivo no cubre el total.")
              : tr("Vuelto: ") + money.format(n - total),
        true,
      ),
    );
  };
  received.addEventListener("input", update);
  update();
  form.append(change);
  const submit = el(
    "button",
    ui(() => tr("Revisar cobro"), false),
    "principal",
  );
  submit.type = "submit";
  submit.disabled = !lines.length;
  form.append(submit);
  box.append(form);
  on(form, "submit", async () => {
    ops.draft.received = received.value;
    await reviewSale();
  });
}
async function reviewSale() {
  if (!ops.draft.lines.length)
    throw new Error(tr("Agregá al menos un producto."));
  const current = await api("/operaciones/caja-actual");
  if (!current.caja || current.caja.referencia !== ops.draft.cash)
    throw new Error(
      tr(
        "La caja cambió o se cerró. Volvé a Caja y revisá el turno antes de cobrar.",
      ),
    );
  for (const line of ops.draft.lines) {
    const c = await api(`/operaciones/productos/${line.id}`);
    line.precio = c.producto.precio;
    line.disponible = c.disponible;
    if (line.cantidad > c.disponible) {
      renderCart();
      throw new Error(
        tr("Stock disponible insuficiente para ") +
          line.nombre +
          tr(". Revisá la cantidad."),
      );
    }
  }
  renderCart();
  const total = totals(ops.draft.lines),
    received = Number(ops.draft.received);
  if (!Number.isSafeInteger(received) || received < total)
    throw new Error(tr("El efectivo recibido no cubre el total actualizado."));
  const op = operation("/ventas-efectivo/" + ref("venta-web"), {
    caja: ops.draft.cash,
    recibido: received,
    total_esperado: total,
    productos: ops.draft.lines.map((x) => ({
      producto_id: x.id,
      cantidad: x.cantidad,
    })),
  });
  const rows = ops.draft.lines.map((x) => [
    `${x.cantidad} × ${x.nombre}`,
    money.format(x.precio * x.cantidad),
  ]);
  reviewOperation(
    [
      ...rows,
      [
        ui(() => tr("Total a cobrar"), false),
        ui(() => money.format(total), false),
      ],
      [
        ui(() => tr("Efectivo recibido"), false),
        ui(() => money.format(received), false),
      ],
      [
        ui(() => tr("Vuelto"), false),
        ui(() => money.format(received - total), false),
      ],
      [ui(() => tr("Turno"), false), ui(() => ops.draft.cash, false)],
    ],
    op,
    tr("Revisar venta en efectivo"),
    tr("Confirmar cobro"),
    async (result) => {
      ops.draft = null;
      await showSale(result.pedido_venta_id);
      announce(
        ui(
          () =>
            tr("Venta {0} registrada. Total: {1}. Vuelto: {2}.", [
              result.pedido_venta_id,
              money.format(result.total),
              money.format(result.vuelto),
            ]),
          false,
        ),
      );
    },
  );
}
function discardCart() {
  if (!ops.draft?.lines.length) {
    ops.draft = null;
    return loadSales(ops.salesPage);
  }
  confirm(
    [
      [
        ui(() => tr("Productos del carrito"), false),
        ui(() => ops.draft.lines.length, false),
      ],
      [
        ui(() => tr("Resultado"), false),
        ui(
          () =>
            tr(
              "Se descarta sólo esta preparación; no se cobra ni se modifica stock.",
            ),
          false,
        ),
      ],
    ],
    async () => {
      ops.draft = null;
      $("confirmacion").close();
      pending = null;
      await loadSales(ops.salesPage);
      announce(ui(() => tr("Carrito descartado."), false));
    },
    tr("Descartar carrito"),
    tr("Descartar preparación"),
  );
}
