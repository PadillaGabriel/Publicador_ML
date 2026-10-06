# Publicador ML Enterprise — Plan maestro de QA y aceptación

**Versión:** 1.0 · **Estado del proyecto:** plan de pruebas; la ejecución y aprobación están pendientes.  
**Alcance:** módulos existentes, seguridad multiusuario (Entrega 2), gestor e historial, actualizaciones individuales y masivas, publicación multicuenta, precios y consolidación operativa (entrega integral propuesta).  
**Regla:** ningún resultado se considera aprobado sin ejecución, evidencia y versión identificada. Casos de funcionalidades aún no desarrolladas = `NO IMPLEMENTADO`, nunca `APROBADO`.

## 0. Registro de ejecución

- **Versión exacta / commit / hash ZIP:** __________
- **Fecha y hora:** __________
- **Entorno:** __________  **URL:** __________
- **Versión PostgreSQL / revisión Alembic:** __________
- **Versión frontend compilada:** __________
- **Versión backend / Python:** __________
- **Cuentas Mercado Libre de prueba:** __________
- **Usuarios de prueba:** Administrador A; Supervisor S; Operadores O1 y O2
- **Ejecutor QA:** __________  **Aprobador:** __________
- **Respaldo previo realizado y restauración ensayada:** __________
- **Incidencias abiertas / enlaces:** __________

### Convenciones

- **Prioridad:** `P0` bloquea producción; `P1` bloquea aceptación del módulo; `P2` mejora o caso no crítico.
- **Estado por caso:** `NO EJECUTADO` / `APROBADO` / `FALLÓ` / `BLOQUEADO` / `NO IMPLEMENTADO` / `NO APLICA`.
- **Evidencia mínima:** fecha, usuario de prueba, identificadores sintéticos usados, captura o respuesta HTTP sin secretos, logs de correlación y observación.
- **Datos:** usar SKU y publicaciones de prueba; no modificar publicaciones comerciales reales durante QA destructivo. Habilitar acciones reales de Mercado Libre solo sobre publicaciones controladas.
- **Separar ambientes:** primero local/staging. El ciclo real de publicación debe contar con autorización explícita y datos de prueba recuperables.

## A. Instalación, integridad y regresión base

- [ ] **QA-001 · P0 · Inventario reproducible.** Identificar ZIP consolidado y hash; verificar que no faltan archivos frente al manifiesto entregado. Resultado: versión unívoca y replicable.
- [ ] **QA-002 · P0 · Configuración sin secretos.** Verificar que `.env`, cookies, OAuth tokens, contraseñas y bases de datos no están en el ZIP de distribución ni en repositorio. Resultado: no hay exposición de secretos.
- [ ] **QA-003 · P0 · Migraciones.** En una copia de BD, ejecutar `alembic upgrade head`; verificar revisión y que no se pierden fichas, cuentas, versiones, lotes, jobs ni auditoría.
- [ ] **QA-004 · P0 · Respaldo/restauración.** Respaldar la BD, restaurarla en ambiente controlado y comprobar que los identificadores y relaciones se conservan.
- [ ] **QA-005 · P0 · Build frontend.** Ejecutar `npm run build` en instalación limpia. Resultado: salida exitosa, sin errores TypeScript.
- [ ] **QA-006 · P0 · Arranque backend.** Reiniciar API y workers con BD operativa. Resultado: sin errores de importación, migración, dependencia o configuración.
- [ ] **QA-007 · P1 · Arranque sin servicios.** Simular BD indisponible. Resultado: falla identificable, sin aceptar operaciones aparentemente exitosas ni perder trazas.
- [ ] **QA-008 · P1 · Regresión comercial.** Abrir ficha histórica, recuperar SKU, editar imágenes, cálculos y logística. Resultado: no se degradan funciones preexistentes.
- [ ] **QA-009 · P1 · Regresión navegador.** Probar recarga dura, volver/avanzar, dos pestañas y tamaño móvil. Resultado: navegación estable, sin estado comercial cruzado.

## B. Autenticación, sesiones y endurecimiento

