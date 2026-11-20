// Supplier catalogs, purchase orders, delivery notes and goods receipt.
"use strict";
const supply = {
  section: "orders",
  page: 1,
  filter: "abiertos",
  provider: "demo",
  draft: null,
};
function resetSupply() {
  Object.assign(supply, {
    section: "orders",
    page: 1,
    filter: "abiertos",
    provider: "demo",
    draft: null,
  });
}
function supplierOnly() {
  if (state.user?.rol_efectivo !== "proveedor" || !state.user.proveedor)
    throw new Error(
      tr("Este recorrido corresponde al proveedor identificado."),
    );
}
function supplyAdmin() {
  if (state.user?.rol_efectivo !== "administrador")
    throw new Error(tr("Esta acción corresponde al administrador."));
}
function isSupplier() {
  return state.user?.rol_efectivo === "proveedor";
}
function supplyStatus(value) {
  return (
    {
      parcial: tr("Recibido parcialmente"),
      recibido: tr("Recibido"),
      cancelado: tr("Cancelado"),
      cerrado_incompleto: tr("Cerrado con faltantes"),
      pendiente: tr("Pendiente"),
      confirmado: tr("Confirmado"),
      despachado: tr("Despachado"),
      sin_disponibilidad: tr("Sin disponibilidad"),
    }[value] || label(value)
  );
}
const costMoney = {
  format: (value) =>
    new Intl.NumberFormat(uiLocale(), {
      style: "currency",
      currency: "ARS",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value),
};
function parseCost(text) {
  const match = /^(\d{1,12})(?:[.,](\d{1,2}))?$/.exec(String(text).trim());
  if (!match)
    throw new Error(
      tr(
        "Ingresá el costo en pesos, sin separador de miles y con hasta dos decimales.",
      ),
    );
  const cents =
    BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0"));
  if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error(
      tr("El costo debe ser positivo y estar dentro del rango admitido."),
    );
  return Number(cents);
}
function costText(cents) {
  return Math.floor(cents / 100) + "." + String(cents % 100).padStart(2, "0");
}
function supplyCount(input, max = 1000000) {
  const text = input.value.trim();
  if (
    !/^\d+$/.test(text) ||
    !Number.isSafeInteger(Number(text)) ||
    Number(text) < 1 ||
    Number(text) > max
  )
    throw new Error(tr("Ingresá una cantidad entera entre 1 y ") + max + ".");
  return Number(text);
}
function supplyPanel(section = "orders") {
  supply.section = section;
  const id = isSupplier() ? "proveedor-web" : "abastecimiento-web";
  view(id);
  const box = $(id);
  box.replaceChildren();
  return box;
}
function supplyCard(box, title) {
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  if (title)
    card.append(
      el(
        "h2",
        ui(() => title, false),
      ),
    );
  box.append(card);
  return card;
}
function supplyPages(box, page, total, load) {
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, total, load);
  box.append(nav);
}
on($("nav-abastecimiento"), "click", () => loadSupplyOrders(1));
on($("nav-proveedor-pedidos"), "click", () => loadSupplyOrders(1));
on($("nav-ofertas"), "click", () => loadSupplyOffers());
on($("nav-proveedor-catalogo"), "click", () => loadSupplyOffers());
async function loadSupplyOrders(page = 1) {
  if (isSupplier()) supplierOnly();
  else staffOnly();
  const base = isSupplier()
    ? "/mi-proveedor/pedidos"
    : "/abastecimiento/pedidos";
  const r = await api(
    base +
      "?" +
      new URLSearchParams({
        filtro: supply.filter,
        pagina: page,
        limite: 10,
      }),
  );
  if (page > 1 && !r.pedidos.length)
    return loadSupplyOrders(Math.max(1, Math.ceil(r.total / 10)));
  supply.page = page;
  const box = supplyPanel();
  heading(
    box,
    ui(
      () => (isSupplier() ? tr("Pedidos del negocio") : tr("Abastecimiento")),
      false,
    ),
    "titulo-abastecimiento",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          isSupplier()
            ? tr(
                "Consultá tus pedidos y registrá avisos. El negocio confirma por separado la recepción física.",
              )
            : tr(
                "Consultá pedidos a proveedores y registrá solamente la mercadería que recibiste físicamente.",
              ),
        false,
      ),
    ),
  );
  const filters = supplyCard(box);
  filterSelect(
    filters,
    tr("Pedidos a mostrar"),
    "filtro-abastecimiento",
    [
      ["abiertos", tr("Abiertos")],
      ["todos", tr("Todos")],
    ],
    supply.filter,
    async (value) => {
      supply.filter = value;
      await loadSupplyOrders(1);
    },
  );
  filters.append(
    button(
      ui(() => tr("Actualizar pedidos"), false),
      () => loadSupplyOrders(supply.page),
    ),
  );
  const list = supplyCard(box);
  if (!r.pedidos.length)
    list.append(
      el(
        "p",
        ui(() => tr("No hay pedidos con este filtro."), false),
      ),
    );
  else
    table(
      list,
      [
        ui(() => tr("Pedido"), false),
        ui(() => tr("Producto ID"), false),
        ui(() => tr("Proveedor"), false),
        ui(() => tr("Estado"), false),
        ui(() => tr("Pedidas"), false),
        ui(() => tr("Recibidas"), false),
        ui(() => tr("Pendientes"), false),
        ui(() => tr("Acción"), false),
      ],
      r.pedidos.map((p) => [
        ui(() => p.id, false),
        ui(() => p.producto_id, false),
        ui(() => p.proveedor, false),
        ui(() => supplyStatus(p.estado), false),
        ui(() => p.cantidad, false),
        ui(() => p.cantidad_recibida, false),
        ui(() => p.cantidad_pendiente, false),
        button(
          ui(() => tr("Abrir pedido ") + p.id, false),
          () => showSupplyOrder(p.id),
        ),
      ]),
    );
  supplyPages(box, page, r.total, loadSupplyOrders);
  focusTitle("titulo-abastecimiento");
}
async function showSupplyOrder(id) {
  if (isSupplier()) supplierOnly();
  else staffOnly();
  const own = isSupplier(),
    c = await api(
      (own ? "/mi-proveedor/pedidos/" : "/abastecimiento/pedidos/") + id,
    ),
    p = c.pedido;
  const box = supplyPanel();
  box.append(
    button(
      ui(() => tr("Volver a pedidos"), false),
      () => loadSupplyOrders(supply.page),
    ),
  );
  heading(
    box,
    ui(() => tr("Pedido al proveedor ") + id, false),
    "titulo-pedido-proveedor",
  );
  const card = supplyCard(box);
  definition(card, [
    [
      ui(() => tr("Producto"), false),
      ui(() => c.producto_nombre || tr("ID ") + p.producto_id, false),
    ],
    [ui(() => tr("Proveedor"), false), ui(() => p.proveedor, false)],
    [
      ui(() => tr("Código del proveedor"), false),
      ui(() => p.id_externo, false),
    ],
    [ui(() => tr("Estado"), false), ui(() => supplyStatus(p.estado), false)],
    [ui(() => tr("Unidades pedidas"), false), ui(() => p.cantidad, false)],
    [
      ui(() => tr("Unidades recibidas"), false),
      ui(() => p.cantidad_recibida, false),
    ],
    [
      ui(() => tr("Unidades pendientes"), false),
      ui(() => p.cantidad_pendiente, false),
    ],
    [
      ui(() => tr("Costo unitario ofertado"), false),
      ui(() => costMoney.format(p.costo_ofertado_centavos / 100), false),
    ],
    [
      ui(() => tr("Costo unitario pagado"), false),
      ui(
        () =>
          p.costo_pagado_centavos
            ? costMoney.format(p.costo_pagado_centavos / 100)
            : tr("Sin recepción"),
        false,
      ),
    ],
  ]);
  if (c.simulacion) {
    const sim = supplyCard(box, tr("Circuito de demostración"));
    definition(sim, [
      [
        ui(() => tr("Pago y entrega simulados"), false),
        ui(() => demoSupplyLabel(c.simulacion.estado), false),
      ],
      [
        ui(() => tr("Importe total ficticio"), false),
        ui(() => costMoney.format(c.simulacion.importe_centavos / 100), false),
      ],
    ]);
    sim.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "El servicio de pagos y el proveedor están simulados. El despacho no aumenta stock; confirmá la recepción física cuando corresponda.",
            ),
          false,
        ),
      ),
    );
    if (!own)
      sim.append(
        button(
          ui(() => tr("Ver fondo y pago simulado"), false),
          () => loadDemoSupply(),
        ),
      );
  }
  if (p.cantidad_no_entregada)
    definition(card, [
      [
        ui(() => tr("Unidades no entregadas al cerrar"), false),
        ui(() => p.cantidad_no_entregada, false),
      ],
    ]);
  if (own) {
    if (c.ultimo_aviso)
      definition(card, [
        [
          ui(() => tr("Último aviso"), false),
          ui(() => supplyStatus(c.ultimo_aviso.estado), false),
        ],
        [
          ui(() => tr("Nota"), false),
          ui(
            () =>
              c.simulacion ? tr(c.ultimo_aviso.nota) : c.ultimo_aviso.nota,
            true,
          ),
        ],
      ]);
    if (c.acciones_aviso.length) {
      const form = el(
        "form",
        ui(() => undefined, false),
        "tarjeta formulario",
      );
      form.append(
        el(
          "h2",
          ui(() => tr("Informar al negocio"), false),
        ),
        el(
          "p",
          ui(
            () =>
              tr("Este aviso no modifica el stock ni confirma una recepción."),
            false,
          ),
        ),
      );
      const status = filterSelect(
          form,
          tr("Estado informado"),
          "aviso-estado",
          c.acciones_aviso.map((x) => [x, supplyStatus(x)]),
          c.acciones_aviso[0],
          () => {},
        ),
        note = field(
          form,
          ui(() => tr("Nota para el negocio"), false),
          "aviso-nota",
          "",
          {
            required: true,
            maxLength: 500,
          },
        );
      const submit = el(
        "button",
        ui(() => tr("Revisar aviso"), false),
        "principal",
      );
      submit.type = "submit";
      form.append(submit);
      box.append(form);
      on(form, "submit", async () => {
        const text = note.value.trim();
        if (!text) throw new Error(tr("Ingresá una nota para el negocio."));
        const fresh = await api("/mi-proveedor/pedidos/" + id);
        if (!fresh.acciones_aviso.includes(status.value))
          throw new Error(
            tr("El pedido ya no permite ese aviso. Actualizá la ficha."),
          );
        if (
          fresh.ultimo_aviso?.estado === status.value &&
          fresh.ultimo_aviso?.nota === text
        )
          throw new Error(tr("Ese aviso ya es el último registrado."));
        const op = operation(
          `/mi-proveedor/pedidos/${id}/avisos/${ref("aviso-web")}`,
          {
            estado: status.value,
            nota: text,
          },
        );
        reviewOperation(
          [
            [ui(() => tr("Pedido"), false), ui(() => id, false)],
            [
              ui(() => tr("Estado informado"), false),
              ui(() => supplyStatus(status.value), true),
            ],
            [ui(() => tr("Nota"), false), ui(() => text, true)],
            [
              ui(() => tr("Cambio de stock"), false),
              ui(() => tr("Ninguno"), false),
            ],
          ],
          op,
          tr("Revisar aviso al negocio"),
          tr("Confirmar aviso"),
          async () => {
            await showSupplyOrder(id);
            announce(
              ui(
                () =>
                  tr(
                    "Aviso registrado. La recepción física sigue a cargo del negocio.",
                  ),
                false,
              ),
            );
          },
        );
      });
    } else
      box.append(
        el(
          "p",
          ui(
            () =>
              c.simulacion
                ? tr(
                    "Los avisos de este pedido se generan automáticamente por el proveedor simulado.",
                  )
                : tr("El pedido está cerrado. No admite nuevos avisos."),
            false,
          ),
          "aviso",
        ),
      );
  } else {
    const actions = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    );
    if (c.acciones.includes("recibir"))
      actions.append(
        button(
          ui(() => tr("Recibir mercadería"), false),
          () => supplyReceiptForm(id),
          "principal",
        ),
      );
    for (const [key, text, path] of [
      ["cancelar", tr("Cancelar pedido sin recepción"), "cancelacion"],
      ["cerrar", tr("Cerrar con faltantes"), "cierre-incompleto"],
    ])
      if (c.acciones.includes(key))
        actions.append(
          button(
            ui(() => text, false),
            () => reviewSupplyClose(id, key, path),
          ),
        );
    box.append(actions);
    const remitos = supplyCard(box, tr("Remitos recibidos"));
    await supplyHistory(
      remitos,
      id,
      "remitos",
      1,
      c.acciones.includes("corregir"),
    );
    const audit = supplyCard(box);
    audit.hidden = true;
    box.append(
      button(
        ui(() => tr("Responsables del pedido"), false),
        () => supplyHistory(audit, id, "auditoria", 1),
      ),
    );
  }
  const notices = supplyCard(box, tr("Avisos del proveedor"));
  await supplyHistory(notices, id, "avisos", 1, false, Boolean(c.simulacion));
  box.append(
    button(
      ui(() => tr("Actualizar pedido"), false),
      () => showSupplyOrder(id),
    ),
  );
  focusTitle("titulo-pedido-proveedor");
}
async function supplyHistory(
  box,
  id,
  kind,
  page = 1,
  canCorrect = false,
  simulated = false,
) {
  const own = isSupplier();
  if (own) supplierOnly();
  else staffOnly();
  if (kind === "auditoria" && own)
    throw new Error(tr("Historial reservado al negocio."));
  const path =
    kind === "auditoria"
      ? `/auditoria/comercial/pedido_proveedor/${id}`
      : (own ? "/mi-proveedor/pedidos/" : "/abastecimiento/pedidos/") +
        id +
        "/" +
        kind;
  const r = await api(path + `?pagina=${page}&limite=10`);
  box.hidden = false;
  box.replaceChildren(
    el(
      "h2",
      ui(
        () =>
          kind === "remitos"
            ? tr("Remitos recibidos")
            : kind === "avisos"
              ? tr("Avisos del proveedor")
              : tr("Responsables del pedido"),
        false,
      ),
    ),
  );
  const rows = r[kind === "auditoria" ? "movimientos" : kind];
  if (!rows.length)
    box.append(
      el(
        "p",
        ui(() => tr("No hay registros en este historial."), false),
      ),
    );
  if (kind === "remitos" && rows.length)
    table(
      box,
      [
        ui(() => tr("Remito"), false),
        ui(() => tr("Unidades"), false),
        ui(() => tr("Costo unitario pagado"), false),
        ui(() => tr("Registrado"), false),
        ui(() => tr("Acción"), false),
      ],
      rows.map((x) => [
        ui(() => x.referencia, true),
        ui(() => x.cantidad, false),
        ui(() => costMoney.format(x.costo_pagado_centavos / 100), false),
        ui(() => date(x.registrado_en), false),
        ui(
          () =>
            canCorrect
              ? button(
                  ui(() => tr("Corregir ") + x.referencia, true),
                  () => supplyReceiptForm(id, x),
                )
              : tr("Sólo consulta"),
          true,
        ),
      ]),
    );
  if (kind === "avisos" && rows.length)
    table(
      box,
      [
        ui(() => tr("Estado informado"), false),
        ui(() => tr("Nota"), false),
        ui(() => tr("Fecha y hora local"), false),
        ui(() => tr("Referencia"), false),
      ],
      rows.map((x) => [
        ui(() => supplyStatus(x.estado), false),
        ui(() => (simulated ? tr(x.nota) : x.nota), true),
        ui(() => date(x.registrado_en), false),
        ui(() => x.referencia, true),
      ]),
    );
  if (kind === "auditoria")
    for (const m of rows) {
      const a = el(
        "article",
        ui(() => undefined, false),
        "evento",
      );
      a.append(
        el(
          "h3",
          ui(() => label(m.accion) + " · " + m.actor, true),
        ),
        el(
          "p",
          ui(() => date(m.registrado_en), false),
        ),
      );
      renderDetails(a, m.detalle);
      box.append(a);
    }
  supplyPages(box, page, r.total, (p) =>
    supplyHistory(box, id, kind, p, canCorrect, simulated),
  );
}
async function supplyReceiptForm(id, remito = null) {
  staffOnly();
  if (remito) supplyAdmin();
  const c = await api("/abastecimiento/pedidos/" + id);
  if (!c.acciones.includes(remito ? "corregir" : "recibir"))
    throw new Error(tr("El pedido ya no permite esta operación."));
  const box = supplyPanel();
  heading(
    box,
    ui(
      () => (remito ? tr("Corregir remito") : tr("Recibir mercadería")),
      false,
    ),
    "titulo-recepcion-proveedor",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr("Pedido {0} · {1} · Pendientes: {2}", [
            id,
            c.producto_nombre,
            c.pedido.cantidad_pendiente,
          ]),
        false,
      ),
    ),
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "El costo se ingresa por unidad, en pesos. Las entregas de un mismo pedido deben conservar el mismo costo; si hay un error, consultá al administrador.",
          ),
        false,
      ),
    ),
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          remito
            ? tr(
                "La cantidad es el nuevo total de este remito. La corrección ajusta el stock por la diferencia y queda en el historial.",
              )
            : tr(
                "Usá la referencia del remito real. No vuelvas a registrar la misma entrega con otra referencia.",
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
    reference = field(
      form,
      ui(() => tr("Referencia del remito"), false),
      "recepcion-referencia",
      remito?.referencia || "",
      {
        required: true,
        maxLength: 64,
        readOnly: Boolean(remito),
        pattern: "[A-Za-z0-9_-]+",
      },
    ),
    quantity = field(
      form,
      ui(
        () =>
          remito
            ? tr("Cantidad total corregida del remito")
            : tr("Cantidad recibida en esta entrega"),
        false,
      ),
      "recepcion-cantidad",
      remito?.cantidad || "",
      {
        type: "number",
        required: true,
        min: 1,
        step: 1,
      },
    ),
    cost = field(
      form,
      ui(() => tr("Costo unitario pagado en pesos (ejemplo: 500,50)"), false),
      "recepcion-costo",
      remito
        ? costText(remito.costo_pagado_centavos)
        : c.pedido.costo_pagado_centavos
          ? costText(c.pedido.costo_pagado_centavos)
          : "",
      {
        required: true,
        inputMode: "decimal",
      },
    );
  const reason = remito
    ? field(
        form,
        ui(() => tr("Motivo de la corrección"), false),
        "recepcion-motivo",
        "",
        {
          required: true,
          maxLength: 500,
        },
      )
    : null;
  const submit = el(
    "button",
    ui(
      () => tr("Revisar ") + (remito ? tr("corrección") : tr("recepción")),
      false,
    ),
    "principal",
  );
  submit.type = "submit";
  form.append(
    button(
      ui(() => tr("Cancelar"), false),
      () => showSupplyOrder(id),
    ),
    submit,
  );
  box.append(form);
  on(form, "submit", async () => {
    const r = reference.value.trim();
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(r))
      throw new Error(
        tr("La referencia admite letras, números, guion y guion bajo."),
      );
    const qty = supplyCount(
        quantity,
        remito ? c.pedido.cantidad : c.pedido.cantidad_pendiente,
      ),
      cents = parseCost(cost.value),
      data = {
        cantidad: qty,
        costo_pagado_centavos: cents,
      };
    if (reason) {
      data.motivo = reason.value.trim();
      if (!data.motivo)
        throw new Error(tr("Ingresá el motivo de la corrección."));
      if (qty === remito.cantidad && cents === remito.costo_pagado_centavos)
        throw new Error(tr("No hay cambios de cantidad ni de costo."));
    }
    const op = operation(
      `/pedidos/${id}/recepciones/${encodeURIComponent(r)}` +
        (remito ? "/correcciones/" + ref("correccion-web") : ""),
      data,
    );
    reviewOperation(
      [
        [ui(() => tr("Pedido"), false), ui(() => id, false)],
        [ui(() => tr("Remito"), false), ui(() => r, false)],
        [
          ui(
            () =>
              remito ? tr("Nuevo total del remito") : tr("Unidades recibidas"),
            false,
          ),
          ui(() => qty, false),
        ],
        [
          ui(() => tr("Costo unitario pagado"), false),
          ui(() => costMoney.format(cents / 100), false),
        ],
        ...(reason
          ? [[ui(() => tr("Motivo"), false), ui(() => data.motivo, true)]]
          : []),
      ],
      op,
      remito
        ? tr("Revisar corrección de remito")
        : tr("Revisar recepción física"),
      remito ? tr("Confirmar corrección") : tr("Confirmar recepción"),
      async () => {
        await showSupplyOrder(id);
        announce(
          ui(
            () =>
              remito
                ? tr("Corrección registrada.")
                : tr(
                    "Recepción registrada. El stock se actualizó con las unidades recibidas.",
                  ),
            false,
          ),
        );
      },
    );
  });
  focusTitle("titulo-recepcion-proveedor");
}
async function reviewSupplyClose(id, key, path) {
  supplyAdmin();
  const c = await api("/abastecimiento/pedidos/" + id);
  if (!c.acciones.includes(key))
    throw new Error(tr("El pedido ya no permite esta operación."));
  reviewOperation(
    [
      [ui(() => tr("Pedido"), false), ui(() => id, false)],
      [
        ui(() => tr("Unidades recibidas"), false),
        ui(() => c.pedido.cantidad_recibida, false),
      ],
      [
        ui(() => tr("Unidades que no se recibirán"), false),
        ui(() => c.pedido.cantidad_pendiente, false),
      ],
      [ui(() => tr("Cambio de stock"), false), ui(() => tr("Ninguno"), false)],
    ],
    operation(`/pedidos/${id}/${path}`),
    key === "cerrar"
      ? tr("Cerrar pedido con faltantes")
      : tr("Cancelar pedido al proveedor"),
    tr("Confirmar"),
    async () => {
      await showSupplyOrder(id);
      announce(
        ui(
          () => tr("Pedido cerrado. No se agregaron unidades al stock."),
          false,
        ),
      );
    },
  );
}
function catalogDraft(offers) {
  return offers
    .filter((x) => x.vigente)
    .map((x) => ({
      id: x.id_externo,
      nombre: x.nombre,
      marca: x.marca,
      categoria: x.categoria,
      precio: costText(x.costo_centavos),
      stock: x.stock_proveedor,
    }));
}
async function loadSupplyOffers() {
  if (isSupplier()) supplierOnly();
  else supplyAdmin();
  const provider = isSupplier() ? state.user.proveedor : supply.provider,
    offers = await api(
      "/proveedores/" + encodeURIComponent(provider) + "/ofertas",
    );
  const box = supplyPanel("offers");
  heading(
    box,
    ui(
      () => (isSupplier() ? tr("Mi catálogo") : tr("Ofertas de proveedores")),
      false,
    ),
    "titulo-ofertas-proveedor",
  );
  if (!isSupplier()) {
    const filters = supplyCard(box);
    filterSelect(
      filters,
      tr("Proveedor"),
      "ofertas-proveedor",
      [
        ["demo", tr("Demo")],
        ["demo-b", tr("Demo B")],
      ],
      provider,
      async (value) => {
        supply.provider = value;
        await loadSupplyOffers();
      },
    );
  }
  box.append(
    el(
      "p",
      ui(
        () =>
          isSupplier()
            ? tr(
                "Publicar ofertas informa precios y disponibilidad al negocio. No crea stock físico en el negocio.",
              )
            : tr(
                "Vinculá cada oferta con el producto local que corresponda. Evaluar reposición puede generar un pedido según las reglas vigentes.",
              ),
        false,
      ),
    ),
  );
  const list = supplyCard(box);
  if (!offers.length)
    list.append(
      el(
        "p",
        ui(() => tr("No hay ofertas publicadas."), false),
      ),
    );
  else
    table(
      list,
      [
        ui(() => tr("Código"), false),
        ui(() => tr("Nombre y marca"), false),
        ui(() => tr("Costo unitario"), false),
        ui(() => tr("Disponible proveedor"), false),
        ui(() => tr("Estado"), false),
        ui(() => tr("Producto vinculado"), false),
        ui(() => tr("Acción"), false),
      ],
      offers.map((o) => [
        ui(() => o.id_externo, false),
        ui(() => `${o.nombre} · ${o.marca}`, true),
        ui(() => costMoney.format(o.costo_centavos / 100), false),
        ui(() => o.stock_proveedor, false),
        ui(() => (o.vigente ? tr("Vigente") : tr("Inactiva")), false),
        ui(
          () =>
            o.producto_id
              ? tr("{0} (ID {1})", [o.producto_nombre, o.producto_id])
              : tr("Sin vínculo"),
          false,
        ),
        ui(
          () =>
            isSupplier() ? tr("Sólo consulta") : offerActions(provider, o),
          false,
        ),
      ]),
    );
  box.append(
    button(
      ui(() => tr("Actualizar ofertas"), false),
      loadSupplyOffers,
    ),
  );
  if (isSupplier())
    box.append(
      button(
        ui(() => tr("Editar y publicar catálogo"), false),
        () => {
          supply.draft = catalogDraft(offers);
          editSupplyCatalog();
        },
        "principal",
      ),
    );
  focusTitle("titulo-ofertas-proveedor");
}
function offerActions(provider, offer) {
  const actions = el(
    "div",
    ui(() => undefined, false),
    "acciones",
  );
  actions.append(
    button(
      ui(() => tr("Elegir producto local"), false),
      () => linkSupplyOffer(provider, offer),
    ),
  );
  if (offer.producto_id && offer.vigente)
    actions.append(
      button(
        ui(() => tr("Evaluar reposición"), false),
        () => evaluateSupply(offer.producto_id),
      ),
    );
  return actions;
}
async function linkSupplyOffer(provider, offer, query = "", page = 1) {
  supplyAdmin();
  const r = await api(
      "/productos?" +
        new URLSearchParams({
          texto: query,
          pagina: page,
          limite: 10,
        }),
    ),
    box = supplyPanel("offers");
  heading(
    box,
    ui(() => tr("Vincular oferta con producto local"), false),
    "titulo-vinculo-oferta",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          `${provider} · ${offer.id_externo} · ${offer.nombre} · ${offer.marca}`,
        true,
      ),
    ),
  );
  const form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    ),
    search = field(
      form,
      ui(() => tr("Buscar producto local por nombre o marca"), false),
      "vinculo-busqueda",
      query,
    ),
    submit = el(
      "button",
      ui(() => tr("Buscar"), false),
    );
  submit.type = "submit";
  form.append(submit);
  box.append(form);
  on(form, "submit", () =>
    linkSupplyOffer(provider, offer, search.value.trim(), 1),
  );
  const list = supplyCard(box);
  if (!r.productos.length)
    list.append(
      el(
        "p",
        ui(() => tr("No hay productos con esa búsqueda."), false),
      ),
    );
  else
    table(
      list,
      [
        ui(() => tr("Producto local"), false),
        ui(() => tr("Marca"), false),
        ui(() => tr("Categoría"), false),
        ui(() => tr("Acción"), false),
      ],
      r.productos.map((p) => [
        ui(() => tr("{0} (ID {1})", [p.nombre, p.id]), true),
        ui(() => p.marca, true),
        ui(() => label(p.categoria), false),
        button(
          ui(() => tr("Vincular ") + p.nombre, true),
          () => {
            if (offer.producto_id === p.id)
              throw new Error(
                tr("La oferta ya está vinculada con este producto."),
              );
            reviewOperation(
              [
                [ui(() => tr("Proveedor"), false), ui(() => provider, false)],
                [
                  ui(() => tr("Oferta"), false),
                  ui(
                    () =>
                      `${offer.id_externo} · ${offer.nombre} · ${offer.marca}`,
                    true,
                  ),
                ],
                [
                  ui(() => tr("Producto local"), false),
                  ui(
                    () => tr("{0} · {1} (ID {2})", [p.nombre, p.marca, p.id]),
                    true,
                  ),
                ],
                [
                  ui(() => tr("Vínculo anterior"), false),
                  ui(() => offer.producto_id || tr("Ninguno"), false),
                ],
              ],
              operation(
                `/proveedores/${encodeURIComponent(provider)}/ofertas/${encodeURIComponent(offer.id_externo)}/vinculo`,
                {
                  producto_id: p.id,
                },
              ),
              tr("Revisar vínculo de oferta"),
              tr("Confirmar vínculo"),
              async () => {
                await loadSupplyOffers();
                announce(
                  ui(() => tr("Oferta vinculada al producto local."), false),
                );
              },
            );
          },
        ),
      ]),
    );
  supplyPages(box, page, r.total, (p) =>
    linkSupplyOffer(provider, offer, query, p),
  );
  box.append(
    button(
      ui(() => tr("Cancelar"), false),
      loadSupplyOffers,
    ),
  );
  focusTitle("titulo-vinculo-oferta");
}
async function evaluateSupply(id) {
  supplyAdmin();
  const p = await api("/productos/" + id);
  reviewOperation(
    [
      [
        ui(() => tr("Producto"), false),
        ui(() => tr("{0} (ID {1})", [p.nombre, id]), true),
      ],
      [ui(() => tr("Stock físico actual"), false), ui(() => p.stock, false)],
      [
        ui(() => tr("Acción"), false),
        ui(
          () =>
            tr(
              "Evaluar reglas y ofertas vinculadas; puede generar un pedido al proveedor",
            ),
          false,
        ),
      ],
      [
        ui(() => tr("Sin regla configurada"), false),
        ui(
          () => tr("Requiere stock cero y una oferta elegible para 3 unidades"),
          false,
        ),
      ],
    ],
    operation(`/productos/${id}/reposicion`, undefined, "POST"),
    tr("Evaluar reposición del producto"),
    tr("Evaluar y generar si corresponde"),
    async (r) => {
      if (r.pedido) {
        await showSupplyOrder(r.pedido.id);
        announce(
          ui(
            () =>
              r.estado === "pedido_generado"
                ? tr("Pedido al proveedor generado.")
                : tr("Evaluación terminada: se muestra el pedido disponible."),
            false,
          ),
        );
      } else {
        await loadSupplyOffers();
        announce(
          ui(
            () => tr("Resultado de la evaluación: ") + label(r.estado) + ".",
            false,
          ),
        );
      }
    },
  );
}
function editSupplyCatalog(editIndex = null) {
  supplierOnly();
  const box = supplyPanel("offers");
  heading(
    box,
    ui(() => tr("Preparar catálogo del proveedor"), false),
    "titulo-editar-catalogo",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "La publicación reemplaza tu catálogo vigente. Conservá las filas que seguís ofreciendo; las que quites quedarán inactivas. Si no tenés disponibilidad, quitá esa fila. Primero agregá o guardá cada fila en el borrador; después revisá y confirmá la publicación.",
          ),
        false,
      ),
      "aviso",
    ),
  );
  const rows = supply.draft || [],
    list = supplyCard(box, tr("Ofertas que se publicarán"));
  if (rows.length)
    table(
      list,
      [
        ui(() => tr("Código"), false),
        ui(() => tr("Nombre"), false),
        ui(() => tr("Marca"), false),
        ui(() => tr("Precio"), false),
        ui(() => tr("Unidades disponibles"), false),
        ui(() => tr("Acción"), false),
      ],
      rows.map((r, i) => {
        const actions = el(
          "div",
          ui(() => undefined, false),
          "acciones",
        );
        actions.append(
          button(
            ui(() => tr("Editar ") + r.id, false),
            () => editSupplyCatalog(i),
          ),
          button(
            ui(() => tr("Quitar ") + r.id, false),
            () => {
              supply.draft.splice(i, 1);
              editSupplyCatalog();
            },
          ),
        );
        return [
          ui(() => r.id, false),
          ui(() => r.nombre, true),
          ui(() => r.marca, true),
          ui(() => r.precio, false),
          ui(() => r.stock, false),
          ui(() => actions, false),
        ];
      }),
    );
  else
    list.append(
      el(
        "p",
        ui(
          () => tr("Catálogo vacío. Publicarlo desactiva todas tus ofertas."),
          false,
        ),
      ),
    );
  const current = editIndex === null ? {} : rows[editIndex],
    form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    );
  form.append(
    el(
      "h2",
      ui(
        () => (editIndex === null ? tr("Agregar oferta") : tr("Editar oferta")),
        false,
      ),
    ),
  );
  const code = field(
      form,
      ui(() => tr("Código propio del producto"), false),
      "catalogo-codigo",
      current.id || "",
      {
        required: true,
        maxLength: 64,
      },
    ),
    name = field(
      form,
      ui(() => tr("Nombre"), false),
      "catalogo-nombre",
      current.nombre || "",
      {
        required: true,
        maxLength: 150,
      },
    ),
    brand = field(
      form,
      ui(() => tr("Marca"), false),
      "catalogo-marca",
      current.marca || "",
      {
        required: true,
        maxLength: 150,
      },
    ),
    category = filterSelect(
      form,
      tr("Categoría"),
      "catalogo-categoria",
      [
        ["tecnologia", tr("Tecnología")],
        ["alimento", tr("Alimento")],
        ["libreria", tr("Librería")],
      ],
      current.categoria || "tecnologia",
      () => {},
    ),
    price = field(
      form,
      ui(() => tr("Precio unitario en pesos (sin separador de miles)"), false),
      "catalogo-precio",
      current.precio || "",
      {
        required: true,
        inputMode: "decimal",
      },
    ),
    stock = field(
      form,
      ui(() => tr("Unidades disponibles (1 a 1000000)"), false),
      "catalogo-stock",
      current.stock || "",
      {
        type: "number",
        required: true,
        min: 1,
        max: 1000000,
        step: 1,
      },
    ),
    submit = el(
      "button",
      ui(
        () =>
          editIndex === null ? tr("Agregar al borrador") : tr("Guardar fila"),
        false,
      ),
    );
  submit.type = "submit";
  form.append(submit);
  box.append(form);
  on(form, "submit", () => {
    const row = {
      id: code.value.trim(),
      nombre: name.value.trim(),
      marca: brand.value.trim(),
      categoria: category.value,
      precio: costText(parseCost(price.value)),
      stock: supplyCount(stock),
    };
    if (!row.id || !row.nombre || !row.marca)
      throw new Error(tr("Completá código, nombre y marca."));
    if (/[\/\\]/.test(row.id))
      throw new Error(
        tr("El código no admite barras. Usá letras, números o guiones."),
      );
    if (rows.some((r, i) => r.id === row.id && i !== editIndex))
      throw new Error(tr("Ese código ya está incluido en el borrador."));
    if (editIndex === null) {
      if (rows.length >= 999)
        throw new Error(tr("El catálogo admite hasta 999 ofertas."));
      rows.push(row);
    } else rows[editIndex] = row;
    supply.draft = rows;
    editSupplyCatalog();
  });
  box.append(
    button(
      ui(() => tr("Descartar borrador y volver"), false),
      async () => {
        supply.draft = null;
        await loadSupplyOffers();
      },
    ),
    button(
      ui(() => tr("Revisar publicación"), false),
      () => {
        if ([code, name, brand, price, stock].some((x) => x.value.trim()))
          throw new Error(
            tr(
              "Primero guardá la fila en el borrador para incluirla en la publicación.",
            ),
          );
        return reviewSupplyCatalog();
      },
      "principal",
    ),
  );
  focusTitle("titulo-editar-catalogo");
}
async function reviewSupplyCatalog() {
  supplierOnly();
  const rows = supply.draft || [],
    current = await api(
      "/proveedores/" + encodeURIComponent(state.user.proveedor) + "/ofertas",
    ),
    omitted = current.filter(
      (x) => x.vigente && !rows.some((r) => r.id === x.id_externo),
    );
  const op = operation("/mi-proveedor/catalogo", {
    productos: rows,
  });
  reviewOperation(
    [
      [
        ui(() => tr("Ofertas que se publicarán"), false),
        ui(() => rows.length, false),
      ],
      ...rows.map((r) => [
        ui(() => r.id, false),
        ui(
          () =>
            tr("{0} · {1} · $ {2} · {3} unidades", [
              r.nombre,
              r.marca,
              r.precio,
              r.stock,
            ]),
          true,
        ),
      ]),
      [
        ui(() => tr("Ofertas que quedarán inactivas"), false),
        ui(
          () =>
            omitted.length
              ? omitted.map((x) => x.id_externo + " · " + x.nombre).join("; ")
              : tr("Ninguna"),
          true,
        ),
      ],
      [
        ui(() => tr("Stock físico del negocio"), false),
        ui(() => tr("No cambia"), false),
      ],
    ],
    op,
    tr("Revisar publicación del catálogo"),
    tr("Publicar catálogo"),
    async (r) => {
      supply.draft = null;
      await loadSupplyOffers();
      announce(
        ui(
          () =>
            tr(
              "Catálogo publicado. Nuevas: {0}; actualizadas: {1}; sin cambios: {2}.",
              [r.nuevas, r.actualizadas, r.sin_cambios],
            ) +
            (r.rechazos?.length
              ? tr(" Filas rechazadas: ") +
                r.rechazos.map((x) => `${x.fila}: ${x.motivo}`).join("; ")
              : ""),
          true,
        ),
      );
    },
  );
}
