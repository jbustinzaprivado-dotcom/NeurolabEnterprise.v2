# Manual de usuario · NeuroLab Enterprise

Entregable del §17: guía por módulo para quien usa la plataforma. Para instalarla y operarla, consulta la [guía operativa](operations/guia-operativa.md).

## Antes de empezar

### Iniciar y cerrar sesión

1. Abre la plataforma (en local, http://localhost:5173) y pulsa **Iniciar sesión**.
2. Entra con la cuenta de tu organización en la pantalla de Keycloak. NeuroLab no recibe tu contraseña.
3. Vuelves a la página donde estabas. La sesión se renueva sola mientras la uses.
4. **Cerrar sesión** está en el menú de tu perfil, arriba a la derecha. Cierra también la sesión en el proveedor, así que la próxima vez se vuelve a pedir la contraseña.

Si ves *"Tu cuenta del proveedor de identidad no está registrada en NeuroLab"*, pide a administración que te invite con el mismo correo de tu cuenta.

**Cuentas demo** (contraseña `neurolab2026`):

| Usuario | Rol | Para probar |
|---|---|---|
| `ana.quispe` | Ingeniera de IA; responsable de Iris, Dígitos y Precios | Diseñar, entrenar y evaluar |
| `rosa.medina` | Revisora | Revisar y aprobar modelos |
| `carla.nunez` | Lectora | Acceso de solo lectura |
| `diego.salas` | Responsable de proyecto | Proyectos de fraude, sismos y compresores |
| `sofia.ramirez` | Administradora | Consola M10 |

### Qué puedes hacer según tu rol

Lo que puedes hacer depende de tu rol **en cada proyecto**. Los botones que tu rol no permite no aparecen, y la API rechaza la acción aunque se intente por otra vía. La matriz completa está en el [documento de arquitectura](architecture/arquitectura.md#2-roles-y-permisos-42-11).

### Recorrido típico

**M02** crea el proyecto → **M04** diseña la red → **M05** registra el dataset → **M06** encola el entrenamiento y sigue su avance → **M07** evalúa → **M08** revisa y aprueba la versión → **M09** exporta el informe.

---

## M01 · Inicio / Dashboard

Resumen de todo lo que tienes accesible.

- **Indicadores:** proyectos activos, entrenamientos en ejecución, modelos aprobados y mejor exactitud validada (solo entre modelos de clasificación).
- **Entrenamientos en ejecución:** cada trabajo activo con su época, pérdida y métricas, que se actualizan solos. En regresión se muestra el MAE en lugar de la exactitud.
- **Curva por modelo:** pérdida en el eje izquierdo y, en el derecho, la exactitud (clasificación) o el error absoluto medio (regresión). Una brecha creciente entre validación y entrenamiento indica sobreajuste.
- **Estado del sistema:** API, workers disponibles, base de datos y almacenamiento.

El entrenamiento continúa en el servidor aunque cierres esta pantalla o el navegador.

## M02 · Proyectos de IA

- **Nuevo proyecto** (responsables, ingenieros y administración): nombre, descripción del problema, familia de red y etiquetas.
- **Cartera:** filtra por estado (borrador, activo, archivado), familia o etiqueta.
- **Ficha del proyecto**, con pestañas internas:
  - **Contexto:** descripción del problema, responsable, familia, estado y etiquetas. El owner los edita.
  - **Arquitectura:** versiones de la red del proyecto, con su familia, número de capas, parámetros y si ya se puede entrenar.
  - **Dataset:** versiones de datos, con filas × columnas, tamaño, particiones y estado.
  - **Entrenamientos:** trabajos en cola o en ejecución, con su progreso y su época actual.
  - **Modelos:** versiones registradas, con su estado de revisión y su métrica principal de prueba (accuracy o R²).
  - **Historial:** cada ejecución terminada con fecha, versión, duración, estado y parámetros principales.
    - Acciones autorizadas: **Evaluación** abre el M07; **Reintentar** está disponible en trabajos fallidos o cancelados, para quien puede lanzar entrenamientos.
    - **Exportar CSV** descarga el historial completo del proyecto.
  - **Miembros:** el owner añade o quita miembros y asigna su rol (owner, ingeniero, revisor o lector). Cada cambio queda en la auditoría.
  - **Documentación:** documentos de contexto del proyecto, que escriben el owner y los ingenieros.

  Las pestañas Arquitectura, Dataset, Entrenamientos, Modelos e Historial resumen lo que el proyecto ya tiene. Para crear o cambiar algo, cada una enlaza a su módulo (M04 a M08).

Solo ves los proyectos de los que eres miembro.

## M03 · Fundamentos neuronales

Material de consulta de la Semana 11, sin datos del proyecto:

- **Concepto:** qué es una red neuronal, por qué importa y cómo aprende (propagación, pérdida y retropropagación).
- **Neurona y capas:** cómo se calcula `z = Σ wᵢxᵢ + b` y cómo se apilan las capas.
- **Activaciones:** ReLU, sigmoide, tanh y softmax, con su forma y su uso.
- **Ejemplo guiado** y **glosario**.

El botón **Diseñar una arquitectura** lleva al M04.

## M04 · Diseñador de arquitecturas

1. Elige la **familia**: Feedforward, Recurrente (LSTM/GRU), Convolucional o GAN. Cada una ofrece solo sus capas válidas.
2. Escribe el **nombre** y elige el **proyecto destino**.
3. Define la **entrada**: número de características (Feedforward), pasos y variables (RNN), o alto, ancho y canales (CNN).
4. **Añade capas** y edita cada una en el panel de propiedades: unidades, activación, descarte, filtros, kernel…
5. Revisa **Resumen y validación**: forma de salida de cada capa, número total de parámetros y avisos. Por ejemplo, una capa densa después de una convolucional necesita `Flatten`, y la última capa debe ser `Dense`.
6. **Guardar versión.** Cada guardado crea una versión nueva; las anteriores se conservan.

La vista previa dibuja neuronas y conexiones. En **Modo conectar** puedes trazar conexiones a mano entre capas adyacentes.

**Hoy solo se entrenan las redes Feedforward.** Las demás familias se diseñan y validan, y se habilitarán más adelante (§18).

## M05 · Datasets

- **Registrar dataset** (owner e ingenieros): sube un CSV y declara las particiones de entrenamiento, validación y prueba (por defecto 70/15/15), la privacidad, la licencia y las etiquetas.
- **Validación automática antes de publicar:**
  - el archivo debe ser un CSV con encabezados, al menos dos columnas y sin columnas duplicadas;
  - se respeta el tamaño máximo vigente (50 MB por defecto) y un mínimo de filas;
  - se rechazan binarios y archivos ilegibles.
- **Versiones:** subir un archivo con el mismo nombre crea la versión siguiente con su checksum SHA-256. Las versiones son inmutables.
- **Eliminar** (solo el owner): pide confirmar escribiendo el nombre y se bloquea si algún entrenamiento usa el dataset.

## M06 · Entrenamientos

**Configurar y encolar:**

1. Elige el proyecto, la **arquitectura** (de M04), el **dataset** (de M05) y la **columna objetivo**. La tarea (clasificación o regresión) se deduce de la columna.
2. Ajusta las **épocas**, el **tamaño de lote**, el **optimizador** (Adam, AdamW, RMSprop o SGD), la **tasa de aprendizaje** y la **semilla**. La misma semilla reproduce la misma curva.
3. Elige la **prioridad** en la cola: crítica, alta, normal o baja, según lo que permita tu rol.
4. **Encolar ejecución.** El trabajo queda **En cola** y el worker lo atiende por prioridad y antigüedad.

**Seguir el avance:** el detalle muestra el estado (*En cola → Preparando → Ejecutando → Completado / Fallido / Cancelado*), la barra de progreso, la época actual, las curvas y los logs del worker en vivo. Si pierdes la conexión, la pantalla recupera lo que faltaba al reconectar.

**Acciones:**

| Acción | Qué hace |
|---|---|
| Cancelar | Pide detenerlo; el worker se detiene al terminar la época en curso y registra el motivo |
| Reintentar | Crea un trabajo nuevo con la misma configuración, enlazado al original |
| Prioridad / Iniciar ahora | Reordena la cola, según tu rol |

Si un trabajo falla, el motivo aparece en lenguaje claro. Por ejemplo, *"El worker dejó de responder; reintenta el trabajo"*. La traza técnica solo la ve administración.

## M07 · Evaluación y métricas

Muestra cada trabajo completado, evaluado sobre la partición de prueba. Lo que se ve depende de la tarea:

| | Clasificación | Regresión |
|---|---|---|
| Indicadores | F1 macro, exactitud balanceada, pérdida de prueba | R², RMSE y MAE (en las unidades del objetivo) |
| Curvas por época | Pérdida, exactitud y F1 macro | Pérdida (MSE) y MAE |
| Evaluación final | Matriz de confusión con precisión y recall por clase | Errores de predicción con su lectura (por ejemplo, si dominan unos pocos errores grandes) |

En ambos casos:

- Cada indicador muestra la diferencia frente a la ejecución anterior, junto con la latencia de inferencia (p95).
- Las curvas separan entrenamiento (línea continua) y validación (discontinua), y se pueden superponer dos ejecuciones.
- La **comparación de ejecuciones** incluye solo las de la misma tarea: accuracy y R² no se miden en la misma escala.
- **Registrar observación:** deja constancia de limitaciones, observaciones o riesgos antes de aprobar una versión. Los revisores las marcan como revisadas.

La partición de prueba nunca interviene en el entrenamiento.

## M08 · Registro de modelos

Cada entrenamiento completado crea una **versión inmutable**: pesos, preprocesador, metadatos y checksum.

- **Tabla:**
  - en clasificación muestra accuracy y F1 macro de prueba;
  - en regresión muestra R² y RMSE, en las unidades del objetivo.
- **Ficha:** dataset y objetivo, clases, parámetros, quién entrenó, checksum e historial de revisión. En regresión añade el **MAE** (error absoluto medio) y la pérdida MSE.
- **Ciclo de revisión:**

| Desde | Acción | Quién |
|---|---|---|
| Borrador | Marcar revisado | Owner o revisor |
| Revisado | Aprobar | Owner o revisor |
| Cualquiera | Retirar | Owner |

Puedes dejar una **nota de revisión**, que queda en el historial.

- **Descargar** (owner, ingeniero o revisor): paquete ZIP con `model.keras`, `preprocessor.pkl` y `metadata.json`. Cada descarga queda auditada.

## M09 · Reportes

Arma el informe de un proyecto en cuatro secciones: **ficha del proyecto**, **resumen de arquitectura**, **historial de entrenamiento** y avisos.

- Elige el proyecto, el rango de fechas y las secciones.
- La **mejor ejecución** se elige por la mayor exactitud de validación en clasificación, o por el menor MAE de validación en regresión.
- **Exportar CSV o PDF** (owner, ingeniero o revisor). La exportación queda registrada con su huella digital. Si tu rol no permite ver un campo, aparece enmascarado.

## M10 · Administración y seguridad

Solo para administración.

- **Usuarios y roles:**
  - **Invitar usuario:** con Keycloak activo, crea también su cuenta en Keycloak con el mismo correo.
  - Cambiar el rol global, y suspender o reactivar cuentas.
  - Las cuentas bloqueadas por intentos fallidos se desbloquean aquí.
- **Matriz de permisos:** la política RBAC vigente, de solo lectura.
- **Auditoría de acciones:** quién hizo qué, cuándo y desde qué IP. Se puede filtrar y exportar.
- **Límites de recursos:** se aplican desde el próximo trabajo.
  - entrenamientos activos por usuario y por proyecto;
  - duración máxima por trabajo y épocas por trabajo;
  - tamaño de carga y cuota de almacenamiento;
  - peticiones por minuto por usuario.
- **Políticas de seguridad:** duración de la sesión, política de MFA y plazos de retención.
- **Aplicar retención:** ejecuta la limpieza en el momento; normalmente la hace el worker cada hora.
- **Salud del sistema:** estado de la API, los workers, la base de datos y el almacenamiento.

---

## Preguntas frecuentes

**Cerré el navegador durante un entrenamiento, ¿se perdió?**
No. El entrenamiento corre en el servidor; al volver verás su estado actual y todas sus épocas.

**¿Por qué no veo un proyecto que existe?**
Solo ves los proyectos de los que eres miembro. Pide al owner del proyecto que te añada.

**¿Puedo cambiar un modelo ya registrado?**
No. Las versiones son inmutables; entrena de nuevo y se registrará la versión siguiente.

**Me aparece "Demasiadas solicitudes".**
Superaste el límite de peticiones por minuto. Espera los segundos que indica el mensaje.