- [ ] **QA-010 · P0 · Sesión anónima.** Sin cookie, consultar cada familia de API comercial y descarga privada. Resultado: `401` o rechazo seguro, sin datos.
- [ ] **QA-011 · P0 · Login válido.** Administrador, Supervisor y Operador inician sesión por separado. Resultado: identidad y rol correctos.
- [ ] **QA-012 · P0 · Contraseña errónea.** Credenciales incorrectas. Resultado: rechazo sin detallar si el usuario existe.
- [ ] **QA-013 · P0 · Logout.** Cerrar sesión y repetir solicitud con cookie anterior. Resultado: sesión revocada; API no devuelve datos privados.
- [ ] **QA-014 · P0 · Desactivación.** Desactivar O1 en sesión activa. Resultado: no puede seguir operando ni emitir nuevas solicitudes autenticadas.
- [ ] **QA-015 · P0 · Cambio de contraseña.** Cambiar contraseña de O1. Resultado: sesiones anteriores revocadas; antigua contraseña rechazada.
- [ ] **QA-016 · P0 · Elevación de privilegios.** Supervisor intenta crear/promover/editar Administradores mediante UI y API manual. Resultado: `403`.
- [ ] **QA-017 · P0 · Último Administrador.** Intentar desactivar el último Administrador activo. Resultado: rechazado.
- [ ] **QA-018 · P0 · CSRF y origen.** Intentar mutación desde origen no autorizado, con y sin cabeceras exigidas. Resultado: rechazo; callback OAuth sigue protegido y operativo.
- [ ] **QA-019 · P0 · Cookies.** Inspeccionar `Set-Cookie`: `HttpOnly`, política `SameSite`, `Secure` bajo HTTPS, expiración y alcance adecuados; sin tokens en `localStorage`.
- [ ] **QA-020 · P0 · Fuerza bruta.** En usuario de prueba, superar límite configurado de fallos. Resultado: `429` persistente tras reinicio y recuperación conforme política.
- [ ] **QA-021 · P1 · Sesión caducada.** Dejar vencer la sesión durante una ficha abierta. Resultado: se solicita login; no se envía un guardado anónimo.
- [ ] **QA-022 · P1 · Contraseña sensible.** Verificar que logs, excepciones, auditoría y consola no exponen contraseña, hash, cookie o secretos OAuth.
- [ ] **QA-023 · P1 · Múltiples sesiones.** Abrir O1 en dos navegadores, cerrar una sesión y verificar política de revocación prevista.

## C. Gestión de usuarios y cuentas Mercado Libre

- [ ] **QA-024 · P0 · RBAC backend.** Repetir acciones prohibidas invocando API directamente, aunque el botón no aparezca. Resultado: backend deniega.
- [ ] **QA-025 · P0 · Asignación O1.** Autorizar a O1 solo cuenta ML-A. Resultado: puede verla y no puede operar en ML-B.
- [ ] **QA-026 · P0 · Alcance indirecto.** Desde O1, intentar usar identificadores `batch_id`, `draft_id`, `job_id`, imágenes y exportes de ML-B. Resultado: acceso denegado.
- [ ] **QA-027 · P0 · Cambio de asignación.** Quitar ML-A a O1 durante sesión activa. Resultado: solicitudes posteriores dejan de permitir operar en ML-A.
- [ ] **QA-028 · P0 · Supervisor/Administradores.** Supervisor intenta administrar un Administrador o sus asignaciones vía API. Resultado: `403`.
- [ ] **QA-029 · P1 · Persistencia.** Modificar asignaciones, recargar y reiniciar API. Resultado: valores consistentes en UI y BD.
- [ ] **QA-030 · P1 · Usuarios desactivados.** Intentar crear trabajo usando sesión, cookie o identificador de usuario desactivado. Resultado: rechazado.

## D. Propiedad de fichas, versiones y edición exclusiva

