// Pruebas de lógica de red en Node; no abre ni automatiza un navegador.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function setup(fetch) {
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',hidden:false,textContent:'',className:'',open:false,addEventListener(){},replaceChildren(){},reset(){},focus(){},close(){this.open=false;}});return nodes.get(id);};
  const context=vm.createContext({document:{getElementById:node,querySelectorAll:()=>[]},fetch,AbortController,setTimeout,clearTimeout,TextEncoder,btoa:x=>Buffer.from(x,'binary').toString('base64'),Intl,URLSearchParams,console});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/messages.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/i18n.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/app.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/ventas_caja.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/devoluciones_web.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/entregas_atencion.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/cliente_web.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/abastecimiento_web.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'interfaz/reposicion_simulada.js'),'utf8'),context);
  return {...vm.runInContext('({api,state,integer,encodeAuth,ops,operation,executeOperation,totals,staffOnly,pendingReturnLines,returnPayload,service,requestBase,loadRequests,loadDeliveries,reviewDelivery,cli,onlinePayload,customerOnly,loadMyOrders,loadMyRequests})',context),context,run:source=>vm.runInContext(source,context)};
}
test('los costos de proveedor usan centavos exactos y rechazan separadores ambiguos',()=>{
  const app=setup();assert.equal(app.run("parseCost('1200,50')"),120050);assert.equal(app.run("parseCost('0.01')"),1);assert.equal(app.run("costText(parseCost('500,50'))"),'500.50');
  for(const value of ['1.200','1,234','-5','0','1e3','1.000,50','NaN'])assert.throws(()=>app.run('parseCost('+JSON.stringify(value)+')'));
});
test('pago simulado prepara sólo la operación del pedido seleccionado',()=>{
  const app=setup();app.state.user={rol_efectivo:'administrador'};
  app.run('reviewOperation=(rows,op)=>{globalThis.revisado={rows,op};};reviewDemoPayment({pedido_id:8,proveedor:"demo",importe_centavos:150150})');
  const data=app.run('revisado');assert.equal(data.op.path,'/reposicion-simulada/pedidos/8/pago-aprobado');assert.equal(data.op.method,'PUT');assert.equal(data.op.data,undefined);
  assert.ok(data.rows.some(x=>String(x[1]).includes('No aumenta')));
});
test('regla general de la prueba se activa sin configurar reglas individuales',()=>{
  const app=setup();app.state.user={rol_efectivo:'administrador'};
  app.run('reviewOperation=(rows,op)=>{globalThis.revisado={rows,op};};reviewDemoConfig({id:6,nombre:"Prueba",stock:0},true)');
  const op=app.run('revisado.op');assert.equal(op.path,'/reposicion-simulada/configuracion');assert.deepEqual(JSON.parse(JSON.stringify(op.data)),{producto_id:6,activa:true});
});
test('empleado no puede confirmar pagos ficticios ni activar la regla',()=>{
  const app=setup();app.state.user={rol_efectivo:'empleado'};
  assert.throws(()=>app.run('reviewDemoPayment({pedido_id:8})'),/administrador/);
  assert.throws(()=>app.run('reviewDemoConfig({id:6},true)'),/administrador/);
});
test('el borrador conserva todas las ofertas vigentes y omite inactivas',()=>{
  const app=setup(),rows=app.run("catalogDraft([{vigente:1,id_externo:'a',nombre:'Mouse',marca:'Demo',categoria:'tecnologia',costo_centavos:50050,stock_proveedor:3},{vigente:0,id_externo:'b'},{vigente:1,id_externo:'c',nombre:'Pan',marca:'Demo',categoria:'alimento',costo_centavos:101,stock_proveedor:4}])");
  assert.deepEqual(JSON.parse(JSON.stringify(rows)).map(x=>[x.id,x.precio,x.stock]),[['a','500.50',3],['c','1.01',4]]);
});
test('recepción incierta reusa remito y costo exacto sin adoptar cambios posteriores',async()=>{
  const calls=[],app=setup(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);if(calls.length===1){const e=new Error('red');e.name='AbortError';throw e;}return {status:200,ok:true,json:async()=>({estado:'parcial'})};});
  const data={cantidad:1,costo_pagado_centavos:50050},op=app.operation('/pedidos/4/recepciones/real-1',data);data.costo_pagado_centavos=99000;
  await assert.rejects(app.executeOperation(op));await app.executeOperation(op);assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1][1].costo_pagado_centavos,50050);
});
test('evaluación de reposición conserva POST sin enviar un cuerpo inventado',async()=>{
  const calls=[],app=setup(async(url,options)=>{calls.push([url,options]);return {status:200,ok:true,json:async()=>({estado:'con_stock'})};});
  await app.executeOperation(app.operation('/productos/7/reposicion',undefined,'POST'));assert.equal(calls[0][1].method,'POST');assert.equal(calls[0][1].body,undefined);
});
test('proveedor y administración restringen sus recorridos también en la interfaz',()=>{
  const app=setup();for(const role of ['cliente','empleado','administrador']){app.state.user={rol_efectivo:role};assert.throws(()=>app.run('supplierOnly()'),/proveedor/);}
  app.state.user={rol_efectivo:'proveedor',proveedor:'demo'};app.run('supplierOnly()');assert.throws(()=>app.run('supplyAdmin()'),/administrador/);
  app.state.user={rol_efectivo:'administrador'};app.run('supplyAdmin()');
});
test('las peticiones no usan cookies ni caché y mantienen el cuerpo JSON',async()=>{
  const calls=[];const app=setup(async(...args)=>{calls.push(args);return {status:200,ok:true,json:async()=>({id:1})};});
  app.state.auth='Basic prueba';
  await app.api('/productos/1','PATCH',{precio:9000});
  const [url,options]=calls[0];assert.equal(url,'/productos/1');assert.equal(options.credentials,'omit');assert.equal(options.cache,'no-store');
  assert.equal(options.headers.Authorization,'Basic prueba');assert.equal(options.headers['X-Interfaz-Web'],'1');assert.deepEqual(JSON.parse(options.body),{precio:9000});
});
test('una escritura sin respuesta informa incertidumbre y no se reenvía',async()=>{
  let calls=0;const app=setup(async()=>{calls++;const error=new Error('timeout');error.name='AbortError';throw error;});
  await assert.rejects(app.api('/productos','POST',{nombre:'Prueba'}),/podría haberse guardado/);assert.equal(calls,1);
});
test('una sesión inválida elimina su autorización y sus datos de usuario',async()=>{
  const app=setup(async()=>({status:401,ok:false,json:async()=>({detail:'Credenciales inválidas'})}));
  app.state.auth='Basic prueba';app.state.user={usuario:'ejemplo'};app.state.product={producto:{id:1}};
  await assert.rejects(app.api('/productos'),/contraseña incorrectos/);
  assert.equal(app.state.auth,null);assert.equal(app.state.user,null);assert.equal(app.state.product,null);
});
test('un conflicto conserva el mensaje de la API para poder corregirlo',async()=>{
  const app=setup(async()=>({status:409,ok:false,json:async()=>({detail:'El producto ya existe'})}));
  await assert.rejects(app.api('/productos','POST',{}),/El producto ya existe/);
});

