// Read-only polling of server-side replenishment progress and explicit demo controls.
"use strict";
const demoSupply = {
  timer: null,
  page: 1,
  version: 0,
};
function stopDemoRefresh() {
  clearTimeout(demoSupply.timer);
  demoSupply.timer = null;
  demoSupply.version++;
}
function resetDemoSupply() {
  stopDemoRefresh();
  demoSupply.page = 1;
}
function demoSupplyLabel(x) {
  return (
    {
      pendiente_pago: tr("Pendiente de pago simulado"),
      preparando: tr("Pago aprobado · En preparación"),
      listo: tr("Listo para despachar"),
      despachado: tr("Despachado · Falta recepción física"),
      recibido: tr("Recibido"),
      cancelado: tr("Cancelado"),
    }[x] || label(x)
  );
}
on($("nav-reposicion-simulada"), "click", () => loadDemoSupply());
async function loadDemoSupply(page = 1) {
  staffOnly();
  const r = await api("/reposicion-simulada?pagina=" + page);
  stopDemoRefresh();
  demoSupply.page = page;
  view("reposicion-web");
  const box = $("reposicion-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Reposición automática · Simulación"), false),
    "titulo-reposicion-simulada",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Sin dinero real ni conexiones con bancos. Esta prueba usa un fondo separado de la caja de ventas. El pago se aprueba con un botón y el proveedor prepara y despacha automáticamente.",
          ),
        false,
      ),
      "aviso",
    ),
  );
  const rule = supplyCard(box, tr("Una regla general"));
  rule.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Al llegar a stock físico 0: pedir 3 unidades a una oferta vigente. Máximo $1.000 por unidad. Sólo se genera el pedido si hay dinero disponible para reservar su importe completo.",
          ),
        false,
      ),
    ),
  );
  const status = el("div");
  status.id = "estado-reposicion-simulada";
  box.append(status);
  renderDemoSupply(status, r);
  if (state.user.rol_efectivo === "administrador") {
    const controls = supplyCard(box, tr("Control de la prueba"));
    controls.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "Elegí un producto de prueba sin regla individual. La regla es la misma para cualquier producto elegido. Pausar detiene pedidos nuevos; los que ya pagaste siguen hasta el despacho.",
            ),
          false,
        ),
      ),
    );
    controls.append(
      button(
        ui(() => tr("Preparar ejemplo"), false),
        reviewDemoExample,
        "principal",
      ),
      button(
        ui(() => tr("Elegir otro producto de prueba"), false),
        () => chooseDemoProduct(),
      ),
    );
    if (r.producto)
      controls.append(
        button(
          ui(
            () =>
              r.configuracion.activa
                ? tr("Pausar generación de pedidos")
                : tr("Activar generación de pedidos"),
            false,
          ),
          () => reviewDemoConfig(r.producto, !r.configuracion.activa),
        ),
      );
    const form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    );
    form.append(
      el(
        "h2",
        ui(() => tr("Agregar dinero ficticio al fondo"), false),
      ),
    );
    const amount = field(
        form,
        ui(() => tr("Importe en pesos (ejemplo: 2000)"), false),
        "aporte-simulado",
        "",
        {
          required: true,
          inputMode: "decimal",
        },
      ),
      submit = el(
        "button",
        ui(() => tr("Revisar aporte simulado"), false),
        "principal",
      );
    submit.type = "submit";
    form.append(submit);
    box.append(form);
    on(form, "submit", () => {
      const cents = parseCost(amount.value);
      if (cents > 100000000)
        throw new Error(tr("El aporte de prueba admite hasta $1.000.000."));
      const op = operation(
        "/reposicion-simulada/aportes/" + ref("aporte-web"),
        {
          importe_centavos: cents,
        },
      );
      reviewOperation(
        [
          [
            ui(() => tr("Fondo"), false),
            ui(() => tr("Reposición simulada"), false),
          ],
          [
            ui(() => tr("Aporte ficticio"), false),
            ui(() => costMoney.format(cents / 100), false),
          ],
          [
            ui(() => tr("Efecto en caja de ventas"), false),
            ui(() => tr("Ninguno"), false),
          ],
        ],
        op,
        tr("Revisar aporte de demostración"),
        tr("Agregar dinero ficticio"),
        async () => {
          await loadDemoSupply(demoSupply.page);
          announce(
            ui(
              () =>
                tr(
                  "Aporte simulado registrado. Si la prueba está activa, el sistema vuelve a evaluar automáticamente.",
                ),
              false,
            ),
          );
        },
      );
    });
  }
  box.append(
    button(
      ui(() => tr("Actualizar ahora"), false),
      () => loadDemoSupply(demoSupply.page),
    ),
  );
  scheduleDemoRefresh(status, demoSupply.version);
  focusTitle("titulo-reposicion-simulada");
}
function reviewDemoExample() {
  supplyAdmin();
  reviewOperation(
    [
      [
        ui(() => tr("Producto nuevo"), false),
        ui(
          () =>
            tr(
              "Prueba reposición automática · Stock inicial 0 · Precio de venta $1.000",
            ),
          false,
        ),
      ],
      [ui(() => tr("Proveedor ficticio"), false), ui(() => "simulado", false)],
      [
        ui(() => tr("Oferta ficticia"), false),
        ui(
          () =>
            tr(
              "3 unidades a $500,50 cada una, vinculadas al producto de muestra",
            ),
          false,
        ),
      ],
      [
        ui(() => tr("Regla general"), false),
        ui(() => tr("Se activa para este producto"), false),
      ],
      [
        ui(() => tr("Fondo simulado"), false),
        ui(() => tr("No se agrega dinero en este paso"), false),
      ],
      [
        ui(() => tr("Datos anteriores"), false),
        ui(
          () => tr("Se conservan productos, ofertas y pedidos anteriores"),
          false,
        ),
      ],
      [
        ui(() => tr("Si ya existe el ejemplo"), false),
        ui(
          () =>
            tr(
              "Se conserva tal como está; no se reinicia ni se duplican sus datos",
            ),
          false,
        ),
      ],
    ],
    operation("/reposicion-simulada/ejemplo"),
    tr("Preparar ejemplo de reposición automática"),
    tr("Preparar ejemplo"),
    async (r) => {
      await loadDemoSupply();
      announce(
        ui(
          () =>
            r.ya_preparado
              ? tr(
                  "El ejemplo ya estaba preparado. Se conservó su estado actual.",
                )
              : tr(
                  "Ejemplo preparado. Agregá $2.000 ficticios al fondo para probar el pedido automático.",
                ),
          false,
        ),
      );
    },
  );
}
function renderDemoSupply(box, r) {
  box.replaceChildren();
  const summary = supplyCard(box, tr("Estado y fondo ficticio"));
  definition(summary, [
    [
      ui(() => tr("Generación de pedidos"), false),
      ui(() => (r.configuracion.activa ? tr("Activa") : tr("Pausada")), false),
    ],
    [
      ui(() => tr("Producto de prueba"), false),
      ui(
        () =>
          r.producto
            ? tr("{0} (ID {1})", [r.producto.nombre, r.producto.id])
            : tr("Sin elegir"),
        true,
      ),
    ],
    [
      ui(() => tr("Stock físico"), false),
      ui(() => r.producto?.stock ?? tr("Sin elegir"), false),
    ],
    [
      ui(() => tr("Última evaluación"), false),
      ui(() => r.configuracion.resultado, false),
    ],
    [
      ui(() => tr("Total aportado"), false),
      ui(() => costMoney.format(r.fondo.aportado_centavos / 100), false),
    ],
    [
      ui(() => tr("Total pagado"), false),
      ui(() => costMoney.format(r.fondo.pagado_centavos / 100), false),
    ],
    [
      ui(() => tr("Saldo del fondo"), false),
      ui(() => costMoney.format(r.fondo.saldo_centavos / 100), false),
    ],
    [
      ui(() => tr("Reservado para pedidos sin pagar"), false),
      ui(() => costMoney.format(r.fondo.reservado_centavos / 100), false),
    ],
    [
      ui(() => tr("Disponible para pedidos nuevos"), false),
      ui(() => costMoney.format(r.fondo.disponible_centavos / 100), false),
    ],
  ]);
  const orders = supplyCard(box, tr("Pedidos de la simulación"));
  if (!r.compras.length)
    orders.append(
      el(
        "p",
        ui(() => tr("Todavía no se generaron pedidos simulados."), false),
      ),
    );
  else
    table(
      orders,
      [
        ui(() => tr("Pedido y producto"), false),
        ui(() => tr("Proveedor"), false),
        ui(() => tr("Unidades"), false),
        ui(() => tr("Importe total"), false),
        ui(() => tr("Circuito simulado"), false),
        ui(() => tr("Acción"), false),
      ],
      r.compras.map((c) => {
        const actions = el(
          "div",
          ui(() => undefined, false),
          "acciones",
        );
        actions.append(
          button(
            ui(() => tr("Abrir pedido ") + c.pedido_id, false),
            () => showSupplyOrder(c.pedido_id),
          ),
        );
        if (
          c.estado === "pendiente_pago" &&
          state.user?.rol_efectivo === "administrador"
        )
          actions.append(
            button(
              ui(() => tr("Simular pago aprobado"), false),
              () => reviewDemoPayment(c),
              "principal",
            ),
          );
        return [
          ui(() => `${c.pedido_id} · ${c.producto_nombre}`, false),
          ui(() => c.proveedor, false),
          ui(
            () => tr("{0} recibidas de {1}", [c.cantidad_recibida, c.cantidad]),
            false,
          ),
          ui(() => costMoney.format(c.importe_centavos / 100), false),
          ui(() => demoSupplyLabel(c.estado), false),
          ui(() => actions, false),
        ];
      }),
    );
  supplyPages(box, r.pagina, r.total, (p) => loadDemoSupply(p));
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Se actualiza automáticamente cada 2 segundos. Después del pago: preparación → listo → despacho simulado, con unos 5 segundos por paso. La recepción sigue siendo manual.",
          ),
        false,
      ),
      "secundario",
    ),
  );
}
function scheduleDemoRefresh(box, version) {
  demoSupply.timer = setTimeout(async () => {
    if (
      version !== demoSupply.version ||
      !box.isConnected ||
      $("reposicion-web").hidden ||
      !state.user
    )
      return;
    try {
      if (!state.busy && !$("confirmacion").open) {
        const user = state.user,
          r = await api("/reposicion-simulada?pagina=" + demoSupply.page);
        if (
          version !== demoSupply.version ||
          state.user !== user ||
          !box.isConnected
        )
          return;
        renderDemoSupply(box, r);
        pruneLocaleBindings();
      }
    } catch (error) {
      if (state.user && version === demoSupply.version)
        announce(
          ui(
            () => tr("No se pudo actualizar la simulación. ") + error.message,
            false,
          ),
          true,
        );
    }
    if (
      version === demoSupply.version &&
      box.isConnected &&
      !$("reposicion-web").hidden
    )
      scheduleDemoRefresh(box, version);
  }, 2000);
}
function reviewDemoPayment(c) {
  supplyAdmin();
  reviewOperation(
    [
      [ui(() => tr("Pedido"), false), ui(() => c.pedido_id, false)],
      [ui(() => tr("Proveedor"), false), ui(() => c.proveedor, false)],
      [
        ui(() => tr("Pago ficticio total"), false),
        ui(() => costMoney.format(c.importe_centavos / 100), false),
      ],
      [
        ui(() => tr("Dinero reservado"), false),
        ui(() => tr("Pasa a pagado una sola vez"), false),
      ],
      [
        ui(() => tr("Proveedor simulado"), false),
        ui(
          () =>
            tr(
              "Recibe la confirmación e inicia preparación; luego despacha automáticamente",
            ),
          false,
        ),
      ],
      [
        ui(() => tr("Stock local"), false),
        ui(() => tr("No aumenta hasta registrar la recepción física"), false),
      ],
    ],
    operation(`/reposicion-simulada/pedidos/${c.pedido_id}/pago-aprobado`),
    tr("Revisar pago simulado al proveedor"),
    tr("Simular pago aprobado"),
    async () => {
      await loadDemoSupply(demoSupply.page);
      announce(
        ui(
          () =>
            tr(
              "Pago simulado aprobado. La preparación y el despacho avanzan automáticamente.",
            ),
          false,
        ),
      );
    },
  );
}
function reviewDemoConfig(p, active) {
  supplyAdmin();
  reviewOperation(
    [
      [
        ui(() => tr("Producto de prueba"), false),
        ui(() => tr("{0} (ID {1})", [p.nombre, p.id]), true),
      ],
      [ui(() => tr("Stock físico actual"), false), ui(() => p.stock, false)],
      [
        ui(() => tr("Regla general"), false),
        ui(() => tr("Stock cero → pedir 3; máximo $1.000 por unidad"), false),
      ],
      [
        ui(() => tr("Generación automática"), false),
        ui(() => (active ? tr("Activar") : tr("Pausar")), false),
      ],
      [
        ui(() => tr("Pedidos ya pagados"), false),
        ui(() => tr("Siguen su preparación y despacho"), false),
      ],
    ],
    operation("/reposicion-simulada/configuracion", {
      producto_id: p.id,
      activa: active,
    }),
    active
      ? tr("Activar prueba de reposición automática")
      : tr("Pausar generación de pedidos"),
    active ? tr("Activar prueba") : tr("Pausar"),
    async () => {
      await loadDemoSupply();
      announce(
        ui(
          () =>
            active
              ? tr(
                  "Prueba activa. Se evalúa automáticamente mientras la API esté encendida.",
                )
              : tr("Generación de pedidos pausada."),
          false,
        ),
      );
    },
  );
}
async function chooseDemoProduct(query = "", page = 1) {
  supplyAdmin();
  const r = await api(
    "/productos?" +
      new URLSearchParams({
        texto: query,
        pagina: page,
        limite: 10,
      }),
  );
  view("reposicion-web");
  const box = $("reposicion-web");
  box.replaceChildren();
  heading(
    box,
    ui(() => tr("Elegir producto para la prueba"), false),
    "titulo-producto-simulado",
  );
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Usá un producto nuevo con stock cero y una oferta vinculada, para conservar los productos de las pruebas anteriores.",
          ),
        false,
      ),
    ),
  );
  const form = el(
      "form",
      ui(() => undefined, false),
      "tarjeta formulario",
    ),
    queryInput = field(
      form,
      ui(() => tr("Nombre o marca"), false),
      "producto-simulado-busqueda",
      query,
    ),
    submit = el(
      "button",
      ui(() => tr("Buscar"), false),
    );
  submit.type = "submit";
  form.append(submit);
  box.append(form);
  on(form, "submit", () => chooseDemoProduct(queryInput.value.trim(), 1));
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
        ui(() => tr("Producto"), false),
        ui(() => tr("Marca"), false),
        ui(() => tr("Stock físico"), false),
        ui(() => tr("Acción"), false),
      ],
      r.productos.map((p) => [
        ui(() => tr("{0} (ID {1})", [p.nombre, p.id]), true),
        ui(() => p.marca, true),
        ui(() => p.stock, false),
        button(
          ui(() => tr("Usar este producto"), false),
          () => reviewDemoConfig(p, true),
        ),
      ]),
    );
  supplyPages(box, page, r.total, (p) => chooseDemoProduct(query, p));
  box.append(
    button(
      ui(() => tr("Volver a la simulación"), false),
      () => loadDemoSupply(),
    ),
  );
  focusTitle("titulo-producto-simulado");
}
