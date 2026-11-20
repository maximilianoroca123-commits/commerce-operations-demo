// Customer cart, simulated checkout and customer-owned requests.
"use strict";
const cli = {
  cart: [],
  section: "cart",
  ordersPage: 1,
  requestsPage: 1,
  requestState: "",
  requestOrder: null,
  mode: "retiro",
  address: "",
};
function resetCliente() {
  Object.assign(cli, {
    cart: [],
    section: "cart",
    ordersPage: 1,
    requestsPage: 1,
    requestState: "",
    requestOrder: null,
    mode: "retiro",
    address: "",
  });
}
function customerOnly() {
  if (state.user?.rol_efectivo !== "cliente")
    throw new Error(tr("Esta sección corresponde a una cuenta de cliente."));
}
function clientPanel(section, title, id) {
  customerOnly();
  cli.section = section;
  view("cliente-web");
  const box = $("cliente-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => title, false),
    id,
  );
  return box;
}
on($("nav-carrito"), "click", () => {
  announce(ui(() => "", false));
  showOnlineCart();
});
on($("nav-mis-pedidos"), "click", async () => {
  announce(ui(() => "", false));
  await loadMyOrders(1);
});
on($("nav-mis-solicitudes"), "click", async () => {
  announce(ui(() => "", false));
  cli.requestOrder = null;
  await loadMyRequests(1);
});
on($("nav-perfil"), "click", async () => {
  announce(ui(() => "", false));
  await showMyProfile();
});
function onlinePayload(lines, mode, address) {
  if (!lines.length)
    throw new Error(tr("Agregá al menos un producto al carrito."));
  if (!["retiro", "envio"].includes(mode))
    throw new Error(tr("Elegí retiro en local o envío."));
  const productos = lines.map((x) => {
    if (
      !Number.isSafeInteger(x.id) ||
      x.id < 1 ||
      !Number.isSafeInteger(x.cantidad) ||
      x.cantidad < 1
    )
      throw new Error(tr("Revisá los productos y cantidades."));
    return {
      producto_id: x.id,
      cantidad: x.cantidad,
    };
  });
  if (new Set(productos.map((x) => x.producto_id)).size !== productos.length)
    throw new Error(tr("No repitas productos en el carrito."));
  const data = {
    productos,
    canal: "online",
    modalidad: mode,
  };
  if (mode === "envio") {
    const text = address.trim();
    if (text.length < 5 || text.length > 500)
      throw new Error(
        tr("Ingresá la dirección completa del envío (5 a 500 caracteres)."),
      );
    data.direccion_entrega = text;
  }
  return data;
}
async function addOnlineProduct(id) {
  customerOnly();
  const p = await api(`/productos/${id}`),
    available = await api(`/productos/${id}/disponibilidad`),
    line = cli.cart.find((x) => x.id === id);
  const quantity = (line?.cantidad || 0) + 1;
  if (quantity > available.disponible)
    throw new Error(
      tr("No hay suficientes unidades disponibles de ") + p.nombre + ".",
    );
  if (line) {
    line.cantidad = quantity;
    line.precio = p.precio;
    line.disponible = available.disponible;
  } else {
    if (cli.cart.length >= 100)
      throw new Error(tr("El carrito admite hasta 100 productos distintos."));
    cli.cart.push({
      id,
      nombre: p.nombre,
      precio: p.precio,
      cantidad: 1,
      disponible: available.disponible,
    });
  }
  announce(
    ui(
      () =>
        p.nombre + tr(" agregado. Podés seguir comprando o abrir Mi carrito."),
      true,
    ),
  );
  if (!$("cliente-web").hidden && cli.section === "cart") showOnlineCart();
}
function showOnlineCart() {
  const box = clientPanel("cart", tr("Mi carrito"), "titulo-carrito-online");
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Prepará tu compra. El pedido se crea al confirmar y el pago de prueba se realiza después.",
          ),
        false,
      ),
    ),
  );
  box.append(
    button(
      ui(() => tr("Seguir comprando"), false),
      () => loadList(state.page),
    ),
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  for (const line of cli.cart) {
    const row = el(
        "div",
        ui(() => undefined, false),
        "seleccion-producto",
      ),
      info = el("div");
    info.append(
      el(
        "strong",
        ui(() => line.nombre, true),
      ),
      el(
        "small",
        ui(() => money.format(line.precio) + tr(" por unidad"), false),
      ),
    );
    const controls = el(
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
                "Ingresá una cantidad positiva que no supere la disponibilidad consultada.",
              ),
            false,
          ),
          true,
        );
        return;
      }
      line.cantidad = value;
      setText(
        $("total-online"),
        ui(
          () => tr("Total consultado: ") + money.format(totals(cli.cart)),
          false,
        ),
      );
    });
    controls.append(
      quantity,
      button(
        ui(() => tr("Quitar"), false),
        () => {
          cli.cart = cli.cart.filter((x) => x.id !== line.id);
          showOnlineCart();
        },
      ),
    );
    row.append(info, controls);
    card.append(row);
  }
  if (!cli.cart.length)
    card.append(
      el(
        "p",
        ui(() => tr("Todavía no agregaste productos."), false),
      ),
    );
  const total = el(
    "p",
    ui(() => tr("Total consultado: ") + money.format(totals(cli.cart)), false),
    "carrito-total",
  );
  total.id = "total-online";
  card.append(total);
  box.append(card);
  if (cli.cart.length) {
    const form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    );
    const mode = filterSelect(
      form,
      tr("Cómo recibir la compra"),
      "online-modalidad",
      [
        ["retiro", tr("Retiro en local")],
        ["envio", tr("Envío a domicilio")],
      ],
      cli.mode,
      (value) => {
        cli.mode = value;
        addressWrap.hidden = value !== "envio";
        address.required = value === "envio";
      },
    );
    const addressWrap = el("div");
    const address = field(
      addressWrap,
      ui(() => tr("Dirección completa del envío"), false),
      "online-direccion",
      cli.address,
      {
        maxLength: 500,
      },
    );
    addressWrap.hidden = cli.mode !== "envio";
    address.required = cli.mode === "envio";
    address.addEventListener("input", () => {
      cli.address = address.value;
    });
    form.append(addressWrap);
    form.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "Al crear el pedido se reserva mercadería. El servidor calcula el importe definitivo, que verás antes de simular el pago.",
            ),
          false,
        ),
        "secundario",
      ),
    );
    const submit = el(
      "button",
      ui(() => tr("Revisar pedido"), false),
      "principal",
    );
    submit.type = "submit";
    form.append(
      submit,
      button(
        ui(() => tr("Vaciar carrito"), false),
        () => {
          confirm(
            [
              [
                ui(() => tr("Resultado"), false),
                ui(
                  () =>
                    tr(
                      "Se descarta esta preparación; no se crea un pedido ni se cobra.",
                    ),
                  false,
                ),
              ],
            ],
            async () => {
              cli.cart = [];
              $("confirmacion").close();
              pending = null;
              showOnlineCart();
            },
            tr("Vaciar carrito"),
            tr("Vaciar carrito"),
          );
        },
      ),
    );
    box.append(form);
    on(form, "submit", async () => {
      cli.mode = mode.value;
      cli.address = address.value;
      await reviewOnlineOrder();
    });
  }
  focusTitle("titulo-carrito-online");
}
async function reviewOnlineOrder() {
  customerOnly();
  for (const line of cli.cart) {
    const p = await api(`/productos/${line.id}`),
      d = await api(`/productos/${line.id}/disponibilidad`);
    line.precio = p.precio;
    line.disponible = d.disponible;
    if (line.cantidad > d.disponible) {
      showOnlineCart();
      throw new Error(
        tr("La disponibilidad cambió para ") +
          line.nombre +
          tr(". Revisá la cantidad."),
      );
    }
  }
  const data = onlinePayload(cli.cart, cli.mode, cli.address),
    sum = totals(cli.cart);
  showOnlineCart();
  const op = operation("/cobros-demo/" + ref("compra-web"), data),
    rows = cli.cart.map((x) => [
      `${x.cantidad} × ${x.nombre}`,
      money.format(x.precio * x.cantidad),
    ]);
  rows.push(
    [tr("Total consultado"), money.format(sum)],
    [tr("Entrega"), label(cli.mode)],
  );
  if (data.direccion_entrega)
    rows.push([tr("Dirección"), data.direccion_entrega]);
  rows.push([
    tr("Pago en este paso"),
    tr("Ninguno: se crea un pedido con reserva"),
  ]);
  reviewOperation(
    rows,
    op,
    tr("Revisar compra online"),
    tr("Crear pedido"),
    async (result) => {
      cli.cart = [];
      await showMyOrder(result.pedido_venta_id);
      announce(
        ui(
          () =>
            tr(
              "Pedido creado. Revisá el importe definitivo y elegí Simular pago para continuar.",
            ),
          false,
        ),
      );
    },
  );
}
async function loadMyOrders(page = 1) {
  customerOnly();
  const r = await api(`/pedidos-venta?pagina=${page}&limite=10`);
  if (page > 1 && page > Math.max(1, Math.ceil(r.total / 10)))
    return loadMyOrders(Math.max(1, Math.ceil(r.total / 10)));
  cli.ordersPage = page;
  const box = clientPanel("orders", tr("Mis pedidos"), "titulo-mis-pedidos");
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Seleccioná un pedido para pagar la simulación, seguir su entrega o consultar sus solicitudes.",
          ),
        false,
      ),
    ),
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  if (!r.pedidos.length)
    card.append(
      el(
        "p",
        ui(
          () => tr("Todavía no tenés pedidos. Podés empezar desde Comprar."),
          false,
        ),
      ),
    );
  else
    table(
      card,
      [
        ui(() => tr("Pedido"), false),
        ui(() => tr("Fecha"), false),
        ui(() => tr("Total"), false),
        ui(() => tr("Pago"), false),
        ui(() => tr("Entrega"), false),
        ui(() => tr("Acción"), false),
      ],
      r.pedidos.map((p) => [
        ui(() => p.id, false),
        ui(() => date(p.creado_en), false),
        ui(() => money.format(p.total), false),
        ui(() => label(p.estado_pago), false),
        ui(() => label(p.estado_entrega), false),
        button(
          ui(() => tr("Abrir pedido ") + p.id, false),
          () => showMyOrder(p.id),
        ),
      ]),
    );
  box.append(
    button(
      ui(() => tr("Actualizar pedidos"), false),
      () => loadMyOrders(cli.ordersPage),
    ),
    card,
  );
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadMyOrders);
  box.append(nav);
  focusTitle("titulo-mis-pedidos");
}
async function showMyOrder(id) {
  customerOnly();
  const p = await api(`/pedidos-venta/${id}`),
    pendingRequests = await api(
      `/solicitudes-clientes?pedido_id=${id}&estado=pendiente_revision&limite=50`,
    );
  const box = clientPanel("orders", tr("Mi pedido ") + id, "titulo-mi-pedido");
  box.append(
    button(
      ui(() => tr("Volver a mis pedidos"), false),
      () => loadMyOrders(cli.ordersPage),
    ),
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  definition(card, [
    [
      ui(() => tr("Importe definitivo"), false),
      ui(() => money.format(p.total), false),
    ],
    [ui(() => tr("Pago"), false), ui(() => label(p.estado_pago), false)],
    [ui(() => tr("Entrega"), false), ui(() => label(p.estado_entrega), false)],
    [ui(() => tr("Modalidad"), false), ui(() => label(p.modalidad), false)],
    [ui(() => tr("Creado"), false), ui(() => date(p.creado_en), false)],
  ]);
  if (p.direccion_entrega)
    definition(card, [
      [
        ui(() => tr("Dirección de envío"), false),
        ui(() => p.direccion_entrega, true),
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
      ui(() => money.format(x.cantidad * x.precio_unitario), false),
    ]),
  );
  box.append(products);
  const summary = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  summary.append(
    el(
      "h2",
      ui(() => tr("Devoluciones y reintegros"), false),
    ),
  );
  definition(summary, [
    [
      ui(() => tr("Estado comercial"), false),
      ui(() => label(p.devoluciones.estado_comercial), false),
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
  box.append(summary);
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  if (p.acciones_cliente.includes("pagar"))
    actions.append(
      button(
        ui(() => tr("Simular pago de este pedido"), false),
        () => paymentForm(id),
        "principal",
      ),
    );
  if (p.acciones_cliente.includes("comprobante"))
    actions.append(
      button(
        ui(() => tr("Guardar comprobante"), false),
        () => downloadTicket(id),
      ),
    );
  for (const [type, text] of [
    ["devolucion", tr("Solicitar devolución")],
    ["cancelacion", tr("Solicitar cancelación")],
  ])
    if (
      p.acciones_cliente.includes(type) &&
      !pendingRequests.solicitudes.some((s) => s.tipo === type)
    )
      actions.append(
        button(
          ui(() => text, false),
          () => customerRequestForm(id, type),
        ),
      );
  actions.append(
    button(
      ui(() => tr("Solicitudes y respuestas de este pedido"), false),
      () => myOrderRequests(id),
    ),
    button(
      ui(() => tr("Actualizar pedido"), false),
      () => showMyOrder(id),
    ),
  );
  box.append(actions);
  if (pendingRequests.total)
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "Hay solicitudes pendientes. Consultá sus respuestas antes de registrar otra gestión.",
            ),
          false,
        ),
        "aviso",
      ),
    );
  if (p.acciones_cliente.includes("pagar"))
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "El pedido tiene una reserva temporal. Si vence o el pago se rechaza, puede liberarse la mercadería. No se cobra dinero real.",
            ),
          false,
        ),
        "aviso",
      ),
    );
  const history = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  history.append(
    el(
      "h2",
      ui(() => tr("Seguimiento de entrega"), false),
    ),
  );
  if (p.historial_entrega.length)
    table(
      history,
      [
        ui(() => tr("Fecha y hora local"), false),
        ui(() => tr("Estado"), false),
      ],
      p.historial_entrega.map((x) => [
        ui(() => date(x.registrado_en), false),
        ui(() => label(x.estado), false),
      ]),
    );
  box.append(history);
  focusTitle("titulo-mi-pedido");
}
async function paymentForm(id) {
  customerOnly();
  const p = await api(`/pedidos-venta/${id}`);
  if (!p.acciones_cliente.includes("pagar")) {
    await showMyOrder(id);
    throw new Error(tr("Este pedido ya no permite simular un pago pendiente."));
  }
  const box = clientPanel(
    "orders",
    tr("Pago simulado · Pedido ") + id,
    "titulo-pago-cliente",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Esto es una prueba: no ingreses datos de tarjeta y no se mueve dinero real.",
          ),
        false,
      ),
      "aviso",
    ),
  );
  const form = el(
    "form",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  definition(form, [
    [
      ui(() => tr("Importe del pedido"), false),
      ui(() => money.format(p.total), false),
    ],
    [ui(() => tr("Entrega"), false), ui(() => label(p.modalidad), false)],
  ]);
  const select = filterSelect(
    form,
    tr("Resultado de la simulación"),
    "cliente-pago-resultado",
    [
      ["", tr("Elegir resultado")],
      ["aprobado", tr("Aprobado")],
      ["rechazado", tr("Rechazado")],
    ],
    "",
    () => {},
  );
  select.required = true;
  const submit = el(
    "button",
    ui(() => tr("Revisar pago simulado"), false),
    "principal",
  );
  submit.type = "submit";
  form.append(
    button(
      ui(() => tr("Cancelar"), false),
      () => showMyOrder(id),
    ),
    submit,
  );
  box.append(form);
  on(form, "submit", async () => {
    if (!["aprobado", "rechazado"].includes(select.value))
      throw new Error(tr("Elegí un resultado para el pago simulado."));
    const chosen = select.value,
      op = operation(`/cobros-demo/${encodeURIComponent(p.referencia)}/pago`, {
        estado: chosen,
      });
    reviewOperation(
      [
        [ui(() => tr("Pedido"), false), ui(() => id, false)],
        [
          ui(() => tr("Importe"), false),
          ui(() => money.format(p.total), false),
        ],
        [
          ui(() => tr("Resultado simulado"), false),
          ui(() => label(chosen), false),
        ],
        [
          ui(() => tr("Dinero real"), false),
          ui(() => tr("No se realiza ningún cobro real"), false),
        ],
      ],
      op,
      tr("Revisar pago de prueba"),
      tr("Confirmar simulación"),
      async () => {
        await showMyOrder(id);
        announce(
          ui(
            () =>
              tr(
                "Resultado del pago simulado registrado. Consultá el estado actualizado del pedido.",
              ),
            false,
          ),
        );
      },
    );
  });
  focusTitle("titulo-pago-cliente");
}
async function customerRequestForm(id, type) {
  customerOnly();
  const p = await api(`/pedidos-venta/${id}`);
  if (
    !["devolucion", "cancelacion"].includes(type) ||
    !p.acciones_cliente.includes(type)
  ) {
    await showMyOrder(id);
    throw new Error(
      tr("Esta solicitud no está disponible para el estado del pedido."),
    );
  }
  const existing = await api(
    `/solicitudes-clientes?pedido_id=${id}&estado=pendiente_revision&limite=50`,
  );
  if (existing.solicitudes.some((s) => s.tipo === type)) {
    await myOrderRequests(id);
    throw new Error(tr("Ya hay una solicitud pendiente de este tipo."));
  }
  const box = clientPanel(
    "requests",
    label(type) + tr(" · Pedido ") + id,
    "titulo-solicitud-cliente",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Esta solicitud avisa al negocio. Por sí sola no recibe mercadería, no cambia el stock y no devuelve dinero.",
          ),
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
    reason = field(
      form,
      ui(() => tr("Motivo de tu solicitud"), false),
      "cliente-solicitud-motivo",
      "",
      {
        required: true,
        maxLength: 500,
      },
    );
  const submit = el(
    "button",
    ui(() => tr("Revisar solicitud"), false),
    "principal",
  );
  submit.type = "submit";
  form.append(
    button(
      ui(() => tr("Cancelar"), false),
      () => showMyOrder(id),
    ),
    submit,
  );
  box.append(form);
  on(form, "submit", async () => {
    const text = reason.value.trim();
    if (!text) throw new Error(tr("Explicá el motivo de la solicitud."));
    const op = operation(
      `/pedidos-venta/${id}/solicitudes/${ref("solicitud-web")}`,
      {
        tipo: type,
        motivo: text,
      },
    );
    reviewOperation(
      [
        [ui(() => tr("Pedido"), false), ui(() => id, false)],
        [ui(() => tr("Solicitud"), false), ui(() => label(type), false)],
        [ui(() => tr("Motivo"), false), ui(() => text, true)],
        [
          ui(() => tr("Stock y dinero"), false),
          ui(() => tr("Sin cambios en este paso"), false),
        ],
      ],
      op,
      tr("Revisar solicitud al negocio"),
      tr("Enviar solicitud"),
      async () => {
        await myOrderRequests(id);
        announce(
          ui(
            () => tr("Solicitud registrada. El negocio debe revisarla."),
            false,
          ),
        );
      },
    );
  });
  focusTitle("titulo-solicitud-cliente");
}
async function myOrderRequests(id) {
  cli.requestOrder = id;
  cli.requestState = "";
  await loadMyRequests(1);
}
async function loadMyRequests(page = 1) {
  customerOnly();
  const params = new URLSearchParams({
    pagina: page,
    limite: 10,
  });
  if (cli.requestOrder) params.set("pedido_id", cli.requestOrder);
  if (cli.requestState) params.set("estado", cli.requestState);
  const r = await api("/solicitudes-clientes?" + params);
  if (page > 1 && page > Math.max(1, Math.ceil(r.total / 10)))
    return loadMyRequests(Math.max(1, Math.ceil(r.total / 10)));
  cli.requestsPage = page;
  const box = clientPanel(
    "requests",
    cli.requestOrder
      ? tr("Mis solicitudes · Pedido ") + cli.requestOrder
      : tr("Mis solicitudes y respuestas"),
    "titulo-mis-solicitudes",
  );
  const filters = el(
    "div",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  filterSelect(
    filters,
    tr("Estado"),
    "cliente-filtro-solicitudes",
    [
      ["", tr("Todas")],
      ["pendiente_revision", tr("Pendientes")],
      ["atendida", tr("Atendidas")],
      ["rechazada", tr("Rechazadas")],
    ],
    cli.requestState,
    async (value) => {
      cli.requestState = value;
      await loadMyRequests(1);
    },
  );
  filters.append(
    button(
      ui(() => tr("Actualizar respuestas"), false),
      () => loadMyRequests(cli.requestsPage),
    ),
  );
  if (cli.requestOrder)
    filters.append(
      button(
        ui(() => tr("Volver al pedido"), false),
        () => showMyOrder(cli.requestOrder),
      ),
      button(
        ui(() => tr("Ver todas mis solicitudes"), false),
        async () => {
          cli.requestOrder = null;
          await loadMyRequests(1);
        },
      ),
    );
  box.append(filters);
  if (!r.solicitudes.length)
    box.append(
      el(
        "p",
        ui(() => tr("No hay solicitudes con este filtro."), false),
        "tarjeta",
      ),
    );
  for (const s of r.solicitudes) {
    const card = el(
      "article",
      ui(() => undefined, false),
      "tarjeta",
    );
    card.append(
      el(
        "h2",
        ui(() => label(s.tipo) + tr(" · Pedido ") + s.pedido_id, false),
      ),
    );
    definition(card, [
      [ui(() => tr("Estado"), false), ui(() => label(s.estado), false)],
      [ui(() => tr("Tu motivo"), false), ui(() => s.motivo, true)],
      [
        ui(() => tr("Registrada"), false),
        ui(() => date(s.registrado_en), false),
      ],
    ]);
    if (s.resolucion) {
      card.append(
        el(
          "h3",
          ui(() => tr("Respuesta del negocio"), false),
        ),
      );
      definition(card, [
        [
          ui(() => tr("Resultado"), false),
          ui(() => label(s.resolucion.estado), false),
        ],
        [
          ui(() => tr("Explicación"), false),
          ui(() => s.resolucion.motivo, true),
        ],
      ]);
    } else
      card.append(
        el(
          "p",
          ui(
            () => tr("Todavía no hay una respuesta final del negocio."),
            false,
          ),
        ),
      );
    card.append(
      button(
        ui(() => tr("Ver pedido ") + s.pedido_id, false),
        () => showMyOrder(s.pedido_id),
      ),
    );
    box.append(card);
  }
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadMyRequests);
  box.append(nav);
  focusTitle("titulo-mis-solicitudes");
}
async function showMyProfile() {
  customerOnly();
  const r = await api("/mi-perfil");
  const box = clientPanel("profile", tr("Mi perfil"), "titulo-mi-perfil"),
    card = el(
      "div",
      ui(() => undefined, false),
      "tarjeta",
    );
  if (r.cliente)
    definition(card, [
      [ui(() => tr("Usuario"), false), ui(() => r.usuario, true)],
      [ui(() => tr("Nombre"), false), ui(() => r.cliente.nombre, true)],
      [ui(() => tr("Apellido"), false), ui(() => r.cliente.apellido, false)],
      [ui(() => tr("Correo"), false), ui(() => r.cliente.correo, true)],
      [
        ui(() => tr("Teléfono"), false),
        ui(() => r.cliente.telefono || tr("Sin teléfono registrado"), true),
      ],
    ]);
  else
    card.append(
      el(
        "p",
        ui(() => r.mensaje || tr("No hay una ficha personal asociada."), false),
      ),
    );
  if (!state.user.cuenta_compatibilidad)
    card.append(
      button(
        ui(() => tr("Cambiar mi contraseña"), false),
        () => changePassword(false),
      ),
    );
  box.append(card);
  focusTitle("titulo-mi-perfil");
}
