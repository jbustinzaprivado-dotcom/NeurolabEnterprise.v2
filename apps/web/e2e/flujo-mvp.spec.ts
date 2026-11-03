import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

/* Flujo end-to-end del MVP (§15, §18), como lo haría una persona en el navegador:
   iniciar sesión → crear proyecto → registrar dataset → diseñar la red → entrenar y seguir
   las épocas en vivo → ver la evaluación → revisar la versión del modelo. */

const ANA = { email: 'ana.quispe@neurolab.enterprise', password: 'neurolab2026' };
const stamp = Date.now().toString(36);
const PROJECT = `Flores E2E ${stamp}`;
const DATASET = `flores-e2e-${stamp}`;
const ARCHITECTURE = `ff-flores-${stamp}`;
const EPOCHS = 40;

/** Tres especies separables con cuatro medidas: 30 filas por clase, sin aleatoriedad. */
function floresCsv(): string {
  const rows = ['largo,ancho,alto,peso,especie'];
  ['alfa', 'beta', 'gamma'].forEach((species, k) => {
    for (let i = 0; i < 30; i += 1) {
      const jitter = ((i * 37) % 11) / 10;
      rows.push([1 + k * 3 + jitter, 2 + k * 2 + jitter / 2, 3 - k + jitter / 3, 5 + k * 4 + jitter, species].join(','));
    }
  });
  return `${rows.join('\n')}\n`;
}

/** Elige en un <select> la opción cuyo texto contiene `text`. */
async function selectByText(select: Locator, text: string) {
  const value = await select.locator('option', { hasText: text }).first().getAttribute('value');
  expect(value, `opción «${text}»`).toBeTruthy();
  await select.selectOption(value as string);
}

async function go(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator('main')).toBeVisible();
}

test('flujo principal: proyecto → dataset → arquitectura → entrenamiento en vivo → versión', async ({ page }) => {
  await test.step('Iniciar sesión (M10 · autenticación local)', async () => {
    await page.goto('/');
    await page.getByLabel('Correo').fill(ANA.email);
    await page.getByLabel('Contraseña').fill(ANA.password);
    await page.getByRole('button', { name: 'Iniciar sesión' }).click();
    await expect(page.getByRole('button', { name: /Cuenta de Ana Quispe/ })).toBeVisible();
  });

  await test.step('Crear el proyecto (M02)', async () => {
    await go(page, '/projects');
    await page.getByRole('button', { name: 'Nuevo proyecto' }).click();
    await page.locator('#pj-field-name').fill(PROJECT);
    await page.locator('#pj-field-family').selectOption('FEEDFORWARD');
    await page.locator('#pj-field-status').selectOption('ACTIVE');
    await page.locator('#pj-field-description').fill('Clasificar tres especies de flores a partir de cuatro medidas (prueba E2E).');
    await page.getByRole('button', { name: 'Crear proyecto' }).click();
    await expect(page.getByText(PROJECT).first()).toBeVisible();
  });

  await test.step('Registrar el dataset (M05)', async () => {
    await go(page, '/datasets');
    await page.getByRole('button', { name: 'Registrar dataset' }).first().click();
    await page.locator('#ds-field-name').fill(DATASET);
    await selectByText(page.locator('#ds-field-project'), PROJECT);
    await page.locator('input[type="file"]').setInputFiles({
      name: `${DATASET}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(floresCsv(), 'utf-8'),
    });
    await page.getByRole('dialog').getByRole('button', { name: 'Registrar dataset' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText(DATASET).first()).toBeVisible();
  });

  await test.step('Diseñar y guardar la arquitectura (M04)', async () => {
    await go(page, '/architectures');
    await page.getByLabel('Nombre de la arquitectura').fill(ARCHITECTURE);
    await selectByText(page.getByLabel('Proyecto destino'), PROJECT);
    await page.getByLabel('Características').fill('4');
    // La plantilla Feedforward termina en Dense 10 softmax: se ajusta a las 3 especies.
    await page.locator('.arch-layer__main').last().click();
    await page.getByLabel('Unidades').fill('3');
    await expect(page.getByText('Configuración válida').first()).toBeVisible();
    await page.getByRole('button', { name: 'Guardar versión' }).click();
    await expect(page.getByText(new RegExp(`«${ARCHITECTURE}» v1 guardada en ${PROJECT}`))).toBeVisible();
  });

  await test.step('Encolar el entrenamiento y seguir las épocas en vivo (M06)', async () => {
    await go(page, '/training');
    await selectByText(page.locator('#tr-project'), PROJECT);
    await selectByText(page.locator('#tr-architecture'), ARCHITECTURE);
    await selectByText(page.locator('#tr-dataset'), DATASET);
    await page.locator('#tr-target').selectOption('especie');
    await page.locator('#tr-epochs').fill(String(EPOCHS));
    await page.locator('#tr-batch').fill('16');
    await page.getByRole('button', { name: 'Encolar ejecución' }).click();
    await expect(page.getByText(/encolado ·/)).toBeVisible();

    // Las épocas llegan por SSE sin recargar la página (§12 Tiempo real).
    const epochLog = page.getByText(new RegExp(`Época \\d+/${EPOCHS} · loss`)).first();
    await expect(epochLog).toBeVisible({ timeout: 150_000 });
    await expect(page.getByText(/Modelo registrado como ff-flores-.* v1\.0/).first()).toBeVisible({ timeout: 150_000 });
  });

  await test.step('Consultar la evaluación final (M07)', async () => {
    await go(page, '/evaluation');
    await selectByText(page.locator('.ev-runbar select'), ARCHITECTURE);
    await expect(page.getByText('Evaluación final · matriz de confusión')).toBeVisible();
    await expect(page.getByText('F1 macro').first()).toBeVisible();
  });

  await test.step('Revisar la versión registrada (M08)', async () => {
    await go(page, '/models');
    await page.getByRole('button', { name: new RegExp(`${ARCHITECTURE} v1\\.0`) }).click();
    await page.getByPlaceholder(/métricas comprobadas/).fill('Revisado por la prueba E2E.');
    await page.getByRole('button', { name: 'Marcar revisado' }).click();
    await expect(page.getByText(`${ARCHITECTURE} v1.0 pasa a revisado.`)).toBeVisible();
    // Quien entrenó no puede aprobar su propio modelo (separación de funciones).
    await expect(page.getByRole('button', { name: 'Aprobar' })).toBeDisabled();
  });
});
