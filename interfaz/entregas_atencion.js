// Delivery transitions and linked customer service workflows.
"use strict";
const service = {
  deliveryPage: 1,
  onlyPending: true,
  requestPage: 1,
  requestState: "pendiente_revision",
  requestOrder: null,
};
function resetAtencion() {
  Object.assign(service, {
    deliveryPage: 1,
    onlyPending: true,
    requestPage: 1,
    requestState: "pendiente_revision",
    requestOrder: null,
  });
}
Object.assign(names, {
  enviado: "Enviado",
  retiro: "Retiro en local",
  pendiente_revision: "Pendiente de revisión",
  atendida: "Atendida",
  rechazada: "Rechazada",
  cancelacion: "Cancelación",
  revision: "En revisión",
  pendiente_pago: "Pendiente de pago",
});
const deliverySteps = {
  preparando: "Iniciar preparación",
  listo: "Marcar listo para entregar",
  enviado: "Confirmar despacho",
  entregado: "Confirmar entrega al cliente",
};
function requestBase(s) {
  return `/solicitudes-clientes/${s.id}/${encodeURIComponent(s.reference)}`;
}
on($("nav-entregas"), "click", async () => {
  announce(ui(() => "", false));
  await loadDeliveries(1);
});
on($("nav-atencion"), "click", async () => {
  announce(ui(() => "", false));
  service.requestOrder = null;
  await loadRequests(1);
});
function filterSelect(parent, title, id, options, value, changed) {
  const l = el(
    "label",
    ui(() => title, false),
  );
  l.htmlFor = id;
  const select = el("select");
  select.id = id;
  for (const [key, text] of options) {
    const option = el(
      "option",
      ui(() => text, false),
    );
    option.value = key;
    select.append(option);
  }
  select.value = value;
  parent.append(l, select);
  on(select, "change", () => changed(select.value));
  return select;
}
function addServiceActions(box, c) {
  const row = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  if (c.acciones.includes("entrega"))
    row.append(
      button(
        ui(() => tr("Gestionar entrega"), false),
        () => showDelivery(c.pedido.id),
        "principal",
      ),
    );
  row.append(
    button(
      ui(
        () =>
          c.acciones.includes("atender_solicitud")
            ? tr("Atender solicitud pendiente")
            : tr("Solicitudes y respuestas de esta venta"),
        false,
      ),
      () => requestsForSale(c.pedido.id),
    ),
  );
  box.append(row);
}
async function loadDeliveries(page = 1) {
  staffOnly();
  const params = new URLSearchParams({
    pagina: page,
    limite: 10,
  });
  if (service.onlyPending) params.set("pendientes_entrega", "true");
  const r = await api("/pedidos-venta?" + params);
  if (page > 1 && page > Math.max(1, Math.ceil(r.total / 10)))
    return loadDeliveries(Math.max(1, Math.ceil(r.total / 10)));
  service.deliveryPage = page;
  view("entregas-web");
  const box = $("entregas-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Entregas"), false),
    "titulo-entregas",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Elegí un pedido y confirmá un paso por vez. Los cambios de entrega no vuelven a cobrar ni a descontar stock.",
          ),
        false,
      ),
    ),
  );
  const filter = el(
    "div",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  filterSelect(
    filter,
    tr("Pedidos a mostrar"),
    "filtro-entregas",
    [
      ["pendientes", tr("Pagados pendientes de entrega")],
      ["todos", tr("Todos los pedidos")],
    ],
    service.onlyPending ? "pendientes" : "todos",
    async (value) => {
      service.onlyPending = value === "pendientes";
      await loadDeliveries(1);
    },
  );
  filter.append(
    button(
      ui(() => tr("Actualizar listado"), false),
      () => loadDeliveries(service.deliveryPage),
    ),
  );
  box.append(filter);
  const list = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  if (!r.pedidos.length)
    list.append(
      el(
        "p",
        ui(
          () =>
            service.onlyPending
              ? tr("No hay pedidos pagados pendientes de entrega.")
              : tr("No hay pedidos en esta página."),
          false,
        ),
      ),
    );
  else
    table(
      list,
      [
        ui(() => tr("Pedido"), false),
        ui(() => tr("Modalidad"), false),
        ui(() => tr("Pago"), false),
        ui(() => tr("Entrega"), false),
        ui(() => tr("Total"), false),
        ui(() => tr("Acción"), false),
      ],
      r.pedidos.map((p) => [
        ui(() => p.id, false),
        ui(() => label(p.modalidad), false),
        ui(() => label(p.estado_pago), false),
        ui(() => label(p.estado_entrega), false),
        ui(() => money.format(p.total), false),
        button(
          ui(() => tr("Abrir pedido ") + p.id, false),
          () => showDelivery(p.id),
        ),
      ]),
    );
  box.append(list);
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadDeliveries);
  box.append(nav);
  focusTitle("titulo-entregas");
}
async function showDelivery(id) {
  staffOnly();
  const p = await api(`/pedidos-venta/${id}`);
  view("entregas-web");
  const box = $("entregas-web");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a entregas"), false),
      () => loadDeliveries(service.deliveryPage),
    ),
  );
  heading(
    box,
    ui(() => tr("Entrega · Pedido {0}", [id]), false),
    "titulo-entrega",
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  definition(card, [
    [ui(() => tr("Modalidad"), false), ui(() => label(p.modalidad), false)],
    [ui(() => tr("Pago"), false), ui(() => label(p.estado_pago), false)],
    [ui(() => tr("Entrega"), false), ui(() => label(p.estado_entrega), false)],
    [ui(() => tr("Total"), false), ui(() => money.format(p.total), false)],
    [
      ui(() => tr("Registrado por"), false),
      ui(() => p.registrado_por || tr("Sin dato individual"), false),
    ],
  ]);
  if (p.cliente_al_comprar)
    definition(card, [
      [
        ui(() => tr("Contacto"), false),
        ui(
          () =>
            `${p.cliente_al_comprar.nombre || ""} ${p.cliente_al_comprar.apellido || ""}`.trim(),
          true,
        ),
      ],
      [
        ui(() => tr("Correo"), false),
        ui(() => p.cliente_al_comprar.correo, true),
      ],
    ]);
  if (p.direccion_entrega)
    definition(card, [
      [
        ui(() => tr("Dirección de entrega"), false),
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
    [ui(() => tr("Producto"), false), ui(() => tr("Unidades"), false)],
    p.productos.map((x) => [
      ui(() => x.nombre, true),
      ui(() => x.cantidad, false),
    ]),
  );
  box.append(products);
  if (p.siguiente_estado_entrega) {
    const step = p.siguiente_estado_entrega,
      actions = el(
        "div",
        ui(() => undefined, false),
        "tarjeta",
      );
    actions.append(
      el(
        "h2",
        ui(() => tr("Próximo paso"), false),
      ),
      el(
        "p",
        ui(() => deliverySteps[step], false),
      ),
    );
    actions.append(
      el(
        "p",
        ui(
          () =>
            step === "enviado"
              ? tr(
                  "Confirmá sólo si la mercadería ya salió hacia el domicilio.",
                )
              : step === "entregado"
                ? tr("Confirmá sólo si el cliente ya recibió la mercadería.")
                : tr(
                    "Confirmá únicamente si este paso corresponde al trabajo realizado.",
                  ),
          false,
        ),
        "aviso",
      ),
    );
    actions.append(
      button(
        ui(() => deliverySteps[step], false),
        () => reviewDelivery(id),
        "principal",
      ),
    );
    box.append(actions);
  } else
    box.append(
      el(
        "p",
        ui(
          () => tr("Este pedido no tiene otro paso de entrega disponible."),
          false,
        ),
        "tarjeta",
      ),
    );
  const log = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  log.append(
    el(
      "h2",
      ui(() => tr("Historial de entrega"), false),
    ),
  );
  if (p.historial_entrega.length)
    table(
      log,
      [
        ui(() => tr("Fecha y hora local"), false),
        ui(() => tr("Estado"), false),
      ],
      p.historial_entrega.map((x) => [
        ui(() => date(x.registrado_en), false),
        ui(() => label(x.estado), false),
      ]),
    );
  box.append(log);
  box.append(
    button(
      ui(() => tr("Solicitudes y respuestas del pedido"), false),
      () => requestsForSale(id),
    ),
    button(
      ui(() => tr("Actualizar pedido"), false),
      () => showDelivery(id),
    ),
  );
  focusTitle("titulo-entrega");
}
async function reviewDelivery(id) {
  const p = await api(`/pedidos-venta/${id}`),
    step = p.siguiente_estado_entrega;
  if (!step) {
    await showDelivery(id);
    throw new Error(tr("El pedido ya no tiene pasos de entrega pendientes."));
  }
  const op = operation(`/pedidos-venta/${id}/entrega`, {
    estado: step,
  });
  reviewOperation(
    [
      [ui(() => tr("Pedido"), false), ui(() => id, false)],
      [
        ui(() => tr("Estado actual"), false),
        ui(() => label(p.estado_entrega), false),
      ],
      [ui(() => tr("Próximo estado"), false), ui(() => label(step), false)],
      [
        ui(() => tr("Cobro o descuento de stock adicional"), false),
        ui(() => tr("Ninguno"), false),
      ],
    ],
    op,
    tr("Revisar paso de entrega"),
    deliverySteps[step],
    async () => {
      await showDelivery(id);
      announce(ui(() => tr("Paso de entrega registrado."), false));
    },
  );
}
async function requestsForSale(id) {
  service.requestOrder = id;
  service.requestState = "";
  await loadRequests(1);
}
async function loadRequests(page = 1) {
  staffOnly();
  const params = new URLSearchParams({
    pagina: page,
    limite: 10,
  });
  if (service.requestState) params.set("estado", service.requestState);
  if (service.requestOrder) params.set("pedido_id", service.requestOrder);
  const r = await api("/solicitudes-clientes?" + params);
  if (page > 1 && page > Math.max(1, Math.ceil(r.total / 10)))
    return loadRequests(Math.max(1, Math.ceil(r.total / 10)));
  service.requestPage = page;
  view("atencion-web");
  const box = $("atencion-web");
  box.replaceChildren();
  heading(
    box,
    ui(
      () =>
        service.requestOrder
          ? tr("Solicitudes · Pedido ") + service.requestOrder
          : tr("Atención al cliente"),
      false,
    ),
    "titulo-solicitudes",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Abrí una solicitud para consultar lo realizado y continuar por el siguiente paso disponible.",
          ),
        false,
      ),
    ),
  );
  const filter = el(
    "div",
    ui(() => undefined, false),
    "tarjeta formulario",
  );
  filterSelect(
    filter,
    tr("Estado de las solicitudes"),
    "filtro-solicitudes",
    [
      ["pendiente_revision", tr("Pendientes de revisión")],
      ["atendida", tr("Atendidas")],
      ["rechazada", tr("Rechazadas")],
      ["", tr("Todas")],
    ],
    service.requestState,
    async (value) => {
      service.requestState = value;
      await loadRequests(1);
    },
  );
  filter.append(
    button(
      ui(() => tr("Actualizar solicitudes"), false),
      () => loadRequests(service.requestPage),
    ),
  );
  if (service.requestOrder)
    filter.append(
      button(
        ui(() => tr("Ver solicitudes de todos los pedidos"), false),
        async () => {
          service.requestOrder = null;
          await loadRequests(1);
        },
      ),
    );
  box.append(filter);
  const list = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  if (!r.solicitudes.length)
    list.append(
      el(
        "p",
        ui(
          () =>
            tr("No hay solicitudes con este filtro. Podés elegir otro estado."),
          false,
        ),
      ),
    );
  else
    table(
      list,
      [
        ui(() => tr("Pedido"), false),
        ui(() => tr("Cliente"), false),
        ui(() => tr("Tipo"), false),
        ui(() => tr("Estado"), false),
        ui(() => tr("Motivo"), false),
        ui(() => tr("Acción"), false),
      ],
      r.solicitudes.map((s) => [
        ui(() => s.pedido_id, false),
        ui(() => s.usuario, true),
        ui(() => label(s.tipo), false),
        ui(() => label(s.estado), false),
        ui(() => s.motivo, true),
        button(
          ui(() => tr("Abrir solicitud"), false),
          () => showRequest(s.pedido_id, s.referencia),
        ),
      ]),
    );
  box.append(list);
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, loadRequests);
  box.append(nav);
  focusTitle("titulo-solicitudes");
}
async function showRequest(id, reference) {
  staffOnly();
  const selected = {
      id,
      reference,
    },
    c = await api(requestBase(selected)),
    p = c.pedido,
    s = c.solicitud;
  view("atencion-web");
  const box = $("atencion-web");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a solicitudes"), false),
      () => loadRequests(service.requestPage),
    ),
  );
  heading(
    box,
    ui(() => tr("{0} · Pedido {1}", [label(s.tipo), id]), false),
    "titulo-solicitud",
  );
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  definition(card, [
    [ui(() => tr("Cliente"), false), ui(() => s.usuario, true)],
    [
      ui(() => tr("Estado de solicitud"), false),
      ui(() => label(s.estado), false),
    ],
    [ui(() => tr("Motivo del cliente"), false), ui(() => s.motivo, true)],
    [ui(() => tr("Pago"), false), ui(() => label(p.estado_pago), false)],
    [ui(() => tr("Entrega"), false), ui(() => label(p.estado_entrega), false)],
  ]);
  card.append(
    el(
      "p",
      ui(() => tr("Solicitud: ") + reference, false),
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
      ui(() => tr("Compradas"), false),
      ui(() => tr("Pendientes de devolución"), false),
    ],
    c.productos.map((x) => [
      ui(() => x.nombre, true),
      ui(() => x.cantidad, false),
      ui(() => x.pendiente_devolver, false),
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
      ui(() => tr("Estado de la gestión"), false),
    ),
  );
  definition(summary, [
    [
      ui(() => tr("Estado comercial de la venta"), false),
      ui(() => label(p.devoluciones.estado_comercial), false),
    ],
    [
      ui(() => tr("Total reintegrado en la venta"), false),
      ui(() => money.format(p.devoluciones.importe_reintegrado), false),
    ],
    [
      ui(() => tr("Total pendiente en la venta"), false),
      ui(() => money.format(p.devoluciones.importe_por_reintegrar), false),
    ],
  ]);
  if (c.operacion)
    definition(summary, [
      [
        ui(() => tr("Importe de esta solicitud"), false),
        ui(() => money.format(c.operacion.importe), false),
      ],
      [
        ui(() => tr("Reintegro de esta solicitud"), false),
        ui(() => label(c.operacion.estado_reintegro), false),
      ],
    ]);
  if (c.resolucion) {
    summary.append(
      el(
        "h2",
        ui(() => tr("Respuesta al cliente"), false),
      ),
    );
    definition(summary, [
      [
        ui(() => tr("Resultado"), false),
        ui(() => label(c.resolucion.estado), false),
      ],
      [ui(() => tr("Explicación"), false), ui(() => c.resolucion.motivo, true)],
      [
        ui(() => tr("Respondida por"), false),
        ui(() => c.resolucion.usuario, true),
      ],
    ]);
  }
  box.append(summary);
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  const available = {
    recibir: [
      tr("Recibir mercadería devuelta"),
      () => returnForm(id, selected),
    ],
    cancelar: [
      tr("Cancelar antes del despacho"),
      () => cancelRequest(selected),
    ],
    reintegrar: [
      tr("Gestionar reintegro simulado"),
      () => refundForm(id, c.referencia_operacion, selected),
    ],
    resolver: [
      tr("Registrar atención completada"),
      () => resolutionForm(selected, "atendida"),
    ],
    rechazar: [
      tr("Rechazar con explicación"),
      () => resolutionForm(selected, "rechazada"),
    ],
  };
  for (const key of [
    "recibir",
    "cancelar",
    "reintegrar",
    "resolver",
    "rechazar",
  ])
    if (c.acciones.includes(key))
      actions.append(
        button(
          ui(() => available[key][0], false),
          available[key][1],
          key === "rechazar" ? undefined : "principal",
        ),
      );
  if (!c.acciones.length && s.estado === "pendiente_revision")
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "No hay pasos disponibles para tu rol y el estado actual. Consultá con el administrador.",
            ),
          false,
        ),
        "aviso",
      ),
    );
  box.append(
    actions,
    button(
      ui(() => tr("Actualizar solicitud"), false),
      () => showRequest(id, reference),
    ),
  );
  const history = el(
    "div",
    ui(() => undefined, false),
    "tarjeta cabecera-turno",
  );
  history.hidden = true;
  box.append(
    button(
      ui(() => tr("Responsables de la gestión"), false),
      () => serviceHistory(history, id, 1),
    ),
    history,
  );
  focusTitle("titulo-solicitud");
}
async function cancelRequest(selected) {
  const c = await api(requestBase(selected));
  if (!c.acciones.includes("cancelar")) {
    await showRequest(selected.id, selected.reference);
    throw new Error(
      tr("La cancelación no está disponible para tu rol o el estado actual."),
    );
  }
  const op = operation(
    `/pedidos-venta/${selected.id}/cancelaciones/${c.referencia_operacion}`,
    {
      motivo: c.solicitud.motivo,
    },
  );
  reviewOperation(
    [
      [ui(() => tr("Pedido"), false), ui(() => selected.id, false)],
      [ui(() => tr("Solicitud"), false), ui(() => selected.reference, false)],
      [ui(() => tr("Motivo"), false), ui(() => c.solicitud.motivo, true)],
      [
        ui(() => tr("Importe pendiente de reintegro"), false),
        ui(() => money.format(c.pedido.total), false),
      ],
      [
        ui(() => tr("Mercadería"), false),
        ui(() => tr("Se repone la totalidad de la venta cancelada"), false),
      ],
      [
        ui(() => tr("Dinero devuelto en este paso"), false),
        ui(() => money.format(0), false),
      ],
    ],
    op,
    tr("Revisar cancelación antes del despacho"),
    tr("Confirmar cancelación"),
    async () => {
      await showRequest(selected.id, selected.reference);
      announce(
        ui(
          () =>
            tr("Cancelación registrada. Continuá con el reintegro pendiente."),
          false,
        ),
      );
    },
  );
}
async function resolutionForm(selected, status) {
  const c = await api(requestBase(selected)),
    action = status === "atendida" ? "resolver" : "rechazar";
  if (!c.acciones.includes(action)) {
    await showRequest(selected.id, selected.reference);
    throw new Error(tr("La solicitud ya no permite esta respuesta."));
  }
  view("atencion-web");
  const box = $("atencion-web");
  box.replaceChildren();
  heading(
    box,
    ui(
      () =>
        status === "atendida"
          ? tr("Registrar atención completada")
          : tr("Rechazar solicitud"),
      false,
    ),
    "titulo-respuesta",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr("Pedido {0} · Motivo del cliente: {1}", [
            selected.id,
            c.solicitud.motivo,
          ]),
        true,
      ),
    ),
  );
  if (status === "atendida")
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "La recepción o cancelación y su reintegro ya están registrados. Esta respuesta no mueve stock ni dinero. Si la devolución fue parcial, la respuesta corresponde a esa gestión.",
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
    explanation = field(
      form,
      ui(() => tr("Explicación para el cliente"), false),
      "respuesta-motivo",
      "",
      {
        required: true,
        maxLength: 500,
      },
    );
  const row = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    ),
    submit = el(
      "button",
      ui(() => tr("Revisar respuesta"), false),
      "principal",
    );
  submit.type = "submit";
  row.append(
    button(
      ui(() => tr("Cancelar"), false),
      () => showRequest(selected.id, selected.reference),
    ),
    submit,
  );
  form.append(row);
  box.append(form);
  on(form, "submit", async () => {
    const reason = explanation.value.trim();
    if (!reason)
      throw new Error(tr("Ingresá una explicación para el cliente."));
    const op = operation(requestBase(selected) + "/resolucion", {
      estado: status,
      motivo: reason,
    });
    reviewOperation(
      [
        [ui(() => tr("Pedido"), false), ui(() => selected.id, false)],
        [ui(() => tr("Solicitud"), false), ui(() => selected.reference, false)],
        [ui(() => tr("Resultado"), false), ui(() => label(status), false)],
        [
          ui(() => tr("Explicación que verá el cliente"), false),
          ui(() => reason, true),
        ],
      ],
      op,
      tr("Revisar respuesta al cliente"),
      tr("Confirmar respuesta"),
      async () => {
        await showRequest(selected.id, selected.reference);
        announce(
          ui(
            () =>
              tr("Respuesta registrada. La solicitud quedó ") +
              label(status).toLowerCase() +
              ".",
            false,
          ),
        );
      },
    );
  });
  focusTitle("titulo-respuesta");
}
async function serviceHistory(box, id, page) {
  const r = await api(
    `/auditoria/comercial/venta/${id}?pagina=${page}&limite=10`,
  );
  box.hidden = false;
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Responsables del pedido"), false),
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
  pager(nav, page, r.total, (p) => serviceHistory(box, id, p));
  box.append(nav);
}
