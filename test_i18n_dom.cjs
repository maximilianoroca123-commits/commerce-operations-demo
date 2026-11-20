// Browser-independent DOM contract tests for the bilingual presentation layer.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const fixtures = JSON.parse(
  fs.readFileSync(path.join(__dirname, "tests/fixtures/i18n.json"), "utf8"),
);
async function app(language = "es") {
  const { Window } = await import("happy-dom");
  const w = new Window({
    url: "http://localhost:8000/interfaz/",
    settings: {
      disableJavaScriptFileLoading: true,
      disableJavaScriptEvaluation: true,
    },
  });
  w.document.write(
    fs.readFileSync(path.join(__dirname, "interfaz/index.html"), "utf8"),
  );
  w.localStorage.setItem("commerce-demo-language", language);
  const f = structuredClone(fixtures),
    calls = [];
  let phase = 0;
  const ctx = vm.createContext(w),
    run = (s) => vm.runInContext(s, ctx);
  ctx.crypto = webcrypto;
  w.fetch = async (url, options) => {
    const data = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ url, method: options.method, data });
    let body;
    if (options.method === "PUT") {
      if (url.includes("/aportes/")) {
        phase = 1;
        body = f.aporte;
      } else if (url.endsWith("/pago-aprobado")) {
        phase = 2;
        body = f.payment;
      } else if (url.includes("/recepciones/")) {
        phase = 4;
        body = f.receipt;
      } else if (url === "/mi-proveedor/catalogo")
        body = { nuevas: 1, actualizadas: 0, sin_cambios: 0, rechazos: [] };
      else if (url === "/reposicion-simulada/configuracion")
        body = { guardada: true };
      else throw new Error("Unexpected mutation " + url);
    } else if (url.startsWith("/reposicion-simulada?"))
      body = f["simulation" + phase];
    else if (url.startsWith("/productos?")) body = f.products;
    else if (url.match(/^\/productos\/\d+\/disponibilidad/))
      body = { disponible: 6, reservado: 0 };
    else if (url.match(/^\/productos\/\d+$/))
      body = f.products.productos.find(
        (x) => x.id === Number(url.split("/").at(-1)),
      );
    else if (url.match(/^\/operaciones\/productos\//)) {
      const p = f.products.productos.find(
        (x) => x.id === Number(url.split("/").at(-1)),
      );
      body = {
        producto: p,
        acciones: ["detalle", "movimientos", "editar"],
        reservadas: 0,
        disponible: p.stock,
        por_recibir: 0,
      };
    } else if (url === "/abastecimiento/pedidos/" + f.order_id)
      body = f[phase >= 4 ? "supply4" : phase >= 3 ? "supply3" : "supply0"];
    else if (url === "/mi-proveedor/pedidos/" + f.order_id) body = f.supplier3;
    else if (url.includes("/remitos?"))
      body = phase >= 4 ? f.remitos : { remitos: [], total: 0 };
    else if (url.includes("/avisos?")) body = f.notices;
    else if (url.startsWith("/proveedores/") && url.endsWith("/ofertas"))
      body = f.offers;
    else if (url.startsWith("/auditoria/")) body = f.audit;
    else if (url.startsWith("/solicitudes-clientes?"))
      body = { solicitudes: [], total: 0 };
    else if (url.match(/^\/pedidos-venta\/\d+$/)) body = f.customer_order1;
    else if (url.startsWith("/pedidos-venta?")) body = f.customer_orders;
    else if (
      url.startsWith("/abastecimiento/pedidos?") ||
      url.startsWith("/mi-proveedor/pedidos?")
    )
      body = f.supply_orders;
    else throw new Error("Unexpected query " + url);
    return { status: 200, ok: true, json: async () => structuredClone(body) };
  };
  for (const file of [
    "messages.js",
    "i18n.js",
    "app.js",
    "ventas_caja.js",
    "devoluciones_web.js",
    "entregas_atencion.js",
    "cliente_web.js",
    "abastecimiento_web.js",
    "reposicion_simulada.js",
  ])
    run(fs.readFileSync(path.join(__dirname, "interfaz", file), "utf8"));
  return {
    w,
    run,
    f,
    calls,
    d: w.document,
    setPhase: (p) => (phase = p),
    user: (role) => {
      ctx.userFixture = structuredClone(f[role]);
      run('state.user=userFixture;state.auth="Basic fixture";showUser()');
    },
    close: async () => {
      run("stopDemoRefresh()");
      await w.happyDOM.abort();
    },
  };
}
const text = (a, id) => a.d.getElementById(id).textContent;
const flush = () => new Promise((r) => setTimeout(r, 15));
async function submit(a, selector) {
  a.d
    .querySelector(selector)
    .dispatchEvent(
      new a.w.Event("submit", { bubbles: true, cancelable: true }),
    );
  await flush();
  assert.notEqual(
    a.d.getElementById("mensaje").className,
    "error",
    text(a, "mensaje"),
  );
}

