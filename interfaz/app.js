// Session state, HTTP transport and product presentation. Server authorization remains authoritative.
"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  auth: null,
  user: null,
  page: 1,
  query: "",
  category: "",
  product: null,
  busy: false,
};
const money = {
  format: (value) =>
    new Intl.NumberFormat(uiLocale(), {
      style: "currency",
      currency: "ARS",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value),
};
const names = {
  tecnologia: "Tecnología",
  alimento: "Alimento",
  libreria: "Librería",
  administrador: "Administrador",
  empleado: "Empleado",
  cliente: "Cliente",
  proveedor: "Proveedor",
  saldo_inicial: "Saldo inicial",
  alta: "Alta",
  baja: "Baja",
  ajuste_manual: "Ajuste manual",
  venta_directa: "Venta directa",
  venta_qr: "Venta por QR",
  venta_efectivo: "Venta en efectivo",
  recepcion: "Recepción",
  reposicion_emergencia: "Reposición de emergencia",
  correccion_remito: "Corrección de remito",
  devolucion: "Devolución",
  cancelacion: "Cancelación",
  producto_creado: "Producto creado",
  producto_actualizado: "Producto actualizado",
  producto_eliminado: "Producto eliminado",
  regla_reposicion_guardada: "Regla de reposición configurada",
  automatico: "Automático",
  manual: "Manual",
  asistido: "Asistido",
};
const label = (x) => tr(names[x] || String(x).replaceAll("_", " "));
function el(tag, text, cls) {
  const x = document.createElement(tag);
  if (text !== undefined && !uiEmpty(text))
    setText(
      x,
      ui(() => text, true),
    );
  if (cls) x.className = cls;
  return x;
}
function announce(text, error = false) {
  const box = $("mensaje");
  setText(
    box,
    ui(() => text, true),
  );
  box.className = error ? "error" : "";
  box.hidden = !String(text);
}
function focusTitle(id) {
  const x = $(id);
  x.tabIndex = -1;
  x.focus();
}
function on(node, event, fn) {
  node.addEventListener(event, async (e) => {
    e.preventDefault();
    if (state.busy) return;
    state.busy = true;
    const enabled = [...document.querySelectorAll("button:not(:disabled)")];
    enabled.forEach((x) => (x.disabled = true));
    try {
      await fn(e);
    } catch (error) {
      announce(
        ui(
          () => error.message || tr("No se pudo completar la operación."),
          false,
        ),
        true,
      );
    } finally {
      state.busy = false;
      pruneLocaleBindings();
      enabled.filter((x) => x.isConnected).forEach((x) => (x.disabled = false));
    }
  });
}
function button(text, fn, cls) {
  const x = el(
    "button",
    ui(() => text, true),
    cls,
  );
  x.type = "button";
  on(x, "click", fn);
  return x;
}
function field(form, title, id, value = "", options = {}) {
  const l = el(
    "label",
    ui(() => title, false),
  );
  l.htmlFor = id;
  form.append(l);
  const input = el("input");
  input.id = id;
  input.value = value;
  input.type = options.type || "text";
  for (const [k, v] of Object.entries(options)) if (k !== "type") input[k] = v;
  form.append(input);
  return input;
}
function definition(target, rows) {
  const dl = el("dl");
  for (const [key, value] of rows)
    dl.append(
      el("dt", key),
      el("dd", uiEmpty(value) ? ui(() => tr("Sin datos")) : value),
    );
  target.append(dl);
}

function date(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(uiLocale());
}
function table(target, headers, rows) {
  const wrap = el(
      "div",
      ui(() => undefined, false),
      "tabla-scroll",
    ),
    t = el("table"),
    head = el("thead"),
    tr = el("tr");
  for (const h of headers) {
    const th = el(
      "th",
      ui(() => h, false),
    );
    th.scope = "col";
    tr.append(th);
  }
  head.append(tr);
  t.append(head);
  const body = el("tbody");
  for (const row of rows) {
    const r = el("tr");
    for (const value of row) {
      const td = el("td");
      const resolved = resolveUi(value);
      if (resolved instanceof Node) td.append(resolved);
      else setText(td, value);
      r.append(td);
    }
    body.append(r);
  }
  t.append(body);
  wrap.append(t);
  target.append(wrap);
}
function pager(target, page, total, load) {
  const pages = Math.max(1, Math.ceil(total / 10));
  const prev = button(
    ui(() => tr("Página anterior"), false),
    () => load(page - 1),
  );
  prev.disabled = page <= 1;
  const next = button(
    ui(() => tr("Página siguiente"), false),
    () => load(page + 1),
  );
  next.disabled = page >= pages;
  target.append(
    prev,
    el(
      "span",
      ui(
        () => tr("Página {0} de {1} · {2} registros", [page, pages, total]),
        false,
      ),
    ),
    next,
  );
}
function view(name) {
  if (typeof ops !== "undefined" && ops.incierta)
    throw new Error(
      tr(
        "Primero confirmá el resultado de la operación pendiente con el mismo botón de reintento.",
      ),
    );
  if (name !== "reposicion-web" && typeof stopDemoRefresh === "function")
    stopDemoRefresh();
  const staff =
    ["administrador", "empleado"].includes(state.user?.rol_efectivo) &&
    !state.user?.debe_cambiar_clave;
  for (const id of ["nav-ventas", "nav-caja", "nav-entregas", "nav-atencion"])
    $(id).hidden = !staff;
  $("nav-abastecimiento").hidden = !staff;
  $("nav-reposicion-simulada").hidden = !staff;
  $("nav-reposicion-simulada").className =
    name === "reposicion-web" ? "seleccionado" : "";
  if (name === "reposicion-web")
    $("nav-reposicion-simulada").setAttribute("aria-current", "page");
  else $("nav-reposicion-simulada").removeAttribute("aria-current");
  $("nav-ofertas").hidden = !(
    staff && state.user?.rol_efectivo === "administrador"
  );
  const supplier =
    state.user?.rol_efectivo === "proveedor" && !state.user?.debe_cambiar_clave;
  for (const id of ["nav-proveedor-pedidos", "nav-proveedor-catalogo"])
    $(id).hidden = !supplier;
  const client =
    state.user?.rol_efectivo === "cliente" && !state.user?.debe_cambiar_clave;
  for (const id of [
    "nav-carrito",
    "nav-mis-pedidos",
    "nav-mis-solicitudes",
    "nav-perfil",
  ])
    $(id).hidden = !client;
  setText(
    $("catalogo"),
    ui(() => (client ? tr("Comprar") : tr("Catálogo e inventario")), false),
  );
  if (typeof cli !== "undefined")
    for (const [id, key] of [
      ["nav-carrito", "cart"],
      ["nav-mis-pedidos", "orders"],
      ["nav-mis-solicitudes", "requests"],
      ["nav-perfil", "profile"],
    ]) {
      const active = name === "cliente-web" && cli.section === key;
      $(id).className = active ? "seleccionado" : "";
      if (active) $(id).setAttribute("aria-current", "page");
      else $(id).removeAttribute("aria-current");
    }
  for (const [id, active] of [
    ["catalogo", ["lista", "ficha", "editor"].includes(name)],
    ["nav-ventas", ["ventas-web", "cobro-web"].includes(name)],
    ["nav-caja", name === "caja-web"],
    ["nav-entregas", name === "entregas-web"],
    ["nav-atencion", name === "atencion-web"],
    [
      "nav-abastecimiento",
      name === "abastecimiento-web" &&
        typeof supply !== "undefined" &&
        supply.section === "orders",
    ],
    [
      "nav-ofertas",
      name === "abastecimiento-web" &&
        typeof supply !== "undefined" &&
        supply.section === "offers",
    ],
    [
      "nav-proveedor-pedidos",
      name === "proveedor-web" &&
        typeof supply !== "undefined" &&
        supply.section === "orders",
    ],
    [
      "nav-proveedor-catalogo",
      name === "proveedor-web" &&
        typeof supply !== "undefined" &&
        supply.section === "offers",
    ],
  ]) {
    $(id).className = active ? "seleccionado" : "";
    if (active) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
  if (name !== "cambio-clave") $("cambio-clave").replaceChildren();
  for (const id of [
    "ventas-web",
    "caja-web",
    "cobro-web",
    "entregas-web",
    "atencion-web",
    "cliente-web",
    "abastecimiento-web",
    "proveedor-web",
    "reposicion-web",
  ])
    if (id !== name) $(id).replaceChildren();
  for (const id of [
    "lista",
    "ficha",
    "editor",
    "cambio-clave",
    "ventas-web",
    "caja-web",
    "cobro-web",
    "entregas-web",
    "atencion-web",
    "cliente-web",
    "abastecimiento-web",
    "proveedor-web",
    "reposicion-web",
  ])
    $(id).hidden = id !== name;
  $("catalogo").hidden = Boolean(state.user?.debe_cambiar_clave) || supplier;
}
function logout(message = tr("Sesión cerrada.")) {
  if (typeof resetVentasCaja === "function") resetVentasCaja();
  if (typeof resetAtencion === "function") resetAtencion();
  if (typeof resetCliente === "function") resetCliente();
  if (typeof resetSupply === "function") resetSupply();
  if (typeof resetDemoSupply === "function") resetDemoSupply();
  state.auth = null;
  state.user = null;
  state.product = null;
  state.query = "";
  state.category = "";
  state.page = 1;
  $("form-acceso").reset();
  $("busqueda").reset();
  for (const id of [
    "ficha",
    "editor",
    "cambio-clave",
    "resultados",
    "paginas",
    "ventas-web",
    "caja-web",
    "cobro-web",
    "entregas-web",
    "atencion-web",
    "cliente-web",
    "abastecimiento-web",
    "proveedor-web",
    "reposicion-web",
    "resumen-confirmacion",
  ])
    $(id).replaceChildren();
  $("aplicacion").hidden = true;
  $("sesion").hidden = true;
  $("acceso").hidden = false;
  setText(
    $("identidad"),
    ui(() => "", false),
  );
  if ($("confirmacion").open) $("confirmacion").close();
  pending = null;
  announce(ui(() => message, false));
  $("usuario").focus();
  pruneLocaleBindings();
}
function encodeAuth(username, password) {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  return "Basic " + btoa(String.fromCharCode(...bytes));
}
async function api(path, method = "GET", data, format = "json") {
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 15000);
  const writes = method !== "GET";
  try {
    const response = await fetch(path, {
      method,
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
      headers: {
        Authorization: state.auth,
        "X-Interfaz-Web": "1",
        ...(data === undefined
          ? {}
          : {
              "Content-Type": "application/json",
            }),
      },
      ...(data === undefined
        ? {}
        : {
            body: JSON.stringify(data),
          }),
    });
    if (response.status === 204) return null;
    let body;
    try {
      body =
        response.ok && format === "text"
          ? await response.text()
          : await response.json();
    } catch {
      const invalid = new Error(
        writes
          ? tr(
              "No se pudo interpretar la respuesta. La operación podría haberse guardado; reintentá con la misma referencia.",
            )
          : tr(
              "El servidor devolvió una respuesta inesperada. Volvé a intentar la consulta.",
            ),
      );
      invalid.uncertain = writes;
      throw invalid;
    }
    if (!response.ok) {
      if (response.status === 401) {
        if (state.user)
          logout(tr("La sesión dejó de ser válida. Volvé a ingresar."));
        else state.auth = null;
        throw new Error(
          tr("Usuario o contraseña incorrectos, o cuenta desactivada."),
        );
      }
      let msg = body.detail || tr("No se pudo completar la operación.");
      if (Array.isArray(msg))
        msg = msg
          .map(
            (x) =>
              `${label(x.loc.at(-1))}: ${serverMessage(x.msg, response.status)}`,
          )
          .join("\n");
      const error = new Error(serverMessage(msg, response.status));
      error.status = response.status;
      error.uncertain = writes && response.status >= 500;
      throw error;
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError" || error instanceof TypeError) {
      const unavailable = new Error(
        writes
          ? tr(
              "No se pudo confirmar la respuesta del servidor. La operación podría haberse guardado. Revisá la ficha o el listado antes de volver a enviarla.",
            )
          : tr(
              "No se pudo conectar con el servidor. Comprobá que la API siga encendida y volvé a intentar.",
            ),
      );
      unavailable.uncertain = writes;
      throw unavailable;
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
function showUser() {
  $("acceso").hidden = true;
  $("aplicacion").hidden = false;
  $("sesion").hidden = false;
  setText(
    $("identidad"),
    ui(() => `${state.user.usuario} · ${label(state.user.rol_efectivo)}`, true),
  );
  $("nuevo").hidden = state.user.rol_efectivo !== "administrador";
  $("mi-clave").hidden =
    state.user.cuenta_compatibilidad || state.user.debe_cambiar_clave;
}
on($("form-acceso"), "submit", async () => {
  if ($("usuario").value.includes(":"))
    throw new Error(tr("El usuario no puede contener dos puntos."));
  state.auth = encodeAuth($("usuario").value.trim(), $("clave").value);
  $("clave").value = "";
  const user = await api("/sesion");
  state.user = user;
  showUser();
  announce(ui(() => "", false));
  if (user.debe_cambiar_clave) changePassword(true);
  else if (user.rol_efectivo === "proveedor") await loadSupplyOrders(1);
  else await loadList(1);
});
on($("salir"), "click", () => {
  if (typeof ops !== "undefined" && ops.incierta)
    throw new Error(
      tr(
        "Hay una operación sin respuesta confirmada. Reintentá con la misma referencia antes de cerrar la sesión.",
      ),
    );
  logout();
});
on($("catalogo"), "click", async () => {
  announce(ui(() => "", false));
  await loadList(state.page);
});
on($("mi-clave"), "click", () => {
  announce(ui(() => "", false));
  changePassword(false);
});
on($("busqueda"), "submit", async () => {
  state.query = $("texto").value.trim();
  state.category = $("categoria").value;
  announce(ui(() => "", false));
  await loadList(1);
});
on($("limpiar"), "click", async () => {
  $("busqueda").reset();
  state.query = "";
  state.category = "";
  announce(ui(() => "", false));
  await loadList(1);
});
on($("nuevo"), "click", () => {
  announce(ui(() => "", false));
  editProduct(null);
});
async function loadList(page = 1) {
  view("lista");
  const box = $("resultados");
  box.setAttribute("aria-busy", "true");
  box.replaceChildren(
    el(
      "p",
      ui(() => tr("Cargando productos…"), false),
    ),
  );
  $("paginas").replaceChildren();
  try {
    const params = new URLSearchParams({
      pagina: page,
      limite: 10,
    });
    if (state.query) params.set("texto", state.query);
    if (state.category) params.set("categoria", state.category);
    const r = await api("/productos?" + params);
    if (page > 1 && !r.productos.length && r.total)
      return await loadList(Math.max(1, Math.ceil(r.total / 10)));
    state.page = page;
    box.replaceChildren();
    if (!r.productos.length)
      box.append(
        el(
          "p",
          ui(
            () =>
              tr(
                "No hay productos con esos filtros. Probá otro nombre o limpiá los filtros.",
              ),
            false,
          ),
        ),
      );
    else
      table(
        box,
        [
          ui(() => tr("Producto"), false),
          ui(() => tr("Marca"), false),
          ui(() => tr("Categoría"), false),
          ui(() => tr("Precio"), false),
          ui(() => tr("Stock físico"), false),
          ui(() => tr("Acción"), false),
        ],
        r.productos.map((p) => [
          ui(() => tr("{0} (ID {1})", [p.nombre, p.id]), true),
          ui(() => p.marca || tr("Sin marca"), true),
          ui(() => label(p.categoria), false),
          ui(() => money.format(p.precio), false),
          ui(() => p.stock, false),
          ui(() => productButtons(p), false),
        ]),
      );
    pager($("paginas"), page, r.total, loadList);
    focusTitle("titulo-lista");
  } catch (error) {
    if (state.user)
      box.replaceChildren(
        el(
          "p",
          ui(() => tr("No se pudo cargar el catálogo."), false),
        ),
        button(
          ui(() => tr("Reintentar"), false),
          () => loadList(page),
        ),
      );
    throw error;
  } finally {
    box.setAttribute("aria-busy", "false");
  }
}
function productButtons(p) {
  const buttons = el(
    "div",
    ui(() => undefined, false),
    "fila",
  );
  buttons.append(
    button(
      ui(() => tr("Abrir {0}", [p.nombre]), true),
      () => openProduct(p.id),
    ),
  );
  if (state.user?.rol_efectivo === "cliente")
    buttons.append(
      button(
        ui(() => tr("Agregar al carrito"), false),
        () => addOnlineProduct(p.id),
      ),
    );
  return buttons;
}
async function getContext(id) {
  if (["administrador", "empleado"].includes(state.user.rol_efectivo))
    return api(`/operaciones/productos/${id}`);
  const p = await api(`/productos/${id}`);
  if (state.user.rol_efectivo === "cliente") {
    const d = await api(`/productos/${id}/disponibilidad`);
    return {
      producto: p,
      acciones: ["detalle"],
      reservadas: d.reservado,
      disponible: d.disponible,
    };
  }
  return {
    producto: p,
    acciones: ["detalle"],
  };
}
async function openProduct(id) {
  const c = await getContext(id);
  state.product = c;
  view("ficha");
  const box = $("ficha");
  box.replaceChildren();
  box.append(
    button(
      ui(() => tr("Volver a productos"), false),
      () => loadList(state.page),
    ),
  );
  const heading = el(
      "div",
      ui(() => undefined, false),
      "encabezado",
    ),
    title = el(
      "h1",
      ui(() => c.producto.nombre, true),
    );
  title.id = "titulo-ficha";
  heading.append(
    title,
    button(
      ui(() => tr("Actualizar ficha"), false),
      () => openProduct(id),
    ),
  );
  box.append(heading);
  const card = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  const p = c.producto;
  definition(card, [
    [ui(() => tr("ID del producto"), false), ui(() => p.id, false)],
    [ui(() => tr("Marca"), false), ui(() => p.marca || tr("Sin marca"), true)],
    [ui(() => tr("Categoría"), false), ui(() => label(p.categoria), false)],
    [
      ui(() => tr("Precio de venta"), false),
      ui(() => money.format(p.precio), false),
    ],
  ]);
  const nums = el(
    "div",
    ui(() => undefined, false),
    "numeros",
  );
  const amounts = [[tr("Stock físico"), p.stock]];
  if (c.reservadas !== undefined)
    amounts.push(
      [tr("Reservadas"), c.reservadas],
      [tr("Disponibles"), c.disponible],
    );
  if (c.por_recibir !== undefined)
    amounts.push([tr("Por recibir"), c.por_recibir]);
  for (const [text, value] of amounts) {
    const n = el(
      "div",
      ui(() => undefined, false),
      "numero",
    );
    n.append(
      el(
        "strong",
        ui(() => value, true),
      ),
      el(
        "span",
        ui(() => text, true),
      ),
    );
    nums.append(n);
  }
  card.append(nums);
  if (c.reservadas !== undefined)
    card.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "Disponible = stock físico menos unidades reservadas. Las unidades por recibir todavía no forman parte del stock.",
            ),
          false,
        ),
        "secundario",
      ),
    );
  box.append(card);
  const tabs = el(
    "div",
    ui(() => undefined, false),
    "pestanas",
  );
  if (c.acciones.includes("editar"))
    tabs.append(
      button(
        ui(() => tr("Editar producto"), false),
        () => editProduct(c),
        "principal",
      ),
    );
  if (c.acciones.includes("movimientos"))
    tabs.append(
      button(
        ui(() => tr("Movimientos de inventario"), false),
        () => loadMovements(id, 1),
      ),
    );
  if (c.acciones.includes("regla"))
    tabs.append(
      button(
        ui(() => tr("Regla de reposición"), false),
        () => showRule(c),
      ),
    );
  if (c.acciones.includes("historial"))
    tabs.append(
      button(
        ui(() => tr("Responsables de cambios"), false),
        () => loadHistory(id, 1),
      ),
    );
  box.append(tabs);
  const sub = el(
    "div",
    ui(() => undefined, false),
    "tarjeta",
  );
  sub.id = "detalle-extra";
  sub.append(
    el(
      "p",
      ui(() => tr("Elegí una acción para continuar."), false),
    ),
  );
  box.append(sub);
  if (state.user.rol_efectivo === "empleado")
    sub.replaceChildren(
      el(
        "p",
        ui(
          () =>
            tr("Tu cuenta puede consultar este producto y sus movimientos."),
          false,
        ),
      ),
    );
  if (state.user.rol_efectivo === "cliente") {
    sub.replaceChildren(
      el(
        "p",
        ui(
          () => tr("Agregá este producto al carrito para preparar una compra."),
          false,
        ),
      ),
    );
    sub.append(
      button(
        ui(() => tr("Agregar al carrito"), false),
        () => addOnlineProduct(p.id),
        "principal",
      ),
      button(
        ui(() => tr("Ver mi carrito"), false),
        showOnlineCart,
      ),
    );
  } else if (!["administrador", "empleado"].includes(state.user.rol_efectivo))
    sub.replaceChildren(
      el(
        "p",
        ui(
          () =>
            tr(
              "Esta primera interfaz permite consultar el catálogo. Las compras y pedidos siguen disponibles en la consola.",
            ),
          false,
        ),
      ),
    );
  focusTitle("titulo-ficha");
}
async function loadMovements(id, page) {
  const r = await api(
      `/inventario/movimientos?producto_id=${id}&pagina=${page}&limite=10`,
    ),
    box = $("detalle-extra");
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Movimientos de inventario"), false),
    ),
  );
  if (!r.movimientos.length)
    box.append(
      el(
        "p",
        ui(() => tr("Todavía no hay movimientos para este producto."), false),
      ),
    );
  else
    table(
      box,
      [
        ui(() => tr("Fecha y hora local"), false),
        ui(() => tr("Movimiento"), false),
        ui(() => tr("Cambio"), false),
        ui(() => tr("Stock anterior"), false),
        ui(() => tr("Stock resultante"), false),
        ui(() => tr("Motivo"), false),
      ],
      r.movimientos.map((m) => [
        ui(() => date(m.registrado_en), false),
        ui(() => label(m.tipo), false),
        ui(() => (m.variacion > 0 ? `+${m.variacion}` : m.variacion), false),
        ui(() => m.stock_anterior, false),
        ui(() => m.stock_resultante, false),
        ui(() => m.motivo, true),
      ]),
    );
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, (p) => loadMovements(id, p));
  box.append(nav);
}
function showRule(c) {
  const box = $("detalle-extra");
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Regla de reposición"), false),
    ),
  );
  const r = c.regla;
  if (!r) {
    box.append(
      el(
        "p",
        ui(() => tr("Este producto no tiene una regla configurada."), false),
      ),
    );
    return;
  }
  const v =
    typeof r.configuracion === "string"
      ? JSON.parse(r.configuracion)
      : r.configuracion;
  definition(box, [
    [
      ui(() => tr("Activa"), false),
      ui(() => (v.activa ? tr("Sí") : tr("No")), false),
    ],
    [ui(() => tr("Modo"), false), ui(() => label(v.modo), false)],
    [ui(() => tr("Stock mínimo"), false), ui(() => v.minimo, false)],
    [ui(() => tr("Stock objetivo"), false), ui(() => v.objetivo, false)],
    [ui(() => tr("Alerta desde"), false), ui(() => v.alerta_desde, false)],
    [
      ui(() => tr("Considera reservas"), false),
      ui(() => (v.considerar_reservas ? tr("Sí") : tr("No")), false),
    ],
    [
      ui(() => tr("Máximo de unidades"), false),
      ui(() => v.max_unidades, false),
    ],
    [ui(() => tr("Versión"), false), ui(() => r.version, false)],
  ]);
  box.append(
    el(
      "p",
      ui(
        () =>
          tr(
            "Consulta de la regla actual. Su configuración y evaluación siguen en el menú de consola.",
          ),
        false,
      ),
      "secundario",
    ),
  );
}
async function loadHistory(id, page) {
  const r = await api(
      `/auditoria/comercial/producto/${id}?pagina=${page}&limite=10`,
    ),
    box = $("detalle-extra");
  box.replaceChildren(
    el(
      "h2",
      ui(() => tr("Responsables de cambios"), false),
    ),
  );
  if (!r.movimientos.length)
    box.append(
      el(
        "p",
        ui(
          () =>
            tr(
              "No hay cambios registrados desde que se incorporó este historial. Los movimientos de stock se consultan por separado.",
            ),
          false,
        ),
      ),
    );
  for (const m of r.movimientos) {
    const item = el(
      "article",
      ui(() => undefined, false),
      "evento",
    );
    item.append(
      el(
        "h3",
        ui(() => `${label(m.accion)} · ${m.actor}`, true),
      ),
      el(
        "p",
        ui(() => date(m.registrado_en), false),
        "secundario",
      ),
    );
    renderDetails(item, m.detalle);
    box.append(item);
  }
  const nav = el(
    "div",
    ui(() => undefined, false),
    "paginacion",
  );
  pager(nav, page, r.total, (p) => loadHistory(id, p));
  box.append(nav);
}
function renderDetails(target, obj) {
  if (obj === null || typeof obj !== "object") {
    target.append(el("p", obj ?? ""));
    return;
  }
  const enumFields = new Set([
    "estado",
    "anterior",
    "nuevo",
    "tipo",
    "modo",
    "estado_pago",
    "estado_entrega",
  ]);
  for (const [key, value] of Object.entries(obj)) {
    if (value && typeof value === "object") {
      const block = el("div");
      block.append(
        el(
          "strong",
          ui(() => label(key)),
        ),
      );
      renderDetails(block, value);
      target.append(block);
    } else
      definition(target, [
        [
          ui(() => label(key)),
          ui(
            () =>
              typeof value === "boolean"
                ? tr(value ? "Sí" : "No")
                : enumFields.has(key) && typeof value === "string"
                  ? label(value)
                  : value,
            !enumFields.has(key) && typeof value !== "boolean",
          ),
        ],
      ]);
  }
}