- [ ] **QA-031 · P0 · Ficha propia.** O1 crea y recupera ficha SKU-TEST-O1. Resultado: propietario O1 y lectura permitida.
- [ ] **QA-032 · P0 · Ficha ajena.** O2 intenta abrir/editar la ficha de O1, compartiendo cuenta ML. Resultado: `403` en backend.
- [ ] **QA-033 · P0 · Histórica sin propietario.** O1 intenta editar ficha histórica sin `created_by_user_id`. Resultado: denegado; Administrador conserva acceso.
- [ ] **QA-034 · P0 · Adquisición concurrente.** O1 adquiere bloqueo; Administrador/O2 intenta adquirirlo en otra sesión. Resultado: solo un titular, segundo recibe `409`.
- [ ] **QA-035 · P0 · Token faltante/ajeno.** Intentar modificar versión o imágenes sin token o con token de otra sesión. Resultado: rechazo (`428`/`409`) sin escritura parcial.
- [ ] **QA-036 · P0 · Token vencido.** Vencer el lease e intentar guardar con token anterior. Resultado: rechazo, incluso si existe nueva titularidad.
- [ ] **QA-037 · P0 · Versión desactualizada.** Solicitar guardar sobre número de versión anterior. Resultado: `409`; no sobrescribe la versión vigente.
- [ ] **QA-038 · P0 · Corrección desde lote.** Intentar `product-correction` sin bloqueo/version; luego repetir con bloqueo válido. Resultado: rechazo primero, escritura y auditoría coherentes después.
- [ ] **QA-039 · P1 · Renovación.** Mantener edición abierta más de dos minutos. Resultado: renovación evita expiración accidental, sin dos titulares simultáneos.
- [ ] **QA-040 · P1 · Desconexión.** Cerrar navegador abruptamente y esperar vencimiento. Resultado: bloqueo recuperable por usuario autorizado.
- [ ] **QA-041 · P1 · Nueva publicación.** Salir de ficha con cambios pendientes. Resultado: confirmación; limpiar datos temporales sin borrar trabajo histórico ni bloquear permanentemente la ficha.
- [ ] **QA-042 · P1 · Guardado simultáneo.** Dos solicitudes concurrentes del titular y otra sesión. Resultado: una secuencia de versiones válida, sin versiones duplicadas ni datos cruzados.

## E. Imágenes, atributos, títulos y validación previa

- [ ] **QA-043 · P0 · Upload autorizado.** O1 carga imágenes de ficha propia con bloqueo. Resultado: archivo y metadatos asociados a ficha/versión correcta.
- [ ] **QA-044 · P0 · Upload ajeno.** O2 intenta cargar o borrar imágenes de ficha de O1. Resultado: `403` sin cambio.
- [ ] **QA-045 · P0 · Descarga privada.** Acceder a `/uploads/` sin sesión o a imágenes ajenas. Resultado: rechazo; no existe acceso público inadvertido.
- [ ] **QA-046 · P0 · Publicación de prueba con imágenes.** Prevalidar/publicar ficha de prueba. Resultado: Mercado Libre recibe y acepta todas las imágenes sin abrir `/uploads/` al público.
- [ ] **QA-047 · P1 · Orden de imágenes.** Cambiar portada y orden; publicar. Resultado: orden y portada coinciden con la confirmación previa.
- [ ] **QA-048 · P1 · Reutilización en lote.** Validar varios borradores que comparten imágenes. Resultado: no hay subidas innecesarias dentro de una misma validación.
- [ ] **QA-049 · P1 · Referencias inválidas.** Usar identificador de imagen borrada/de otra ficha. Resultado: validación falla de forma explícita.
- [ ] **QA-050 · P1 · Imagen 2400×2400.** Cargar imagen de prueba según límites aceptados del producto. Resultado: respuesta clara y procesamiento estable; registrar tamaño y uso de memoria.
- [ ] **QA-051 · P1 · Títulos.** Generar títulos nuevos en varias cuentas. Resultado: cumplimiento de restricciones de ML y unicidad del lote donde sea exigida.
- [ ] **QA-052 · P0 · Atributos ajenos.** O2 reutiliza atributos de la ficha de O1 o de cuenta no asignada. Resultado: backend rechaza.
- [ ] **QA-053 · P1 · GTIN y variaciones.** Probar producto individual, pack/set y variantes. Resultado: atributos coherentes, errores ML visibles sin fallbacks silenciosos.

## F. Borradores, trabajos y publicación