test("static login, navigation and language preference are bilingual", async () => {
  const a = await app();
  try {
    assert.match(text(a, "acceso"), /Ingresar al sistema/);
    assert.equal(a.run('setLanguage("en")'), true);
    assert.match(text(a, "acceso"), /Sign in/);
    assert.equal(a.d.documentElement.lang, "en");
    assert.equal(a.w.localStorage.getItem("commerce-demo-language"), "en");
    assert.match(a.d.title, /Business operations/);
    a.user("admin");
    await a.run("loadList(1)");
    assert.equal(text(a, "nav-reposicion-simulada"), "Simulated replenishment");
    assert.match(text(a, "resultados"), /Category/);
    assert.match(text(a, "resultados"), /Open Mouse/);
    a.run('setLanguage("es")');
    assert.match(text(a, "resultados"), /Categoría/);
    assert.match(text(a, "resultados"), /Abrir Mouse/);
    assert.equal(a.w.localStorage.length, 1);
    assert.equal(a.run("state.auth"), "Basic fixture");
  } finally {
    await a.close();
  }
});

test("language changes preserve product names, notes, input values and cart state", async () => {
  const a = await app();
  try {
    a.f.products.productos[0].nombre = "Recibido";
    a.user("customer");
    await a.run("addOnlineProduct(1)");
    a.run("showOnlineCart()");
    const state = a.run("JSON.stringify(cli.cart)");
    a.run('setLanguage("en")');
    assert.equal(a.run("JSON.stringify(cli.cart)"), state);
    assert.match(text(a, "cliente-web"), /Recibido/);
    assert.match(text(a, "cliente-web"), /My cart/);
    assert.equal(a.d.querySelector(".cantidad-carrito").value, "1");
    assert.equal(
      a.d.querySelector(".cantidad-carrito").getAttribute("aria-label"),
      "Quantity of Recibido",
    );
    a.user("admin");
    await a.run("openProduct(1)");
    a.run("editProduct(state.product)");
    a.d.getElementById("producto-marca").value = "Confirmar";
    a.run('setLanguage("es")');
    assert.equal(a.d.getElementById("producto-marca").value, "Confirmar");
    assert.equal(a.calls.filter((x) => x.method !== "GET").length, 0);
    const node = a.d.createElement("div");
    a.d.body.append(node);
    a.run('setLanguage("en")');
    a.run('globalThis.dataFixture={motivo:"Recibido",nombre:"Confirmar"}');
    a.run("renderDetails(document.body.lastChild,dataFixture)");
    assert.match(node.textContent, /Recibido/);
    assert.match(node.textContent, /Confirmar/);
  } finally {
    await a.close();
  }
});

for (const language of ["es", "en"])
  test(
    "funded replenishment workflow has identical writes in " + language,
    async () => {
      const a = await app(language);
      try {
        a.user("admin");
        await a.run("loadDemoSupply()");
        assert.match(
          text(a, "reposicion-web"),
          language === "en"
            ? /Insufficient simulated funds/
            : /Fondo simulado insuficiente/,
        );
        a.d.getElementById("aporte-simulado").value = "2000";
        await submit(a, "#reposicion-web form");
        assert.equal(a.calls.filter((x) => x.method !== "GET").length, 0);
        assert.equal(
          a.run(
            "setLanguage(" +
              JSON.stringify(language === "es" ? "en" : "es") +
              ")",
          ),
          false,
        );
        await a.run("pending()");
        assert.deepEqual(a.calls.find((x) => x.method === "PUT").data, {
          importe_centavos: 200000,
        });
        const buttons = [...a.d.querySelectorAll("button")];
        const pay = buttons.find(
          (x) =>
            x.textContent ===
            (language === "en"
              ? "Simulate approved payment"
              : "Simular pago aprobado"),
        );
        assert.ok(pay);
        pay.click();
        await flush();
        await a.run("pending()");
        assert.equal(
          a.calls.at(-2).method === "PUT" ||
            a.calls.some((x) => x.url.endsWith("/pago-aprobado")),
          true,
        );
        a.setPhase(3);
        a.user("employee");
        await a.run("showSupplyOrder(" + a.f.order_id + ")");
        assert.match(
          text(a, "abastecimiento-web"),
          language === "en"
            ? /Awaiting goods receipt/
            : /Falta recepción física/,
        );
        await a.run("supplyReceiptForm(" + a.f.order_id + ")");
        a.d.getElementById("recepcion-referencia").value = "delivery-i18n";
        a.d.getElementById("recepcion-cantidad").value = "3";
        a.d.getElementById("recepcion-costo").value = "500.50";
        await submit(a, "#abastecimiento-web form");
        await a.run("pending()");
        const receipt = a.calls.find((x) => x.url.includes("/recepciones/"));
        assert.deepEqual(receipt.data, {
          cantidad: 3,
          costo_pagado_centavos: 50050,
        });
        assert.match(
          text(a, "abastecimiento-web"),
          language === "en" ? /Received/ : /Recibido/,
        );
      } finally {
        await a.close();
      }
    },
  );