function integer(input, min) {
  const n = Number(input.value);
  if (!Number.isSafeInteger(n) || n < min)
    throw new Error(
      tr("{0}: ingresá un número entero desde {1}.", [
        input.labels[0].textContent,
        min,
      ]),
    );
  return n;
}
function editProduct(context) {
  view("editor");
  const p = context?.producto,
    box = $("editor");
  box.replaceChildren();
  const title = el(
    "h1",
    ui(() => (p ? tr("Editar {0}", [p.nombre]) : tr("Crear producto")), true),
  );
  title.id = "titulo-editor";
  box.append(title);
  box.append(
    el(
      "p",
      ui(
        () =>
          p
            ? tr(
                "Modificá los campos necesarios y revisá el resumen antes de guardar.",
              )
            : tr(
                "Completá los datos. El producto se crea después de tu confirmación.",
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
  let name, category;
  if (!p) {
    name = field(
      form,
      ui(() => tr("Nombre"), false),
      "producto-nombre",
      "",
      {
        required: true,
        maxLength: 150,
      },
    );
    const l = el(
      "label",
      ui(() => tr("Categoría"), false),
    );
    l.htmlFor = "producto-categoria";
    category = el("select");
    category.id = "producto-categoria";
    for (const v of ["tecnologia", "alimento", "libreria"]) {
      const o = el(
        "option",
        ui(() => label(v), false),
      );
      o.value = v;
      category.append(o);
    }
    form.append(l, category);
  }
  const brand = field(
    form,
    ui(() => tr("Marca (opcional)"), false),
    "producto-marca",
    p?.marca || "",
    {
      maxLength: 150,
    },
  );
  const price = field(
    form,
    ui(() => tr("Precio de venta en pesos, sin centavos"), false),
    "producto-precio",
    p?.precio || "",
    {
      type: "number",
      min: 1,
      step: 1,
      required: true,
    },
  );
  const stock = field(
    form,
    ui(() => tr("Stock físico total"), false),
    "producto-stock",
    p?.stock ?? 0,
    {
      type: "number",
      min: 0,
      step: 1,
      required: true,
    },
  );
  form.append(
    el(
      "small",
      ui(
        () =>
          tr(
            "Ingresá la cantidad total que debe quedar, no la cantidad a sumar o restar.",
          ),
        false,
      ),
    ),
  );
  let reason;
  if (p) {
    reason = field(
      form,
      ui(() => tr("Motivo del ajuste de stock"), false),
      "producto-motivo",
      "",
      {
        maxLength: 500,
      },
    );
    form.append(
      el(
        "small",
        ui(
          () =>
            tr(
              "Obligatorio sólo si cambiás el stock. Para ventas, devoluciones y recepciones usá sus recorridos específicos en la consola.",
            ),
          false,
        ),
      ),
    );
  }
  const actions = el(
      "div",
      ui(() => undefined, false),
      "acciones",
    ),
    submit = el(
      "button",
      ui(() => tr("Revisar cambios"), false),
      "principal",
    );
  submit.type = "submit";
  actions.append(
    button(
      ui(() => tr("Cancelar"), false),
      () => (p ? openProduct(p.id) : loadList(state.page)),
    ),
    submit,
  );
  form.append(actions);
  box.append(form);
  on(form, "submit", async () => {
    const priceValue = integer(price, 1),
      stockValue = integer(stock, 0),
      brandValue = brand.value.trim() || null;
    const data = {},
      rows = [];
    if (!p) {
      data.nombre = name.value.trim();
      if (!data.nombre) throw new Error(tr("Ingresá el nombre del producto."));
      data.categoria = category.value;
      data.marca = brandValue;
      data.precio = priceValue;
      data.stock = stockValue;
      rows.push(
        [tr("Nombre"), data.nombre],
        [tr("Categoría"), label(data.categoria)],
        [tr("Marca"), brandValue || tr("Sin marca")],
        [tr("Precio"), money.format(priceValue)],
        [tr("Stock inicial"), stockValue],
      );
    } else {
      if (brandValue !== (p.marca || null)) {
        data.marca = brandValue;
        rows.push([
          tr("Marca"),
          `${p.marca || tr("Sin marca")} → ${brandValue || tr("Sin marca")}`,
        ]);
      }
      if (priceValue !== p.precio) {
        data.precio = priceValue;
        rows.push([
          tr("Precio"),
          `${money.format(p.precio)} → ${money.format(priceValue)}`,
        ]);
      }
      if (stockValue !== p.stock) {
        data.stock = stockValue;
        data.motivo_stock = reason.value.trim();
        if (!data.motivo_stock) {
          reason.focus();
          throw new Error(tr("Explicá el motivo del ajuste de stock."));
        }
        rows.push(
          [tr("Stock físico"), `${p.stock} → ${stockValue}`],
          [tr("Motivo"), data.motivo_stock],
        );
      }
      if (!Object.keys(data).length) {
        announce(ui(() => tr("No cambiaste ningún dato."), false));
        return;
      }
    }
    confirm(rows, async () => {
      const result = await api(
        p ? `/productos/${p.id}` : "/productos",
        p ? "PATCH" : "POST",
        data,
      );
      $("confirmacion").close();
      pending = null;
      announce(
        ui(
          () => (p ? tr("Cambios guardados.") : tr("Producto creado.")),
          false,
        ),
      );
      try {
        await openProduct(result.id);
      } catch {
        await loadList(state.page);
        announce(
          ui(
            () =>
              tr(
                "La operación se guardó. Actualizá el listado para consultar el resultado.",
              ),
            false,
          ),
        );
      }
    });
  });
  focusTitle("titulo-editor");
}
let pending = null;
function confirm(
  rows,
  action,
  title = tr("Revisar antes de guardar"),
  accept = tr("Confirmar y guardar"),
) {
  setText(
    $("titulo-confirmacion"),
    ui(() => title, false),
  );
  setText(
    $("aceptar-confirmacion"),
    ui(() => accept, false),
  );
  const box = $("resumen-confirmacion");
  box.replaceChildren();
  definition(box, rows);
  $("error-confirmacion").hidden = true;
  pending = action;
  $("confirmacion").showModal();
  $("cancelar-confirmacion").focus();
}
on($("cancelar-confirmacion"), "click", () => {
  $("confirmacion").close();
  pending = null;
});
$("confirmacion").addEventListener("cancel", (e) => {
  if (state.busy) e.preventDefault();
  else pending = null;
});
on($("aceptar-confirmacion"), "click", async () => {
  if (!pending) return;
  try {
    await pending();
  } catch (error) {
    if ($("confirmacion").open) {
      setText(
        $("error-confirmacion"),
        ui(() => error.message, false),
      );
      $("error-confirmacion").hidden = false;
    } else throw error;
  }
});
function changePassword(forced) {
  view("cambio-clave");
  const box = $("cambio-clave");
  box.replaceChildren();
  const title = el(
    "h1",
    ui(() => tr("Cambiar mi contraseña"), false),
  );
  title.id = "titulo-clave";
  box.append(title);
  box.append(
    el(
      "p",
      ui(
        () =>
          forced
            ? tr(
                "Tu contraseña es temporal. Elegí una nueva antes de continuar.",
              )
            : tr("Ingresá tu contraseña actual y elegí una nueva."),
        false,
      ),
    ),
  );
  const form = el("form");
  const current = field(
    form,
    ui(() => tr("Contraseña actual"), false),
    "clave-actual",
    "",
    {
      type: "password",
      required: true,
      maxLength: 128,
      autocomplete: "current-password",
    },
  );
  const next = field(
    form,
    ui(() => tr("Nueva contraseña (mínimo 10 caracteres)"), false),
    "clave-nueva",
    "",
    {
      type: "password",
      required: true,
      minLength: 10,
      maxLength: 128,
      autocomplete: "new-password",
    },
  );
  const repeat = field(
    form,
    ui(() => tr("Repetir nueva contraseña"), false),
    "clave-repetida",
    "",
    {
      type: "password",
      required: true,
      minLength: 10,
      maxLength: 128,
      autocomplete: "new-password",
    },
  );
  form.append(
    el(
      "small",
      ui(
        () =>
          tr(
            "Usá letras sin tildes, números y símbolos. La contraseña nueva debe ser diferente de la actual.",
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
  if (!forced)
    actions.append(
      button(
        ui(() => tr("Cancelar"), false),
        () =>
          state.user?.rol_efectivo === "proveedor"
            ? loadSupplyOrders(supply.page)
            : loadList(state.page),
      ),
    );
  const submit = el(
    "button",
    ui(() => tr("Guardar contraseña"), false),
    "principal",
  );
  submit.type = "submit";
  actions.append(submit);
  form.append(actions);
  box.append(form);
  on(form, "submit", async () => {
    if (next.value !== repeat.value)
      throw new Error(tr("Las contraseñas nuevas no coinciden."));
    await api("/mi-cuenta/clave", "PUT", {
      actual: current.value,
      nueva: next.value,
    });
    logout(tr("Contraseña actualizada. Ingresá con tu nueva contraseña."));
  });
  focusTitle("titulo-clave");
}