- [ ] **QA-054 · P0 · Crear lote propio.** O1 crea lote a partir de versión propia, en ML-A autorizada. Resultado: lote vinculado a cuenta/ficha/usuario.
- [ ] **QA-055 · P0 · Crear lote ajeno.** O2 intenta generar lote sobre versión de O1 o cuenta ML-B. Resultado: `403`.
- [ ] **QA-056 · P0 · Mutar borrador ajeno.** O2 edita, aprueba o excluye borrador de O1 mediante ID. Resultado: `403` y sin cambio.
- [ ] **QA-057 · P0 · Job ajeno.** O2 consulta, cancela o exporta trabajo de O1. Resultado: permisos según propiedad y cuenta; no filtra información ajena.
- [ ] **QA-058 · P0 · Idempotencia/reintentos.** Reenviar solicitud de publicación o reiniciar worker durante ejecución. Resultado: no hay publicaciones duplicadas por reproceso.
- [ ] **QA-059 · P0 · Publicación parcial.** Simular error de una publicación dentro de un lote. Resultado: éxito/error individualizados, sin reportar todo el lote como éxito.
- [ ] **QA-060 · P0 · Publicación multicuenta.** Una ficha, dos cuentas ML autorizadas. Resultado: trabajos/publicaciones por cuenta correctos, títulos únicos cuando se requieran.
- [ ] **QA-061 · P0 · Solicitud sin permiso.** Alterar manualmente `account_id` de una publicación en tránsito. Resultado: backend rechaza la cuenta no asignada.
- [ ] **QA-062 · P1 · Prevalidación.** Error de imagen/atributo/precio. Resultado: borrador no publicable y error legible, sin subidas erróneas.
- [ ] **QA-063 · P1 · Cancelación.** Cancelar job pendiente/con curso bajo política. Resultado: estado persistido, sin cancelar publicaciones ya materializadas, autoría registrada.
- [ ] **QA-064 · P1 · Recuperación job.** Reiniciar API y worker durante job de prueba. Resultado: recuperación consistente, sin trabajos fantasma ni duplicación.
- [ ] **QA-065 · P1 · Historial de resultado.** Consultar estados, errores y MLA definitivo tras una ejecución. Resultado: coincide con respuesta de ML y BD.
- [ ] **QA-066 · P1 · OAuth ML.** Reconectar cuenta de prueba. Resultado: callback firmado válido, sin desactivar autenticación en otras rutas.

## G. Gestor e historial (funcionalidad de entrega integral)

- [ ] **QA-067 · P0 · Búsqueda multiidentificador.** Buscar por SKU y MLA; comprobar resultados de todas las cuentas autorizadas.
- [ ] **QA-068 · P1 · Variaciones.** Buscar por ID de variación; mostrar publicación y relación con SKU correctamente.
- [ ] **QA-069 · P1 · Múltiples MLA por SKU.** Un SKU vinculado a varias publicaciones/cuentas. Resultado: sin colapsar registros distintos.
- [ ] **QA-070 · P1 · Filtros.** Cuenta, estado, fecha, responsable y paginación; resultado y totales coherentes.
- [ ] **QA-071 · P0 · Aislamiento del historial.** O1 no visualiza publicaciones/trabajos no autorizados aunque cambie filtros o parámetros de exportación.
- [ ] **QA-072 · P1 · Trazabilidad.** Mostrar quién, cuándo, qué cambió, resultado/error y referencia a job o publicación.
- [ ] **QA-073 · P1 · Exportación.** Exportar listado; filas, columnas, filtros y permisos coinciden con la vista.

## H. Actualización individual y masiva (funcionalidad de entrega integral)

- [ ] **QA-074 · P0 · Selección específica.** Seleccionar una MLA entre varias del mismo SKU. Resultado: no actualizar otras MLA por accidente.
- [ ] **QA-075 · P0 · Vista previa.** Mostrar valor anterior/nuevo, campo, cuenta, motivo y cantidad de destinos antes de ejecutar.
- [ ] **QA-076 · P0 · Confirmación.** Sin confirmación explícita no se efectúan cambios remotos.
- [ ] **QA-077 · P0 · Permisos.** Intentar actualizar una MLA de cuenta no asignada mediante request manual. Resultado: `403`.
- [ ] **QA-078 · P0 · Actualización parcial.** Modificar solo precio o stock; verificar que atributos no seleccionados no se sobrescriben.
- [ ] **QA-079 · P0 · Fallos parciales masivos.** Uno de diez MLA falla. Resultado: éxito/error por MLA, reintento selectivo y auditoría.
- [ ] **QA-080 · P1 · Volumen.** Ejecutar actualización masiva de prueba representativa. Resultado: progreso, cancelación y consumo de recursos dentro de objetivos medidos.
- [ ] **QA-081 · P1 · Concurrencia de cambios.** Cambiar precio remoto entre previsualización y confirmación. Resultado: detectar diferencia cuando sea posible y evitar sobrescritura ciega.
- [ ] **QA-082 · P1 · Idempotencia.** Reintentar tras timeout. Resultado: no aplicar dos veces incrementos porcentuales.