test('un cobro sin respuesta se reintenta con la misma referencia y una copia de sus datos',async()=>{
  const calls=[];const app=setup(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);if(calls.length===1){const e=new Error('red');e.name='AbortError';throw e;}return {status:200,ok:true,json:async()=>({pedido_venta_id:12})};});
  const data={caja:'turno',recibido:10000,total_esperado:8500,productos:[{producto_id:1,cantidad:1}]};
  const op=app.operation('/ventas-efectivo/venta-web-fija',data);data.productos[0].cantidad=9;
  await assert.rejects(app.executeOperation(op),/podría haberse guardado/);assert.equal(app.ops.incierta,op);
  const result=await app.executeOperation(op);assert.equal(result.pedido_venta_id,12);assert.equal(app.ops.incierta,null);
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1][1].productos[0].cantidad,1);
});
test('el comprobante se recibe como HTML y no intenta decodificarse como JSON',async()=>{
  const app=setup(async()=>({status:200,ok:true,text:async()=>'<html>Comprobante</html>',json:async()=>{throw new Error('no es JSON');}}));
  assert.equal(await app.api('/pedidos-venta/12/ticket','GET',undefined,'text'),'<html>Comprobante</html>');
});
test('un conflicto conocido no deja bloqueada la pantalla como respuesta incierta',async()=>{
  const app=setup(async()=>({status:409,ok:false,json:async()=>({detail:'El precio cambió'})}));
  const op=app.operation('/ventas-efectivo/fija',{});app.ops.incierta=op;
  await assert.rejects(app.executeOperation(op),/El precio cambió/);assert.equal(app.ops.incierta,null);
});
test('los totales del carrito mantienen precisión y rechazan desbordamientos',()=>{
  const app=setup();assert.equal(app.totals([{precio:8500,cantidad:2},{precio:7500,cantidad:1}]),24500);
  assert.throws(()=>app.totals([{precio:Number.MAX_SAFE_INTEGER,cantidad:2}]),/rango admitido/);
});
test('ventas y caja no habilitan el recorrido para clientes ni proveedores',()=>{
  const app=setup();for(const rol of ['cliente','proveedor']){app.state.user={rol_efectivo:rol};assert.throws(()=>app.staffOnly(),/personal/);}
  app.state.user={rol_efectivo:'empleado'};app.staffOnly();
});