test("customer and supplier workflows expose English actions without translating data", async () => {
  const a = await app("en");
  try {
    a.user("customer");
    await a.run("showMyOrder(" + a.f.sale_id + ")");
    assert.match(text(a, "cliente-web"), /My order/);
    assert.match(text(a, "cliente-web"), /Final amount/);
    assert.match(text(a, "cliente-web"), /Approved/);
    assert.match(text(a, "cliente-web"), /Request cancellation/);
    a.run('setLanguage("es")');
    assert.match(text(a, "cliente-web"), /Solicitar cancelación/);
    a.user("supplier");
    a.run('setLanguage("en")');
    await a.run("showSupplyOrder(" + a.f.order_id + ")");
    assert.match(text(a, "proveedor-web"), /generated automatically/);
    assert.match(text(a, "proveedor-web"), /Supplier notices/);
    await a.run("loadSupplyOffers()");
    assert.match(text(a, "proveedor-web"), /My catalog/);
    a.run(
      "supply.draft=catalogDraft(" +
        JSON.stringify(a.f.offers) +
        ");editSupplyCatalog()",
    );
    assert.match(text(a, "proveedor-web"), /Prepare supplier catalog/);
    assert.match(text(a, "proveedor-web"), /Add to draft/);
  } finally {
    await a.close();
  }
});

test("API errors and background results are readable in English, with codes preserved", async () => {
  const a = await app("en");
  try {
    assert.equal(
      a.run('serverMessage("La referencia ya se usó con otros datos",409)'),
      "The reference was already used with different data",
    );
    assert.equal(
      a.run('tr("Producto 47 no encontrado")'),
      "Product 47 not found",
    );
    assert.equal(
      a.run(
        'serverMessage("Value error, La referencia ya se usó con otros datos",422)',
      ),
      "Invalid input: The reference was already used with different data",
    );
    assert.equal(a.run('label("pedido_generado")'), "Purchase order created");
    assert.equal(
      a.run(
        'JSON.stringify(operation("/pedidos/1/recepciones/x",{cantidad:3,costo_pagado_centavos:50050}).data)',
      ),
      '{"cantidad":3,"costo_pagado_centavos":50050}',
    );
  } finally {
    await a.close();
  }
});

test("automatic status refresh keeps the selected language and unsent form values", async () => {
  const a = await app("en");
  try {
    a.user("admin");
    await a.run("loadDemoSupply()");
    a.d.getElementById("aporte-simulado").value = "37.25";
    a.setPhase(3);
    await new Promise((r) => setTimeout(r, 2150));
    assert.match(
      text(a, "estado-reposicion-simulada"),
      /Awaiting goods receipt/,
    );
    assert.equal(a.d.getElementById("aporte-simulado").value, "37.25");
    assert.equal(a.calls.filter((x) => x.method !== "GET").length, 0);
  } finally {
    await a.close();
  }
});

test("simulated supplier notices are localized but user notes remain unchanged", async () => {
  const a = await app("en");
  try {
    a.user("supplier");
    await a.run("showSupplyOrder(" + a.f.order_id + ")");
    assert.match(text(a, "proveedor-web"), /Simulated dispatch/);
    assert.doesNotMatch(text(a, "proveedor-web"), /Despacho simulado/);
    a.f.supplier3.simulacion = null;
    a.f.supplier3.ultimo_aviso.nota = "Recibido";
    a.f.supplier3.acciones_aviso = ["confirmado"];
    await a.run("showSupplyOrder(" + a.f.order_id + ")");
    assert.match(text(a, "proveedor-web"), /Recibido/);
  } finally {
    await a.close();
  }
});


test('browser catalog matches the editable translation source',async()=>{const a=await app();try{const source=JSON.parse(fs.readFileSync(path.join(__dirname,'interfaz/messages.json'),'utf8'));assert.deepEqual(JSON.parse(a.run('JSON.stringify(MESSAGES)')),source);}finally{await a.close();}});