## I. Precios y reglas comerciales (funcionalidad de entrega integral)

- [ ] **QA-083 · P0 · Precio clásico compartido.** Actualizar base clásica e inspeccionar propuestas para todas las MLA vinculadas sin aplicar cambios no confirmados.
- [ ] **QA-084 · P0 · Excepción por MLA.** Precio manual de una MLA no se sobrescribe silenciosamente por un cambio global.
- [ ] **QA-085 · P0 · Cuotas 3 y 6.** Configurar recargos independientes; validar fórmulas, redondeo y payload enviado a ML.
- [ ] **QA-086 · P0 · Precio mayorista.** Comprobar niveles mayoristas, descuentos configurados y edición manual, sin duplicar escalones.
- [ ] **QA-087 · P1 · Margen.** Recalcular manualmente costo, comisiones, cargo fijo, logística e impuestos configurados; resultado coherente y claramente orientativo si corresponde.
- [ ] **QA-088 · P1 · Datos faltantes.** Falta costo o tarifa. Resultado: estado no confiable explícito, nunca recomendación inventada.
- [ ] **QA-089 · P1 · Precio 0.** Verificar contrato comercial de precio cero y mensaje previsto; no confundir cero válido con dato ausente.
- [ ] **QA-090 · P1 · Edición posterior.** Después del cálculo, modificar precio manual y asegurar que se conserva hasta confirmación.

## J. Rendimiento, operación y resiliencia

- [ ] **QA-091 · P0 · Integridad referencial.** Identificadores de cuentas, usuarios, versiones, lotes y jobs sin referencias huérfanas; migraciones consistentes.
- [ ] **QA-092 · P0 · Secretos y despliegue.** Variables críticas fuera del repositorio; HTTPS y callback OAuth restringidos a host esperado.
- [ ] **QA-093 · P0 · Recuperación.** Simular caída de API y worker; comprobar reinicio, continuidad de jobs, reconciliación e integridad.
- [ ] **QA-094 · P0 · RPO.** Simular pérdida/restauración controlada; medir pérdida efectiva y contrastar con objetivo RPO ≤ 5 min.
- [ ] **QA-095 · P0 · RTO.** Cronometrar desde fallo hasta operación recuperada; contrastar con objetivo RTO ≤ 5 min.
- [ ] **QA-096 · P1 · Objetivo de capacidad.** Ejecutar carga representativa de >500 publicaciones/día y actualizaciones masivas. Medir throughput, colas y fallas sin asumir que el objetivo ya se cumple.
- [ ] **QA-097 · P1 · Concurrencia 10 usuarios.** Simular 10 sesiones y medir errores, latencia por operación y bloqueos de BD.
- [ ] **QA-098 · P1 · Memoria.** Ejecutar generación de títulos, imágenes y validación bajo carga; registrar RSS/working set, pico y reinicios.
- [ ] **QA-099 · P1 · Métricas P95.** Medir latencia P95 real por endpoint y jornada; fijar SLO por operación solo después de datos representativos.
- [ ] **QA-100 · P1 · Disponibilidad.** Definir ventana de observación, registrar incidentes y evaluar objetivo ≥99,5% en 30 días; no declararlo aprobado por una prueba instantánea.
- [ ] **QA-101 · P1 · Observabilidad.** Eventos estructurados con `request_id`, `job_id`, actor autorizado, latencia, motivo de fallo; sin secretos ni títulos innecesarios.
- [ ] **QA-102 · P1 · Reintentos API ML.** Simular `429`, expiración OAuth, timeout y error `5xx`. Resultado: reintentos acotados, backoff y error trazable.
- [ ] **QA-103 · P1 · Compatibilidad UI.** Probar Opera/Chrome y ventanas estrechas; sin botones desbordados ni menús inaccesibles.
- [ ] **QA-104 · P2 · Accesibilidad básica.** Foco de teclado, formularios etiquetados, mensajes claros, estados de carga y contraste de botones.