test('una escritura con respuesta ilegible conserva la operación para el mismo reintento',async()=>{
  const app=setup(async()=>({status:502,ok:false,json:async()=>{throw new SyntaxError('HTML');}}));
  const op=app.operation('/ventas-efectivo/fija',{});
  await assert.rejects(app.executeOperation(op),/misma referencia/);assert.equal(app.ops.incierta,op);
});

function saleFixture(){return {productos:[{producto_id:4,nombre:'Joystick',cantidad:3,precio_unitario:1000}],devoluciones:{operaciones:[{productos:[{producto_id:4,cantidad:1,reponer:true}]}]}};}
test('la devolución propone sólo la cantidad todavía no recibida',()=>{
  const app=setup(),p=saleFixture();assert.equal(app.pendingReturnLines(p)[0].pendientes,2);
  p.devoluciones.operaciones.push({productos:[{producto_id:4,cantidad:2,reponer:false}]});assert.equal(app.pendingReturnLines(p).length,0);
});
test('el resumen usa precio original y permite recepción no apta',()=>{
  const app=setup();const payload=app.returnPayload(saleFixture(),[{producto_id:4,cantidad:2,reponer:false}],'  Recibido roto  ');
  assert.equal(payload.amount,2000);assert.equal(payload.data.motivo,'Recibido roto');assert.equal(payload.data.productos[0].reponer,false);
});
test('no envía devolución vacía, excesiva ni sin decisión sobre stock',()=>{
  const app=setup(),p=saleFixture();
  for(const values of [[{producto_id:4,cantidad:0,reponer:null}],[{producto_id:4,cantidad:3,reponer:true}],[{producto_id:4,cantidad:1,reponer:null}]])assert.throws(()=>app.returnPayload(p,values,'Motivo'));
  assert.throws(()=>app.returnPayload(p,[{producto_id:4,cantidad:1,reponer:true}],'  '),/motivo/);
});
test('referencias de reintegro y caja se conservan si se pierde la respuesta',async()=>{
  const calls=[];const app=setup(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);if(calls.length===1){const e=new Error('red');e.name='AbortError';throw e;}return {status:200,ok:true,json:async()=>({importe_por_reintegrar:0})};});
  const op=app.operation('/pedidos-venta/12/devoluciones/dev-web/reintegro',{estado:'confirmado',caja_esperada:'turno-web'});
  await assert.rejects(app.executeOperation(op));await app.executeOperation(op);assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1][1].caja_esperada,'turno-web');
});