## K. Verificación de auditoría y cumplimiento

- [ ] **QA-105 · P0 · Autoría servidor.** Interceptar request e intentar sustituir `actor_user_id`. Resultado: backend registra identidad de cookie real.
- [ ] **QA-106 · P0 · Mutación + auditoría.** Crear/corregir ficha, aprobar borrador, cargar imagen, cancelar job y modificar permisos. Resultado: evento correspondiente consistente con transacción.
- [ ] **QA-107 · P1 · Históricos.** Verificar que registros anteriores al login mantienen autor `NULL`/desconocido, sin atribución retrospectiva.
- [ ] **QA-108 · P1 · Datos de auditoría.** Inspeccionar que no se registran credenciales, tokens, contraseñas ni información privada innecesaria.

## L. Escenarios end-to-end obligatorios

- [ ] **E2E-01 · P0 · Publicación completa:** ficha nueva → imágenes → atributos → cálculo de precio → títulos únicos → borradores → validación → aprobación → job → publicación → búsqueda en gestor → auditoría.
- [ ] **E2E-02 · P0 · Dos operadores, una cuenta:** O1 y O2 autorizados sobre ML-A, fichas propias distintas, intentos cruzados denegados, jobs separados y visibilidad correcta.
- [ ] **E2E-03 · P0 · Actualización multicuenta:** un SKU con dos MLA y variaciones → vista previa por destino → actualización selectiva → resultado individual, sin modificaciones no seleccionadas.
- [ ] **E2E-04 · P0 · Recuperación:** job activo → reinicio simulado → reanudación/reconciliación → sin duplicación de publicación.
- [ ] **E2E-05 · P0 · Revocación:** O1 con sesión activa y ficha bloqueada → desactivar usuario → rechazar nuevos cambios, verificar recuperación del bloqueo.

## M. Criterio de aceptación / Gate final

**GO a producción solo si:**

1. Todos los **P0 aplicables están APROBADOS**, incluida la publicación real de prueba y el aislamiento multiusuario.
2. Los **P1 necesarios para los módulos comprometidos** están aprobados o disponen de una excepción documentada, acotada y aceptada por el responsable; ninguna excepción puede convertir en aceptable una vulnerabilidad de aislamiento o pérdida de datos.
3. No quedan defectos abiertos de severidad **Crítica** o **Alta**.
4. Base de datos respaldada, migraciones verificadas, mecanismo de rollback documentado y ensayado.
5. Todos los módulos ofrecidos en la entrega final tienen pruebas positivas, negativas y end-to-end.
6. La versión evaluada coincide exactamente con el artefacto que se desplegará.
7. Se adjuntan evidencias, reporte de cobertura y resultados de las pruebas.
8. Los objetivos de disponibilidad (≥99,5%/30 días) y recuperación (RTO/RPO ≤5 min) se reportan como **objetivos pendientes** hasta tener una medición suficiente; no se infiere cumplimiento de una prueba aislada.

### Registro de incidencias

Para cada fallo: `ID | fecha | versión | prioridad | precondición | pasos | resultado esperado | resultado observado | evidencia | responsable | estado de corrección | fecha de retest`.

### Acta de cierre

- Casos totales: ____ · Aprobados: ____ · Fallidos: ____ · Bloqueados: ____ · No implementados: ____ · No aplican: ____
- P0 pendientes: ____ · P1 pendientes: ____
- Publicación real con imágenes: ____ · Concurrencia real: ____ · Recuperación: ____
- Defectos críticos/altos abiertos: ____
- **Decisión:** [ ] GO [ ] NO-GO [ ] GO condicionado (detallar excepciones no críticas)
- **Firmas:** Responsable técnico __________ · Responsable comercial __________ · QA __________