test('el filtro de atención conserva el pedido seleccionado y pagina en la API',async()=>{
  let path;const app=setup(async url=>{path=url;return {status:409,ok:false,json:async()=>({detail:'Fin de consulta de prueba'})};});
  app.state.user={rol_efectivo:'empleado'};app.service.requestOrder=12;app.service.requestState='pendiente_revision';
  await assert.rejects(app.loadRequests(2));const params=new URL(path,'http://localhost').searchParams;
  assert.equal(params.get('pedido_id'),'12');assert.equal(params.get('estado'),'pendiente_revision');assert.equal(params.get('pagina'),'2');
});
test('entregas solicita sólo pendientes cuando corresponde',async()=>{
  let path;const app=setup(async url=>{path=url;return {status:409,ok:false,json:async()=>({detail:'Fin de consulta'})};});app.state.user={rol_efectivo:'empleado'};
  await assert.rejects(app.loadDeliveries());assert.equal(new URL(path,'http://localhost').searchParams.get('pendientes_entrega'),'true');
  app.service.onlyPending=false;await assert.rejects(app.loadDeliveries());assert.equal(new URL(path,'http://localhost').searchParams.has('pendientes_entrega'),false);
});
test('revisar una entrega sólo prepara el próximo paso y no lo escribe',async()=>{
  const calls=[];const app=setup(async(url,options)=>{calls.push(options.method);return {status:200,ok:true,json:async()=>({estado_entrega:'listo',siguiente_estado_entrega:'enviado'})};});
  let op;app.context.capture=(rows,operation)=>{op=operation;};app.run('reviewOperation=capture');await app.reviewDelivery(5);
  assert.deepEqual(calls,['GET']);assert.equal(op.path,'/pedidos-venta/5/entrega');assert.equal(op.data.estado,'enviado');
});
test('al vencer la sesión se borran también filtros del cliente atendido',async()=>{
  const app=setup(async()=>({status:401,ok:false,json:async()=>({detail:'Vencida'})}));app.state.user={usuario:'operador'};app.service.requestOrder=99;app.service.requestState='atendida';
  await assert.rejects(app.api('/sesion'));assert.equal(app.service.requestOrder,null);assert.equal(app.service.requestState,'pendiente_revision');
});

test('compra online en retiro no envía una dirección guardada de otra preparación',()=>{
  const app=setup();const payload=app.onlinePayload([{id:4,cantidad:1}],'retiro','Dirección anterior');
  assert.equal(payload.canal,'online');assert.equal(payload.modalidad,'retiro');assert.equal('direccion_entrega' in payload,false);
});
test('compra con envío exige dirección completa y cantidades válidas',()=>{
  const app=setup();const payload=app.onlinePayload([{id:4,cantidad:1}],'envio','  Calle 123, Ciudad  ');
  assert.equal(payload.direccion_entrega,'Calle 123, Ciudad');
  assert.throws(()=>app.onlinePayload([{id:4,cantidad:1}],'envio',''),/dirección/);
  assert.throws(()=>app.onlinePayload([{id:4,cantidad:0}],'retiro',''),/cantidades/);
  assert.throws(()=>app.onlinePayload([{id:4,cantidad:1},{id:4,cantidad:1}],'retiro',''),/repitas/);
});
test('la lista de pedidos del cliente usa la ruta de titularidad y pagina',async()=>{
  let path;const app=setup(async url=>{path=url;return {status:409,ok:false,json:async()=>({detail:'Fin de consulta'})};});app.state.user={rol_efectivo:'cliente'};
  await assert.rejects(app.loadMyOrders(2));assert.equal(new URL(path,'http://localhost').pathname,'/pedidos-venta');assert.equal(new URL(path,'http://localhost').searchParams.get('pagina'),'2');
});
test('cerrar por credenciales inválidas borra carrito y dirección del cliente',async()=>{
  const app=setup(async()=>({status:401,ok:false,json:async()=>({detail:'Vencida'})}));app.state.user={usuario:'ana'};app.cli.cart=[{id:4,cantidad:1}];app.cli.address='Dirección personal';app.cli.requestOrder=13;
  await assert.rejects(app.api('/sesion'));assert.equal(app.cli.cart.length,0);assert.equal(app.cli.address,'');assert.equal(app.cli.requestOrder,null);
});
test('un pedido online sin respuesta conserva referencia y datos al reintentar',async()=>{
  const calls=[];const app=setup(async(url,options)=>{calls.push([url,JSON.parse(options.body)]);if(calls.length===1){const e=new Error('red');e.name='AbortError';throw e;}return {status:200,ok:true,json:async()=>({pedido_venta_id:14})};});
  const op=app.operation('/cobros-demo/compra-web-fija',app.onlinePayload([{id:4,cantidad:1}],'retiro',''));
  await assert.rejects(app.executeOperation(op));await app.executeOperation(op);assert.deepEqual(calls[0],calls[1]);
});
test('la sección del cliente no permite usar una cuenta de personal o proveedor',()=>{
  const app=setup();for(const rol of ['administrador','empleado','proveedor']){app.state.user={rol_efectivo:rol};assert.throws(()=>app.customerOnly(),/cliente/);}
  app.state.user={rol_efectivo:'cliente'};app.customerOnly();
});
